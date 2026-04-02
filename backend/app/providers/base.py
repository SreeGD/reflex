"""Abstract provider interfaces for all external data sources.

Pipeline nodes depend on these protocols, never on concrete implementations.
Mock providers fulfill these for the demo. Real providers (MCP-backed) swap in
post-funding without changing any pipeline code.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


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
        time: Optional[str] = None,
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
        service: Optional[str] = None,
        level: Optional[str] = None,
        message_contains: Optional[str] = None,
        trace_id: Optional[str] = None,
        time_from: Optional[str] = None,
        time_to: Optional[str] = None,
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
        source_types: Optional[list[str]] = None,
        limit: int = 5,
    ) -> list[dict]:
        """Find knowledge chunks relevant to a query.

        Returns list of dicts with keys: source_type, source_id, title,
        content, score, metadata.
        """
        ...

    async def get_runbook(self, runbook_id: str) -> Optional[str]:
        """Get full runbook content by ID (e.g. 'RB-001')."""
        ...

    async def get_ticket(self, ticket_key: str) -> Optional[dict]:
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
        self, namespace: str, label_selector: Optional[str] = None
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


@runtime_checkable
class ContextProvider(Protocol):
    """Provides environmental context for dynamic risk assessment.

    Mock: returns scenario-configured context.
    Real: queries Kubernetes, incident DB, deploy tracker, service catalog.
    """

    async def get_environment_context(self, service: str) -> dict:
        """Returns context dict with keys:
        - current_hour_utc: int
        - is_change_freeze: bool
        - recent_deploys: list[dict] (service, minutes_ago)
        - active_incident_count: int
        - recent_action_history: list[dict] (action, service, status)
        - service_tier: int (1-3)
        """
        ...


@runtime_checkable
class LLMProvider(Protocol):
    """Provides LLM instances configured per purpose.

    Mock: returns MockLLM or MockChatLLM.
    Real: returns ChatAnthropic or ChatOpenAI with appropriate settings.
    """

    def get_model(self, purpose: str = "chat") -> Any:
        """Return an LLM instance for the given purpose.

        Purposes:
        - "chat": Conversational agent (may use higher temperature)
        - "rca": Root cause analysis (temperature=0, deterministic)
        - "review": Review/critique (temperature=0, deterministic)
        """
        ...
