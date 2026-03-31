"""Abstract provider interfaces for all external data sources.

Pipeline nodes depend on these protocols, never on concrete implementations.
Mock providers fulfill these for the demo. Real providers (MCP-backed) swap in
post-funding without changing any pipeline code.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class MetricsProvider(Protocol):
    """Query time-series metrics.

    Mock: generators with diurnal patterns + anomaly injection.
    Real: Prometheus MCP server.
    """

    async def query(
        self,
        metric: str,
        labels: dict[str, str],
        time: str | None = None,
    ) -> dict:
        """Instant query for a metric at a point in time."""
        ...

    async def query_range(
        self,
        metric: str,
        labels: dict[str, str],
        start: str,
        end: str,
        step: str = "15s",
    ) -> dict:
        """Range query returning time-series data."""
        ...

    async def get_alerts(self) -> list[dict]:
        """Return currently firing alerts."""
        ...


@runtime_checkable
class LogsProvider(Protocol):
    """Search structured logs.

    Mock: generated logs from templates.
    Real: Elasticsearch MCP server.
    """

    async def search(
        self,
        service: str | None = None,
        level: str | None = None,
        message_contains: str | None = None,
        trace_id: str | None = None,
        time_from: str | None = None,
        time_to: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """Search logs with optional filters."""
        ...


@runtime_checkable
class KnowledgeProvider(Protocol):
    """Retrieve runbooks, Jira tickets, confluence docs, codebase context.

    Mock: keyword search over static files.
    Real: pgvector similarity search + live MCP queries.
    """

    async def search_similar(
        self,
        query: str,
        source_types: list[str] | None = None,
        limit: int = 5,
    ) -> list[dict]:
        """Find knowledge chunks relevant to a query.

        Returns list of dicts with keys: source_type, source_id, title,
        content, score, metadata.
        """
        ...

    async def get_runbook(self, runbook_id: str) -> str | None:
        """Get full runbook content by ID (e.g. 'RB-001')."""
        ...

    async def get_ticket(self, ticket_key: str) -> dict | None:
        """Get a Jira ticket by key (e.g. 'OPS-1234')."""
        ...


@runtime_checkable
class ActionsProvider(Protocol):
    """Execute remediation actions.

    Mock: log action + simulate success.
    Real: Kubernetes MCP server.
    """

    async def restart_deployment(
        self, namespace: str, deployment: str
    ) -> dict:
        """Trigger a rolling restart. Returns action result."""
        ...

    async def scale_deployment(
        self, namespace: str, deployment: str, replicas: int
    ) -> dict:
        """Scale a deployment to a target replica count."""
        ...

    async def get_pods(
        self, namespace: str, label_selector: str | None = None
    ) -> list[dict]:
        """List pods with status."""
        ...


@runtime_checkable
class AlertsProvider(Protocol):
    """Send alerts and approval requests.

    Mock: rich terminal output + log to file.
    Real: Slack MCP + PagerDuty MCP.
    """

    async def send_alert(
        self, channel: str, incident: dict, rca: dict
    ) -> dict:
        """Send an incident alert with RCA context."""
        ...

    async def request_approval(
        self, channel: str, incident: dict, action: dict
    ) -> dict:
        """Send an approval request (for human-in-the-loop)."""
        ...

    async def escalate(self, incident: dict, reason: str) -> dict:
        """Escalate via PagerDuty."""
        ...
