"""Layered prompt system — loads and composes markdown prompt files."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

_PROMPTS_DIR = Path(__file__).parent

# Default prompt layers in load order
_DEFAULT_LAYERS = [
    "base_persona.md",
    "tool_instructions.md",
    "safety_rails.md",
]


def load_prompt(filename: str, prompts_dir: Optional[Path] = None) -> str:
    """Load a single prompt file by name."""
    directory = prompts_dir or _PROMPTS_DIR
    path = directory / filename
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text().strip()


def compose_prompt(
    layers: Optional[List[str]] = None,
    context: Optional[Dict[str, str]] = None,
    prompts_dir: Optional[Path] = None,
) -> str:
    """Load and concatenate prompt layers, then append dynamic context.

    Args:
        layers: List of prompt filenames to load. Defaults to all standard layers.
        context: Dynamic context to inject (e.g., active incidents, time of day).
        prompts_dir: Override prompt directory for testing.

    Returns:
        Composed system prompt string.
    """
    layers = layers or _DEFAULT_LAYERS
    parts = []

    for filename in layers:
        try:
            parts.append(load_prompt(filename, prompts_dir))
        except FileNotFoundError:
            continue

    # Inject dynamic context
    if context:
        context_lines = ["## Current Context", ""]
        for key, value in context.items():
            context_lines.append(f"- **{key}**: {value}")
        parts.append("\n".join(context_lines))

    return "\n\n---\n\n".join(parts)


def get_default_context() -> Dict[str, str]:
    """Generate default dynamic context for prompt injection."""
    now = datetime.now(timezone.utc)
    return {
        "Current time (UTC)": now.strftime("%Y-%m-%d %H:%M UTC"),
        "Time of day": _time_of_day(now.hour),
    }


def _time_of_day(hour: int) -> str:
    if 2 <= hour < 6:
        return "Late night (low traffic, skeleton crew)"
    elif 6 <= hour < 9:
        return "Early morning (traffic ramping up)"
    elif 9 <= hour < 17:
        return "Business hours (peak traffic)"
    elif 17 <= hour < 22:
        return "Evening (traffic declining)"
    else:
        return "Night (low traffic)"
