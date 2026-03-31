# RB-001: Database Connection Pool Exhaustion

| Field         | Value                                                    |
|---------------|----------------------------------------------------------|
| **Service**   | order-service, inventory-service, payment-service        |
| **Severity**  | P1 - Critical                                            |
| **Last Updated** | 2026-02-18                                            |
| **Author**    | Platform Engineering / ShopFast SRE                      |
| **Alert**     | `DBConnectionPoolExhausted`                              |

## Symptoms

- **Alert fires:** `DBConnectionPoolExhausted` with labels `service=<affected-service>`, `namespace=shopfast-prod`
- **Grafana dashboard:** "ShopFast / Database Connections" shows active connections approaching or at pool max (20)
- **Metrics:**
  - `hikaricp_connections_active{service="order-service"} >= 20`
  - `hikaricp_connections_pending{service="order-service"} > 0`
  - `hikaricp_connections_timeout_total` increasing
- **User impact:** HTTP 500 errors on endpoints that require database access. Orders fail to submit, inventory lookups time out, payment records not written.
- **Logs:** `org.postgresql.util.PSQLException: Cannot acquire connection from pool` or `HikariPool-1 - Connection is not available, request timed out after 30000ms`

## Investigation Steps

### 1. Confirm which pods are affected

```bash
kubectl get pods -n shopfast-prod -l app=order-service -o wide
kubectl top pods -n shopfast-prod -l app=order-service
```

### 2. Check application connection pool metrics

```bash
kubectl exec -n shopfast-prod deploy/order-service -- curl -s localhost:8080/actuator/metrics/hikaricp.connections.active | jq .
kubectl exec -n shopfast-prod deploy/order-service -- curl -s localhost:8080/actuator/metrics/hikaricp.connections.pending | jq .
kubectl exec -n shopfast-prod deploy/order-service -- curl -s localhost:8080/actuator/metrics/hikaricp.connections.idle | jq .
```

### 3. Check PostgreSQL server-side connections

```sql
-- Run against the shopfast-prod database (connect via psql or pgAdmin)
SELECT count(*) AS total_connections FROM pg_stat_activity WHERE datname = 'shopfast';

SELECT usename, application_name, state, count(*)
FROM pg_stat_activity
WHERE datname = 'shopfast'
GROUP BY usename, application_name, state
ORDER BY count(*) DESC;

-- Find long-running or idle-in-transaction connections
SELECT pid, usename, application_name, state, query_start, now() - query_start AS duration, left(query, 80) AS query
FROM pg_stat_activity
WHERE datname = 'shopfast'
  AND state IN ('idle in transaction', 'active')
  AND now() - query_start > interval '30 seconds'
ORDER BY duration DESC;
```

### 4. Check if connections are leaking (idle in transaction)

```sql
SELECT pid, usename, state, now() - state_change AS idle_duration
FROM pg_stat_activity
WHERE datname = 'shopfast'
  AND state = 'idle in transaction'
  AND now() - state_change > interval '5 minutes';
```

### 5. Check recent deployments

```bash
kubectl rollout history deployment/order-service -n shopfast-prod
kubectl rollout history deployment/inventory-service -n shopfast-prod
kubectl rollout history deployment/payment-service -n shopfast-prod
```

## Remediation

### Immediate (restore service)

1. **Kill leaked connections on the database side:**

```sql
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE datname = 'shopfast'
  AND state = 'idle in transaction'
  AND now() - state_change > interval '10 minutes';
```

2. **Rolling restart of the affected service:**

```bash
kubectl rollout restart deployment/order-service -n shopfast-prod
kubectl rollout status deployment/order-service -n shopfast-prod --timeout=120s
```

3. **If pool is still saturated after restart, scale horizontally to distribute load:**

```bash
kubectl scale deployment/order-service -n shopfast-prod --replicas=5
```

### Root Cause

- Check for missing `@Transactional` timeout annotations or unclosed connections in recent code changes.
- Verify `spring.datasource.hikari.maximum-pool-size` is set to 20 and `leak-detection-threshold` is configured (recommended: 60000ms).
- Review slow queries that may hold connections open. Check `pg_stat_statements` for queries with `mean_exec_time > 5000`.
- If a downstream service is slow, connections may be held waiting for responses within a transaction boundary.

## Escalation

| Condition                                            | Action                                      |
|------------------------------------------------------|---------------------------------------------|
| Pool exhausted on 2+ services simultaneously         | Page Database DBA on-call                   |
| PostgreSQL total connections > 200 (server max=300)  | Page Database DBA on-call immediately       |
| Remediation steps do not resolve within 15 minutes   | Escalate to P0, engage Platform Engineering |
| Suspected connection leak in application code        | Create JIRA ticket for owning dev team      |
