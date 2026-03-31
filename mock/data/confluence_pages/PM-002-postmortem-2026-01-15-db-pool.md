# Postmortem: DB Connection Pool Exhaustion on order-service

**Date:** 2026-01-15
**Severity:** SEV-2
**Incident Commander:** Alice Chen
**Author:** Alice Chen
**JIRA Ticket:** OPS-1234
**Duration:** 17 minutes (03:18 to 03:35 UTC)

## Summary

On January 15, 2026, the order-service experienced DB connection pool exhaustion caused by a connection leak in the `bulk_update()` method introduced in v2.14.3. The leak caused all 20 HikariCP connections per pod to be held indefinitely during batch processing, resulting in 500 errors on the order creation API. Approximately 12% of checkout requests failed over a 17-minute window. The incident was resolved by rolling back to v2.14.2.

## Impact

- **Duration:** 03:18 to 03:35 UTC (17 minutes)
- **Users Affected:** ~8% of active users (those attempting checkout)
- **Revenue Impact:** Estimated $4,200 in lost orders (based on average order value and failure rate)
- **Orders Affected:** ~340 failed checkout attempts, 290 successfully retried by customers after resolution
- **SLA Impact:** None (monthly error budget not exceeded)
- **Data Loss:** None. Failed orders were not created; no partial writes.

## Detection

- **How detected:** Prometheus alert `DBPoolExhaustion` fired when pool utilization exceeded 95% for 2 minutes
- **Alert that fired:** `hikaricp_connections_active / hikaricp_connections_max > 0.95` for 2min on order-service
- **Time to detect:** 4 minutes (pool started filling at 03:18, alert fired at 03:22)
- **Gap:** An 80% threshold alert would have given 3-4 minutes earlier warning. The pool climbed from 40% to 95% in about 4 minutes under batch load.

## Timeline

All times in UTC.

| Time | Event |
|------|-------|
| 03:14 | Batch order processing job starts (triggered by partner API bulk import) |
| 03:18 | DB pool utilization crosses 80% on order-service pods. No alert at this threshold. |
| 03:20 | Pool at 90%. Order API response times climbing (p99: 120ms -> 800ms) |
| 03:22 | Pool at 100%. Alert fires. 500 errors begin on /api/orders. Alice paged via PagerDuty. |
| 03:24 | Alice acknowledges. Opens Grafana Service Detail and DB Pool dashboards. |
| 03:26 | Confirms pool saturation (20/20 active connections, all pods). Checks ArgoCD for recent deploys. |
| 03:28 | Identifies v2.14.3 deployed at 22:00 previous day. Reviews PR diff. Spots bulk_update() refactor. |
| 03:30 | Root cause confirmed: bulk_update() acquires one connection per batch item, releases only in outer finally block. Under concurrent batch load, connections leak faster than they're released. |
| 03:32 | Initiates rollback to v2.14.2 via ArgoCD. |
| 03:34 | Rollback pods healthy. Pool utilization dropping. |
| 03:35 | Pool at normal levels (8/20). Error rate at 0%. Incident resolved. |

## Root Cause Analysis (5 Whys)

1. **Why** were checkout orders failing with 500 errors?
   Because the order-service could not acquire database connections from the HikariCP pool (30s timeout exceeded).

2. **Why** were all connections in use?
   Because the `bulk_update()` method in `OrderBatchProcessor` was acquiring a new connection for each item in the batch but only releasing connections in an outer `finally` block after the entire batch completed.

3. **Why** was the code structured this way?
   Because the v2.14.3 refactoring moved the connection acquisition inside a `for` loop to support per-item transaction isolation, but the corresponding `connection.close()` was not moved inside the loop.

4. **Why** was this not caught during code review or testing?
   Because unit tests mock the DataSource and don't enforce connection lifecycle. Integration tests run with a batch size of 5 items, which doesn't exhaust the pool. Production batches from the partner API are 200-500 items.

5. **Why** don't integration tests simulate production-scale batch sizes?
   Because test data generation for large batches was descoped during the Q4 sprint due to time constraints, and no follow-up ticket was created.

## Contributing Factors

- **No pgbouncer:** Direct connections to PostgreSQL mean the 20-connection pool per pod is a hard limit with no multiplexing. pgbouncer deployment has been deferred since Q3 2025 (INFRA-445).
- **Alert threshold too high:** The 95% pool utilization alert left only ~2 minutes between warning and full exhaustion. An 80% threshold would have provided earlier signal.
- **No pool utilization trend alert:** A rate-of-change alert on pool utilization would have caught the linear climb pattern minutes earlier.
- **Batch processing shares the same pool as API traffic:** No isolation between batch workloads and real-time API queries. A saturated pool from batch work directly impacts checkout.

## What Went Well

- On-call response was fast: 2 minutes from page to investigation start
- Correlation with recent deployment was quick thanks to ArgoCD deployment history
- Rollback was clean and fast (ArgoCD blue-green, 3-minute rollback)
- No data corruption or partial writes — failed connections resulted in clean errors

## What Went Poorly

- 4-minute detection gap between pool saturation start and alert firing
- No batch processing observability — no dashboard showing batch job status or resource consumption
- The v2.14.3 deploy was 5 hours old before the incident — batch job only runs at 03:14 UTC, so the bug was dormant until then

## Action Items

| ID | Action | Owner | Priority | Due Date | Status |
|----|--------|-------|----------|----------|--------|
| 1 | Fix bulk_update() connection handling using context manager pattern (PR #1847) | Bob Kim | P1 | 2026-01-17 | Complete |
| 2 | Add 80% pool utilization alert threshold (SEV-3 warning) | Alice Chen | P1 | 2026-01-18 | Complete |
| 3 | Deploy pgbouncer for connection pooling (INFRA-445) | Platform Team (Carol Davis) | P2 | 2026-02-28 | In Progress |
| 4 | Add integration tests for bulk operations with production-scale batch sizes (100+ items) | Bob Kim | P2 | 2026-01-31 | Complete |
| 5 | Implement separate connection pool for batch processing vs API traffic | Alice Chen | P2 | 2026-02-15 | Open |

## Lessons Learned

This incident reinforces a recurring theme in our DB connection management: we are operating without a connection pooler (pgbouncer) and with pool sizes that leave little headroom for unexpected load patterns. This is the third DB pool exhaustion incident in 5 months (after OPS-1198 and OPS-1056), each with a different proximate cause but the same underlying fragility. The pgbouncer deployment (INFRA-445) must be prioritized.

The detection gap also highlights a pattern: our alert thresholds are set for "already broken" rather than "trending toward broken." Adding rate-of-change alerts and lower warning thresholds would improve our MTTD for gradual degradation scenarios. The batch processing path is particularly risky because it runs during low-traffic hours when on-call attention is lowest, yet it can consume the same shared resources that the API depends on.

## Review

- [x] Reviewed by incident commander (Alice Chen)
- [x] Reviewed by Commerce team lead (Bob Kim)
- [x] Reviewed by platform team (Carol Davis)
- [x] Presented in weekly operations meeting (2026-01-16)
- [x] Action items created in JIRA
- [x] Runbook RB-001 updated with batch processing considerations
