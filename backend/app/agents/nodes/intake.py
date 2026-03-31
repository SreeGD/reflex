"""Intake node — parse alarm, initialize state."""

from __future__ import annotations

import uuid

from backend.app.agents.state import AgentState


async def intake_node(state: AgentState) -> AgentState:
    alarm = state["alarm"]
    service = alarm.get("labels", {}).get("service", "unknown")
    incident_id = f"INC-{uuid.uuid4().hex[:8].upper()}"
    return {
        **state,
        "incident_id": incident_id,
        "service": service,
    }
