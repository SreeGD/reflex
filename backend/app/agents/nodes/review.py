"""Review Agent node — validates RCA, assesses risk, critiques, decides.

Sits between RCA and Remediation. Replaces the simple action_router.

5 steps:
1. Validate recommended action against runbook
2. Assess dynamic risk (6 factors)
3. Self-critique the RCA (LLM, only when confidence is uncertain)
4. Make decision (auto_execute / human_approval / escalate)
5. Generate decision brief (when human is needed)
"""

from __future__ import annotations

from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage

from backend.app.agents.models import DecisionBrief, RiskAssessment
from backend.app.agents.risk import assess_risk
from backend.app.agents.state import AgentState
from backend.app.providers.base import ContextProvider

AUTO_EXECUTE_THRESHOLD = 0.90
CRITIQUE_LOW = 0.70
CRITIQUE_HIGH = 0.93

CRITIQUE_PROMPT = """You are a senior SRE reviewing a junior engineer's root cause analysis.

The RCA claims:
ROOT CAUSE: {root_cause}
CONFIDENCE: {confidence}
EVIDENCE: {evidence}
SUGGESTED ACTION: {action}

{runbook_context}
{tickets_context}

Critically evaluate:
1. CONFIDENCE_JUSTIFIED: Is {confidence} reasonable given the evidence? (yes/no, then reasoning)
2. ALTERNATIVE_CAUSES: List 0-3 alternative root causes that could fit these symptoms (or "none")
3. MIGHT_BE_SYMPTOM: Is the identified root cause actually just a symptom of something deeper? (yes/no, then explain)
4. ADJUSTED_CONFIDENCE: What confidence would you assign? (float 0-1)
"""


async def review_node(
    state: AgentState,
    context_provider: ContextProvider,
    llm: object,
) -> AgentState:
    service = state.get("service", "unknown")
    confidence = state.get("confidence", 0)
    actions = state.get("suggested_actions", [])
    action = actions[0] if actions else {"action": "unknown", "deployment": service}

    adjustments: List[str] = []

    # ── Step 1: Runbook Validation ──
    runbook_content = state.get("matching_runbook")
    runbook_valid, runbook_note = _validate_against_runbook(action, runbook_content)
    if not runbook_valid:
        confidence -= 0.05
        adjustments.append(f"Runbook mismatch: {runbook_note} (-0.05 confidence)")
    elif runbook_note:
        adjustments.append(f"Runbook validated: {runbook_note}")

    # ── Step 2: Dynamic Risk Assessment ──
    env_context = await context_provider.get_environment_context(service)
    risk = assess_risk(
        action=action,
        service=service,
        context=env_context,
        confidence=confidence,
        matching_tickets=state.get("matching_tickets", []),
    )

    for rf in risk.risk_factors:
        if rf.risk_delta != 0:
            sign = "+" if rf.risk_delta > 0 else ""
            adjustments.append(f"{rf.name}: {rf.value} ({sign}{rf.risk_delta:.2f} risk)")

    if risk.effective_blast_radius != risk.base_blast_radius:
        adjustments.append(
            f"Blast radius upgraded: {risk.base_blast_radius} → {risk.effective_blast_radius}"
        )

    # ── Step 3: RCA Self-Critique (LLM, conditional) ──
    critique = None
    if CRITIQUE_LOW <= confidence <= CRITIQUE_HIGH:
        critique = await _run_critique(state, action, llm)
        if critique:
            adjusted = critique.get("adjusted_confidence", confidence)
            if adjusted != confidence:
                adjustments.append(
                    f"Critique adjusted confidence: {confidence:.2f} → {adjusted:.2f}"
                )
                confidence = adjusted

            if critique.get("alternative_causes"):
                alts = critique["alternative_causes"]
                adjustments.append(f"Critique flagged {len(alts)} alternative cause(s)")

            if critique.get("might_be_symptom"):
                adjustments.append("Critique: action may treat symptom, not root cause")
                confidence -= 0.03
                adjustments.append("Symptom treatment penalty (-0.03 confidence)")
    elif confidence > CRITIQUE_HIGH:
        adjustments.append(f"Confidence {confidence:.2f} > {CRITIQUE_HIGH} — critique skipped (strong evidence)")
    elif confidence < CRITIQUE_LOW:
        adjustments.append(f"Confidence {confidence:.2f} < {CRITIQUE_LOW} — escalating directly")

    adjusted_confidence = round(max(0, min(1, confidence)), 3)

    # ── Step 4: Decision ──
    effective_blast = risk.effective_blast_radius

    if env_context.get("is_change_freeze"):
        decision = "escalate"
    elif adjusted_confidence >= AUTO_EXECUTE_THRESHOLD and effective_blast == "low":
        decision = "auto_execute"
    elif adjusted_confidence >= AUTO_EXECUTE_THRESHOLD and effective_blast != "low":
        decision = "human_approval"
    elif effective_blast == "high" and adjusted_confidence < AUTO_EXECUTE_THRESHOLD:
        decision = "escalate"
    else:
        decision = "human_approval"

    # ── Step 5: Decision Brief (if human needed) ──
    brief = None
    if decision in ("human_approval", "escalate"):
        brief = _build_decision_brief(state, action, risk, critique, adjusted_confidence)

    return {
        **state,
        "action_decision": decision,
        "blast_radius": effective_blast,
        "action_taken": action,
        "adjusted_confidence": adjusted_confidence,
        "risk_assessment": risk.to_dict(),
        "decision_brief": brief.to_dict() if brief else None,
        "review_critique": critique,
        "review_adjustments": adjustments,
    }


def _validate_against_runbook(
    action: dict, runbook_content: Optional[str]
) -> tuple[bool, str]:
    """Check if the suggested action matches the runbook's remediation section."""
    if not runbook_content:
        return True, "No runbook to validate against"

    action_type = action.get("action", "")
    runbook_lower = runbook_content.lower()

    # Check if the runbook's remediation section mentions this action type
    remediation_section = ""
    in_remediation = False
    for line in runbook_content.split("\n"):
        if "remediation" in line.lower() or "immediate" in line.lower():
            in_remediation = True
        elif line.startswith("## ") and in_remediation:
            break
        if in_remediation:
            remediation_section += line + "\n"

    section = remediation_section.lower() if remediation_section else runbook_lower

    if action_type == "restart_deployment" and ("restart" in section or "rollout restart" in section):
        return True, "Runbook recommends restart"
    elif action_type == "scale_deployment" and ("scale" in section or "replicas" in section):
        return True, "Runbook recommends scaling"
    elif action_type == "rollback_deploy" and ("rollback" in section or "roll back" in section):
        return True, "Runbook recommends rollback"
    elif action_type in ("restart_deployment", "scale_deployment"):
        # Partial: action type is common but not explicitly in runbook
        return True, f"Action '{action_type}' is a standard remediation (not explicitly in runbook)"

    return False, f"Runbook does not mention '{action_type}' in remediation section"


async def _run_critique(state: AgentState, action: dict, llm: object) -> Optional[dict]:
    """Run LLM self-critique on the RCA."""
    root_cause = state.get("root_cause", "")
    confidence = state.get("confidence", 0)
    evidence = state.get("evidence", [])

    runbook_context = ""
    if state.get("matching_runbook"):
        rb_excerpt = state["matching_runbook"][:800]
        runbook_context = f"Matching runbook ({state.get('matching_runbook_id', '')}):\n{rb_excerpt}"

    tickets_context = ""
    tickets = state.get("matching_tickets", [])
    if tickets:
        parts = ["Similar past incidents:"]
        for t in tickets[:3]:
            parts.append(f"- {t['key']}: {t.get('summary', '')} (Resolution: {t.get('resolution_notes', '')[:200]})")
        tickets_context = "\n".join(parts)

    prompt = CRITIQUE_PROMPT.format(
        root_cause=root_cause,
        confidence=confidence,
        evidence=", ".join(evidence),
        action=f"{action.get('action', '')}({action.get('deployment', '')})",
        runbook_context=runbook_context,
        tickets_context=tickets_context,
    )

    messages = [
        SystemMessage(content="You are a senior SRE reviewer. Be concise and critical."),
        HumanMessage(content=prompt),
    ]
    response = await llm.ainvoke(messages)
    text = response.content

    return {
        "confidence_justified": "yes" in _extract_field(text, "CONFIDENCE_JUSTIFIED", "yes").lower(),
        "alternative_causes": _extract_list(text, "ALTERNATIVE_CAUSES"),
        "might_be_symptom": "yes" in _extract_field(text, "MIGHT_BE_SYMPTOM", "no").lower(),
        "adjusted_confidence": _extract_float(text, "ADJUSTED_CONFIDENCE", state.get("confidence", 0.7)),
        "raw_critique": text,
    }


def _build_decision_brief(
    state: AgentState,
    action: dict,
    risk: RiskAssessment,
    critique: Optional[dict],
    adjusted_confidence: float,
) -> DecisionBrief:
    service = state.get("service", "unknown")
    root_cause = state.get("root_cause", "Unknown")
    action_desc = f"{action.get('action', '')}({action.get('deployment', '')})"

    # Summary
    summary = f"{root_cause[:100]}. Proposed: {action_desc}."

    # Risk if act
    blast = risk.effective_blast_radius
    if blast == "low":
        risk_if_act = f"Low risk. Brief service interruption during {action.get('action', 'action')}."
    elif blast == "medium":
        risk_if_act = f"Medium risk. {service} may experience 10-30s of errors during {action.get('action', '')}. Tier {risk.service_tier} service."
    else:
        risk_if_act = f"High risk. Significant blast radius. {service} is Tier {risk.service_tier}. Potential downstream impact."

    # Risk if wait
    alert_desc = state.get("alarm", {}).get("annotations", {}).get("description", "Ongoing incident")
    risk_if_wait = f"Continued degradation. {alert_desc}"

    # Evidence for
    evidence_for = list(state.get("evidence", []))

    # Evidence against (contra-indicators)
    evidence_against: List[str] = []
    for rf in risk.risk_factors:
        if rf.risk_delta > 0:
            evidence_against.append(rf.explanation)
    if critique:
        for alt in critique.get("alternative_causes", []):
            evidence_against.append(f"Alternative cause: {alt}")
        if critique.get("might_be_symptom"):
            evidence_against.append("Action may treat symptom, not root cause")

    # Recommendation
    if adjusted_confidence >= 0.80:
        recommendation = f"Approve — confidence {adjusted_confidence:.0%} with known risk factors. Monitor after execution."
    elif adjusted_confidence >= 0.60:
        recommendation = f"Approve with caution — confidence {adjusted_confidence:.0%}. Consider alternatives if available."
    else:
        recommendation = f"Consider alternatives — confidence {adjusted_confidence:.0%} is low. Manual investigation may be needed."

    # Estimated TTR from historical tickets
    tickets = state.get("matching_tickets", [])
    estimated_ttr = _estimate_ttr(tickets)

    # Alternatives
    alternatives: List[dict] = []
    recent_deploys = [rf for rf in risk.risk_factors if rf.name == "recent_deploy"]
    if recent_deploys:
        alternatives.append({
            "action": "rollback_deploy",
            "reason": "Recent deploy detected — rollback may address root cause",
            "namespace": action.get("namespace", "shopfast-prod"),
            "deployment": service,
        })
    if critique and critique.get("might_be_symptom"):
        alternatives.append({
            "action": "investigate_further",
            "reason": "Current action may only treat symptoms",
        })

    return DecisionBrief(
        summary=summary,
        risk_if_act=risk_if_act,
        risk_if_wait=risk_if_wait,
        evidence_for=evidence_for,
        evidence_against=evidence_against,
        recommendation=recommendation,
        estimated_ttr_minutes=estimated_ttr,
        alternatives=alternatives,
    )


def _estimate_ttr(tickets: List[dict]) -> int:
    """Estimate TTR from historical ticket resolution times."""
    if not tickets:
        return 15  # default

    ttrs = []
    for t in tickets:
        created = t.get("created", "")
        resolved = t.get("resolved", "")
        if created and resolved:
            from datetime import datetime
            try:
                c = datetime.fromisoformat(created.replace("Z", "+00:00"))
                r = datetime.fromisoformat(resolved.replace("Z", "+00:00"))
                ttrs.append(int((r - c).total_seconds() / 60))
            except (ValueError, TypeError):
                pass

    return int(sum(ttrs) / len(ttrs)) if ttrs else 15


def _extract_field(text: str, field: str, default: str = "") -> str:
    for line in text.split("\n"):
        if line.strip().upper().startswith(field.upper() + ":"):
            return line.split(":", 1)[1].strip()
    return default


def _extract_float(text: str, field: str, default: float = 0.7) -> float:
    val = _extract_field(text, field)
    if val:
        try:
            return float(val.split()[0])
        except (ValueError, IndexError):
            pass
    return default


def _extract_list(text: str, field: str) -> List[str]:
    val = _extract_field(text, field)
    if not val or val.lower() == "none":
        return []
    return [item.strip().strip("-•") .strip() for item in val.split(",") if item.strip()]
