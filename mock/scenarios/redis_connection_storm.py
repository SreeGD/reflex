"""Scenario 4: Redis Connection Storm on cart-service.

Sudden spike in Redis connections → pool exhaustion → cart operations fail.
"""

from __future__ import annotations

import time

from mock.generators.logs import LogGenerator
from mock.generators.metrics import MetricsGenerator
from mock.generators.traces import TraceGenerator

from mock.generators.base import AnomalyType

from .base import BeforeStory, Scenario, ScenarioTimeline


class RedisConnectionStorm(Scenario):
    def get_name(self) -> str:
        return "redis_connection_storm"

    def get_display_name(self) -> str:
        return "Redis Connection Storm (cart-service)"

    def get_description(self) -> str:
        return "cart-service Redis pool spikes to 50/50 → timeout errors → cart failures"

    def get_affected_service(self) -> str:
        return "cart-service"

    def get_timeline(self) -> ScenarioTimeline:
        return ScenarioTimeline(
            normal_start=-1800, anomaly_start=0, alert_time=120,
            resolution_time=180, normal_end=1800,
        )

    def get_before_story(self) -> BeforeStory:
        return BeforeStory(
            steps=[
                ("11:30 AM", "Alert fires: RedisPoolExhausted on cart-service"),
                ("11:32", "On-call checks Redis dashboard"),
                ("11:35", "Sees 50/50 connections, timeout errors"),
                ("11:38", "Checks for recent deploys — none"),
                ("11:40", "Restarts cart-service pods"),
                ("11:43", "Verifies connections dropped, service healthy"),
                ("11:45", "Updates ticket with root cause"),
            ],
            total_mttr_minutes=15,
            manual_steps=6,
        )

    def get_alert_payload(self) -> dict:
        return {
            "status": "firing",
            "labels": {
                "alertname": "RedisPoolExhausted",
                "service": "cart-service",
                "severity": "critical",
                "namespace": "shopfast-prod",
            },
            "annotations": {
                "summary": "Redis connection pool exhausted on cart-service",
                "description": "cart-service Redis pool at 50/50. p99 latency 5000ms.",
            },
            "startsAt": "2026-03-31T11:30:00Z",
        }

    def get_matching_runbook_id(self) -> str:
        return "RB-004"

    def get_matching_ticket_keys(self) -> list[str]:
        return ["OPS-1312"]

    def get_expected_remediation(self) -> dict:
        return {
            "action": "restart_deployment",
            "namespace": "shopfast-prod",
            "deployment": "cart-service",
        }

    def get_blast_radius(self) -> str:
        return "low"

    def configure_metrics(self, gen: MetricsGenerator) -> None:
        now = time.time()
        gen.inject_anomaly("cart-service:redis_pool_active", AnomalyType.SPIKE, now, 300, 2.5)
        gen.inject_anomaly("cart-service:latency_p99", AnomalyType.SPIKE, now, 300, 100.0)
        gen.inject_anomaly("cart-service:error_rate", AnomalyType.SPIKE, now + 60, 240, 300.0)

    def configure_logs(self, gen: LogGenerator) -> None:
        gen.set_scenario("redis_pool_exhaustion", ["cart-service"])

    def configure_traces(self, gen: TraceGenerator) -> None:
        gen.set_anomaly("cart-service", "add_item", duration_ms=5000, status="ERROR",
                        error_message="Redis connection pool exhausted (active: 50/50)")


def create_scenario() -> RedisConnectionStorm:
    return RedisConnectionStorm()
