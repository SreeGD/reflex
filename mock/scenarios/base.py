"""Base class for incident scenarios.

Each scenario defines: what goes wrong, what data looks like during the incident,
what knowledge matches, and what remediation should happen.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from mock.generators.logs import LogGenerator
from mock.generators.metrics import MetricsGenerator
from mock.generators.traces import TraceGenerator


@dataclass
class ScenarioTimeline:
    """Timeline for an incident scenario (all values are relative to T=0)."""

    normal_start: float  # Start of baseline period (negative, e.g., -1800 = 30min before)
    anomaly_start: float  # When the anomaly begins (0 = incident start)
    alert_time: float  # When alert fires
    resolution_time: float  # When remediation resolves it
    normal_end: float  # End of post-resolution period


@dataclass
class BeforeStory:
    """The 'manual ops' timeline shown in the demo for contrast."""

    steps: list[tuple[str, str]]  # (time offset like "03:22 AM", description)
    total_mttr_minutes: int
    manual_steps: int


class Scenario(ABC):
    """Base class for all incident scenarios."""

    def __init__(self) -> None:
        self.metrics_generator = MetricsGenerator()
        self.log_generator = LogGenerator()
        self.trace_generator = TraceGenerator()
        self._configure()

    def _configure(self) -> None:
        """Called during __init__ to set up generators with anomalies."""
        self.configure_metrics(self.metrics_generator)
        self.configure_logs(self.log_generator)
        self.configure_traces(self.trace_generator)

    @abstractmethod
    def get_name(self) -> str:
        """Short identifier (e.g., 'db_pool_exhaustion')."""
        ...

    @abstractmethod
    def get_display_name(self) -> str:
        """Human-readable name for demo output."""
        ...

    @abstractmethod
    def get_description(self) -> str:
        """One-line description."""
        ...

    @abstractmethod
    def get_affected_service(self) -> str:
        """Primary service affected."""
        ...

    @abstractmethod
    def get_timeline(self) -> ScenarioTimeline:
        ...

    @abstractmethod
    def get_before_story(self) -> BeforeStory:
        """The manual ops story for BEFORE/AFTER comparison."""
        ...

    @abstractmethod
    def get_alert_payload(self) -> dict:
        """Alertmanager-style webhook payload that triggers the pipeline."""
        ...

    @abstractmethod
    def get_matching_runbook_id(self) -> str:
        """Runbook ID that matches (e.g., 'RB-001')."""
        ...

    @abstractmethod
    def get_matching_ticket_keys(self) -> list[str]:
        """Jira ticket keys that match."""
        ...

    @abstractmethod
    def get_expected_remediation(self) -> dict:
        """Expected remediation action."""
        ...

    @abstractmethod
    def get_blast_radius(self) -> str:
        """'low', 'medium', or 'high'."""
        ...

    @abstractmethod
    def configure_metrics(self, gen: MetricsGenerator) -> None:
        """Inject anomalies into the metrics generator."""
        ...

    @abstractmethod
    def configure_logs(self, gen: LogGenerator) -> None:
        """Configure error log patterns."""
        ...

    @abstractmethod
    def configure_traces(self, gen: TraceGenerator) -> None:
        """Configure anomalous traces."""
        ...
