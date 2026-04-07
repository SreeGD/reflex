"""Scenario: Medication Service Slow Query Cascade.

Missing database index on drugs table in medication-service ->
drug interaction checks take >5s -> cascades to patient-service and ehr-gateway.
"""

from __future__ import annotations

import time

from mock.generators.logs import LogGenerator
from mock.generators.metrics import MetricsGenerator
from mock.generators.traces import TraceGenerator

from mock.generators.base import AnomalyType

from .base import BeforeStory, Scenario, ScenarioTimeline


class MedicationSlowQuery(Scenario):
    def get_name(self) -> str:
        return "medication_slow_query"

    def get_display_name(self) -> str:
        return "Medication Service Slow Query Cascade"

    def get_description(self) -> str:
        return "medication-service slow query on drugs table -> drug interaction checks >5s -> cascades to patient-service"

    def get_affected_service(self) -> str:
        return "medication-service"

    def get_timeline(self) -> ScenarioTimeline:
        return ScenarioTimeline(
            normal_start=-1800, anomaly_start=0, alert_time=360,
            resolution_time=420, normal_end=1800,
        )

    def get_before_story(self) -> BeforeStory:
        return BeforeStory(
            steps=[
                ("11:30 AM", "Alert fires: MedicationSlowQueryDetected on medication-service"),
                ("11:33", "On-call checks medication-service dashboard"),
                ("11:37", "Sees p99 latency at 5.2s on /api/v1/interactions endpoint"),
                ("11:42", "Clinicians report drug interaction checks hanging during order entry"),
                ("11:48", "Checks PostgreSQL slow query log, finds full table scan on drugs table"),
                ("11:55", "Identifies missing index on drugs.ndc_code column"),
                ("12:02 PM", "Restarts medication-service to clear query plan cache"),
                ("12:05", "Interaction checks return to <200ms, clinicians resume ordering"),
                ("12:10", "Creates follow-up ticket for CREATE INDEX CONCURRENTLY"),
            ],
            total_mttr_minutes=40,
            manual_steps=8,
        )

    def get_alert_payload(self) -> dict:
        return {
            "status": "firing",
            "labels": {
                "alertname": "MedicationSlowQueryDetected",
                "service": "medication-service",
                "severity": "warning",
                "namespace": "medflow-prod",
            },
            "annotations": {
                "summary": "Slow query detected on medication-service",
                "description": (
                    "medication-service p99 latency at 5.2s on /api/v1/interactions. "
                    "Drug interaction checks doing full table scan on drugs table. "
                    "Cascading to patient-service medication order workflow."
                ),
                "runbook_url": "https://wiki.medflow.com/runbooks/RB-105",
            },
            "startsAt": "2026-03-31T11:30:00Z",
        }

    def get_matching_runbook_id(self) -> str:
        return "RB-105"

    def get_matching_ticket_keys(self) -> list[str]:
        return ["EHR-1006"]

    def get_expected_remediation(self) -> dict:
        return {
            "action": "restart_deployment",
            "namespace": "medflow-prod",
            "deployment": "medication-service",
        }

    def get_blast_radius(self) -> str:
        return "low"

    def configure_metrics(self, gen: MetricsGenerator) -> None:
        now = time.time()
        gen.inject_anomaly(
            "medication-service:latency_p99",
            AnomalyType.SPIKE,
            start_time=now,
            duration_seconds=420,
            magnitude=25.0,
        )
        gen.inject_anomaly(
            "medication-service:error_rate",
            AnomalyType.SPIKE,
            start_time=now + 240,
            duration_seconds=180,
            magnitude=200.0,
        )
        # Cascading impact on patient-service
        gen.inject_anomaly(
            "patient-service:latency_p99",
            AnomalyType.SPIKE,
            start_time=now + 120,
            duration_seconds=300,
            magnitude=3.0,
        )
        # ehr-gateway sees elevated latency
        gen.inject_anomaly(
            "ehr-gateway:latency_p99",
            AnomalyType.SPIKE,
            start_time=now + 180,
            duration_seconds=240,
            magnitude=2.0,
        )

    def configure_logs(self, gen: LogGenerator) -> None:
        gen.set_scenario("slow_query", ["medication-service"])

    def configure_traces(self, gen: TraceGenerator) -> None:
        gen.set_anomaly(
            "medication-service",
            "check_drug_interactions",
            duration_ms=5200,
            status="ERROR",
            error_message="Query execution exceeded 5000ms threshold on drugs table",
        )


def create_scenario() -> MedicationSlowQuery:
    return MedicationSlowQuery()
