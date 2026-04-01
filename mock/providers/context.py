"""Mock ContextProvider — scenario-configurable environment context."""

from __future__ import annotations

from typing import Optional

from datetime import datetime, timezone

from backend.app.agents.risk import SERVICE_TIERS


class MockContextProvider:
    """Fulfills ContextProvider protocol with scenario-configured overrides.

    Default context simulates a calm environment. Scenarios can inject
    overrides like recent_deploys or change_freeze to demonstrate
    dynamic risk factors in the review agent.
    """

    def __init__(self, overrides: Optional[dict] = None) -> None:
        self._overrides = overrides or {}

    async def get_environment_context(self, service: str) -> dict:
        context = {
            "current_hour_utc": datetime.now(tz=timezone.utc).hour,
            "is_change_freeze": False,
            "recent_deploys": [],
            "active_incident_count": 0,
            "recent_action_history": [],
            "service_tier": SERVICE_TIERS.get(service, 3),
        }
        context.update(self._overrides)
        return context
