"""Scenario 5: Slow Query Cascade from inventory-service.

Missing index → inventory-service p99 spikes → cascades to catalog, order, api-gateway.
"""

from __future__ import annotations

import time

from mock.generators.logs import LogGenerator
from mock.generators.metrics import MetricsGenerator
from mock.generators.traces import TraceGenerator

from mock.generators.base import AnomalyType

from .base import BeforeStory, Scenario, ScenarioTimeline


class SlowQueryCascade(Scenario):
    def get_name(self) -> str:
        return "slow_query_cascade"

    def get_display_name(self) -> str:
        return "Slow Query Cascade (inventory-service)"

    def get_description(self) -> str:
        return "inventory-service slow query → cascades to catalog, order, api-gateway"

    def get_affected_service(self) -> str:
        return "inventory-service"

    def get_timeline(self) -> ScenarioTimeline:
        return ScenarioTimeline(
            normal_start=-1800, anomaly_start=0, alert_time=180,
            resolution_time=300, normal_end=1800,
        )

    def get_before_story(self) -> BeforeStory:
        return BeforeStory(
            steps=[
                ("09:00 AM", "Alert fires: SlowQueryDetected on inventory-service"),
                ("09:03", "On-call sees p99 at 4.5s on stock endpoint"),
                ("09:08", "Notices catalog-service and order-service also slow"),
                ("09:12", "Checks inventory-service logs: slow query on sku lookup"),
                ("09:18", "Runs EXPLAIN — full table scan, missing index"),
                ("09:22", "Restarts inventory-service (clears query cache)"),
                ("09:25", "Files ticket for DBA to add index"),
            ],
            total_mttr_minutes=25,
            manual_steps=6,
        )

    def get_alert_payload(self) -> dict:
        return {
            "status": "firing",
            "labels": {
                "alertname": "SlowQueryDetected",
                "service": "inventory-service",
                "severity": "warning",
                "namespace": "shopfast-prod",
            },
            "annotations": {
                "summary": "Slow query detected on inventory-service",
                "description": "inventory-service /api/v1/stock p99 at 4.5s. SELECT on products table taking >4s.",
            },
            "startsAt": "2026-03-31T09:00:00Z",
        }

    def get_matching_runbook_id(self) -> str:
        return "RB-008"

    def get_matching_ticket_keys(self) -> list[str]:
        return ["OPS-1267"]

    def get_expected_remediation(self) -> dict:
        return {
            "action": "restart_deployment",
            "namespace": "shopfast-prod",
            "deployment": "inventory-service",
        }

    def get_blast_radius(self) -> str:
        return "low"

    def configure_metrics(self, gen: MetricsGenerator) -> None:
        now = time.time()
        gen.inject_anomaly("inventory-service:latency_p99", AnomalyType.SPIKE, now, 600, 90.0)
        gen.inject_anomaly("catalog-service:latency_p99", AnomalyType.SPIKE, now + 60, 540, 4.0)
        gen.inject_anomaly("order-service:latency_p99", AnomalyType.SPIKE, now + 120, 480, 3.0)
        gen.inject_anomaly("api-gateway:latency_p99", AnomalyType.SPIKE, now + 180, 420, 2.5)

    def configure_logs(self, gen: LogGenerator) -> None:
        gen.set_scenario("slow_query", ["inventory-service"])

    def configure_traces(self, gen: TraceGenerator) -> None:
        gen.set_anomaly("inventory-service", "db_query", duration_ms=4500, status="OK",
                        error_message=None)
        gen.set_anomaly("inventory-service", "reserve_stock", duration_ms=4800, status="OK")


def create_scenario() -> SlowQueryCascade:
    return SlowQueryCascade()
