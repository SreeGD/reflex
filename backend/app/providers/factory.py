"""Provider factory — swap mock/production via config.

Usage:
    providers = create_providers(mode="mock", scenario=scenario)
    providers = create_providers(mode="production", mcp_pool=pool)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .base import (
        ActionsProvider,
        AlertsProvider,
        ContextProvider,
        KnowledgeProvider,
        LogsProvider,
        MetricsProvider,
    )


class Providers:
    """Container holding all provider instances for a pipeline run."""

    def __init__(
        self,
        metrics: MetricsProvider,
        logs: LogsProvider,
        knowledge: KnowledgeProvider,
        actions: ActionsProvider,
        alerts: AlertsProvider,
        context: ContextProvider,
    ) -> None:
        self.metrics = metrics
        self.logs = logs
        self.knowledge = knowledge
        self.actions = actions
        self.alerts = alerts
        self.context = context


def create_providers(mode: str = "mock", **kwargs: Any) -> Providers:
    if mode == "mock":
        from mock.providers.actions import MockActionsProvider
        from mock.providers.alerts import MockAlertsProvider
        from mock.providers.context import MockContextProvider
        from mock.providers.knowledge import MockKnowledgeProvider
        from mock.providers.logs import MockLogsProvider
        from mock.providers.metrics import MockMetricsProvider

        scenario = kwargs["scenario"]
        context_overrides = {}
        if hasattr(scenario, "get_context_overrides"):
            context_overrides = scenario.get_context_overrides()

        return Providers(
            metrics=MockMetricsProvider(scenario.metrics_generator),
            logs=MockLogsProvider(scenario.log_generator),
            knowledge=MockKnowledgeProvider(),
            actions=MockActionsProvider(),
            alerts=MockAlertsProvider(),
            context=MockContextProvider(context_overrides),
        )
    elif mode == "production":
        raise NotImplementedError(
            "Production providers require MCP pool — coming post-funding"
        )
    else:
        raise ValueError(f"Unknown mode: {mode}")
