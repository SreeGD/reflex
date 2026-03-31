# RB-002: Payment Gateway Timeout

| Field         | Value                                                    |
|---------------|----------------------------------------------------------|
| **Service**   | payment-service                                          |
| **Severity**  | P1 - Critical                                            |
| **Last Updated** | 2026-03-05                                            |
| **Author**    | Platform Engineering / ShopFast SRE                      |
| **Alert**     | `PaymentGatewayTimeout`                                  |

## Symptoms

- **Alert fires:** `PaymentGatewayTimeout` with labels `service=payment-service`, `namespace=shopfast-prod`, `provider=stripe|adyen`
- **Grafana dashboard:** "ShopFast / Payment Service" shows p99 latency on `/api/v1/payments/charge` exceeding 30 seconds
- **Metrics:**
  - `http_server_requests_seconds{service="payment-service", uri="/api/v1/payments/charge", quantile="0.99"} > 30`
  - `payment_gateway_request_duration_seconds{provider="stripe", quantile="0.99"} > 25`
  - `resilience4j_circuitbreaker_state{name="paymentGateway"} == 1` (OPEN)
  - `payment_gateway_timeout_total` rate increasing
- **User impact:** Checkout fails with "Payment processing error, please try again." Customers cannot complete purchases. Revenue loss is immediate.
- **Logs:** `java.net.SocketTimeoutException: Read timed out` and `CircuitBreaker 'paymentGateway' is OPEN and does not permit further calls`

## Investigation Steps

### 1. Confirm the alert and check payment-service health

```bash
kubectl get pods -n shopfast-prod -l app=payment-service -o wide
kubectl logs -n shopfast-prod -l app=payment-service --tail=100 | grep -i "timeout\|circuit\|error"
```

### 2. Check circuit breaker state

```bash
kubectl exec -n shopfast-prod deploy/payment-service -- curl -s localhost:8080/actuator/health | jq '.components.circuitBreakers'
kubectl exec -n shopfast-prod deploy/payment-service -- curl -s localhost:8080/actuator/metrics/resilience4j.circuitbreaker.state | jq .
```

### 3. Check external provider status

- **Stripe:** https://status.stripe.com
- **Adyen:** https://status.adyen.com
- Check the ShopFast Slack channel `#vendor-status` for reported outages.

### 4. Verify network connectivity from the pod

```bash
kubectl exec -n shopfast-prod deploy/payment-service -- curl -sv --max-time 10 https://api.stripe.com/v1/charges 2>&1 | head -30
kubectl exec -n shopfast-prod deploy/payment-service -- nslookup api.stripe.com
```

### 5. Check if the issue is isolated or widespread

```bash
# Check error rate across all payment-service pods
kubectl exec -n shopfast-prod deploy/payment-service -- curl -s localhost:8080/actuator/metrics/payment.gateway.timeout.total | jq .

# Check if other outbound calls are also slow
kubectl exec -n shopfast-prod deploy/payment-service -- curl -s localhost:8080/actuator/metrics/http.client.requests | jq .
```

### 6. Review recent configuration or deployment changes

```bash
kubectl rollout history deployment/payment-service -n shopfast-prod
kubectl get configmap payment-service-config -n shopfast-prod -o yaml | grep -A5 "gateway\|timeout\|provider"
```

## Remediation

### Immediate (restore service)

1. **If the primary provider (Stripe) is down, switch to the fallback provider (Adyen):**

```bash
kubectl set env deployment/payment-service -n shopfast-prod PAYMENT_PROVIDER_PRIMARY=adyen
kubectl rollout status deployment/payment-service -n shopfast-prod --timeout=120s
```

2. **If circuit breaker is stuck OPEN, force a reset:**

```bash
kubectl exec -n shopfast-prod deploy/payment-service -- curl -X POST localhost:8080/actuator/circuitbreakerevents/paymentGateway/reset
```

3. **Scale up payment-service to handle retried requests once the provider recovers:**

```bash
kubectl scale deployment/payment-service -n shopfast-prod --replicas=6
```

4. **If timeouts are caused by load, increase the gateway timeout temporarily:**

```bash
kubectl set env deployment/payment-service -n shopfast-prod PAYMENT_GATEWAY_TIMEOUT_MS=45000
```

### Root Cause

- Most commonly caused by the external payment provider experiencing degraded performance or an outage.
- Check if a recent deploy changed timeout values, retry policies, or TLS configuration.
- Verify that the Kubernetes egress NetworkPolicy allows traffic to the provider IP ranges.
- Investigate if the pod's NAT gateway or egress proxy is saturated (check `node_network_transmit_bytes_total`).

## Escalation

| Condition                                                | Action                                          |
|----------------------------------------------------------|------------------------------------------------|
| Provider outage confirmed, ETA unknown                   | Activate fallback provider, notify VP Engineering |
| Revenue loss exceeds $10K/hour                           | Escalate to P0, page CTO                        |
| Fallback provider also experiencing issues               | Escalate to P0, consider maintenance page        |
| Issue persists after provider switch for > 10 minutes    | Engage Platform Engineering and Network team     |
| Suspected internal network/proxy issue                   | Page Network Engineering on-call                 |
