"""Scenario 3: JVM Memory Leak in payment-service.

Slow heap drift over hours → GC pauses increase → latency degrades → OOM risk.
"""

from __future__ import annotations

import time

from mock.generators.logs import LogGenerator
from mock.generators.metrics import MetricsGenerator
from mock.generators.traces import TraceGenerator

from mock.generators.base import AnomalyType

from .base import BeforeStory, Scenario, ScenarioTimeline


class MemoryLeak(Scenario):
    def get_name(self) -> str:
        return "memory_leak"

    def get_display_name(self) -> str:
        return "JVM Memory Leak (payment-service)"

    def get_description(self) -> str:
        return "payment-service heap drifts upward over hours → GC pauses → latency degradation"

    def get_affected_service(self) -> str:
        return "payment-service"

    def get_timeline(self) -> ScenarioTimeline:
        return ScenarioTimeline(
            normal_start=-3600, anomaly_start=0, alert_time=900,
            resolution_time=960, normal_end=1800,
        )

    def get_before_story(self) -> BeforeStory:
        return BeforeStory(
            steps=[
                ("06:00 AM", "Alert fires: HighHeapUsage on payment-service"),
                ("06:05", "On-call checks JVM dashboard, sees heap at 90%"),
                ("06:10", "GC pauses at 1.2s, p99 latency spiking"),
                ("06:15", "Checks recent deploys — new version 3 days ago"),
                ("06:20", "Captures heap dump for analysis"),
                ("06:25", "Decides to restart as immediate fix"),
                ("06:28", "Runs kubectl rollout restart"),
                ("06:30", "Verifies heap returned to normal"),
                ("06:45", "Files bug for heap dump analysis"),
            ],
            total_mttr_minutes=28,
            manual_steps=8,
        )

    def get_alert_payload(self) -> dict:
        return {
            "status": "firing",
            "labels": {
                "alertname": "HighHeapUsage",
                "service": "payment-service",
                "severity": "warning",
                "namespace": "shopfast-prod",
            },
            "annotations": {
                "summary": "JVM heap usage above 85% for 15 minutes on payment-service",
                "description": "payment-service heap at 1.85GB/2GB. GC pause time 1.2s.",
            },
            "startsAt": "2026-03-31T06:00:00Z",
        }

    def get_matching_runbook_id(self) -> str:
        return "RB-003"

    def get_matching_ticket_keys(self) -> list[str]:
        return ["OPS-1287", "OPS-1245"]

    def get_expected_remediation(self) -> dict:
        return {
            "action": "restart_deployment",
            "namespace": "shopfast-prod",
            "deployment": "payment-service",
        }

    def get_blast_radius(self) -> str:
        return "low"

    def get_context_overrides(self) -> dict:
        return {
            "recent_deploys": [
                {"service": "payment-service", "minutes_ago": 90, "version": "v2.3.0"}
            ],
        }

    def configure_metrics(self, gen: MetricsGenerator) -> None:
        now = time.time()
        gen.inject_anomaly("payment-service:jvm_heap", AnomalyType.DRIFT, now, 900, 1.7)
        gen.inject_anomaly("payment-service:gc_pause", AnomalyType.DRIFT, now + 600, 300, 15.0)
        gen.inject_anomaly("payment-service:latency_p99", AnomalyType.DRIFT, now + 700, 200, 3.0)

    def configure_logs(self, gen: LogGenerator) -> None:
        gen.set_scenario("memory_leak", ["payment-service"])

    def configure_traces(self, gen: TraceGenerator) -> None:
        gen.set_anomaly("payment-service", "charge", duration_ms=2000, status="OK")


def create_scenario() -> MemoryLeak:
    return MemoryLeak()
