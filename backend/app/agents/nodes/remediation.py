"""Remediation node — execute action via ActionsProvider."""

from __future__ import annotations

from backend.app.agents.state import AgentState
from backend.app.providers.base import ActionsProvider


async def remediation_node(state: AgentState, actions: ActionsProvider) -> AgentState:
    decision = state.get("action_decision")
    action = state.get("action_taken")

    if decision != "auto_execute" or not action:
        return {**state, "action_result": None}

    action_type = action.get("action")
    namespace = action.get("namespace", "shopfast-prod")
    deployment = action.get("deployment", "unknown")

    if action_type == "restart_deployment":
        result = await actions.restart_deployment(namespace, deployment)
    elif action_type == "scale_deployment":
        replicas = action.get("replicas", 3)
        result = await actions.scale_deployment(namespace, deployment, replicas)
    else:
        result = {"status": "unsupported", "message": f"Unknown action: {action_type}"}

    return {**state, "action_result": result}
