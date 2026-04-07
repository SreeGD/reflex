"""Scenario: Scheduling Service Redis Connection Storm.

Redis connection pool exhaustion on scheduling-service ->
appointment booking failures -> bed management stale data.
"""

from __future__ import annotations

import time

from mock.generators.logs import LogGenerator
from mock.generators.metrics import MetricsGenerator
from mock.generators.traces import TraceGenerator

from mock.generators.base import AnomalyType

from .base import BeforeStory, Scenario, ScenarioTimeline


class SchedulingRedisStorm(Scenario):
    def get_name(self) -> str:
        return "scheduling_redis_storm"

    def get_display_name(self) -> str:
        return "Scheduling Service Redis Connection Storm"

    def get_description(self) -> str:
        return "scheduling-service Redis pool exhausted -> appointment booking fails -> bed management stale"

    def get_affected_service(self) -> str:
        return "scheduling-service"

    def get_timeline(self) -> ScenarioTimeline:
        return ScenarioTimeline(
            normal_start=-1800, anomaly_start=0, alert_time=420,
            resolution_time=480, normal_end=1800,
        )

    def get_before_story(self) -> BeforeStory:
        return BeforeStory(
            steps=[
                ("08:15 AM", "Alert fires: SchedulingRedisPoolExhausted"),
                ("08:18", "On-call checks scheduling-service dashboard"),
                ("08:22", "Sees Redis connections at 50/50, all slots occupied"),
                ("08:26", "Front desk reports appointment booking system down"),
                ("08:30", "Patients in waiting room cannot be checked in electronically"),
                ("08:35", "Identifies connection leak in session cache handler"),
                ("08:40", "Restarts scheduling-service pods"),
                ("08:44", "Redis connections return to normal, bookings resume"),
                ("08:48", "Updates Jira, notifies clinical operations"),
            ],
            total_mttr_minutes=33,
            manual_steps=8,
        )

    def get_alert_payload(self) -> dict:
        return {
            "status": "firing",
            "labels": {
                "alertname": "SchedulingRedisPoolExhausted",
                "service": "scheduling-service",
                "severity": "warning",
                "namespace": "medflow-prod",
            },
            "annotations": {
                "summary": "Redis connection pool exhausted on scheduling-service",
                "description": (
                    "scheduling-service has 50/50 active Redis connections. "
                    "Appointment booking API returning timeout errors. Bed management "
                    "dashboard showing stale data."
                ),
                "runbook_url": "https://wiki.medflow.com/runbooks/RB-104",
            },
            "startsAt": "2026-03-31T08:15:00Z",
        }

    def get_matching_runbook_id(self) -> str:
        return "RB-104"

    def get_matching_ticket_keys(self) -> list[str]:
        return ["EHR-1005"]

    def get_expected_remediation(self) -> dict:
        return {
            "action": "restart_deployment",
            "namespace": "medflow-prod",
            "deployment": "scheduling-service",
        }

    def get_blast_radius(self) -> str:
        return "low"

    def configure_metrics(self, gen: MetricsGenerator) -> None:
        now = time.time()
        gen.inject_anomaly(
            "scheduling-service:redis_pool_active",
            AnomalyType.SATURATION,
            start_time=now,
            duration_seconds=420,
            limit=50.0,
        )
        gen.inject_anomaly(
            "scheduling-service:redis_pool_wait",
            AnomalyType.SPIKE,
            start_time=now + 300,
            duration_seconds=180,
            magnitude=8.0,
        )
        gen.inject_anomaly(
            "scheduling-service:error_rate",
            AnomalyType.SPIKE,
            start_time=now + 420,
            duration_seconds=180,
            magnitude=350.0,
        )
        gen.inject_anomaly(
            "scheduling-service:latency_p99",
            AnomalyType.SPIKE,
            start_time=now + 360,
            duration_seconds=180,
            magnitude=6.0,
        )

    def configure_logs(self, gen: LogGenerator) -> None:
        gen.set_scenario("redis_pool_exhaustion", ["scheduling-service"])

    def configure_traces(self, gen: TraceGenerator) -> None:
        gen.set_anomaly(
            "scheduling-service",
            "book_appointment",
            duration_ms=6000,
            status="ERROR",
            error_message="Redis connection pool exhausted - timeout after 5000ms",
        )


def create_scenario() -> SchedulingRedisStorm:
    return SchedulingRedisStorm()
