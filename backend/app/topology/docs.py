"""Auto-documentation generator — Mermaid diagrams and service catalog from topology."""

from __future__ import annotations

from typing import Any, Dict, List

from backend.app.topology.graph import TopologyGraph


def generate_mermaid(graph: TopologyGraph, highlight_service: str = "") -> str:
    """Generate a Mermaid flowchart from the topology graph."""
    data = graph.to_dict()
    lines = ["graph TD"]

    # Style mapping
    health_styles = {
        "healthy": "fill:#40C057,color:#fff",
        "degraded": "fill:#FFA94D,color:#000",
        "down": "fill:#FF6B6B,color:#fff",
    }

    tier_shapes = {1: "{{%s}}", 2: "[%s]", 3: "(%s)"}  # hexagon, rect, rounded

    for node in data["nodes"]:
        name = node["name"]
        display = node.get("display_name", name)
        tier = node.get("tier", 3)
        lang = node.get("language", "")
        label = f"{display}<br/><i>{lang}</i>"

        shape = tier_shapes.get(tier, "[%s]")
        node_def = f"    {name}{shape % label}"
        lines.append(node_def)

    lines.append("")

    for edge in data["edges"]:
        lines.append(f"    {edge['source']} --> {edge['target']}")

    lines.append("")

    # Apply styles
    for node in data["nodes"]:
        name = node["name"]
        health = node.get("health", "healthy")
        style = health_styles.get(health, health_styles["healthy"])
        if name == highlight_service:
            style = "fill:#FF6B6B,color:#fff,stroke:#FF0000,stroke-width:3px"
        lines.append(f"    style {name} {style}")

    return "\n".join(lines)


def generate_catalog(graph: TopologyGraph) -> str:
    """Generate a service catalog as markdown."""
    data = graph.to_dict()
    lines = [
        "# Service Catalog",
        "",
        f"*{len(data['nodes'])} services, {len(data['edges'])} dependencies*",
        "",
        "| Service | Tier | Language | Replicas | Health | Dependencies | Callers |",
        "|---------|------|----------|----------|--------|-------------|---------|",
    ]

    for node in sorted(data["nodes"], key=lambda n: n.get("tier", 3)):
        name = node["name"]
        tier = node.get("tier", "?")
        lang = node.get("language", "?")
        replicas = node.get("replicas", "?")
        health = node.get("health", "?")
        downstream = ", ".join(node.get("downstream", [])) or "none"
        upstream = ", ".join(node.get("upstream", [])) or "none"
        lines.append(f"| {name} | {tier} | {lang} | {replicas} | {health} | {downstream} | {upstream} |")

    lines.extend([
        "",
        "## Service Details",
        "",
    ])

    for node in sorted(data["nodes"], key=lambda n: n.get("tier", 3)):
        name = node["name"]
        display = node.get("display_name", name)
        tier = node.get("tier", "?")
        tier_label = {1: "Tier 1 (revenue-critical)", 2: "Tier 2 (standard)", 3: "Tier 3 (non-critical)"}.get(tier, f"Tier {tier}")

        lines.extend([
            f"### {display}",
            f"- **Name:** `{name}`",
            f"- **Tier:** {tier_label}",
            f"- **Language:** {node.get('language', '?')}",
            f"- **Replicas:** {node.get('replicas', '?')}",
            f"- **Port:** {node.get('port', '?')}",
            f"- **Namespace:** {node.get('namespace', '?')}",
            f"- **Calls:** {', '.join(node.get('downstream', [])) or 'none'}",
            f"- **Called by:** {', '.join(node.get('upstream', [])) or 'none (entry point)'}",
            "",
        ])

    return "\n".join(lines)
