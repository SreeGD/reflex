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


# Pre-built critique responses for the Review Agent (keyed by alert patterns)
_CRITIQUE_RESPONSES = {
    "PaymentGatewayTimeout": (
        "CONFIDENCE_JUSTIFIED: no — 0.78 may be too high given external dependency uncertainty. "
        "Scaling payment-service adds capacity but does not address the root cause if the external "
        "gateway itself is completely down.\n"
        "ALTERNATIVE_CAUSES: DNS resolution failure to payment provider, "
        "network partition between payment-service and gateway, "
        "TLS certificate expiration on gateway endpoint\n"
        "MIGHT_BE_SYMPTOM: yes — the timeout is a symptom of external gateway degradation. "
        "Scaling treats the symptom by absorbing more concurrent waiting requests, but if the "
        "gateway is fully down, no amount of scaling helps.\n"
        "ADJUSTED_CONFIDENCE: 0.72"
    ),
    "HighHeapUsage": (
        "CONFIDENCE_JUSTIFIED: yes — matches OPS-1287 pattern closely, and heap drift + GC "
        "pauses are consistent with a memory leak.\n"
        "ALTERNATIVE_CAUSES: large response caching (similar to OPS-1245)\n"
        "MIGHT_BE_SYMPTOM: no — the memory leak is the root cause. However, if a recent deploy "
        "introduced the leak, rollback would be a better fix than restart (restart only buys time).\n"
        "ADJUSTED_CONFIDENCE: 0.85"
    ),
    "RedisPoolExhausted": (
        "CONFIDENCE_JUSTIFIED: yes — pattern matches OPS-1312 exactly. Redis pool at max with "
        "timeout errors is a clear signal.\n"
        "ALTERNATIVE_CAUSES: none\n"
        "MIGHT_BE_SYMPTOM: no — connection pool exhaustion is the direct cause of failures.\n"
        "ADJUSTED_CONFIDENCE: 0.90"
    ),
    "SlowQueryDetected": (
        "CONFIDENCE_JUSTIFIED: yes — slow query logs and p99 spike on stock endpoint are "
        "consistent with a missing index.\n"
        "ALTERNATIVE_CAUSES: table bloat requiring VACUUM, lock contention from concurrent writes\n"
        "MIGHT_BE_SYMPTOM: yes — restart will clear the query plan cache and resolve symptoms "
        "for approximately 2 hours, but the slow queries will return. The root cause is a missing "
        "index on the products.sku column. Root fix requires CREATE INDEX CONCURRENTLY.\n"
        "ADJUSTED_CONFIDENCE: 0.82"
    ),
}


class MockLLM:
    """Drop-in replacement for ChatAnthropic that returns pre-built responses."""

    async def ainvoke(self, messages: list[BaseMessage], **kwargs) -> AIMessage:
        full_text = " ".join(m.content for m in messages if hasattr(m, "content"))

        # Dispatch: critique prompts vs RCA prompts
        is_critique = "critically evaluate" in full_text.lower() or "confidence_justified" in full_text.lower()

        if is_critique:
            for pattern, response in _CRITIQUE_RESPONSES.items():
                if pattern.lower() in full_text.lower():
                    return AIMessage(content=response)
            # Fallback critique: everything looks fine
            return AIMessage(content=(
                "CONFIDENCE_JUSTIFIED: yes — evidence supports the assessment.\n"
                "ALTERNATIVE_CAUSES: none\n"
                "MIGHT_BE_SYMPTOM: no\n"
                "ADJUSTED_CONFIDENCE: 0.85"
            ))

        # RCA prompts
        for alert_pattern, response in _RCA_RESPONSES.items():
            if alert_pattern.lower() in full_text.lower():
                return AIMessage(content=response)

        return AIMessage(content=(
            "ROOT_CAUSE: Service degradation detected. Unable to determine specific root cause "
            "from available context. Manual investigation recommended.\n"
            "REMEDIATION: restart deployment affected-service in namespace shopfast-prod\n"
            "CONFIDENCE: 0.5\n"
            "EVIDENCE: alert context"
        ))
