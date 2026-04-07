# RB-102: Billing Insurance Verification Timeout

| Field         | Value                                                    |
|---------------|----------------------------------------------------------|
| **Service**   | billing-service                                          |
| **Severity**  | SEV-2 - High                                             |
| **Last Updated** | 2026-03-01                                            |
| **Author**    | MedFlow Platform Engineering / Revenue Cycle IT          |
| **Alert**     | `BillingInsuranceTimeout`                                |
| **Financial Impact** | Claims processing halted, revenue cycle delayed   |

## Symptoms

- **Alert fires:** `BillingInsuranceTimeout` with labels `service=billing-service`, `namespace=medflow-prod`
- **Grafana dashboard:** "MedFlow / Billing Pipeline" shows insurance verification p99 latency >20s
- **Metrics:**
  - `billing_insurance_verify_latency_p99{service="billing-service"} > 20`
  - `billing_edi_837_submission_errors_total` increasing
  - `billing_claims_queue_depth > 2000`
- **User impact:** Insurance eligibility checks timing out. EDI 837 (claim submission) and 835 (remittance) transactions failing. Revenue cycle team unable to process claims. Pre-authorization checks for procedures failing.
- **Logs:** `InsuranceVerificationTimeoutException: Clearinghouse API did not respond within 25000ms` or `EDI837SubmissionFailed: Connection reset by peer`

## Investigation Steps

### 1. Confirm billing-service pod health

```bash
kubectl get pods -n medflow-prod -l app=billing-service -o wide
kubectl top pods -n medflow-prod -l app=billing-service
```

### 2. Check insurance verification endpoint

```bash
kubectl exec -n medflow-prod deploy/billing-service -- curl -s localhost:9084/actuator/metrics/billing.insurance.verify.latency | jq .
kubectl exec -n medflow-prod deploy/billing-service -- curl -s localhost:9084/actuator/metrics/billing.claims.queue.depth | jq .
```

### 3. Verify clearinghouse connectivity

```bash
# Check connectivity to primary clearinghouse (Change Healthcare / Availity)
kubectl exec -n medflow-prod deploy/billing-service -- curl -s -o /dev/null -w "%{http_code}" https://api.clearinghouse.example.com/v2/eligibility/health

# Check DNS resolution
kubectl exec -n medflow-prod deploy/billing-service -- nslookup api.clearinghouse.example.com
```

### 4. Check EDI transaction status

```bash
# Check 837/835 transaction counts
kubectl exec -n medflow-prod deploy/billing-service -- curl -s localhost:9084/api/v1/edi/stats | jq .
```

### 5. Review thread pool utilization

```bash
kubectl exec -n medflow-prod deploy/billing-service -- curl -s localhost:9084/actuator/metrics/executor.pool.size | jq .
kubectl exec -n medflow-prod deploy/billing-service -- curl -s localhost:9084/actuator/metrics/executor.active | jq .
```

## Remediation

### Immediate (restore claims processing)

1. **Scale billing-service to absorb backlog:**

```bash
kubectl scale deployment/billing-service -n medflow-prod --replicas=4
kubectl rollout status deployment/billing-service -n medflow-prod --timeout=120s
```

2. **Increase clearinghouse timeout (temporary):**

```bash
kubectl set env deployment/billing-service -n medflow-prod INSURANCE_VERIFY_TIMEOUT_MS=45000
```

3. **If clearinghouse is fully down, enable fallback:**

```bash
# Switch to secondary clearinghouse endpoint
kubectl set env deployment/billing-service -n medflow-prod CLEARINGHOUSE_URL=https://api.secondary-clearinghouse.example.com/v2
```

4. **Verify claims processing resumes:**

```bash
kubectl exec -n medflow-prod deploy/billing-service -- curl -s localhost:9084/api/v1/claims/queue/status | jq .
```

### Root Cause

- Insurance verification API (external clearinghouse) experiencing degraded performance or outage.
- Thread pool on billing-service saturates as threads block waiting for the slow external API.
- No circuit breaker configured for the clearinghouse integration, allowing cascade failure.
- Claims queue depth grows unbounded, consuming memory and causing backpressure to ehr-gateway.

## Financial Impact Assessment

| Impact Area                    | Severity | Estimated Loss                   |
|--------------------------------|----------|----------------------------------|
| Real-time eligibility checks   | High     | Delayed admissions               |
| EDI 837 claim submissions      | High     | Revenue delay, $50K+/hour        |
| Pre-authorization requests     | Medium   | Procedure scheduling delays      |
| EDI 835 remittance processing  | Medium   | Payment posting delayed          |

## Escalation

| Condition                                            | Action                                          |
|------------------------------------------------------|-------------------------------------------------|
| Claims queue >5000                                   | Page Revenue Cycle Director                     |
| Clearinghouse fully unreachable >30 min              | Contact clearinghouse support, activate fallback|
| Pre-authorization failures for scheduled surgeries   | Notify Surgical Services Director               |
| Not resolved within 30 minutes                       | Escalate to SEV-1, engage VP of Revenue Cycle   |

## References

- EHR-1002: Previous billing timeout incident
- Clearinghouse SLA: https://wiki.medflow.com/vendors/clearinghouse-sla
- EDI 837/835 Specification: https://wiki.medflow.com/integrations/edi-specs
