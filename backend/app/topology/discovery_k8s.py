"""Kubernetes manifest discovery — extract topology from YAML manifests."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from backend.app.topology.graph import TopologyGraph

# Patterns for extracting service dependencies from env var values
_SERVICE_URL_PATTERN = re.compile(r"https?://([a-z][\w-]+)(?:\.[\w.-]+)?:(\d+)")
_AMQP_PATTERN = re.compile(r"amqp://[^@]*@([a-z][\w-]+)(?:\.[\w.-]+)?:\d+")
_POSTGRES_PATTERN = re.compile(r"postgresql://[^@]*@([a-z][\w-]+)(?:\.[\w.-]+)?:\d+/(\w+)")
_REDIS_HOST_PATTERN = re.compile(r"([a-z][\w-]+)(?:\.[\w.-]+\.svc\.cluster\.local)?")

# Known infrastructure service names
_INFRA_SERVICES = {"redis", "rabbitmq", "opensearch", "shopfast-db", "elasticsearch"}


def from_k8s_manifests(manifest_dir: Path) -> TopologyGraph:
    """Discover topology from Kubernetes YAML manifests."""
    graph = TopologyGraph()
    deployments: Dict[str, Dict[str, Any]] = {}
    services: Dict[str, Dict[str, Any]] = {}
    hpas: Dict[str, Dict[str, Any]] = {}

    for yaml_file in sorted(manifest_dir.glob("*.yaml")):
        try:
            doc = yaml.safe_load(yaml_file.read_text())
        except Exception:
            continue

        if not isinstance(doc, dict):
            continue

        kind = doc.get("kind", "")
        name = doc.get("metadata", {}).get("name", "")

        if kind == "Deployment":
            deployments[name] = doc
        elif kind == "Service":
            services[name] = doc
        elif kind == "HorizontalPodAutoscaler":
            target = doc.get("spec", {}).get("scaleTargetRef", {}).get("name", "")
            hpas[target] = doc

    # Process deployments — primary source of topology
    for name, deploy in deployments.items():
        spec = deploy.get("spec", {})
        template = spec.get("template", {}).get("spec", {})
        containers = template.get("containers", [])
        namespace = deploy.get("metadata", {}).get("namespace", "default")

        if not containers:
            continue

        container = containers[0]
        ports = container.get("ports", [])
        port = ports[0].get("containerPort", 0) if ports else 0
        resources = container.get("resources", {})
        image = container.get("image", "")

        # HPA info
        hpa = hpas.get(name, {}).get("spec", {})
        min_replicas = hpa.get("minReplicas", spec.get("replicas", 1))
        max_replicas = hpa.get("maxReplicas", min_replicas)

        graph.add_service(
            name,
            source="k8s",
            port=port,
            replicas=spec.get("replicas", 1),
            namespace=namespace,
            image=image,
            cpu_request=resources.get("requests", {}).get("cpu", ""),
            cpu_limit=resources.get("limits", {}).get("cpu", ""),
            mem_request=resources.get("requests", {}).get("memory", ""),
            mem_limit=resources.get("limits", {}).get("memory", ""),
            min_replicas=min_replicas,
            max_replicas=max_replicas,
        )

        # Extract dependencies from env vars
        env_vars = container.get("env", [])
        for env in env_vars:
            env_name = env.get("name", "")
            env_value = env.get("value", "")
            if not env_value:
                continue

            # HTTP service URLs -> service dependency
            for match in _SERVICE_URL_PATTERN.finditer(env_value):
                target_host = match.group(1)
                if target_host in deployments or target_host in services:
                    graph.add_dependency(name, target_host, source="k8s", protocol="http")
                elif _is_infra(target_host):
                    _add_infra_node(graph, target_host, "http")
                    graph.add_dependency(name, target_host, source="k8s", protocol="http")

            # AMQP -> RabbitMQ dependency
            for match in _AMQP_PATTERN.finditer(env_value):
                target = match.group(1)
                _add_infra_node(graph, target, "amqp")
                graph.add_dependency(name, target, source="k8s", protocol="amqp")

            # PostgreSQL -> database dependency
            for match in _POSTGRES_PATTERN.finditer(env_value):
                target = match.group(1)
                db_name = match.group(2)
                _add_infra_node(graph, target, "postgresql")
                graph.add_dependency(name, target, source="k8s", protocol="postgresql")

            # Redis host
            if env_name in ("REDIS_HOST", "REDIS_URL"):
                target = _REDIS_HOST_PATTERN.match(env_value)
                if target:
                    host = target.group(1)
                    _add_infra_node(graph, host, "redis")
                    graph.add_dependency(name, host, source="k8s", protocol="redis")

            # Elasticsearch/OpenSearch
            if "ELASTICSEARCH" in env_name or "OPENSEARCH" in env_name:
                for match in _SERVICE_URL_PATTERN.finditer(env_value):
                    host = match.group(1)
                    _add_infra_node(graph, host, "elasticsearch")
                    graph.add_dependency(name, host, source="k8s", protocol="http")

    return graph


def _is_infra(name: str) -> bool:
    """Check if a hostname looks like infrastructure (not an application service)."""
    return any(infra in name for infra in _INFRA_SERVICES)


def _add_infra_node(graph: TopologyGraph, name: str, infra_type: str) -> None:
    """Add an infrastructure node if not already present."""
    graph.add_service(name, source="k8s", node_type="infrastructure", infra_type=infra_type)
