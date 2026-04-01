"""Scenario 2: Payment Gateway Timeout Cascade.

External payment gateway goes slow → payment-service threads block →
order-service times out → api-gateway errors cascade.
"""

from __future__ import annotations

import time

from mock.generators.logs import LogGenerator
from mock.generators.metrics import MetricsGenerator
from mock.generators.traces import TraceGenerator

from mock.generators.base import AnomalyType

from .base import BeforeStory, Scenario, ScenarioTimeline


class PaymentTimeoutCascade(Scenario):
    def get_name(self) -> str:
        return "payment_timeout_cascade"

    def get_display_name(self) -> str:
        return "Payment Gateway Timeout Cascade"

    def get_description(self) -> str:
        return "External payment gateway slow → cascading timeouts across order + api-gateway"

    def get_affected_service(self) -> str:
        return "payment-service"

    def get_timeline(self) -> ScenarioTimeline:
        return ScenarioTimeline(
            normal_start=-1800, anomaly_start=0, alert_time=300,
            resolution_time=600, normal_end=1800,
        )

    def get_before_story(self) -> BeforeStory:
        return BeforeStory(
            steps=[
                ("02:15 AM", "Alert fires: PaymentGatewayTimeout"),
                ("02:18", "On-call checks payment-service dashboard"),
                ("02:22", "Sees p99 at 30s, suspects external gateway"),
                ("02:28", "Checks gateway status page — degraded"),
                ("02:35", "Tries scaling payment-service replicas"),
                ("02:40", "Realizes circuit breaker not configured"),
                ("02:45", "Manually enables fallback payment provider"),
                ("02:50", "Verifies recovery, updates ticket"),
            ],
            total_mttr_minutes=35,
            manual_steps=7,
        )

    def get_alert_payload(self) -> dict:
        return {
            "status": "firing",
            "labels": {
                "alertname": "PaymentGatewayTimeout",
                "service": "payment-service",
                "severity": "critical",
                "namespace": "shopfast-prod",
            },
            "annotations": {
                "summary": "Payment gateway timeout on payment-service",
                "description": "payment-service p99 latency at 30s. External gateway timeouts. Error rate 35%.",
            },
            "startsAt": "2026-03-31T02:15:00Z",
        }

    def get_matching_runbook_id(self) -> str:
        return "RB-002"

    def get_matching_ticket_keys(self) -> list[str]:
        return ["OPS-1301", "OPS-1334"]

    def get_expected_remediation(self) -> dict:
        return {
            "action": "scale_deployment",
            "namespace": "shopfast-prod",
            "deployment": "payment-service",
            "replicas": 4,
        }

    def get_blast_radius(self) -> str:
        return "medium"

    def get_context_overrides(self) -> dict:
        return {
            "recent_deploys": [
                {"service": "payment-service", "minutes_ago": 45, "version": "v2.3.1"}
            ],
        }

    def configure_metrics(self, gen: MetricsGenerator) -> None:
        now = time.time()
        gen.inject_anomaly("payment-service:latency_p99", AnomalyType.SPIKE, now, 600, 100.0)
        gen.inject_anomaly("payment-service:error_rate", AnomalyType.SPIKE, now + 120, 480, 350.0)
        gen.inject_anomaly("order-service:latency_p99", AnomalyType.SPIKE, now + 180, 420, 4.0)
        gen.inject_anomaly("api-gateway:error_rate", AnomalyType.SPIKE, now + 300, 300, 200.0)

    def configure_logs(self, gen: LogGenerator) -> None:
        gen.set_scenario("gateway_timeout", ["payment-service"])

    def configure_traces(self, gen: TraceGenerator) -> None:
        gen.set_anomaly("payment-service", "gateway_call", duration_ms=30000, status="ERROR",
                        error_message="Payment gateway timeout after 30000ms")


def create_scenario() -> PaymentTimeoutCascade:
    return PaymentTimeoutCascade()
