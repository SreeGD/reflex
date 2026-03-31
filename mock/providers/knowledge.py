"""Mock KnowledgeProvider — keyword search over static files.

No pgvector, no embeddings. Simple TF-IDF-like keyword matching over
runbooks, Jira tickets, and confluence pages. Good enough for demo,
replaceable with PgVectorKnowledgeProvider post-funding.
"""

from __future__ import annotations

from typing import Optional

import json
from pathlib import Path

_DATA_DIR = Path(__file__).parent.parent / "data"


class MockKnowledgeProvider:
    """Fulfills KnowledgeProvider protocol using local files + keyword search."""

    def __init__(self, data_dir: Optional[Path] = None) -> None:
        self._data_dir = data_dir or _DATA_DIR
        self._runbooks: dict[str, str] = {}
        self._tickets: list[dict] = []
        self._confluence: dict[str, str] = {}
        self._load_data()

    def _load_data(self) -> None:
        # Load runbooks
        runbooks_dir = self._data_dir / "runbooks"
        if runbooks_dir.exists():
            for f in runbooks_dir.glob("*.md"):
                # Extract ID like "RB-001" from "RB-001-db-connection-pool-exhaustion.md"
                rb_id = f.stem.split("-", 2)[:2]
                rb_id = "-".join(rb_id) if len(rb_id) >= 2 else f.stem
                self._runbooks[rb_id] = f.read_text()

        # Load Jira tickets
        tickets_path = self._data_dir / "jira_tickets.json"
        if tickets_path.exists():
            data = json.loads(tickets_path.read_text())
            self._tickets = data.get("tickets", [])

        # Load confluence pages
        pages_dir = self._data_dir / "confluence_pages"
        if pages_dir.exists():
            for f in pages_dir.glob("*.md"):
                self._confluence[f.stem] = f.read_text()

    async def search_similar(
        self,
        query: str,
        source_types: Optional[list[str]] = None,
        limit: int = 5,
    ) -> list[dict]:
        """Keyword-based search across all knowledge sources."""
        results: list[dict] = []
        query_lower = query.lower()
        keywords = query_lower.split()

        types = source_types or ["runbook", "jira", "confluence"]

        if "runbook" in types:
            for rb_id, content in self._runbooks.items():
                score = _keyword_score(content.lower(), keywords)
                if score > 0:
                    results.append({
                        "source_type": "runbook",
                        "source_id": rb_id,
                        "title": _extract_title(content),
                        "content": content[:500],
                        "score": score,
                        "metadata": {},
                    })

        if "jira" in types:
            for ticket in self._tickets:
                text = f"{ticket.get('summary', '')} {ticket.get('description', '')} {ticket.get('resolution_notes', '')}".lower()
                score = _keyword_score(text, keywords)
                if score > 0:
                    results.append({
                        "source_type": "jira",
                        "source_id": ticket["key"],
                        "title": ticket.get("summary", ""),
                        "content": ticket.get("resolution_notes", "")[:500],
                        "score": score,
                        "metadata": {
                            "status": ticket.get("status"),
                            "priority": ticket.get("priority"),
                            "labels": ticket.get("labels", []),
                            "resolved": ticket.get("resolved"),
                        },
                    })

        if "confluence" in types:
            for page_id, content in self._confluence.items():
                score = _keyword_score(content.lower(), keywords)
                if score > 0:
                    results.append({
                        "source_type": "confluence",
                        "source_id": page_id,
                        "title": _extract_title(content),
                        "content": content[:500],
                        "score": score,
                        "metadata": {},
                    })

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:limit]

    async def get_runbook(self, runbook_id: str) -> Optional[str]:
        return self._runbooks.get(runbook_id)

    async def get_ticket(self, ticket_key: str) -> Optional[dict]:
        for t in self._tickets:
            if t["key"] == ticket_key:
                return t
        return None


def _keyword_score(text: str, keywords: list[str]) -> float:
    """Simple keyword frequency scoring."""
    if not keywords:
        return 0.0
    matches = sum(1 for kw in keywords if kw in text)
    # Bonus for exact multi-word matches
    full_query = " ".join(keywords)
    bonus = 0.5 if full_query in text else 0.0
    return matches / len(keywords) + bonus


def _extract_title(content: str) -> str:
    """Extract first markdown heading as title."""
    for line in content.split("\n"):
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    return "Untitled"
