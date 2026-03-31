"""Action router node — confidence x blast radius → decision."""

from __future__ import annotations

from backend.app.agents.state import AgentState

BLAST_RADIUS_MAP = {
    "restart_deployment": "low",
    "clear_cache": "low",
    "flush_queue": "low",
    "rollback_deploy": "medium",
    "scale_deployment": "medium",
    "scale_cluster": "high",
    "db_migration": "high",
    "delete_resource": "high",
}

AUTO_EXECUTE_THRESHOLD = 0.90


async def action_router_node(state: AgentState) -> AgentState:
    confidence = state.get("confidence", 0)
    actions = state.get("suggested_actions", [])

    if not actions:
        return {**state, "action_decision": "escalate", "blast_radius": "unknown"}

    action = actions[0]
    action_type = action.get("action", "unknown")
    blast_radius = BLAST_RADIUS_MAP.get(action_type, "high")

    # Decision matrix
    if confidence >= AUTO_EXECUTE_THRESHOLD and blast_radius == "low":
        decision = "auto_execute"
    elif confidence >= AUTO_EXECUTE_THRESHOLD and blast_radius in ("medium", "high"):
        decision = "human_approval"
    elif blast_radius == "high":
        decision = "escalate"
    else:
        decision = "human_approval"

    return {
        **state,
        "action_decision": decision,
        "blast_radius": blast_radius,
        "action_taken": action,
    }
