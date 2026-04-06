"""Multi-source topology merge engine with confidence scoring."""

from __future__ import annotations

from backend.app.topology.graph import TopologyGraph


def merge_topologies(*graphs: TopologyGraph) -> TopologyGraph:
    """Merge multiple TopologyGraphs into one, accumulating provenance.

    Later graphs override conflicting metadata from earlier graphs.
    Source tracking and edge confidence are accumulated across all graphs.
    """
    if not graphs:
        return TopologyGraph()

    merged = graphs[0]
    for graph in graphs[1:]:
        merged.merge(graph)

    return merged
