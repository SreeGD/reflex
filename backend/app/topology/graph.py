"""TopologyGraph — service dependency graph with metadata.

Nodes are services, edges are directed dependencies (caller → callee).
Supports traversal, serialization, and health overlay.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Dict, List, Optional, Set


class TopologyGraph:
    """In-memory service topology graph."""

    def __init__(self) -> None:
        self._nodes: Dict[str, Dict[str, Any]] = {}  # service_name -> metadata
        self._edges: Dict[str, List[str]] = {}  # caller -> [callees]
        self._health: Dict[str, str] = {}  # service -> "healthy"|"degraded"|"down"

    def add_service(self, name: str, **metadata: Any) -> None:
        """Add or update a service node."""
        if name not in self._nodes:
            self._nodes[name] = {}
            self._edges.setdefault(name, [])
            self._health[name] = "healthy"
        self._nodes[name].update(metadata)

    def add_dependency(self, caller: str, callee: str, **metadata: Any) -> None:
        """Add a directed edge: caller depends on callee."""
        self._edges.setdefault(caller, [])
        if callee not in self._edges[caller]:
            self._edges[caller].append(callee)

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
        """Get all transitive downstream dependencies."""
        return self._traverse(service, depth=99, direction="downstream")

    def get_all_upstream(self, service: str) -> List[str]:
        """Get all transitive upstream callers."""
        return self._traverse(service, depth=99, direction="upstream")

    def _traverse(self, service: str, depth: int, direction: str) -> List[str]:
        """BFS traversal in the given direction."""
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

    def get_service(self, name: str) -> Optional[Dict[str, Any]]:
        """Get service metadata."""
        if name not in self._nodes:
            return None
        return {
            "name": name,
            **self._nodes[name],
            "health": self._health.get(name, "unknown"),
            "downstream": self._edges.get(name, []),
            "upstream": [s for s, deps in self._edges.items() if name in deps],
        }

    def list_services(self) -> List[str]:
        """List all service names."""
        return list(self._nodes.keys())

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the full graph for API/UI consumption."""
        nodes = []
        for name, meta in self._nodes.items():
            nodes.append({
                "name": name,
                "health": self._health.get(name, "unknown"),
                "upstream": [s for s, deps in self._edges.items() if name in deps],
                "downstream": self._edges.get(name, []),
                **meta,
            })

        edges = []
        for caller, callees in self._edges.items():
            for callee in callees:
                edges.append({"source": caller, "target": callee})

        return {"nodes": nodes, "edges": edges}
