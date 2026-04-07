# RB-105: Medication Service Slow Query

| Field         | Value                                                    |
|---------------|----------------------------------------------------------|
| **Service**   | medication-service                                       |
| **Severity**  | SEV-3 - Medium                                           |
| **Last Updated** | 2026-03-15                                            |
| **Author**    | MedFlow Platform Engineering / Pharmacy IT               |
| **Alert**     | `MedicationSlowQueryDetected`                            |
| **Clinical Impact** | Drug interaction checks delayed, medication ordering slow |

## Symptoms

- **Alert fires:** `MedicationSlowQueryDetected` with labels `service=medication-service`, `namespace=medflow-prod`
- **Grafana dashboard:** "MedFlow / Database Performance" shows medication-service query latency >5s
- **Metrics:**
  - `medication_query_latency_p99{service="medication-service"} > 5`
  - `medication_interaction_check_errors_total` increasing
  - `pg_stat_statements_mean_exec_time{query_pattern="drugs.*ndc_code"} > 4000`
- **User impact:** Drug interaction checks taking >5 seconds instead of <200ms. Clinicians experience hangs during medication order entry in the CPOE (Computerized Provider Order Entry) system. Cascades to patient-service which calls medication-service for drug validation during admission workflows.
- **Logs:** `WARN SlowQueryDetector: Query on drugs table exceeded 5000ms threshold` or `SELECT * FROM drugs WHERE ndc_code = ? -- execution time: 5234ms (full table scan)`

## Investigation Steps

### 1. Confirm medication-service pod health

```bash
kubectl get pods -n medflow-prod -l app=medication-service -o wide
kubectl top pods -n medflow-prod -l app=medication-service
```

### 2. Check query performance metrics

```bash
kubectl exec -n medflow-prod deploy/medication-service -- curl -s localhost:9081/actuator/metrics/medication.query.latency | jq .
kubectl exec -n medflow-prod deploy/medication-service -- curl -s localhost:9081/actuator/metrics/medication.interaction.check.latency | jq .
```

### 3. Analyze PostgreSQL slow query log

```sql
-- Connect to medflow_medications database
SELECT query, calls, mean_exec_time, total_exec_time
FROM pg_stat_statements
WHERE dbid = (SELECT oid FROM pg_database WHERE datname = 'medflow_medications')
ORDER BY mean_exec_time DESC
LIMIT 10;

-- Check for missing indexes on drugs table
SELECT schemaname, tablename, indexname
FROM pg_indexes
WHERE tablename = 'drugs'
ORDER BY indexname;

-- Check table size and row count
SELECT pg_size_pretty(pg_total_relation_size('drugs')) AS total_size,
       (SELECT count(*) FROM drugs) AS row_count;
```

### 4. Verify the query plan

```sql
EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM drugs WHERE ndc_code = '00069-3150-83';
-- Look for "Seq Scan" indicating missing index
```

### 5. Check cascading impact on patient-service

```bash
kubectl exec -n medflow-prod deploy/patient-service -- curl -s localhost:9083/actuator/metrics/patient.admission.latency | jq .
```

## Remediation

### Immediate (restore query performance)

1. **Restart medication-service to clear query plan cache:**

```bash
kubectl rollout restart deployment/medication-service -n medflow-prod
kubectl rollout status deployment/medication-service -n medflow-prod --timeout=120s
```

2. **Verify interaction check latency returns to normal:**

```bash
kubectl exec -n medflow-prod deploy/medication-service -- curl -s localhost:9081/api/v1/interactions/check -X POST -H "Content-Type: application/json" -d '{"drug_codes":["00069-3150-83","00378-0152-01"]}' -o /dev/null -w "latency: %{time_total}s\n"
```

3. **Create the missing index (permanent fix, requires DBA approval):**

```sql
-- Run during maintenance window or use CONCURRENTLY
CREATE INDEX CONCURRENTLY idx_drugs_ndc_code ON drugs (ndc_code);
CREATE INDEX CONCURRENTLY idx_drugs_rxnorm_code ON drugs (rxnorm_code);
```

4. **Verify formulary and interaction endpoints:**

```bash
kubectl exec -n medflow-prod deploy/medication-service -- curl -s -o /dev/null -w "%{http_code}" localhost:9081/api/v1/formulary/search?q=metformin
kubectl exec -n medflow-prod deploy/medication-service -- curl -s -o /dev/null -w "%{http_code}" localhost:9081/api/v1/drugs/ndc/00069-3150-83
```

### Root Cause

- Missing database index on `drugs.ndc_code` column. The drugs table contains 180,000+ NDC (National Drug Code) entries. Without an index, every drug lookup and interaction check performs a full sequential scan.
- The issue was introduced when the drugs table was rebuilt during a formulary data refresh. The migration script recreated the table but did not recreate the indexes.
- Restart clears the PostgreSQL query plan cache on the application side, which may temporarily improve performance as the planner re-evaluates execution paths, but the slow queries will return within ~2 hours as the cache warms.

## Clinical Impact Assessment

| Impact Area                    | Severity | Workaround                              |
|--------------------------------|----------|-----------------------------------------|
| Drug interaction checks        | High     | Pharmacist manual review using Lexicomp |
| CPOE medication ordering       | High     | Verbal orders with pharmacist validation|
| Formulary lookups              | Medium   | Reference printed formulary guide       |
| Patient admission drug review  | Medium   | Delayed admission medication reconciliation |

## Escalation

| Condition                                            | Action                                          |
|------------------------------------------------------|-------------------------------------------------|
| Interaction checks unavailable >10 minutes           | Page Chief Pharmacist                           |
| CPOE ordering blocked                                | Notify Chief Medical Information Officer (CMIO) |
| Cascading to patient-service admissions              | Escalate to SEV-2                               |
| DBA unavailable for index creation                   | Engage Platform Engineering lead                |

## References

- EHR-1006: Medication slow query incident
- NDC Database: https://wiki.medflow.com/data/ndc-database
- Formulary Refresh SOP: https://wiki.medflow.com/sop/formulary-refresh
