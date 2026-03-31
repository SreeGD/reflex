"""Scenario 1: Database Connection Pool Exhaustion on order-service.

Timeline:
- T+0: db_connection_pool_active drifts from 12/20 toward 20/20
- T+8min: db_connection_pool_wait_seconds spikes
- T+10min: Error rate jumps to 45%, alert fires
- Correlated: api-gateway latency increases (downstream impact)
"""

from __future__ import annotations

import time

from mock.generators.logs import LogGenerator
from mock.generators.metrics import MetricsGenerator
from mock.generators.traces import TraceGenerator

from mock.generators.base import AnomalyType

from .base import BeforeStory, Scenario, ScenarioTimeline


class DBPoolExhaustion(Scenario):
    def get_name(self) -> str:
        return "db_pool_exhaustion"

    def get_display_name(self) -> str:
        return "Database Connection Pool Exhaustion"

    def get_description(self) -> str:
        return "order-service DB pool saturates → checkout failures → api-gateway errors"

    def get_affected_service(self) -> str:
        return "order-service"

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
                ("03:22 AM", "Alert fires: DBConnectionPoolExhausted"),
                ("03:25", "On-call engineer wakes up, opens laptop"),
                ("03:28", "Checks Grafana dashboard, sees pool at 20/20"),
                ("03:30", "Searches Confluence for 'connection pool'"),
                ("03:35", "Finds runbook RB-001, starts investigation"),
                ("03:42", "Checks Jira for similar incidents"),
                ("03:48", "Identifies root cause: connection leak"),
                ("03:52", "Runs kubectl rollout restart"),
                ("03:55", "Verifies fix, updates Jira ticket"),
            ],
            total_mttr_minutes=33,
            manual_steps=8,
        )

    def get_alert_payload(self) -> dict:
        return {
            "status": "firing",
            "labels": {
                "alertname": "DBConnectionPoolExhausted",
                "service": "order-service",
                "severity": "critical",
                "namespace": "shopfast-prod",
            },
            "annotations": {
                "summary": "Database connection pool exhausted on order-service",
                "description": (
                    "order-service has 20/20 active DB connections with 47 requests "
                    "waiting. Error rate at 45%."
                ),
                "runbook_url": "https://wiki.shopfast.com/runbooks/RB-001",
            },
            "startsAt": "2026-03-31T10:10:00Z",
        }

    def get_matching_runbook_id(self) -> str:
        return "RB-001"

    def get_matching_ticket_keys(self) -> list[str]:
        return ["OPS-1234", "OPS-1198", "OPS-1056"]

    def get_expected_remediation(self) -> dict:
        return {
            "action": "restart_deployment",
            "namespace": "shopfast-prod",
            "deployment": "order-service",
        }

    def get_blast_radius(self) -> str:
        return "low"

    def configure_metrics(self, gen: MetricsGenerator) -> None:
        now = time.time()
        # Pool active drifts to max over 10 minutes
        gen.inject_anomaly(
            "order-service:db_pool_active",
            AnomalyType.SATURATION,
            start_time=now,
            duration_seconds=600,
            limit=20.0,
        )
        # Wait time spikes at T+8min
        gen.inject_anomaly(
            "order-service:db_pool_wait",
            AnomalyType.SPIKE,
            start_time=now + 480,
            duration_seconds=300,
            magnitude=10.0,
        )
        # Error rate spikes at T+10min
        gen.inject_anomaly(
            "order-service:error_rate",
            AnomalyType.SPIKE,
            start_time=now + 600,
            duration_seconds=300,
            magnitude=450.0,  # 0.001 * 450 ≈ 0.45 (45%)
        )
        # Latency spike on order-service
        gen.inject_anomaly(
            "order-service:latency_p99",
            AnomalyType.SPIKE,
            start_time=now + 600,
            duration_seconds=300,
            magnitude=5.0,
        )
        # Upstream impact: api-gateway latency increases
        gen.inject_anomaly(
            "api-gateway:latency_p99",
            AnomalyType.SPIKE,
            start_time=now + 620,
            duration_seconds=280,
            magnitude=3.0,
        )

    def configure_logs(self, gen: LogGenerator) -> None:
        gen.set_scenario("db_pool_exhaustion", ["order-service"])

    def configure_traces(self, gen: TraceGenerator) -> None:
        gen.set_anomaly(
            "order-service",
            "create_order",
            duration_ms=5000,
            status="ERROR",
            error_message="could not acquire database connection within 5000ms",
        )


def create_scenario() -> DBPoolExhaustion:
    return DBPoolExhaustion()
