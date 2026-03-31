"""RCA node — root cause analysis using LLM + knowledge retrieval.

This is the most important node. It:
1. Searches knowledge base for matching runbooks, tickets, docs
2. Fetches recent error logs
3. Calls the LLM with all context to produce a root cause analysis
4. Computes multi-signal confidence score
"""

from __future__ import annotations

from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage

from backend.app.agents.scoring import ConfidenceSignals, compute_confidence
from backend.app.agents.state import AgentState
from backend.app.providers.base import KnowledgeProvider, LogsProvider

RCA_SYSTEM_PROMPT = """You are an expert Site Reliability Engineer performing root cause analysis.

Given an alert, relevant runbooks, past incident tickets, and recent logs, determine:
1. The root cause of the incident
2. The immediate remediation action to take
3. Your confidence level (0.0 to 1.0)

Be specific. Reference the runbook steps and past incidents when applicable.
Output format:
ROOT_CAUSE: <one paragraph explaining what happened and why>
REMEDIATION: <specific action, e.g., "restart deployment order-service in namespace shopfast-prod">
CONFIDENCE: <float between 0 and 1>
EVIDENCE: <comma-separated list of evidence sources, e.g., "RB-001, OPS-1234, error logs">
"""


async def rca_node(
    state: AgentState,
    knowledge: KnowledgeProvider,
    logs: LogsProvider,
    llm: object,
) -> AgentState:
    service = state["service"]
    alert = state["alarm"]
    alert_name = alert.get("labels", {}).get("alertname", "")
    description = alert.get("annotations", {}).get("description", "")

    # 1. Search knowledge base
    query = f"{service} {alert_name} {description}"
    knowledge_results = await knowledge.search_similar(query, limit=8)

    # Separate by type
    runbook_results = [r for r in knowledge_results if r["source_type"] == "runbook"]
    ticket_results = [r for r in knowledge_results if r["source_type"] == "jira"]
    doc_results = [r for r in knowledge_results if r["source_type"] == "confluence"]

    # Get full runbook content if we have a match
    runbook_content = None
    runbook_id = None
    if runbook_results:
        runbook_id = runbook_results[0]["source_id"]
        runbook_content = await knowledge.get_runbook(runbook_id)

    # Get full ticket details for top matches
    full_tickets = []
    for tr in ticket_results[:3]:
        ticket = await knowledge.get_ticket(tr["source_id"])
        if ticket:
            full_tickets.append(ticket)

    # 2. Fetch recent error logs
    error_logs = await logs.search(
        service=service,
        level="ERROR",
        limit=10,
    )

    # 3. Build LLM prompt
    context_parts = [f"ALERT: {alert_name} on {service}\n{description}"]

    if runbook_content:
        context_parts.append(f"\nMATCHING RUNBOOK ({runbook_id}):\n{runbook_content[:2000]}")

    if full_tickets:
        context_parts.append("\nSIMILAR PAST INCIDENTS:")
        for t in full_tickets:
            context_parts.append(
                f"- {t['key']}: {t['summary']}\n"
                f"  Resolution: {t.get('resolution_notes', 'N/A')[:500]}"
            )

    if error_logs:
        context_parts.append("\nRECENT ERROR LOGS:")
        for log in error_logs[:5]:
            context_parts.append(f"- [{log['timestamp']}] {log['message']}")

    context = "\n".join(context_parts)

    # 4. Call LLM
    messages = [
        SystemMessage(content=RCA_SYSTEM_PROMPT),
        HumanMessage(content=context),
    ]
    response = await llm.ainvoke(messages)
    rca_text = response.content

    # 5. Parse LLM response
    root_cause = _extract_field(rca_text, "ROOT_CAUSE")
    remediation = _extract_field(rca_text, "REMEDIATION")
    llm_confidence = _extract_float(rca_text, "CONFIDENCE", default=0.7)
    evidence_str = _extract_field(rca_text, "EVIDENCE")
    evidence = [e.strip() for e in evidence_str.split(",") if e.strip()] if evidence_str else []

    # 6. Compute multi-signal confidence
    best_rag_score = max((r["score"] for r in knowledge_results), default=0.0)
    has_pattern_match = len(ticket_results) >= 2
    recency_days = _days_since_resolution(full_tickets[0]) if full_tickets else None

    signals = ConfidenceSignals(
        rag_match_score=best_rag_score,
        pattern_match=has_pattern_match,
        recency_days=recency_days,
        historical_success_rate=1.0 if has_pattern_match else 0.5,
        llm_assessment=llm_confidence,
    )
    confidence = compute_confidence(signals)

    # Build suggested actions from remediation text
    suggested_actions = []
    remediation_lower = (remediation or "").lower()
    if "restart" in remediation_lower:
        suggested_actions.append({
            "action": "restart_deployment",
            "namespace": "shopfast-prod",
            "deployment": service,
        })
    if "scale" in remediation_lower:
        suggested_actions.append({
            "action": "scale_deployment",
            "namespace": "shopfast-prod",
            "deployment": service,
            "replicas": 4,
        })
    if not suggested_actions:
        suggested_actions.append({
            "action": "restart_deployment",
            "namespace": "shopfast-prod",
            "deployment": service,
        })

    return {
        **state,
        "matching_runbook": runbook_content,
        "matching_runbook_id": runbook_id,
        "matching_tickets": full_tickets,
        "matching_docs": doc_results,
        "recent_error_logs": error_logs,
        "root_cause": root_cause or rca_text,
        "confidence": confidence,
        "confidence_signals": {
            "rag_match_score": round(best_rag_score, 2),
            "pattern_match": has_pattern_match,
            "recency_days": recency_days,
            "historical_success_rate": 1.0 if has_pattern_match else 0.5,
            "llm_assessment": llm_confidence,
        },
        "evidence": evidence,
        "suggested_actions": suggested_actions,
    }


def _extract_field(text: str, field: str) -> Optional[str]:
    for line in text.split("\n"):
        if line.strip().upper().startswith(field.upper() + ":"):
            return line.split(":", 1)[1].strip()
    return None


def _extract_float(text: str, field: str, default: float = 0.7) -> float:
    val = _extract_field(text, field)
    if val:
        try:
            return float(val)
        except ValueError:
            pass
    return default


def _days_since_resolution(ticket: dict) -> Optional[int]:
    from datetime import datetime, timezone

    resolved = ticket.get("resolved")
    if not resolved:
        return None
    try:
        resolved_dt = datetime.fromisoformat(resolved.replace("Z", "+00:00"))
        delta = datetime.now(tz=timezone.utc) - resolved_dt
        return max(0, delta.days)
    except (ValueError, TypeError):
        return None
