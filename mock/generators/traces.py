"""OpenTelemetry-style distributed trace generator."""

from __future__ import annotations

from typing import Optional

import random
import uuid

from mock.config import SERVICES, ServiceDef

from .base import Span

# Trace templates define span trees for common user flows.
# Format: (service, operation, base_duration_min_ms, base_duration_max_ms)
TRACE_TEMPLATES: dict[str, dict] = {
    "checkout": {
        "root": ("api-gateway", "handle_request", 10, 20),
        "children": [
            {"node": ("api-gateway", "authenticate", 5, 15)},
            {
                "node": ("order-service", "create_order", 80, 200),
                "children": [
                    {"node": ("order-service", "validate_cart", 5, 15)},
                    {
                        "node": ("inventory-service", "reserve_stock", 20, 60),
                        "children": [
                            {"node": ("inventory-service", "db_query", 10, 40)},
                        ],
                    },
                    {
                        "node": ("payment-service", "charge", 50, 150),
                        "children": [
                            {"node": ("payment-service", "gateway_call", 40, 130)},
                        ],
                    },
                    {"node": ("notification-service", "enqueue", 5, 20)},
                ],
            },
        ],
    },
    "browse_catalog": {
        "root": ("api-gateway", "handle_request", 5, 15),
        "children": [
            {
                "node": ("catalog-service", "search_products", 8, 30),
                "children": [
                    {"node": ("inventory-service", "batch_stock_check", 10, 25)},
                ],
            },
        ],
    },
    "add_to_cart": {
        "root": ("api-gateway", "handle_request", 5, 10),
        "children": [
            {
                "node": ("cart-service", "add_item", 8, 25),
                "children": [
                    {"node": ("catalog-service", "validate_product", 3, 10)},
                ],
            },
        ],
    },
}


class TraceGenerator:
    """Generate distributed traces across ShopFast services."""

    def __init__(self, services: Optional[dict[str, ServiceDef]] = None, seed: int = 42):
        self.services = services or SERVICES
        self.rng = random.Random(seed)
        self._anomaly_overrides: dict[str, dict] = {}

    def set_anomaly(
        self,
        service: str,
        operation: str,
        duration_ms: Optional[float] = None,
        status: str = "ERROR",
        error_message: Optional[str] = None,
    ) -> None:
        """Override a specific span to simulate an anomaly."""
        key = f"{service}:{operation}"
        self._anomaly_overrides[key] = {
            "duration_ms": duration_ms,
            "status": status,
            "error_message": error_message,
        }

    def generate_trace(
        self, template_name: str, start_time: float
    ) -> list[Span]:
        """Generate a complete trace from a template."""
        template = TRACE_TEMPLATES.get(template_name)
        if template is None:
            return []

        trace_id = uuid.uuid4().hex[:16]
        spans: list[Span] = []
        self._build_spans(template, trace_id, None, start_time, spans)
        return spans

    def _build_spans(
        self,
        node: dict,
        trace_id: str,
        parent_span_id: Optional[str],
        current_time: float,
        spans: list[Span],
    ) -> float:
        root_info = node.get("root") or node.get("node")
        if root_info is None:
            return current_time

        service, operation, dur_min, dur_max = root_info
        span_id = uuid.uuid4().hex[:8]

        # Check for anomaly override
        key = f"{service}:{operation}"
        override = self._anomaly_overrides.get(key)

        if override and override.get("duration_ms"):
            duration = override["duration_ms"]
            status = override.get("status", "ERROR")
        else:
            duration = self.rng.uniform(dur_min, dur_max)
            status = "OK"

        events = []
        if override and override.get("error_message"):
            events.append({
                "name": "exception",
                "timestamp": current_time + duration / 2000,
                "attributes": {"exception.message": override["error_message"]},
            })

        span = Span(
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            operation_name=f"{service}.{operation}",
            service_name=service,
            start_time=current_time,
            duration_ms=duration,
            status=status if override else "OK",
            attributes={"service": service, "operation": operation},
            events=events or None,
        )
        spans.append(span)

        # Process children sequentially within the parent span
        child_time = current_time + self.rng.uniform(1, 5) / 1000
        for child in node.get("children", []):
            child_time = self._build_spans(child, trace_id, span_id, child_time, spans)
            child_time += self.rng.uniform(1, 5) / 1000  # gap between children

        return current_time + duration / 1000
