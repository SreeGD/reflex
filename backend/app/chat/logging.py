"""Structured conversation logger — NDJSON output for audit and debugging.

Every conversation turn (inbound message + outbound response) produces
a log entry with the full schema defined in the PRD.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


class ConversationLogger:
    """Writes structured NDJSON log entries for chat interactions."""

    def __init__(self, log_path: Optional[str] = None) -> None:
        """Initialize the logger.

        Args:
            log_path: Path to the NDJSON log file. Defaults to stdout if None.
        """
        self._log_path = Path(log_path) if log_path else None
        if self._log_path:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)

    def log_inbound(
        self,
        conversation_id: str,
        user_id: str,
        message_text: str,
        incident_id: Optional[str] = None,
    ) -> None:
        """Log an inbound user message."""
        entry = self._base_entry(conversation_id, user_id, incident_id)
        entry["direction"] = "inbound"
        entry["message_text"] = message_text
        self._write(entry)

    def log_outbound(
        self,
        conversation_id: str,
        user_id: str,
        message_text: str,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        llm_usage: Optional[Dict[str, Any]] = None,
        actions_taken: Optional[List[Dict[str, Any]]] = None,
        incident_id: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        """Log an outbound agent response."""
        entry = self._base_entry(conversation_id, user_id, incident_id)
        entry["direction"] = "outbound"
        entry["message_text"] = message_text[:500]  # Truncate for log storage
        entry["tool_calls"] = tool_calls or []
        entry["llm_usage"] = llm_usage or {}
        entry["actions_taken"] = actions_taken or []
        if error:
            entry["error"] = error
        self._write(entry)

    def _base_entry(
        self,
        conversation_id: str,
        user_id: str,
        incident_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        return {
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "conversation_id": conversation_id,
            "incident_id": incident_id,
            "user_id": user_id,
        }

    def _write(self, entry: Dict[str, Any]) -> None:
        line = json.dumps(entry, default=str)
        if self._log_path:
            with open(self._log_path, "a") as f:
                f.write(line + "\n")
        else:
            print(line, file=sys.stderr)


class TimedToolTracker:
    """Context manager to track tool call timing for logging."""

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []
        self._start_times: Dict[str, float] = {}

    def start(self, tool_name: str, args: Dict[str, Any]) -> str:
        """Record the start of a tool call. Returns a call_id."""
        call_id = f"{tool_name}_{len(self.calls)}"
        self._start_times[call_id] = time.time()
        self.calls.append({
            "name": tool_name,
            "args": {k: str(v)[:100] for k, v in args.items()},
            "duration_ms": 0,
            "success": True,
        })
        return call_id

    def finish(self, call_id: str, success: bool = True) -> None:
        """Record the completion of a tool call."""
        idx = int(call_id.rsplit("_", 1)[-1])
        if idx < len(self.calls):
            start = self._start_times.get(call_id, time.time())
            self.calls[idx]["duration_ms"] = int((time.time() - start) * 1000)
            self.calls[idx]["success"] = success

    def get_calls(self) -> List[Dict[str, Any]]:
        return list(self.calls)
