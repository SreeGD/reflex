"""Mock LogsProvider — backed by LogGenerator."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone

from mock.generators.logs import LogGenerator


class MockLogsProvider:
    """Fulfills LogsProvider protocol using in-memory log generator."""

    def __init__(self, generator: LogGenerator) -> None:
        self._gen = generator

    async def search(
        self,
        service: str | None = None,
        level: str | None = None,
        message_contains: str | None = None,
        trace_id: str | None = None,
        time_from: str | None = None,
        time_to: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        start = _parse_time(time_from) if time_from else datetime.now(tz=timezone.utc).timestamp() - 600
        end = _parse_time(time_to) if time_to else datetime.now(tz=timezone.utc).timestamp()

        entries = self._gen.search(
            service=service,
            level=level,
            message_contains=message_contains,
            time_from=start,
            time_to=end,
            limit=limit,
        )

        # Filter by trace_id if provided
        if trace_id:
            entries = [e for e in entries if e.trace_id == trace_id]

        return [asdict(e) for e in entries[:limit]]


def _parse_time(t: str) -> float:
    try:
        return float(t)
    except ValueError:
        return datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp()
