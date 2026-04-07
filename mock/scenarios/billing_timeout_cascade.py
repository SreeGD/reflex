"""Scenario: Billing Insurance Verification Timeout Cascade.

Insurance verification API goes slow -> billing-service threads block ->
claims processing halts -> EDI 837/835 failures cascade.
"""

from __future__ import annotations

import time

from mock.generators.logs import LogGenerator
from mock.generators.metrics import MetricsGenerator
from mock.generators.traces import TraceGenerator

from mock.generators.base import AnomalyType

from .base import BeforeStory, Scenario, ScenarioTimeline


class BillingTimeoutCascade(Scenario):
    def get_name(self) -> str:
        return "billing_timeout_cascade"

    def get_display_name(self) -> str:
        return "Billing Insurance Verification Timeout Cascade"

    def get_description(self) -> str:
        return "Insurance verification API slow -> billing-service threads block -> claims backed up"

    def get_affected_service(self) -> str:
        return "billing-service"

    def get_timeline(self) -> ScenarioTimeline:
        return ScenarioTimeline(
            normal_start=-1800, anomaly_start=0, alert_time=300,
            resolution_time=600, normal_end=1800,
        )

    def get_before_story(self) -> BeforeStory:
        return BeforeStory(
            steps=[
                ("10:15 AM", "Alert fires: BillingInsuranceTimeout on billing-service"),
                ("10:18", "On-call checks billing-service dashboard"),
                ("10:22", "Sees p99 at 25s, suspects insurance verification API"),
                ("10:28", "Checks clearinghouse status page -- degraded performance"),
                ("10:35", "Claims queue backing up, EDI 837 submissions failing"),
                ("10:42", "Tries scaling billing-service replicas to absorb backlog"),
                ("10:48", "Revenue cycle team reports claims not processing"),
                ("10:55", "Manually increases timeout and scales to 4 replicas"),
                ("11:00", "Verifies claims processing resuming, updates ticket"),
            ],
            total_mttr_minutes=45,
            manual_steps=8,
        )

    def get_alert_payload(self) -> dict:
        return {
            "status": "firing",
            "labels": {
                "alertname": "BillingInsuranceTimeout",
                "service": "billing-service",
                "severity": "critical",
                "namespace": "medflow-prod",
            },
            "annotations": {
                "summary": "Insurance verification timeout on billing-service",
                "description": (
                    "billing-service p99 latency at 25s. Insurance verification API "
                    "timeouts. EDI 837 submission error rate at 38%. Claims queue depth "
                    "at 2,400 and growing."
                ),
            },
            "startsAt": "2026-03-31T10:15:00Z",
        }

    def get_matching_runbook_id(self) -> str:
        return "RB-102"

    def get_matching_ticket_keys(self) -> list[str]:
        return ["EHR-1002"]

    def get_expected_remediation(self) -> dict:
        return {
            "action": "scale_deployment",
            "namespace": "medflow-prod",
            "deployment": "billing-service",
            "replicas": 4,
        }

    def get_blast_radius(self) -> str:
        return "medium"

    def get_context_overrides(self) -> dict:
        return {
            "recent_deploys": [
                {"service": "billing-service", "minutes_ago": 45, "version": "v3.1.0"}
            ],
        }

    def configure_metrics(self, gen: MetricsGenerator) -> None:
        now = time.time()
        gen.inject_anomaly("billing-service:latency_p99", AnomalyType.SPIKE, now, 600, 80.0)
        gen.inject_anomaly("billing-service:error_rate", AnomalyType.SPIKE, now + 120, 480, 380.0)
        gen.inject_anomaly("ehr-gateway:latency_p99", AnomalyType.SPIKE, now + 180, 420, 3.0)
        gen.inject_anomaly("ehr-gateway:error_rate", AnomalyType.SPIKE, now + 300, 300, 150.0)

    def configure_logs(self, gen: LogGenerator) -> None:
        gen.set_scenario("gateway_timeout", ["billing-service"])

    def configure_traces(self, gen: TraceGenerator) -> None:
        gen.set_anomaly("billing-service", "verify_insurance", duration_ms=25000, status="ERROR",
                        error_message="Insurance verification API timeout after 25000ms")


def create_scenario() -> BillingTimeoutCascade:
    return BillingTimeoutCascade()
