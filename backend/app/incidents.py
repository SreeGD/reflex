"""Shared incident store — singleton for cross-component incident access.

Used by: webhook handler, chat tools, Streamlit polling, incidents API.
Replaces the ad-hoc _incidents_store dict that was in tools.py.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional


class IncidentStore:
    """Thread-safe in-memory incident store."""

    def __init__(self) -> None:
        self._incidents: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def put(self, incident_id: str, state: Dict[str, Any], source: str = "chat") -> None:
        """Store an incident result."""
        with self._lock:
            state["_stored_at"] = time.time()
            state["_source"] = source
            severity = "unknown"
            alarm = state.get("alarm", {})
            if isinstance(alarm, dict):
                severity = alarm.get("labels", {}).get("severity", "unknown")
            state["_severity_label"] = severity
            self._incidents[incident_id] = state

    def get(self, incident_id: str) -> Optional[Dict[str, Any]]:
        """Get an incident by ID."""
        with self._lock:
            return self._incidents.get(incident_id)

    def list_all(self) -> Dict[str, Dict[str, Any]]:
        """Return all incidents."""
        with self._lock:
            return dict(self._incidents)

    def list_since(self, timestamp: float) -> List[Dict[str, Any]]:
        """Return incidents stored after the given timestamp."""
        with self._lock:
            return [
                state for state in self._incidents.values()
                if state.get("_stored_at", 0) > timestamp
            ]

    def update(self, incident_id: str, updates: Dict[str, Any]) -> bool:
        """Merge partial updates into an existing incident. Returns True if found."""
        with self._lock:
            if incident_id not in self._incidents:
                return False
            self._incidents[incident_id].update(updates)
            return True

    def count(self) -> int:
        """Return total incident count."""
        with self._lock:
            return len(self._incidents)

    def clear(self) -> None:
        """Clear all incidents (for testing)."""
        with self._lock:
            self._incidents.clear()

    def to_summary_list(self) -> List[Dict[str, Any]]:
        """Return a list of incident summaries for API/polling."""
        with self._lock:
            summaries = []
            for iid, state in self._incidents.items():
                summaries.append({
                    "incident_id": iid,
                    "service": state.get("service", "unknown"),
                    "severity": state.get("_severity_label", "unknown"),
                    "is_noise": state.get("is_noise", False),
                    "root_cause": (state.get("root_cause") or "")[:100],
                    "confidence": state.get("confidence", 0),
                    "action_decision": state.get("action_decision", ""),
                    "blast_radius": state.get("blast_radius", ""),
                    "source": state.get("_source", "unknown"),
                    "stored_at": state.get("_stored_at", 0),
                    "actioned_by": state.get("_actioned_by", ""),
                    "actioned_at": state.get("_actioned_at", 0),
                })
            return sorted(summaries, key=lambda x: x["stored_at"], reverse=True)


# Module-level singleton
incident_store = IncidentStore()
