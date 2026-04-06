"""Topology API router — service graph, impact analysis, auto-docs."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

from backend.app.topology.discovery import get_topology
from backend.app.topology.impact import (
    calculate_blast_radius,
    get_affected_journeys,
    get_affected_services,
)
from backend.app.topology.docs import generate_catalog, generate_mermaid

router = APIRouter(prefix="/topology", tags=["topology"])


@router.get("")
async def get_full_topology():
    """Get the full service topology graph (nodes + edges + health)."""
    graph = get_topology()
    return graph.to_dict()


# Static routes BEFORE parameterized /{service} routes
@router.get("/sources")
async def get_sources():
    """Get discovery source statistics."""
    graph = get_topology()
    return graph.get_source_stats()


@router.get("/docs/mermaid", response_class=PlainTextResponse)
async def get_mermaid(highlight: Optional[str] = None):
    """Get a Mermaid diagram of the service topology."""
    graph = get_topology()
    return generate_mermaid(graph, highlight_service=highlight or "")


@router.get("/docs/catalog", response_class=PlainTextResponse)
async def get_catalog():
    """Get the service catalog as markdown."""
    graph = get_topology()
    return generate_catalog(graph)


# Parameterized routes AFTER static routes
@router.get("/{service}")
async def get_service(service: str):
    """Get details for a single service."""
    graph = get_topology()
    info = graph.get_service(service)
    if info is None:
        raise HTTPException(404, f"Service {service} not found")
    return info


@router.get("/{service}/impact")
async def get_impact(service: str):
    """Get impact analysis for a service outage."""
    graph = get_topology()
    if graph.get_service(service) is None:
        raise HTTPException(404, f"Service {service} not found")

    affected = get_affected_services(graph, service)
    journeys = get_affected_journeys(graph, service)

    return {
        "service": service,
        "upstream_affected": affected["upstream"],
        "downstream_affected": affected["downstream"],
        "total_affected": len(set(affected["upstream"] + affected["downstream"])),
        "affected_journeys": journeys,
    }


@router.get("/{service}/blast-radius")
async def get_blast_radius(service: str, action: str = "restart_deployment"):
    """Calculate propagated blast radius for an action on a service."""
    graph = get_topology()
    if graph.get_service(service) is None:
        raise HTTPException(404, f"Service {service} not found")

    return calculate_blast_radius(graph, service, action)
