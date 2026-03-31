"""Mock LLM that produces realistic RCA output without API calls.

Used when no ANTHROPIC_API_KEY is set or --mock-llm is passed.
Parses the alert context from the prompt and returns scenario-appropriate analysis.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, BaseMessage

# Pre-built RCA responses keyed by alert name patterns
_RCA_RESPONSES = {
    "DBConnectionPoolExhausted": (
        "ROOT_CAUSE: Database connection pool exhaustion on order-service. "
        "Connections are being leaked or held too long, saturating the pool at 20/20 active connections. "
        "All incoming requests fail with timeout waiting for a free connection. "
        "This matches the pattern from incidents OPS-1234 and OPS-1056 where connection leaks in "
        "the OrderRepository caused identical symptoms. The immediate fix is a rolling restart to "
        "clear leaked connections.\n"
        "REMEDIATION: restart deployment order-service in namespace shopfast-prod\n"
        "CONFIDENCE: 0.92\n"
        "EVIDENCE: RB-001, OPS-1234, OPS-1198, OPS-1056, error logs showing pool exhaustion"
    ),
    "PaymentGatewayTimeout": (
        "ROOT_CAUSE: External payment gateway is experiencing degraded performance, causing "
        "payment-service p99 latency to spike to 30+ seconds. This cascades to order-service "
        "(which calls payment-service for checkout) and api-gateway. Thread pool saturation on "
        "payment-service amplifies the impact. Similar to OPS-1301 where the external provider "
        "had an outage.\n"
        "REMEDIATION: scale deployment payment-service in namespace shopfast-prod to 4 replicas\n"
        "CONFIDENCE: 0.78\n"
        "EVIDENCE: RB-002, OPS-1301, OPS-1334, gateway timeout errors in logs"
    ),
    "HighHeapUsage": (
        "ROOT_CAUSE: JVM memory leak in payment-service. Heap usage has been drifting upward over "
        "hours, now at 90% of the 2GB limit. GC pause times exceeding 1 second are causing latency "
        "spikes. If not addressed, this will result in an OutOfMemoryError and pod crash within "
        "30 minutes. Matches pattern from OPS-1287 (HTTP client memory leak).\n"
        "REMEDIATION: restart deployment payment-service in namespace shopfast-prod\n"
        "CONFIDENCE: 0.88\n"
        "EVIDENCE: RB-003, OPS-1287, OPS-1245, GC pause warnings in logs"
    ),
    "RedisPoolExhausted": (
        "ROOT_CAUSE: Redis connection pool exhaustion on cart-service. All 50 connections are in use, "
        "causing timeout errors for cart operations. Likely caused by a connection leak or sudden "
        "traffic spike that exceeded pool capacity. Matches OPS-1312 where max connections were hit.\n"
        "REMEDIATION: restart deployment cart-service in namespace shopfast-prod\n"
        "CONFIDENCE: 0.90\n"
        "EVIDENCE: RB-004, OPS-1312, Redis timeout errors in logs"
    ),
    "SlowQueryDetected": (
        "ROOT_CAUSE: Missing database index on the products table sku column in inventory-service. "
        "SELECT queries on /api/v1/stock are doing full table scans taking 4.5+ seconds. This cascades "
        "to catalog-service and order-service which both depend on inventory-service for stock checks. "
        "Matches OPS-1267 where the same missing index caused identical symptoms.\n"
        "REMEDIATION: restart deployment inventory-service in namespace shopfast-prod\n"
        "CONFIDENCE: 0.85\n"
        "EVIDENCE: RB-008, OPS-1267, slow query warnings in logs"
    ),
}


class MockLLM:
    """Drop-in replacement for ChatAnthropic that returns pre-built responses."""

    async def ainvoke(self, messages: list[BaseMessage], **kwargs) -> AIMessage:
        # Extract alert context from messages
        full_text = " ".join(m.content for m in messages if hasattr(m, "content"))

        for alert_pattern, response in _RCA_RESPONSES.items():
            if alert_pattern.lower() in full_text.lower():
                return AIMessage(content=response)

        # Fallback generic response
        return AIMessage(content=(
            "ROOT_CAUSE: Service degradation detected. Unable to determine specific root cause "
            "from available context. Manual investigation recommended.\n"
            "REMEDIATION: restart deployment affected-service in namespace shopfast-prod\n"
            "CONFIDENCE: 0.5\n"
            "EVIDENCE: alert context"
        ))
