"""Scenario: Pharmacy Service Memory Leak.

JVM heap usage drifts upward on pharmacy-service -> GC pauses ->
medication dispensing delays -> cascades to patient-service and alert-service.
"""

from __future__ import annotations

import time

from mock.generators.logs import LogGenerator
from mock.generators.metrics import MetricsGenerator
from mock.generators.traces import TraceGenerator

from mock.generators.base import AnomalyType

from .base import BeforeStory, Scenario, ScenarioTimeline


class PharmacyMemoryLeak(Scenario):
    def get_name(self) -> str:
        return "pharmacy_memory_leak"

    def get_display_name(self) -> str:
        return "Pharmacy Service Memory Leak"

    def get_description(self) -> str:
        return "pharmacy-service JVM heap leak -> GC pauses -> dispensing delays"

    def get_affected_service(self) -> str:
        return "pharmacy-service"

    def get_timeline(self) -> ScenarioTimeline:
        return ScenarioTimeline(
            normal_start=-3600, anomaly_start=0, alert_time=900,
            resolution_time=960, normal_end=1800,
        )

    def get_before_story(self) -> BeforeStory:
        return BeforeStory(
            steps=[
                ("06:30 AM", "Alert fires: PharmacyHighHeapUsage on pharmacy-service"),
                ("06:33", "On-call checks pharmacy-service Grafana dashboard"),
                ("06:37", "Sees heap at 92% of 4GB limit, GC pause times >1.5s"),
                ("06:42", "Pharmacy technicians report dispensing queue frozen"),
                ("06:48", "Reviews recent deploys, finds v2.4.0 deployed 90 min ago"),
                ("06:55", "Checks thread dump, identifies leak in DrugInteractionCache"),
                ("07:02", "Restarts pharmacy-service pods"),
                ("07:06", "Heap returns to normal, dispensing resumes"),
                ("07:10", "Updates Jira, flags v2.4.0 for rollback review"),
            ],
            total_mttr_minutes=40,
            manual_steps=8,
        )

    def get_alert_payload(self) -> dict:
        return {
            "status": "firing",
            "labels": {
                "alertname": "PharmacyHighHeapUsage",
                "service": "pharmacy-service",
                "severity": "warning",
                "namespace": "medflow-prod",
            },
            "annotations": {
                "summary": "High JVM heap usage on pharmacy-service",
                "description": (
                    "pharmacy-service heap usage at 92% of 4GB limit. GC pause times "
                    "exceeding 1.5 seconds. Medication dispensing latency at 8s p99. "
                    "Risk of OutOfMemoryError within 20 minutes."
                ),
                "runbook_url": "https://wiki.medflow.com/runbooks/RB-103",
            },
            "startsAt": "2026-03-31T06:30:00Z",
        }

    def get_matching_runbook_id(self) -> str:
        return "RB-103"

    def get_matching_ticket_keys(self) -> list[str]:
        return ["EHR-1004"]

    def get_expected_remediation(self) -> dict:
        return {
            "action": "restart_deployment",
            "namespace": "medflow-prod",
            "deployment": "pharmacy-service",
        }

    def get_blast_radius(self) -> str:
        return "low"

    def get_context_overrides(self) -> dict:
        return {
            "recent_deploys": [
                {"service": "pharmacy-service", "minutes_ago": 90, "version": "v2.4.0"}
            ],
        }

    def configure_metrics(self, gen: MetricsGenerator) -> None:
        now = time.time()
        gen.inject_anomaly(
            "pharmacy-service:jvm_heap_used",
            AnomalyType.SATURATION,
            start_time=now,
            duration_seconds=900,
            limit=0.92,
        )
        gen.inject_anomaly(
            "pharmacy-service:gc_pause_seconds",
            AnomalyType.SPIKE,
            start_time=now + 600,
            duration_seconds=300,
            magnitude=15.0,
        )
        gen.inject_anomaly(
            "pharmacy-service:latency_p99",
            AnomalyType.SPIKE,
            start_time=now + 600,
            duration_seconds=300,
            magnitude=8.0,
        )
        gen.inject_anomaly(
            "pharmacy-service:error_rate",
            AnomalyType.SPIKE,
            start_time=now + 800,
            duration_seconds=200,
            magnitude=200.0,
        )

    def configure_logs(self, gen: LogGenerator) -> None:
        gen.set_scenario("memory_leak", ["pharmacy-service"])

    def configure_traces(self, gen: TraceGenerator) -> None:
        gen.set_anomaly(
            "pharmacy-service",
            "dispense_medication",
            duration_ms=8000,
            status="ERROR",
            error_message="GC overhead limit exceeded during medication dispensing",
        )


def create_scenario() -> PharmacyMemoryLeak:
    return PharmacyMemoryLeak()
