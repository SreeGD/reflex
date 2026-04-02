"""Webhook and incidents API router.

POST /webhook/alertmanager — receive Alertmanager payloads, run pipeline
GET /incidents — list incidents (with optional ?since= for polling)
GET /incidents/{id} — get single incident
"""

from __future__ import annotations

import importlib
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.app.incidents import incident_store

router = APIRouter(tags=["webhook"])

# Scenario lookup: (alertname, service) -> scenario module name
_SCENARIO_MAP = None


def _get_scenario_map() -> Dict[tuple, str]:
    """Build a lookup table mapping (alertname, service) to scenario names."""
    global _SCENARIO_MAP
    if _SCENARIO_MAP is not None:
        return _SCENARIO_MAP

    scenarios = {
        "db_pool_exhaustion": "mock.scenarios.db_pool_exhaustion",
        "payment_timeout_cascade": "mock.scenarios.payment_timeout_cascade",
        "memory_leak": "mock.scenarios.memory_leak",
        "redis_connection_storm": "mock.scenarios.redis_connection_storm",
        "slow_query_cascade": "mock.scenarios.slow_query_cascade",
    }

    _SCENARIO_MAP = {}
    for name, module_path in scenarios.items():
        try:
            mod = importlib.import_module(module_path)
            scenario = mod.create_scenario()
            payload = scenario.get_alert_payload()
            alertname = payload.get("labels", {}).get("alertname", "")
            service = payload.get("labels", {}).get("service", "")
            _SCENARIO_MAP[(alertname, service)] = name
            _SCENARIO_MAP[(alertname, "")] = name  # Match by alertname alone too
        except Exception:
            pass

    return _SCENARIO_MAP


def _match_scenario(alarm: Dict[str, Any]) -> str:
    """Match an alarm payload to a mock scenario name."""
    labels = alarm.get("labels", {})
    alertname = labels.get("alertname", "")
    service = labels.get("service", "")

    scenario_map = _get_scenario_map()

    # Try exact match first, then alertname-only
    match = scenario_map.get((alertname, service))
    if match:
        return match
    match = scenario_map.get((alertname, ""))
    if match:
        return match

    return "db_pool_exhaustion"  # Default fallback


def _get_llm():
    """Get an LLM instance."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model="claude-sonnet-4-20250514", temperature=0)
    from mock.providers.mock_llm import MockLLM
    return MockLLM()


async def _run_pipeline(alarm: Dict[str, Any]) -> Dict[str, Any]:
    """Run the Reflex pipeline on an alarm and return the final state."""
    from backend.app.agents.graph import build_graph
    from backend.app.providers.factory import create_providers

    scenario_name = _match_scenario(alarm)
    mod = importlib.import_module(f"mock.scenarios.{scenario_name}")
    scenario = mod.create_scenario()
    providers = create_providers(mode="mock", scenario=scenario)
    llm = _get_llm()
    graph = build_graph(providers, llm)

    final_state = {}
    async for event in graph.astream({"alarm": alarm}):
        for _node_name, node_state in event.items():
            final_state.update(node_state)

    # Preserve the original alarm for metadata
    final_state["alarm"] = alarm
    return final_state


# --- Request/Response models ---

class AlertmanagerPayload(BaseModel):
    """Accepts both Alertmanager batch format and single flat alerts."""
    # Batch format
    status: Optional[str] = "firing"
    alerts: Optional[List[Dict[str, Any]]] = None
    # Single flat alert (convenience for curl testing)
    labels: Optional[Dict[str, str]] = None
    annotations: Optional[Dict[str, str]] = None
    startsAt: Optional[str] = None


class WebhookResponse(BaseModel):
    received: int
    processed: List[str]
    skipped: int


class IncidentSummary(BaseModel):
    incident_id: str
    service: str
    severity: str
    is_noise: bool
    root_cause: str
    confidence: float
    action_decision: str
    blast_radius: str
    source: str
    stored_at: float
    actioned_by: str = ""
    actioned_at: float = 0


class ActionRequest(BaseModel):
    user_id: str = "demo-user"
    reason: str = ""


# --- Endpoints ---

@router.post("/webhook/alertmanager", response_model=WebhookResponse)
async def receive_alertmanager(payload: AlertmanagerPayload):
    """Receive Alertmanager webhook payloads and run the Reflex pipeline."""
    # Normalize: extract list of individual alerts
    alerts = []

    if payload.alerts:
        alerts = payload.alerts
    elif payload.labels:
        # Single flat alert
        alerts = [{
            "status": payload.status or "firing",
            "labels": payload.labels,
            "annotations": payload.annotations or {},
            "startsAt": payload.startsAt or "",
        }]

    if not alerts:
        return WebhookResponse(received=0, processed=[], skipped=0)

    processed = []
    skipped = 0

    for alert in alerts:
        # Skip resolved alerts
        status = alert.get("status", payload.status or "firing")
        if status == "resolved":
            skipped += 1
            continue

        # Filter for SEV-2 (critical/warning)
        severity = alert.get("labels", {}).get("severity", "warning")
        if severity.lower() in ("info", "none"):
            skipped += 1
            continue

        # Run the pipeline
        try:
            final_state = await _run_pipeline(alert)
            incident_id = final_state.get("incident_id", "unknown")
            incident_store.put(incident_id, final_state, source="webhook")
            processed.append(incident_id)
        except Exception as e:
            skipped += 1

    return WebhookResponse(
        received=len(alerts),
        processed=processed,
        skipped=skipped,
    )


@router.get("/incidents", response_model=List[IncidentSummary])
async def list_incidents(since: Optional[float] = None):
    """List incidents, optionally filtered by timestamp for polling."""
    if since is not None:
        items = incident_store.list_since(since)
        summaries = []
        for state in items:
            summaries.append(IncidentSummary(
                incident_id=state.get("incident_id", "unknown"),
                service=state.get("service", "unknown"),
                severity=state.get("_severity_label", "unknown"),
                is_noise=state.get("is_noise", False),
                root_cause=(state.get("root_cause") or "")[:100],
                confidence=state.get("confidence", 0),
                action_decision=state.get("action_decision", ""),
                blast_radius=state.get("blast_radius", ""),
                source=state.get("_source", "unknown"),
                stored_at=state.get("_stored_at", 0),
            ))
        return summaries
    return incident_store.to_summary_list()


@router.get("/incidents/{incident_id}")
async def get_incident(incident_id: str):
    """Get full incident details by ID."""
    state = incident_store.get(incident_id)
    if state is None:
        raise HTTPException(404, f"Incident {incident_id} not found")
    # Return a clean copy without internal metadata
    return {k: v for k, v in state.items() if not k.startswith("_")}


# --- Incident Action Endpoints ---

async def _execute_action(incident_id: str, action_type: str, user_id: str, reason: str = "") -> Dict[str, Any]:
    """Execute an action on an incident and update the store."""
    import time as _time
    from mock.providers.actions import MockActionsProvider
    from mock.providers.alerts import MockAlertsProvider
    import tempfile
    from pathlib import Path

    state = incident_store.get(incident_id)
    if state is None:
        raise HTTPException(404, f"Incident {incident_id} not found")

    if state.get("_actioned_by"):
        return {"status": "already_actioned", "message": f"Incident already actioned by {state['_actioned_by']}"}

    actions_provider = MockActionsProvider()
    alerts_provider = MockAlertsProvider(log_dir=Path(tempfile.mkdtemp()))
    result = {}

    if action_type == "approve":
        action = (state.get("suggested_actions") or [{}])[0]
        action_name = action.get("action", "restart_deployment")
        deployment = action.get("deployment", state.get("service", "unknown"))
        namespace = action.get("namespace", "default")

        if "restart" in action_name:
            result = await actions_provider.restart_deployment(namespace, deployment)
        elif "scale" in action_name:
            result = await actions_provider.scale_deployment(namespace, deployment, action.get("replicas", 3))
        else:
            result = {"status": "success", "message": f"Executed {action_name}"}

        incident_store.update(incident_id, {
            "action_decision": "approved",
            "action_result": result,
            "_actioned_by": user_id,
            "_actioned_at": _time.time(),
        })
        return {"status": "approved", "message": f"Action approved by {user_id}. {result.get('message', '')}", "result": result}

    elif action_type == "deny":
        incident_store.update(incident_id, {
            "action_decision": "denied",
            "_actioned_by": user_id,
            "_actioned_at": _time.time(),
            "_deny_reason": reason,
        })
        return {"status": "denied", "message": f"Action denied by {user_id}. Reason: {reason}"}

    elif action_type == "escalate":
        await alerts_provider.escalate(
            {"incident_id": incident_id, "service": state.get("service", "")},
            reason or "Manual escalation",
        )
        incident_store.update(incident_id, {
            "action_decision": "escalated",
            "_actioned_by": user_id,
            "_actioned_at": _time.time(),
            "_escalate_reason": reason,
        })
        return {"status": "escalated", "message": f"Incident escalated by {user_id}. On-call team notified."}

    raise HTTPException(400, f"Unknown action type: {action_type}")


@router.post("/incidents/{incident_id}/approve")
async def approve_incident(incident_id: str, request: ActionRequest):
    """Approve a pending remediation action."""
    return await _execute_action(incident_id, "approve", request.user_id)


@router.post("/incidents/{incident_id}/deny")
async def deny_incident(incident_id: str, request: ActionRequest):
    """Deny a pending remediation action."""
    return await _execute_action(incident_id, "deny", request.user_id, request.reason)


@router.post("/incidents/{incident_id}/escalate")
async def escalate_incident(incident_id: str, request: ActionRequest):
    """Escalate an incident."""
    return await _execute_action(incident_id, "escalate", request.user_id, request.reason)
