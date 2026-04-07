"""Scenario: EHR Database Connection Pool Exhaustion on patient-service.

Timeline:
- T+0: db_connection_pool_active drifts from 10/20 toward 20/20
- T+8min: db_connection_pool_wait_seconds spikes
- T+10min: Error rate jumps to 50%, alert fires
- Correlated: ehr-gateway latency increases (downstream impact)
- Context: 3 AM, ER running on paper workarounds
"""

from __future__ import annotations

import time

from mock.generators.logs import LogGenerator
from mock.generators.metrics import MetricsGenerator
from mock.generators.traces import TraceGenerator

from mock.generators.base import AnomalyType

from .base import BeforeStory, Scenario, ScenarioTimeline


class EHRDBPoolExhaustion(Scenario):
    def get_name(self) -> str:
        return "ehr_db_pool_exhaustion"

    def get_display_name(self) -> str:
        return "EHR Database Connection Pool Exhaustion"

    def get_description(self) -> str:
        return "patient-service DB pool saturates -> patient record queries fail -> ehr-gateway errors"

    def get_affected_service(self) -> str:
        return "patient-service"

    def get_timeline(self) -> ScenarioTimeline:
        return ScenarioTimeline(
            normal_start=-1800,
            anomaly_start=0,
            alert_time=600,  # 10 min
            resolution_time=660,  # 11 min (after restart)
            normal_end=1800,
        )

    def get_before_story(self) -> BeforeStory:
        return BeforeStory(
            steps=[
                ("03:02 AM", "Alert fires: EHRConnectionPoolExhausted on patient-service"),
                ("03:05", "On-call clinician-IT support wakes up, opens laptop"),
                ("03:08", "Checks Grafana dashboard, sees pool at 20/20 on patient-service"),
                ("03:12", "ER staff reports patient lookup failures, switches to paper workaround"),
                ("03:18", "Searches Confluence for 'patient-service connection pool'"),
                ("03:25", "Finds runbook RB-101, starts investigation"),
                ("03:32", "Checks Jira for similar EHR incidents, finds EHR-1001"),
                ("03:38", "Identifies root cause: connection leak in PatientRepository"),
                ("03:42", "Runs kubectl rollout restart on patient-service"),
                ("03:47", "Verifies FHIR endpoints responding, ER resumes electronic records"),
                ("03:51", "Updates Jira ticket, notifies clinical staff"),
            ],
            total_mttr_minutes=49,
            manual_steps=10,
        )

    def get_alert_payload(self) -> dict:
        return {
            "status": "firing",
            "labels": {
                "alertname": "EHRConnectionPoolExhausted",
                "service": "patient-service",
                "severity": "critical",
                "namespace": "medflow-prod",
            },
            "annotations": {
                "summary": "Database connection pool exhausted on patient-service",
                "description": (
                    "patient-service has 20/20 active DB connections with 53 requests "
                    "waiting. Error rate at 50%. FHIR Patient endpoints returning 500. "
                    "ER staff reporting inability to access patient records."
                ),
                "runbook_url": "https://wiki.medflow.com/runbooks/RB-101",
            },
            "startsAt": "2026-03-31T03:02:00Z",
        }

    def get_matching_runbook_id(self) -> str:
        return "RB-101"

    def get_matching_ticket_keys(self) -> list[str]:
        return ["EHR-1001", "EHR-1003"]

    def get_expected_remediation(self) -> dict:
        return {
            "action": "restart_deployment",
            "namespace": "medflow-prod",
            "deployment": "patient-service",
        }

    def get_blast_radius(self) -> str:
        return "low"

    def configure_metrics(self, gen: MetricsGenerator) -> None:
        now = time.time()
        # Pool active drifts to max over 10 minutes
        gen.inject_anomaly(
            "patient-service:db_pool_active",
            AnomalyType.SATURATION,
            start_time=now,
            duration_seconds=600,
            limit=20.0,
        )
        # Wait time spikes at T+8min
        gen.inject_anomaly(
            "patient-service:db_pool_wait",
            AnomalyType.SPIKE,
            start_time=now + 480,
            duration_seconds=300,
            magnitude=12.0,
        )
        # Error rate spikes at T+10min
        gen.inject_anomaly(
            "patient-service:error_rate",
            AnomalyType.SPIKE,
            start_time=now + 600,
            duration_seconds=300,
            magnitude=500.0,  # 0.001 * 500 ~ 0.50 (50%)
        )
        # Latency spike on patient-service
        gen.inject_anomaly(
            "patient-service:latency_p99",
            AnomalyType.SPIKE,
            start_time=now + 600,
            duration_seconds=300,
            magnitude=6.0,
        )
        # Upstream impact: ehr-gateway latency increases
        gen.inject_anomaly(
            "ehr-gateway:latency_p99",
            AnomalyType.SPIKE,
            start_time=now + 620,
            duration_seconds=280,
            magnitude=4.0,
        )

    def configure_logs(self, gen: LogGenerator) -> None:
        gen.set_scenario("db_pool_exhaustion", ["patient-service"])

    def configure_traces(self, gen: TraceGenerator) -> None:
        gen.set_anomaly(
            "patient-service",
            "create_patient",
            duration_ms=5000,
            status="ERROR",
            error_message="could not acquire database connection within 5000ms",
        )


def create_scenario() -> EHRDBPoolExhaustion:
    return EHRDBPoolExhaustion()
