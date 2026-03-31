# RB-005: High Error Rate (Generic)

| Field         | Value                                                    |
|---------------|----------------------------------------------------------|
| **Service**   | Any ShopFast microservice                                |
| **Severity**  | P1 - Critical (if > 10%), P2 - High (if 5-10%)          |
| **Last Updated** | 2026-03-12                                            |
| **Author**    | Platform Engineering / ShopFast SRE                      |
| **Alert**     | `HighErrorRate`                                          |

## Symptoms

- **Alert fires:** `HighErrorRate` with labels `service=<service-name>`, `namespace=shopfast-prod` when the 5xx error rate exceeds 5% of total requests over a 5-minute window
- **Grafana dashboard:** "ShopFast / Service Overview" shows error rate spike for the affected service
- **Metrics:**
  - `sum(rate(http_server_requests_seconds_count{namespace="shopfast-prod", service="<service>", status=~"5.."}[5m])) / sum(rate(http_server_requests_seconds_count{namespace="shopfast-prod", service="<service>"}[5m])) > 0.05`
  - `http_server_requests_seconds_count{status="500"}` increasing
  - `http_server_requests_seconds_count{status="503"}` increasing (if upstream dependency down)
  - `http_server_requests_seconds_count{status="502"}` increasing (if pod is crashing)
- **User impact:** Varies by service. Could be failed searches (catalog-service), lost carts (cart-service), blocked checkouts (order-service/payment-service), or missing notifications (notification-service).
- **Logs:** Stack traces, connection refused errors, null pointer exceptions, or timeout messages depending on the root cause

## Investigation Steps

### 1. Identify the affected service and scope

```bash
# Check which service the alert is for and its current pod status
kubectl get pods -n shopfast-prod -l app=<service-name>
kubectl top pods -n shopfast-prod -l app=<service-name>
```

### 2. Check recent logs for error patterns

```bash
kubectl logs -n shopfast-prod -l app=<service-name> --tail=200 | grep -c "ERROR"
kubectl logs -n shopfast-prod -l app=<service-name> --tail=200 | grep "ERROR" | sort | uniq -c | sort -rn | head -10
```

### 3. Determine if errors are on specific endpoints

```bash
# Check Prometheus for per-endpoint error breakdown
# PromQL: topk(5, sum by (uri, status) (rate(http_server_requests_seconds_count{service="<service>", status=~"5.."}[5m])))

kubectl exec -n shopfast-prod deploy/<service-name> -- curl -s localhost:8080/actuator/metrics/http.server.requests?tag=status:500 | jq '.availableTags[] | select(.tag=="uri") | .values'
```

### 4. Check dependency health

```bash
# Check if downstream services are healthy
kubectl get pods -n shopfast-prod
kubectl exec -n shopfast-prod deploy/<service-name> -- curl -s localhost:8080/actuator/health | jq '.components | to_entries[] | select(.value.status != "UP")'
```

### 5. Check for recent deployments

```bash
kubectl rollout history deployment/<service-name> -n shopfast-prod
# Check deploy timestamps vs error rate spike in Grafana
kubectl get replicasets -n shopfast-prod -l app=<service-name> --sort-by='.metadata.creationTimestamp' | tail -5
```

### 6. Check Kubernetes events for the namespace

```bash
kubectl get events -n shopfast-prod --sort-by='.lastTimestamp' | tail -20
kubectl get events -n shopfast-prod --field-selector involvedObject.kind=Pod | grep <service-name> | tail -10
```

### 7. Check ingress and api-gateway for upstream errors

```bash
kubectl logs -n shopfast-prod -l app=api-gateway --tail=100 | grep "502\|503\|504" | grep <service-name>
```

## Remediation

### Immediate (restore service)

1. **If a recent deployment correlates with the error spike, rollback:**

```bash
kubectl rollout undo deployment/<service-name> -n shopfast-prod
kubectl rollout status deployment/<service-name> -n shopfast-prod --timeout=180s
```

2. **If a downstream dependency is the cause, check if that dependency has its own runbook and follow it.**

3. **If errors are caused by resource exhaustion, scale up:**

```bash
kubectl scale deployment/<service-name> -n shopfast-prod --replicas=<current+2>
```

4. **If a single pod is the source of most errors, delete it to force rescheduling:**

```bash
kubectl delete pod <problem-pod-name> -n shopfast-prod
```

### Root Cause

- **Recent deploy:** Check the diff between the current and previous image tags. Review the associated PR for breaking changes.
- **Dependency failure:** Trace the error chain using distributed tracing (Jaeger UI at `https://jaeger.shopfast.internal`). Look for the deepest failing span.
- **Resource exhaustion:** Check CPU throttling (`container_cpu_cfs_throttled_seconds_total`), memory pressure, or connection pool metrics.
- **Data issue:** If errors are on specific request payloads, check for malformed data or missing database records.
- **Infrastructure:** Check node health (`kubectl get nodes`), PVC status, and recent cluster events.

## Escalation

| Condition                                              | Action                                         |
|--------------------------------------------------------|-------------------------------------------------|
| Error rate > 10% for more than 5 minutes               | P1 page to owning team on-call                 |
| Error rate > 25% or affecting checkout flow             | Escalate to P0, page SRE lead                  |
| Rollback does not reduce error rate                     | Engage Platform Engineering                    |
| Multiple services showing high error rates              | Suspect infrastructure issue, page SRE + Infra |
| Root cause unclear after 30 minutes of investigation    | Escalate to senior on-call engineer            |
