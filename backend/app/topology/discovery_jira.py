"""Jira ticket mining — discover service dependencies from incident history."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.app.topology.graph import TopologyGraph

# Known service names for pattern matching
SERVICE_NAMES = {
    "api-gateway", "catalog-service", "cart-service", "order-service",
    "payment-service", "notification-service", "inventory-service",
}

# Patterns indicating causal dependency direction
_DEPENDENCY_PATTERNS = [
    # "X cascaded to Y" -> X depends on Y (Y failure causes X failure)
    re.compile(r"(\w[\w-]+(?:-service)?)\s+(?:cascaded?|propagated?)\s+to\s+(\w[\w-]+(?:-service)?)", re.I),
    # "X which calls Y" or "X makes calls to Y"
    re.compile(r"(\w[\w-]+(?:-service)?)\s+(?:which\s+)?(?:calls?|invokes?|makes\s+(?:synchronous\s+)?calls?\s+to)\s+(\w[\w-]+(?:-service)?)", re.I),
    # "X depends on Y"
    re.compile(r"(\w[\w-]+(?:-service)?)\s+depends?\s+on\s+(\w[\w-]+(?:-service)?)", re.I),
    # "Y failure caused X to timeout/fail"
    re.compile(r"(\w[\w-]+(?:-service)?)\s+(?:failure|outage|degradation)\s+(?:caused|led)\s+(\w[\w-]+(?:-service)?)\s+to", re.I),
]

# Pattern for scaling events
_SCALING_PATTERN = re.compile(
    r"scaled?\s+(\w[\w-]+(?:-service)?)\s+(?:from\s+\d+\s+)?to\s+(\d+)\s+(?:replicas?|pods?|instances?)",
    re.I,
)


def from_jira_tickets(tickets_path: Path) -> TopologyGraph:
    """Discover topology from Jira ticket history."""
    graph = TopologyGraph()

    data = json.loads(tickets_path.read_text())
    tickets = data.get("tickets", [])

    for ticket in tickets:
        _process_ticket(graph, ticket)

    return graph


def _process_ticket(graph: TopologyGraph, ticket: Dict[str, Any]) -> None:
    """Extract topology information from a single ticket."""
    key = ticket.get("key", "")

    # Extract services from structured fields
    components = ticket.get("components", [])
    labels = ticket.get("labels", [])
    all_text_parts = [
        ticket.get("summary", ""),
        ticket.get("description", ""),
        ticket.get("resolution_notes", ""),
    ]
    full_text = " ".join(all_text_parts)

    # Add services found in components
    for comp in components:
        if comp in SERVICE_NAMES:
            graph.add_service(comp, source="jira")

    # Find service mentions in text
    mentioned_services = set()
    for svc in SERVICE_NAMES:
        if svc in full_text.lower():
            mentioned_services.add(svc)
            graph.add_service(svc, source="jira")

    # Extract explicit dependency patterns
    for pattern in _DEPENDENCY_PATTERNS:
        for match in pattern.finditer(full_text):
            caller = _normalize_service(match.group(1))
            callee = _normalize_service(match.group(2))
            if caller and callee and caller != callee:
                graph.add_dependency(caller, callee, source="jira")

    # Extract scaling history
    for match in _SCALING_PATTERN.finditer(full_text):
        svc = _normalize_service(match.group(1))
        replicas = int(match.group(2))
        if svc:
            graph.add_service(svc, source="jira")
            # Store scaling event as metadata
            existing = graph.get_service(svc)
            history = (existing or {}).get("scaling_history", [])
            history.append({
                "ticket": key,
                "replicas": replicas,
            })
            graph.add_service(svc, source="jira", scaling_history=history)

    # Co-occurrence: services mentioned together in same incident suggest relationship
    if len(mentioned_services) >= 2:
        svc_list = sorted(mentioned_services)
        for i, svc_a in enumerate(svc_list):
            for svc_b in svc_list[i + 1:]:
                # Store co-occurrence as weak metadata (not a dependency edge)
                existing_a = graph.get_service(svc_a)
                cooccurrences = (existing_a or {}).get("co_occurred_with", {})
                cooccurrences[svc_b] = cooccurrences.get(svc_b, 0) + 1
                graph.add_service(svc_a, source="jira", co_occurred_with=cooccurrences)

    # Extract incident count per service
    for svc in mentioned_services:
        existing = graph.get_service(svc)
        count = (existing or {}).get("incident_count", 0) + 1
        graph.add_service(svc, source="jira", incident_count=count)


def _normalize_service(name: str) -> Optional[str]:
    """Normalize a service name to match known services."""
    name = name.lower().strip()
    if name in SERVICE_NAMES:
        return name
    # Try adding -service suffix
    with_suffix = name + "-service"
    if with_suffix in SERVICE_NAMES:
        return with_suffix
    # Try common abbreviations
    for svc in SERVICE_NAMES:
        if name in svc or svc.startswith(name):
            return svc
    return None
