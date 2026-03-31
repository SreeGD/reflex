"""Mock AlertsProvider — rich terminal output + log to file."""

from __future__ import annotations

from typing import Optional

import json
from datetime import datetime, timezone
from pathlib import Path


class MockAlertsProvider:
    """Fulfills AlertsProvider protocol. Prints to terminal, logs to JSONL."""

    def __init__(self, log_dir: Optional[Path] = None) -> None:
        self._log_dir = log_dir or Path(__file__).parent.parent / "data"
        self.sent_alerts: list[dict] = []

    async def send_alert(
        self, channel: str, incident: dict, rca: dict
    ) -> dict:
        alert = {
            "type": "alert",
            "channel": channel,
            "incident_id": incident.get("incident_id", "unknown"),
            "service": incident.get("service", "unknown"),
            "summary": rca.get("root_cause", ""),
            "confidence": rca.get("confidence", 0),
            "evidence": rca.get("evidence", []),
            "action_taken": incident.get("action_taken"),
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        }
        self.sent_alerts.append(alert)
        self._log(alert)
        return {"ok": True, "channel": channel, "ts": str(datetime.now(tz=timezone.utc).timestamp())}

    async def request_approval(
        self, channel: str, incident: dict, action: dict
    ) -> dict:
        approval = {
            "type": "approval_request",
            "channel": channel,
            "incident_id": incident.get("incident_id", "unknown"),
            "action": action,
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        }
        self.sent_alerts.append(approval)
        self._log(approval)
        # In mock mode, auto-approve for demo
        return {"ok": True, "approved": True, "approved_by": "demo-auto-approve"}

    async def escalate(self, incident: dict, reason: str) -> dict:
        escalation = {
            "type": "escalation",
            "incident_id": incident.get("incident_id", "unknown"),
            "reason": reason,
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        }
        self.sent_alerts.append(escalation)
        self._log(escalation)
        return {"ok": True, "escalated": True}

    def _log(self, entry: dict) -> None:
        log_file = self._log_dir / "slack_messages.jsonl"
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with open(log_file, "a") as f:
            f.write(json.dumps(entry) + "\n")
