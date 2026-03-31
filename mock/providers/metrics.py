"""Mock MetricsProvider — backed by MetricsGenerator."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from mock.generators.metrics import MetricsGenerator


class MockMetricsProvider:
    """Fulfills MetricsProvider protocol using in-memory generators."""

    def __init__(self, generator: MetricsGenerator) -> None:
        self._gen = generator

    async def query(
        self,
        metric: str,
        labels: dict[str, str],
        time: str | None = None,
    ) -> dict:
        ts = _parse_time(time) if time else datetime.now(tz=timezone.utc).timestamp()
        samples = self._gen.query(metric, labels, ts)
        return {
            "status": "success",
            "data": {
                "resultType": "vector",
                "result": [
                    {
                        "metric": {**s.labels, "__name__": s.name},
                        "value": [s.timestamp, f"{s.value:.4f}"],
                    }
                    for s in samples
                ],
            },
        }

    async def query_range(
        self,
        metric: str,
        labels: dict[str, str],
        start: str,
        end: str,
        step: str = "15s",
    ) -> dict:
        start_ts = _parse_time(start)
        end_ts = _parse_time(end)
        step_seconds = _parse_step(step)
        series_data = self._gen.query_range(metric, labels, start_ts, end_ts, step_seconds)
        # Flatten into Prometheus range response format
        values: list[list[Any]] = []
        for samples in series_data:
            for s in samples:
                values.append([s.timestamp, f"{s.value:.4f}"])
        return {
            "status": "success",
            "data": {
                "resultType": "matrix",
                "result": [
                    {
                        "metric": {**labels, "__name__": metric},
                        "values": values,
                    }
                ]
                if values
                else [],
            },
        }

    async def get_alerts(self) -> list[dict]:
        # Alerts are injected by the scenario, not generated dynamically
        return []


def _parse_time(t: str) -> float:
    try:
        return float(t)
    except ValueError:
        return datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp()


def _parse_step(step: str) -> int:
    if step.endswith("s"):
        return int(step[:-1])
    elif step.endswith("m"):
        return int(step[:-1]) * 60
    return 15
