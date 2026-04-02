"""ChatResponse — structured response contract between engine and adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Action:
    """An action the user can take (rendered as buttons in Slack/Streamlit)."""

    label: str
    action_id: str
    value: str = ""
    style: str = "default"  # "default", "primary", "danger"


@dataclass
class ChatResponse:
    """Structured response from the chat engine.

    Adapters (CLI, Streamlit, Slack) render this per platform.
    """

    text: str
    structured_data: Optional[Dict[str, Any]] = None
    actions: List[Action] = field(default_factory=list)
    severity: str = "info"  # "info", "warning", "critical"
    conversation_id: str = ""
