"""Noise management node — check if alarm is noise or real."""

from __future__ import annotations

from backend.app.agents.state import AgentState
from backend.app.providers.base import KnowledgeProvider


async def noise_node(state: AgentState, knowledge: KnowledgeProvider) -> AgentState:
    """Check for known issues, maintenance windows, flapping alerts.

    For the demo, uses keyword search to check for open tickets matching
    this service/alert combination. A real implementation would query
    Jira for open tickets and check a maintenance calendar.
    """
    service = state["service"]
    alert_name = state["alarm"].get("labels", {}).get("alertname", "")

    # Search for open (unresolved) tickets that might indicate a known issue
    results = await knowledge.search_similar(
        f"{service} {alert_name} open in-progress",
        source_types=["jira"],
        limit=3,
    )

    # Check if any ticket is still open (status != Resolved)
    open_tickets = [
        r for r in results
        if r.get("metadata", {}).get("status") not in ("Resolved", "Closed", None)
    ]

    if open_tickets:
        return {
            **state,
            "is_noise": True,
            "noise_reason": f"Known open issue: {open_tickets[0]['source_id']}",
        }

    return {
        **state,
        "is_noise": False,
        "noise_reason": None,
    }
