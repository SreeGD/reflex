"""Structured JSON log generator with per-service templates."""

from __future__ import annotations

import random
import uuid
from datetime import datetime, timezone

from mock.config import SERVICES, ServiceDef

from .base import LogEntry

# Log templates: (level, message_template, logger)
# Placeholders are filled by the generator.
LOG_TEMPLATES: dict[str, dict[str, list[tuple[str, str, str]]]] = {
    "order-service": {
        "normal": [
            ("INFO", "Order {order_id} created successfully", "app.handlers.order"),
            ("INFO", "Payment initiated for order {order_id}", "app.handlers.order"),
            ("DEBUG", "DB query completed in {duration_ms}ms", "app.db"),
            ("INFO", "Order {order_id} status updated to {status}", "app.handlers.order"),
        ],
        "db_pool_exhaustion": [
            ("WARN", "Connection pool utilization at {pool_pct}%: {active}/{max} active", "app.db.pool"),
            ("ERROR", "Database connection pool exhausted. Active: {active}/{max}, waiting: {waiting}. Timeout after {timeout_ms}ms", "app.db.pool"),
            ("ERROR", "Failed to create order {order_id}: could not acquire database connection within 5000ms", "app.handlers.order"),
            ("WARN", "Connection pool health check: {healthy}/{total} connections healthy", "app.db.pool"),
        ],
    },
    "payment-service": {
        "normal": [
            ("INFO", "Payment processed for order {order_id}: ${amount} USD", "c.s.payment.PaymentHandler"),
            ("DEBUG", "Gateway response in {duration_ms}ms: status={gateway_status}", "c.s.payment.GatewayClient"),
        ],
        "gateway_timeout": [
            ("WARN", "Payment gateway slow response: {duration_ms}ms for order {order_id}", "c.s.payment.GatewayClient"),
            ("ERROR", "Payment gateway timeout after 30000ms for order_id={order_id}. Retry {retry}/{max_retries}", "c.s.payment.GatewayClient"),
            ("ERROR", "Circuit breaker OPEN for payment gateway. Failures: {failures}/{threshold}", "c.s.payment.CircuitBreaker"),
        ],
        "memory_leak": [
            ("WARN", "GC pause {gc_pause_ms}ms exceeds threshold 500ms. Heap: {heap_used_mb}MB/{heap_max_mb}MB", "c.s.payment.GCMonitor"),
            ("WARN", "Heap utilization {heap_pct}% - approaching limit", "c.s.payment.HeapMonitor"),
            ("ERROR", "OutOfMemoryError: Java heap space", "c.s.payment.Main"),
        ],
    },
    "cart-service": {
        "normal": [
            ("INFO", "Cart updated: user={user_id}, items={item_count}", "cart.handler"),
            ("DEBUG", "Redis GET cart:{user_id} in {duration_ms}ms", "cart.cache"),
        ],
        "redis_pool_exhaustion": [
            ("WARN", "Redis pool utilization high: {active}/{max} connections", "cart.redis"),
            ("ERROR", "Redis connection failed: Connection pool exhausted (active: {active}/{max})", "cart.redis"),
            ("ERROR", "Failed to fetch cart for user {user_id}: Redis connection timeout after 3000ms", "cart.handler"),
        ],
    },
    "inventory-service": {
        "normal": [
            ("INFO", "Stock check for SKU {sku}: {quantity} available", "inventory.handler"),
            ("DEBUG", "DB query completed in {duration_ms}ms", "inventory.db"),
        ],
        "slow_query": [
            ("WARN", "Slow query detected: SELECT stock FROM products WHERE sku IN (...) took {duration_ms}ms", "inventory.db"),
            ("ERROR", "Query timeout after {duration_ms}ms on stock-check endpoint", "inventory.handler"),
        ],
    },
    "catalog-service": {
        "normal": [
            ("INFO", "Product search: query='{query}' returned {count} results", "catalog.search"),
            ("DEBUG", "Cache hit for product {product_id}", "catalog.cache"),
        ],
    },
    "notification-service": {
        "normal": [
            ("INFO", "Notification sent: type={type}, recipient={recipient}", "notify.handler"),
            ("DEBUG", "Message enqueued to {queue}", "notify.queue"),
        ],
    },
    "api-gateway": {
        "normal": [
            ("INFO", "{method} {path} -> {status_code} ({duration_ms}ms)", "gateway.access"),
            ("DEBUG", "Auth token validated for user {user_id}", "gateway.auth"),
        ],
    },
}


class LogGenerator:
    """Generate structured logs for ShopFast services."""

    def __init__(self, services: dict[str, ServiceDef] | None = None, seed: int = 42):
        self.services = services or SERVICES
        self.rng = random.Random(seed)
        self._active_scenario: str = "normal"
        self._scenario_services: set[str] = set()

    def set_scenario(self, scenario: str, affected_services: list[str]) -> None:
        self._active_scenario = scenario
        self._scenario_services = set(affected_services)

    def generate_logs(
        self,
        service: str,
        start: float,
        end: float,
        logs_per_second: float = 2.0,
    ) -> list[LogEntry]:
        """Generate logs for a service in a time range."""
        svc = self.services.get(service)
        if svc is None:
            return []

        scenario = (
            self._active_scenario
            if service in self._scenario_services
            else "normal"
        )
        templates = LOG_TEMPLATES.get(service, {}).get(scenario) or LOG_TEMPLATES.get(
            service, {}
        ).get("normal", [])
        if not templates:
            return []

        logs: list[LogEntry] = []
        t = start
        interval = 1.0 / logs_per_second
        while t < end:
            level, msg_template, logger = self.rng.choice(templates)
            msg = self._fill_template(msg_template, svc)
            instance = f"{service}-{self._pod_suffix()}"

            logs.append(
                LogEntry(
                    timestamp=datetime.fromtimestamp(t, tz=timezone.utc).isoformat(),
                    level=level,
                    service=service,
                    instance=instance,
                    trace_id=uuid.uuid4().hex[:16],
                    span_id=uuid.uuid4().hex[:8],
                    message=msg,
                    logger=logger,
                    endpoint=svc.endpoints[0].path if svc.endpoints else None,
                    method="POST" if "order" in service or "payment" in service else "GET",
                    status_code=500 if level == "ERROR" else 200,
                    duration_ms=round(self.rng.uniform(5, 5000 if level == "ERROR" else 200), 1),
                    extra={},
                )
            )
            t += interval + self.rng.uniform(-interval * 0.3, interval * 0.3)
        return logs

    def search(
        self,
        service: str | None = None,
        level: str | None = None,
        message_contains: str | None = None,
        time_from: float | None = None,
        time_to: float | None = None,
        limit: int = 20,
    ) -> list[LogEntry]:
        """Search logs across all or specific services."""
        start = time_from or 0
        end = time_to or (start + 3600)
        services_to_query = [service] if service else list(self.services.keys())

        all_logs: list[LogEntry] = []
        for svc_name in services_to_query:
            all_logs.extend(self.generate_logs(svc_name, start, end))

        if level:
            all_logs = [log for log in all_logs if log.level == level]
        if message_contains:
            kw = message_contains.lower()
            all_logs = [log for log in all_logs if kw in log.message.lower()]

        all_logs.sort(key=lambda x: x.timestamp, reverse=True)
        return all_logs[:limit]

    def _fill_template(self, template: str, svc: ServiceDef) -> str:
        pool_max = svc.db_pool_max or 20
        replacements = {
            "order_id": f"ORD-{self.rng.randint(1000, 9999)}",
            "user_id": f"USR-{self.rng.randint(100, 999)}",
            "duration_ms": str(self.rng.randint(5, 5000)),
            "active": str(self.rng.randint(pool_max - 3, pool_max)),
            "max": str(pool_max),
            "waiting": str(self.rng.randint(10, 60)),
            "pool_pct": str(self.rng.randint(85, 100)),
            "timeout_ms": "5000",
            "healthy": str(self.rng.randint(10, pool_max)),
            "total": str(pool_max),
            "amount": f"{self.rng.uniform(10, 500):.2f}",
            "gateway_status": self.rng.choice(["OK", "TIMEOUT", "ERROR"]),
            "retry": str(self.rng.randint(1, 3)),
            "max_retries": "3",
            "failures": str(self.rng.randint(3, 10)),
            "threshold": "5",
            "gc_pause_ms": str(self.rng.randint(500, 2000)),
            "heap_used_mb": str(self.rng.randint(1500, 1950)),
            "heap_max_mb": "2048",
            "heap_pct": str(self.rng.randint(85, 98)),
            "sku": f"SKU-{self.rng.randint(10000, 99999)}",
            "quantity": str(self.rng.randint(0, 500)),
            "item_count": str(self.rng.randint(1, 10)),
            "query": self.rng.choice(["laptop", "phone", "headphones"]),
            "count": str(self.rng.randint(0, 50)),
            "product_id": f"PROD-{self.rng.randint(1000, 9999)}",
            "type": self.rng.choice(["email", "sms", "push"]),
            "recipient": f"user{self.rng.randint(1, 100)}@example.com",
            "queue": "notifications",
            "method": "POST",
            "path": "/api/v1/orders",
            "status_code": "200",
            "status": self.rng.choice(["confirmed", "processing", "shipped"]),
        }
        result = template
        for k, v in replacements.items():
            result = result.replace("{" + k + "}", v)
        return result

    def _pod_suffix(self) -> str:
        chars = "abcdefghijklmnopqrstuvwxyz0123456789"
        return "".join(self.rng.choices(chars, k=5))
