"""Alert node — send notification via AlertsProvider."""

from __future__ import annotations

from backend.app.agents.state import AgentState
from backend.app.providers.base import AlertsProvider


async def alert_node(state: AgentState, alerts: AlertsProvider) -> AgentState:
    decision = state.get("action_decision", "")
    incident = {
        "incident_id": state.get("incident_id", "unknown"),
        "service": state.get("service", "unknown"),
        "action_taken": state.get("action_result"),
        "action_decision": decision,
    }
    rca = {
        "root_cause": state.get("root_cause", ""),
        "confidence": state.get("confidence", 0),
        "evidence": state.get("evidence", []),
    }

    if decision == "auto_execute":
        await alerts.send_alert("#incidents", incident, rca)
    elif decision == "human_approval":
        await alerts.request_approval("#incidents", incident, state.get("action_taken", {}))
    elif decision == "escalate":
        await alerts.escalate(incident, "Low confidence + high blast radius")

    return {**state, "alert_sent": True}
