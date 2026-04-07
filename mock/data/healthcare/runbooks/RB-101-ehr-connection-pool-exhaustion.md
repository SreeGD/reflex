# RB-101: EHR Connection Pool Exhaustion

| Field         | Value                                                    |
|---------------|----------------------------------------------------------|
| **Service**   | patient-service                                          |
| **Severity**  | SEV-2 - High                                             |
| **Last Updated** | 2026-02-25                                            |
| **Author**    | MedFlow Platform Engineering / Clinical IT SRE           |
| **Alert**     | `EHRConnectionPoolExhausted`                             |
| **HIPAA Impact** | PHI access disrupted - patient records unavailable    |

## Symptoms

- **Alert fires:** `EHRConnectionPoolExhausted` with labels `service=patient-service`, `namespace=medflow-prod`
- **Grafana dashboard:** "MedFlow / Database Connections" shows active connections approaching or at pool max (20)
- **Metrics:**
  - `hikaricp_connections_active{service="patient-service"} >= 20`
  - `hikaricp_connections_pending{service="patient-service"} > 0`
  - `hikaricp_connections_timeout_total` increasing
- **User impact:** FHIR Patient endpoints returning HTTP 500. Clinicians unable to access patient records. ER staff forced to paper-based workarounds. Medication ordering blocked (patient-service dependency).
- **Logs:** `org.postgresql.util.PSQLException: Cannot acquire connection from pool` or `HikariPool-1 - Connection is not available, request timed out after 5000ms`
- **Downstream:** ehr-gateway latency spikes (depends on patient-service for patient context), medication-service unable to validate patient IDs for drug interaction checks.

## Investigation Steps

### 1. Confirm which pods are affected

```bash
kubectl get pods -n medflow-prod -l app=patient-service -o wide
kubectl top pods -n medflow-prod -l app=patient-service
```

### 2. Check application connection pool metrics

```bash
kubectl exec -n medflow-prod deploy/patient-service -- curl -s localhost:9083/actuator/metrics/hikaricp.connections.active | jq .
kubectl exec -n medflow-prod deploy/patient-service -- curl -s localhost:9083/actuator/metrics/hikaricp.connections.pending | jq .
kubectl exec -n medflow-prod deploy/patient-service -- curl -s localhost:9083/actuator/metrics/hikaricp.connections.idle | jq .
```

### 3. Check PostgreSQL server-side connections

```sql
-- Run against the medflow-prod patient database (encrypted RDS instance)
SELECT count(*) AS total_connections FROM pg_stat_activity WHERE datname = 'medflow_patients';

SELECT usename, application_name, state, count(*)
FROM pg_stat_activity
WHERE datname = 'medflow_patients'
GROUP BY usename, application_name, state
ORDER BY count(*) DESC;

-- Find long-running or idle-in-transaction connections (PHI query audit)
SELECT pid, usename, application_name, state, query_start, now() - query_start AS duration, left(query, 80) AS query
FROM pg_stat_activity
WHERE datname = 'medflow_patients'
  AND state IN ('idle in transaction', 'active')
  AND now() - query_start > interval '30 seconds'
ORDER BY duration DESC;
```

### 4. Check if connections are leaking (idle in transaction)

```sql
SELECT pid, usename, state, now() - state_change AS idle_duration
FROM pg_stat_activity
WHERE datname = 'medflow_patients'
  AND state = 'idle in transaction'
  AND now() - state_change > interval '5 minutes';
```

### 5. Check FHIR endpoint health

```bash
# Verify FHIR R4 Patient endpoint
kubectl exec -n medflow-prod deploy/patient-service -- curl -s -o /dev/null -w "%{http_code}" localhost:9083/fhir/r4/Patient?_count=1

# Check FHIR capability statement
kubectl exec -n medflow-prod deploy/patient-service -- curl -s localhost:9083/fhir/r4/metadata | jq '.status'
```

### 6. Check recent deployments

```bash
kubectl rollout history deployment/patient-service -n medflow-prod
```

## Remediation

### Immediate (restore service)

1. **Kill leaked connections on the database side:**

```sql
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE datname = 'medflow_patients'
  AND state = 'idle in transaction'
  AND now() - state_change > interval '10 minutes';
```

2. **Rolling restart of patient-service:**

```bash
kubectl rollout restart deployment/patient-service -n medflow-prod
kubectl rollout status deployment/patient-service -n medflow-prod --timeout=120s
```

3. **Verify FHIR endpoints are responding:**

```bash
# Patient search should return 200
kubectl exec -n medflow-prod deploy/patient-service -- curl -s -o /dev/null -w "%{http_code}" localhost:9083/fhir/r4/Patient?_count=1

# Patient create should accept POST
kubectl exec -n medflow-prod deploy/patient-service -- curl -s -X POST -H "Content-Type: application/fhir+json" -d '{"resourceType":"Patient","name":[{"family":"Test"}]}' localhost:9083/fhir/r4/Patient -o /dev/null -w "%{http_code}"
```

4. **If pool is still saturated after restart, scale horizontally:**

```bash
kubectl scale deployment/patient-service -n medflow-prod --replicas=5
```

### Root Cause

- Connection leak in `PatientRepository.findByMRN()` method. The JDBC connection is acquired but not released when the patient lookup returns no results (null path does not close the connection).
- Verify `spring.datasource.hikari.maximum-pool-size` is set to 20 and `leak-detection-threshold` is configured (recommended: 60000ms).
- Review slow queries on the `patients` table, especially full-text searches on `patient_name` that hold connections open.
- If ehr-gateway is sending high-volume batch patient lookups (e.g., during shift change or census report), connections may be held waiting within transaction boundaries.

## Clinical Impact Assessment

| Impact Area                  | Severity | Workaround                         |
|------------------------------|----------|-------------------------------------|
| Patient record lookup        | High     | Paper-based patient identification  |
| Medication ordering          | High     | Verbal orders with dual-nurse verify|
| ER triage                    | Medium   | Manual triage without history       |
| Lab result delivery          | Low      | Results still available in LIS      |

## Escalation

| Condition                                            | Action                                           |
|------------------------------------------------------|--------------------------------------------------|
| Pool exhausted for >10 minutes                       | Page Clinical IT on-call + Chief Medical Officer  |
| FHIR endpoints down during active ER cases           | Escalate to SEV-1, activate clinical downtime SOP |
| PHI data integrity concern                           | Engage HIPAA Privacy Officer immediately          |
| Remediation steps do not resolve within 15 minutes   | Escalate to P0, engage Platform Engineering       |

## References

- EHR-1001: Previous patient-service pool exhaustion incident
- EHR-1003: Connection leak identified in PatientRepository
- HIPAA Downtime Procedures: https://wiki.medflow.com/sop/hipaa-downtime
