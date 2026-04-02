"""Chat agent tool registry.

Each tool is a thin wrapper around an existing provider interface.
Tools are registered with the LangGraph agent via bind_tools().
"""

from __future__ import annotations

from typing import Optional

from langchain_core.tools import tool

# Provider instances are injected at module level by the engine before
# the agent is built. This avoids passing providers through LangGraph's
# tool-calling mechanism (which only supports serializable args).
_knowledge_provider = None
_UNSET = object()


def set_providers(knowledge=_UNSET):
    """Inject provider instances. Called once at engine startup."""
    global _knowledge_provider
    if knowledge is not _UNSET:
        _knowledge_provider = knowledge


@tool
async def search_knowledge(
    query: str,
    source_type: Optional[str] = None,
    limit: int = 5,
) -> str:
    """Search the knowledge base for runbooks, Jira tickets, and Confluence docs.

    Use this when the user asks about incidents, runbooks, procedures,
    past tickets, or operational knowledge.

    Args:
        query: Search query describing what to find.
        source_type: Optional filter — "runbook", "jira", or "confluence".
        limit: Max results to return (default 5).
    """
    if _knowledge_provider is None:
        return "Knowledge provider not available."

    source_types = [source_type] if source_type else None
    results = await _knowledge_provider.search_similar(
        query=query, source_types=source_types, limit=limit
    )

    if not results:
        return "No matching knowledge found."

    lines = []
    for r in results:
        lines.append(
            f"[{r['source_type'].upper()}] {r['source_id']}: {r['title']} "
            f"(score: {r['score']:.2f})"
        )
        content_preview = r.get("content", "")[:200]
        if content_preview:
            lines.append(f"  {content_preview}")
        lines.append("")

    return "\n".join(lines)


def get_tools():
    """Return all tools for the chat agent."""
    return [search_knowledge]
