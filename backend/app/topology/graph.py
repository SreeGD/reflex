"""TopologyGraph — service dependency graph with metadata and provenance.

Nodes are services, edges are directed dependencies (caller -> callee).
Supports traversal, multi-source provenance tracking, confidence scoring,
graph merging, serialization, and health overlay.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Dict, List, Optional, Set, Tuple

# Source reliability weights for confidence scoring
SOURCE_WEIGHTS = {
    "config": 1.0,
    "traces": 0.9,
    "k8s": 0.8,
    "docs": 0.7,
    "jira": 0.5,
}


class TopologyGraph:
    """In-memory service topology graph with multi-source provenance."""

    def __init__(self) -> None:
        self._nodes: Dict[str, Dict[str, Any]] = {}
        self._edges: Dict[str, List[str]] = {}  # caller -> [callees]
        self._health: Dict[str, str] = {}
        self._node_sources: Dict[str, Set[str]] = {}  # service -> {sources}
        self._edge_metadata: Dict[Tuple[str, str], Dict[str, Any]] = {}  # (caller, callee) -> metadata

    def add_service(self, name: str, source: str = "config", **metadata: Any) -> None:
        """Add or update a service node with source tracking."""
        if name not in self._nodes:
            self._nodes[name] = {}
            self._edges.setdefault(name, [])
            self._health[name] = "healthy"
            self._node_sources[name] = set()
        self._nodes[name].update(metadata)
        self._node_sources[name].add(source)

    def add_dependency(self, caller: str, callee: str, source: str = "config", **metadata: Any) -> None:
        """Add a directed edge with source tracking."""
        self._edges.setdefault(caller, [])
        if callee not in self._edges[caller]:
            self._edges[caller].append(callee)

        key = (caller, callee)
        if key not in self._edge_metadata:
            self._edge_metadata[key] = {"discovered_by": set()}
        self._edge_metadata[key]["discovered_by"].add(source)
        if metadata:
            self._edge_metadata[key].update(metadata)

    def set_health(self, service: str, status: str) -> None:
        """Set service health: 'healthy', 'degraded', or 'down'."""
        if service in self._health:
            self._health[service] = status

    def get_downstream(self, service: str, depth: int = 1) -> List[str]:
        """Get services that this service calls (transitive up to depth)."""
        return self._traverse(service, depth, direction="downstream")

    def get_upstream(self, service: str, depth: int = 1) -> List[str]:
        """Get services that call this service (transitive up to depth)."""
        return self._traverse(service, depth, direction="upstream")

    def get_all_downstream(self, service: str) -> List[str]:
        return self._traverse(service, depth=99, direction="downstream")

    def get_all_upstream(self, service: str) -> List[str]:
        return self._traverse(service, depth=99, direction="upstream")

    def _traverse(self, service: str, depth: int, direction: str) -> List[str]:
        visited: Set[str] = set()
        queue: deque = deque()
        queue.append((service, 0))
        visited.add(service)
        result = []

        while queue:
            current, current_depth = queue.popleft()
            if current_depth >= depth:
                continue

            if direction == "downstream":
                neighbors = self._edges.get(current, [])
            else:
                neighbors = [s for s, deps in self._edges.items() if current in deps]

            for neighbor in neighbors:
                if neighbor not in visited:
                    visited.add(neighbor)
                    result.append(neighbor)
                    queue.append((neighbor, current_depth + 1))

        return result

    def get_edge_sources(self, caller: str, callee: str) -> Set[str]:
        """Get the set of discovery sources for an edge."""
        meta = self._edge_metadata.get((caller, callee), {})
        return meta.get("discovered_by", set())

    def get_edge_confidence(self, caller: str, callee: str) -> float:
        """Compute confidence score for an edge based on corroborating sources."""
        sources = self.get_edge_sources(caller, callee)
        if not sources:
            return 0.0
        score = sum(SOURCE_WEIGHTS.get(s, 0.5) for s in sources)
        max_score = sum(SOURCE_WEIGHTS.values())
        return round(min(score / max_score, 1.0), 2)

    def get_node_sources(self, name: str) -> Set[str]:
        """Get the set of discovery sources for a node."""
        return self._node_sources.get(name, set())

    def merge(self, other: "TopologyGraph") -> None:
        """Merge another graph into this one, accumulating sources."""
        for name, meta in other._nodes.items():
            if name not in self._nodes:
                self._nodes[name] = {}
                self._edges.setdefault(name, [])
                self._health[name] = other._health.get(name, "healthy")
                self._node_sources[name] = set()
            # Merge metadata (other overrides on conflict)
            self._nodes[name].update(meta)
            self._node_sources[name] |= other._node_sources.get(name, set())

        for caller, callees in other._edges.items():
            self._edges.setdefault(caller, [])
            for callee in callees:
                if callee not in self._edges[caller]:
                    self._edges[caller].append(callee)
                # Merge edge metadata
                key = (caller, callee)
                if key not in self._edge_metadata:
                    self._edge_metadata[key] = {"discovered_by": set()}
                other_meta = other._edge_metadata.get(key, {})
                self._edge_metadata[key]["discovered_by"] |= other_meta.get("discovered_by", set())
                for k, v in other_meta.items():
                    if k != "discovered_by":
                        self._edge_metadata[key][k] = v

    def get_service(self, name: str) -> Optional[Dict[str, Any]]:
        """Get service metadata including provenance."""
        if name not in self._nodes:
            return None
        return {
            "name": name,
            **self._nodes[name],
            "health": self._health.get(name, "unknown"),
            "downstream": self._edges.get(name, []),
            "upstream": [s for s, deps in self._edges.items() if name in deps],
            "sources": sorted(self._node_sources.get(name, set())),
        }

    def list_services(self) -> List[str]:
        return list(self._nodes.keys())

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the full graph with provenance and confidence."""
        nodes = []
        for name, meta in self._nodes.items():
            nodes.append({
                "name": name,
                "health": self._health.get(name, "unknown"),
                "upstream": [s for s, deps in self._edges.items() if name in deps],
                "downstream": self._edges.get(name, []),
                "sources": sorted(self._node_sources.get(name, set())),
                **meta,
            })

        edges = []
        for caller, callees in self._edges.items():
            for callee in callees:
                sources = self.get_edge_sources(caller, callee)
                edges.append({
                    "source": caller,
                    "target": callee,
                    "discovered_by": sorted(sources),
                    "confidence": self.get_edge_confidence(caller, callee),
                })

        return {"nodes": nodes, "edges": edges}

    def get_source_stats(self) -> Dict[str, Dict[str, int]]:
        """Return statistics per discovery source."""
        stats: Dict[str, Dict[str, int]] = {}
        for name, sources in self._node_sources.items():
            for src in sources:
                stats.setdefault(src, {"nodes": 0, "edges": 0})
                stats[src]["nodes"] += 1

        for key, meta in self._edge_metadata.items():
            for src in meta.get("discovered_by", set()):
                stats.setdefault(src, {"nodes": 0, "edges": 0})
                stats[src]["edges"] += 1

        return stats
