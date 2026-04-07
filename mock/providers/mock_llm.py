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
    # --- Healthcare / MedFlow scenarios ---
    "EHRConnectionPoolExhausted": (
        "ROOT_CAUSE: Database connection pool exhaustion on patient-service. "
        "Connections are being leaked in PatientRepository.findByMRN() — when a patient lookup "
        "returns no results (null path), the JDBC connection is acquired but never returned to the "
        "HikariCP pool. During overnight ER registration with high volumes of new-patient lookups, "
        "each 'patient not found' query leaks a connection. The pool saturates at 20/20, causing "
        "all FHIR Patient endpoints to return HTTP 500. This matches the pattern from incident "
        "EHR-1001 where the identical connection leak was identified in the v2.1.0 deployment.\n"
        "REMEDIATION: restart deployment patient-service in namespace medflow-prod\n"
        "CONFIDENCE: 0.92\n"
        "EVIDENCE: RB-101, EHR-1001, EHR-1003, error logs showing pool exhaustion, "
        "idle-in-transaction connections in pg_stat_activity"
    ),
    "BillingInsuranceTimeout": (
        "ROOT_CAUSE: External insurance verification API (clearinghouse) is experiencing degraded "
        "performance, causing billing-service p99 latency to spike to 25+ seconds. This blocks the "
        "claims processing pipeline — EDI 837 submissions fail, and the claims queue depth grows "
        "unbounded. Thread pool on billing-service saturates as threads block waiting for the slow "
        "clearinghouse API. No circuit breaker is configured, allowing the cascade. Similar to "
        "EHR-1002 where the clearinghouse had an unannounced maintenance window.\n"
        "REMEDIATION: scale deployment billing-service in namespace medflow-prod to 4 replicas\n"
        "CONFIDENCE: 0.78\n"
        "EVIDENCE: RB-102, EHR-1002, clearinghouse timeout errors in logs, EDI 837 submission failures"
    ),
    "PharmacyHighHeapUsage": (
        "ROOT_CAUSE: JVM memory leak in pharmacy-service. Heap usage has been drifting upward, now "
        "at 92% of the 4GB limit. GC pause times exceeding 1.5 seconds are causing medication "
        "dispensing delays. The leak is in DrugInteractionCache — the eviction listener for expired "
        "cache entries allocates new InteractionResult objects that create a strong reference chain "
        "preventing garbage collection. Under high-volume morning medication pass, the cache churns "
        "frequently, accelerating the leak. Matches pattern from EHR-1004.\n"
        "REMEDIATION: restart deployment pharmacy-service in namespace medflow-prod\n"
        "CONFIDENCE: 0.88\n"
        "EVIDENCE: RB-103, EHR-1004, GC pause warnings in logs, heap dump showing "
        "DrugInteractionCache holding 450K+ InteractionResult objects"
    ),
    "SchedulingRedisPoolExhausted": (
        "ROOT_CAUSE: Redis connection pool exhaustion on scheduling-service. All 50 connections are "
        "in use, causing timeout errors for appointment booking and bed management operations. The "
        "session cache expiration handler opens new Redis connections to clean up booking locks when "
        "sessions expire, but does not return connections to the pool. Under Monday morning scheduling "
        "rush with high session churn, the pool exhausts within 30 minutes. Matches EHR-1005.\n"
        "REMEDIATION: restart deployment scheduling-service in namespace medflow-prod\n"
        "CONFIDENCE: 0.90\n"
        "EVIDENCE: RB-104, EHR-1005, Redis timeout errors in logs, pool at 50/50"
    ),
    "MedicationSlowQueryDetected": (
        "ROOT_CAUSE: Missing database index on the drugs table ndc_code column in medication-service. "
        "SELECT queries for drug interaction checks on /api/v1/interactions are doing full sequential "
        "scans across 180K+ NDC entries, taking 5+ seconds per query. This cascades to patient-service "
        "which calls medication-service for drug validation during admission workflows, and to CPOE "
        "ordering in ehr-gateway. The index was lost during a formulary data refresh that rebuilt the "
        "drugs table without recreating secondary indexes. Matches EHR-1006.\n"
        "REMEDIATION: restart deployment medication-service in namespace medflow-prod\n"
        "CONFIDENCE: 0.85\n"
        "EVIDENCE: RB-105, EHR-1006, slow query warnings in logs, EXPLAIN showing Seq Scan on drugs"
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
    # --- Healthcare / MedFlow scenarios ---
    "EHRConnectionPoolExhausted": (
        "CONFIDENCE_JUSTIFIED: yes — pattern matches EHR-1001 exactly. Pool at 20/20 with "
        "idle-in-transaction connections is a clear indicator of the PatientRepository connection leak.\n"
        "ALTERNATIVE_CAUSES: high concurrent admission volume during ER surge, "
        "database server-side connection limit reached\n"
        "MIGHT_BE_SYMPTOM: no — the connection leak is the direct root cause. However, if ER "
        "patient volume was unusually high, the leak would manifest faster.\n"
        "ADJUSTED_CONFIDENCE: 0.90"
    ),
    "BillingInsuranceTimeout": (
        "CONFIDENCE_JUSTIFIED: no — 0.78 may be too high given external dependency uncertainty. "
        "Scaling billing-service adds capacity to absorb the backlog but does not address the root "
        "cause if the clearinghouse API is completely down rather than degraded.\n"
        "ALTERNATIVE_CAUSES: DNS resolution failure to clearinghouse endpoint, "
        "network partition between billing-service and clearinghouse, "
        "TLS certificate issue on clearinghouse API, EDI gateway rate limiting\n"
        "MIGHT_BE_SYMPTOM: yes — the timeout is a symptom of clearinghouse degradation. "
        "Scaling treats the symptom by absorbing more concurrent waiting requests, but if the "
        "clearinghouse is fully down, scaling alone will not resolve the claims backlog.\n"
        "ADJUSTED_CONFIDENCE: 0.72"
    ),
    "PharmacyHighHeapUsage": (
        "CONFIDENCE_JUSTIFIED: yes — matches EHR-1004 pattern closely. Heap drift + GC pauses "
        "during morning medication pass are consistent with the DrugInteractionCache leak.\n"
        "ALTERNATIVE_CAUSES: large formulary cache reload after data refresh, "
        "thread pool exhaustion causing object accumulation\n"
        "MIGHT_BE_SYMPTOM: no — the memory leak is the root cause. However, if v2.4.0 introduced "
        "the leak, rollback to v2.3.x would be a more durable fix than restart (restart only "
        "buys time until the heap fills again).\n"
        "ADJUSTED_CONFIDENCE: 0.85"
    ),
    "SchedulingRedisPoolExhausted": (
        "CONFIDENCE_JUSTIFIED: yes — pattern matches EHR-1005 exactly. Redis pool at max with "
        "timeout errors during high session churn is a clear signal of the session cleanup leak.\n"
        "ALTERNATIVE_CAUSES: Redis server memory pressure, network connectivity issue to Redis\n"
        "MIGHT_BE_SYMPTOM: no — connection pool exhaustion is the direct cause of booking failures.\n"
        "ADJUSTED_CONFIDENCE: 0.90"
    ),
    "MedicationSlowQueryDetected": (
        "CONFIDENCE_JUSTIFIED: yes — slow query logs and p99 spike on interactions endpoint are "
        "consistent with a missing index after formulary refresh.\n"
        "ALTERNATIVE_CAUSES: drugs table bloat requiring VACUUM FULL, "
        "lock contention from concurrent formulary data import, "
        "PostgreSQL query planner regression after ANALYZE\n"
        "MIGHT_BE_SYMPTOM: yes — restart will clear the query plan cache and may resolve symptoms "
        "temporarily, but the slow queries will return once the cache warms. The root cause is a "
        "missing index on drugs.ndc_code. Permanent fix requires CREATE INDEX CONCURRENTLY.\n"
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
