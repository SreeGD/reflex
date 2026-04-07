"""ShopFast e-commerce platform — service definitions and dependency graph.

This is the fictional distributed system being monitored by Reflex.
All mock data generators and scenarios reference these definitions.
"""

from __future__ import annotations

from typing import Optional

from dataclasses import dataclass, field
from enum import Enum


class ServiceType(Enum):
    PYTHON_FASTAPI = "python-fastapi"
    GO = "go"
    NODEJS = "nodejs"
    JAVA_SPRING = "java-spring"


@dataclass
class Endpoint:
    path: str
    method: str = "GET"
    baseline_rps: float = 50.0
    baseline_latency_p50_ms: float = 25.0
    baseline_latency_p99_ms: float = 120.0
    baseline_error_rate: float = 0.001


@dataclass
class ServiceDef:
    name: str
    display_name: str
    service_type: ServiceType
    port: int
    replicas: int
    namespace: str = "shopfast-prod"
    dependencies: list[str] = field(default_factory=list)
    endpoints: list[Endpoint] = field(default_factory=list)
    # Normal operating baselines (mean, stddev)
    baseline_cpu_pct: tuple[float, float] = (20.0, 5.0)
    baseline_memory_mb: tuple[float, float] = (256.0, 30.0)
    baseline_rps: tuple[float, float] = (100.0, 20.0)
    baseline_latency_p50_ms: tuple[float, float] = (25.0, 5.0)
    baseline_latency_p99_ms: tuple[float, float] = (120.0, 20.0)
    baseline_error_rate: tuple[float, float] = (0.001, 0.0005)
    # Resource-specific
    db_pool_max: Optional[int] = None
    redis_pool_max: Optional[int] = None
    jvm_heap_max_mb: Optional[int] = None


SERVICES: dict[str, ServiceDef] = {
    "api-gateway": ServiceDef(
        name="api-gateway",
        display_name="API Gateway",
        service_type=ServiceType.PYTHON_FASTAPI,
        port=8080,
        replicas=3,
        dependencies=["catalog-service", "cart-service", "order-service", "payment-service"],
        baseline_rps=(500.0, 80.0),
        baseline_latency_p50_ms=(15.0, 3.0),
        baseline_latency_p99_ms=(80.0, 15.0),
        endpoints=[
            Endpoint("/api/v1/catalog", "GET", 200.0, 12.0, 60.0),
            Endpoint("/api/v1/cart", "POST", 80.0, 18.0, 90.0),
            Endpoint("/api/v1/orders", "POST", 50.0, 45.0, 200.0),
            Endpoint("/api/v1/payments", "POST", 40.0, 80.0, 300.0),
        ],
    ),
    "catalog-service": ServiceDef(
        name="catalog-service",
        display_name="Catalog Service",
        service_type=ServiceType.GO,
        port=8081,
        replicas=3,
        dependencies=["inventory-service"],
        baseline_rps=(300.0, 50.0),
        baseline_latency_p50_ms=(8.0, 2.0),
        baseline_latency_p99_ms=(40.0, 8.0),
        endpoints=[
            Endpoint("/api/v1/products", "GET", 250.0, 6.0, 30.0),
            Endpoint("/api/v1/products/search", "GET", 50.0, 15.0, 80.0),
        ],
    ),
    "cart-service": ServiceDef(
        name="cart-service",
        display_name="Cart Service",
        service_type=ServiceType.NODEJS,
        port=8082,
        replicas=2,
        dependencies=["catalog-service"],
        redis_pool_max=50,
        baseline_latency_p50_ms=(10.0, 2.0),
        baseline_latency_p99_ms=(50.0, 10.0),
        endpoints=[
            Endpoint("/api/v1/cart", "GET", 60.0, 8.0, 40.0),
            Endpoint("/api/v1/cart", "POST", 40.0, 12.0, 60.0),
        ],
    ),
    "order-service": ServiceDef(
        name="order-service",
        display_name="Order Service",
        service_type=ServiceType.PYTHON_FASTAPI,
        port=8083,
        replicas=3,
        dependencies=["payment-service", "inventory-service", "notification-service"],
        db_pool_max=20,
        baseline_latency_p50_ms=(45.0, 8.0),
        baseline_latency_p99_ms=(200.0, 30.0),
        endpoints=[
            Endpoint("/api/v1/orders", "POST", 50.0, 45.0, 200.0),
            Endpoint("/api/v1/orders", "GET", 30.0, 15.0, 60.0),
        ],
    ),
    "payment-service": ServiceDef(
        name="payment-service",
        display_name="Payment Service",
        service_type=ServiceType.JAVA_SPRING,
        port=8084,
        replicas=2,
        dependencies=[],
        db_pool_max=15,
        jvm_heap_max_mb=2048,
        baseline_latency_p50_ms=(80.0, 15.0),
        baseline_latency_p99_ms=(300.0, 50.0),
        endpoints=[
            Endpoint("/api/v1/payments", "POST", 40.0, 80.0, 300.0),
            Endpoint("/api/v1/refunds", "POST", 10.0, 100.0, 400.0),
        ],
    ),
    "notification-service": ServiceDef(
        name="notification-service",
        display_name="Notification Service",
        service_type=ServiceType.PYTHON_FASTAPI,
        port=8085,
        replicas=2,
        dependencies=[],
        baseline_latency_p50_ms=(5.0, 1.0),
        baseline_latency_p99_ms=(20.0, 5.0),
        endpoints=[
            Endpoint("/api/v1/notify", "POST", 50.0, 5.0, 20.0),
        ],
    ),
    "inventory-service": ServiceDef(
        name="inventory-service",
        display_name="Inventory Service",
        service_type=ServiceType.GO,
        port=8086,
        replicas=2,
        dependencies=[],
        db_pool_max=15,
        baseline_latency_p50_ms=(12.0, 3.0),
        baseline_latency_p99_ms=(50.0, 10.0),
        endpoints=[
            Endpoint("/api/v1/stock", "GET", 80.0, 10.0, 40.0),
            Endpoint("/api/v1/reserve", "POST", 40.0, 15.0, 60.0),
        ],
    ),
}

DEPENDENCY_GRAPH: dict[str, list[str]] = {
    "api-gateway": ["catalog-service", "cart-service", "order-service"],
    "cart-service": ["catalog-service"],
    "catalog-service": ["inventory-service"],
    "order-service": ["payment-service", "inventory-service", "notification-service"],
    "payment-service": [],
    "notification-service": [],
    "inventory-service": [],
}


def get_upstream_services(service: str) -> list[str]:
    """Return services that call this service (reverse dependency lookup)."""
    return [s for s, deps in DEPENDENCY_GRAPH.items() if service in deps]


def get_downstream_services(service: str) -> list[str]:
    """Return services this service calls."""
    return DEPENDENCY_GRAPH.get(service, [])


# Thread-local override for per-request system selection (set by API/UI)
_system_override = None


def set_system_override(system):
    """Override the active system (for per-request switching in API/UI)."""
    global _system_override
    _system_override = system


def get_active_system() -> str:
    """Return the active mock system name."""
    if _system_override:
        return _system_override
    import os
    return os.environ.get("MOCK_SYSTEM", "shopfast").lower()


def get_active_config(system=None):
    """Return (SERVICES, DEPENDENCY_GRAPH) for the given or active mock system."""
    system = system or get_active_system()
    if system == "healthcare":
        from mock.healthcare_config import HEALTHCARE_SERVICES, HEALTHCARE_DEPENDENCY_GRAPH
        return HEALTHCARE_SERVICES, HEALTHCARE_DEPENDENCY_GRAPH
    return SERVICES, DEPENDENCY_GRAPH


def get_active_scenarios(system=None):
    """Return (SCENARIOS_DICT, LABELS_DICT) for the given or active mock system."""
    system = system or get_active_system()
    if system == "healthcare":
        from mock.healthcare_config import HEALTHCARE_SCENARIOS, HEALTHCARE_SCENARIO_LABELS
        return HEALTHCARE_SCENARIOS, HEALTHCARE_SCENARIO_LABELS
    return {
        "db_pool_exhaustion": "mock.scenarios.db_pool_exhaustion",
        "payment_timeout_cascade": "mock.scenarios.payment_timeout_cascade",
        "memory_leak": "mock.scenarios.memory_leak",
        "redis_connection_storm": "mock.scenarios.redis_connection_storm",
        "slow_query_cascade": "mock.scenarios.slow_query_cascade",
    }, {
        "db_pool_exhaustion": "DB Connection Pool Exhaustion",
        "payment_timeout_cascade": "Payment Gateway Timeout Cascade",
        "memory_leak": "JVM Memory Leak",
        "redis_connection_storm": "Redis Connection Storm",
        "slow_query_cascade": "Slow Query Cascade",
    }
