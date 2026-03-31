# RB-008: Slow Query Cascade

| Field         | Value                                                    |
|---------------|----------------------------------------------------------|
| **Service**   | inventory-service                                        |
| **Severity**  | P2 - High                                                |
| **Last Updated** | 2026-03-15                                            |
| **Author**    | Platform Engineering / ShopFast SRE                      |
| **Alert**     | `SlowQueryDetected`                                      |

## Symptoms

- **Alert fires:** `SlowQueryDetected` with labels `service=inventory-service`, `namespace=shopfast-prod`, `endpoint=/api/v1/stock` when p99 latency exceeds 5 seconds
- **Grafana dashboard:** "ShopFast / Inventory Service" shows p99 latency spike on `/api/v1/stock` and `/api/v1/stock/bulk` endpoints, while other endpoints remain normal
- **Metrics:**
  - `http_server_requests_seconds{service="inventory-service", uri="/api/v1/stock", quantile="0.99"} > 5`
  - `http_server_requests_seconds{service="inventory-service", uri="/api/v1/stock/bulk", quantile="0.99"} > 10`
  - `hikaricp_connections_active{service="inventory-service"}` climbing (connections held by slow queries)
  - `pg_stat_activity_max_tx_duration{datname="shopfast_inventory"} > 5`
- **User impact:** Product pages load slowly or time out when displaying stock availability. Cart checkout stalls when verifying inventory. Catalog-service and order-service experience cascading timeouts because they call inventory-service synchronously.
- **Logs:** `WARN  SlowQueryInterceptor - Query took 8432ms` and upstream services logging `java.net.SocketTimeoutException: Read timed out` when calling inventory-service

## Investigation Steps

### 1. Confirm latency spike and affected endpoints

```bash
kubectl exec -n shopfast-prod deploy/inventory-service -- curl -s localhost:8080/actuator/metrics/http.server.requests?tag=uri:/api/v1/stock | jq '.measurements[] | select(.statistic=="MAX" or .statistic=="COUNT")'
kubectl logs -n shopfast-prod -l app=inventory-service --tail=100 | grep "SlowQuery\|slow\|took.*ms"
```

### 2. Check PostgreSQL for slow running queries

```sql
-- Connect to shopfast_inventory database
SELECT pid, usename, now() - query_start AS duration, state, left(query, 120) AS query
FROM pg_stat_activity
WHERE datname = 'shopfast_inventory'
  AND state = 'active'
  AND now() - query_start > interval '2 seconds'
ORDER BY duration DESC;
```

### 3. Check pg_stat_statements for the offending query pattern

```sql
SELECT queryid, calls, mean_exec_time::numeric(10,2) AS avg_ms,
       max_exec_time::numeric(10,2) AS max_ms,
       rows, left(query, 100) AS query
FROM pg_stat_statements
WHERE dbid = (SELECT oid FROM pg_database WHERE datname = 'shopfast_inventory')
  AND mean_exec_time > 1000
ORDER BY mean_exec_time DESC
LIMIT 10;
```

### 4. Run EXPLAIN ANALYZE on the suspected slow query

```sql
-- The typical slow query pattern for /api/v1/stock
EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
SELECT sku, warehouse_id, quantity_available, quantity_reserved, last_updated
FROM inventory_stock
WHERE sku = ANY(ARRAY['SKU-10234', 'SKU-10235', 'SKU-10236'])
  AND warehouse_id IN (SELECT id FROM warehouses WHERE region = 'us-east-1')
  AND quantity_available > 0;

-- Check for sequential scans that should be index scans
EXPLAIN (ANALYZE, BUFFERS)
SELECT sku, SUM(quantity_available) AS total_stock
FROM inventory_stock
WHERE last_updated > now() - interval '24 hours'
GROUP BY sku
HAVING SUM(quantity_available) < 10;
```

### 5. Check for missing indexes

```sql
-- Check index usage on the inventory_stock table
SELECT relname, indexrelname, idx_scan, idx_tup_read, idx_tup_fetch
FROM pg_stat_user_indexes
WHERE relname = 'inventory_stock'
ORDER BY idx_scan;

-- Check for sequential scans on large tables
SELECT relname, seq_scan, seq_tup_read, idx_scan, idx_tup_fetch,
       n_live_tup, last_autoanalyze, last_autovacuum
FROM pg_stat_user_tables
WHERE relname IN ('inventory_stock', 'warehouses', 'stock_reservations')
ORDER BY seq_scan DESC;
```

### 6. Check table bloat and statistics freshness

```sql
SELECT relname, n_live_tup, n_dead_tup,
       round(n_dead_tup::numeric / NULLIF(n_live_tup, 0) * 100, 2) AS dead_pct,
       last_autovacuum, last_autoanalyze
FROM pg_stat_user_tables
WHERE schemaname = 'public'
  AND relname IN ('inventory_stock', 'stock_reservations')
ORDER BY n_dead_tup DESC;
```

### 7. Check if the issue cascades to upstream services

```bash
kubectl logs -n shopfast-prod -l app=catalog-service --tail=50 | grep -i "timeout\|inventory"
kubectl logs -n shopfast-prod -l app=order-service --tail=50 | grep -i "timeout\|inventory"
```

## Remediation

### Immediate (reduce impact)

1. **Kill the long-running queries to free connections:**

```sql
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE datname = 'shopfast_inventory'
  AND state = 'active'
  AND now() - query_start > interval '30 seconds'
  AND query NOT LIKE '%pg_stat%';
```

2. **Add the missing index (if identified via EXPLAIN):**

```sql
-- Common missing index for the stock lookup pattern
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_inventory_stock_sku_warehouse
  ON inventory_stock (sku, warehouse_id)
  WHERE quantity_available > 0;

-- Index for the time-based aggregation query
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_inventory_stock_last_updated
  ON inventory_stock (last_updated)
  WHERE last_updated > now() - interval '7 days';
```

3. **Force a statistics refresh if query planner estimates are stale:**

```sql
ANALYZE inventory_stock;
ANALYZE stock_reservations;
```

4. **Scale inventory-service to absorb load while queries are slow:**

```bash
kubectl scale deployment/inventory-service -n shopfast-prod --replicas=6
```

5. **If the cascade is severe, temporarily increase timeouts on upstream services:**

```bash
kubectl set env deployment/catalog-service -n shopfast-prod INVENTORY_CLIENT_TIMEOUT_MS=10000
kubectl set env deployment/order-service -n shopfast-prod INVENTORY_CLIENT_TIMEOUT_MS=10000
```

### Root Cause

- **Missing index:** The most common cause. The `inventory_stock` table grows as SKU count increases. A full table scan on 10M+ rows causes multi-second queries. Verify that indexes exist for the query patterns used by `/api/v1/stock`.
- **Table bloat:** If autovacuum is not keeping up, dead tuple accumulation causes index scans to degrade. Check `n_dead_tup` vs `n_live_tup` ratio. If dead_pct > 20%, run `VACUUM ANALYZE inventory_stock`.
- **Query plan regression:** A PostgreSQL version upgrade or `ANALYZE` run can change the query planner's chosen plan. Compare `EXPLAIN` output with the known-good plan.
- **Data growth:** A bulk import or inventory sync job may have added millions of rows without corresponding index maintenance. Check `pg_stat_user_tables.n_live_tup` trend.
- **Lock contention:** Concurrent stock reservation writes (`UPDATE inventory_stock SET quantity_reserved = ...`) can cause row-level lock waits. Check `pg_stat_activity` for `wait_event_type = 'Lock'`.

## Escalation

| Condition                                                   | Action                                        |
|-------------------------------------------------------------|-----------------------------------------------|
| Slow queries persist after adding index                     | Engage DBA team for query plan analysis       |
| Cascade causes order-service or catalog-service to degrade  | Escalate to P1, page SRE lead                 |
| Table bloat > 30% and autovacuum is stuck                   | Page DBA team for manual vacuum               |
| Connection pool exhaustion on inventory-service (see RB-001)| Follow RB-001, cross-reference with this issue|
| Root cause requires schema migration                        | Schedule maintenance window with DBA team     |
