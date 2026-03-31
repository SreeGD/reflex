# RB-003: JVM Memory Leak / High Heap Usage

| Field         | Value                                                    |
|---------------|----------------------------------------------------------|
| **Service**   | payment-service (Java 17 / Spring Boot 3.x)              |
| **Severity**  | P2 - High                                                |
| **Last Updated** | 2026-01-22                                            |
| **Author**    | Platform Engineering / ShopFast SRE                      |
| **Alert**     | `HighHeapUsage`                                          |

## Symptoms

- **Alert fires:** `HighHeapUsage` with labels `service=payment-service`, `namespace=shopfast-prod` when heap usage exceeds 85% of max (2GB) for more than 5 minutes
- **Grafana dashboard:** "ShopFast / JVM Metrics" shows Old Gen heap growing steadily without being reclaimed by GC
- **Metrics:**
  - `jvm_memory_used_bytes{area="heap", service="payment-service"} / jvm_memory_max_bytes{area="heap"} > 0.85`
  - `jvm_gc_pause_seconds_sum{service="payment-service"}` increasing (long GC pauses > 2s)
  - `jvm_gc_memory_promoted_bytes_total` growing faster than `jvm_gc_memory_allocated_bytes_total`
  - `process_cpu_usage{service="payment-service"}` spikes correlating with Full GC events
- **User impact:** Increasing latency on payment endpoints. Eventual OOMKilled pods causing request failures during checkout.
- **Logs:** `java.lang.OutOfMemoryError: Java heap space` or GC logs showing repeated Full GC cycles with diminishing returns

## Investigation Steps

### 1. Check current memory state of pods

```bash
kubectl top pods -n shopfast-prod -l app=payment-service
kubectl get pods -n shopfast-prod -l app=payment-service -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.containerStatuses[0].restartCount}{"\t"}{.status.containerStatuses[0].lastState.terminated.reason}{"\n"}{end}'
```

### 2. Check JVM heap usage via actuator

```bash
kubectl exec -n shopfast-prod deploy/payment-service -- curl -s localhost:8080/actuator/metrics/jvm.memory.used?tag=area:heap | jq .
kubectl exec -n shopfast-prod deploy/payment-service -- curl -s localhost:8080/actuator/metrics/jvm.memory.max?tag=area:heap | jq .
kubectl exec -n shopfast-prod deploy/payment-service -- curl -s localhost:8080/actuator/metrics/jvm.gc.pause | jq .
```

### 3. Check GC behavior

```bash
kubectl logs -n shopfast-prod -l app=payment-service --tail=200 | grep -i "GC\|garbage\|pause\|heap"
```

### 4. Check for OOMKilled events

```bash
kubectl get events -n shopfast-prod --field-selector reason=OOMKilling --sort-by='.lastTimestamp' | grep payment
kubectl describe pod -n shopfast-prod -l app=payment-service | grep -A3 "Last State\|Restart Count\|OOM"
```

### 5. Capture a heap dump (before restarting)

```bash
# Identify the pod with highest memory usage
PROBLEM_POD=$(kubectl top pods -n shopfast-prod -l app=payment-service --sort-by=memory --no-headers | head -1 | awk '{print $1}')

# Trigger heap dump inside the container
kubectl exec -n shopfast-prod $PROBLEM_POD -- jcmd 1 GC.heap_dump /tmp/heapdump.hprof

# Copy heap dump to local machine for analysis
kubectl cp shopfast-prod/$PROBLEM_POD:/tmp/heapdump.hprof ./heapdump-$(date +%Y%m%d-%H%M%S).hprof
```

### 6. Check recent deployments for regression

```bash
kubectl rollout history deployment/payment-service -n shopfast-prod
kubectl describe deployment/payment-service -n shopfast-prod | grep -A2 "Image\|JAVA_OPTS"
```

### 7. Review JVM configuration

```bash
kubectl get deployment payment-service -n shopfast-prod -o jsonpath='{.spec.template.spec.containers[0].env}' | jq '.[] | select(.name | startswith("JAVA"))'
kubectl get deployment payment-service -n shopfast-prod -o jsonpath='{.spec.template.spec.containers[0].resources}' | jq .
```

## Remediation

### Immediate (restore service)

1. **Rolling restart to reclaim memory (buys time):**

```bash
kubectl rollout restart deployment/payment-service -n shopfast-prod
kubectl rollout status deployment/payment-service -n shopfast-prod --timeout=180s
```

2. **If the leak was introduced by a recent deploy, rollback:**

```bash
kubectl rollout undo deployment/payment-service -n shopfast-prod
kubectl rollout status deployment/payment-service -n shopfast-prod --timeout=180s
```

3. **Temporarily increase memory limit if pods are OOMKilled before heap dump can be captured:**

```bash
kubectl patch deployment payment-service -n shopfast-prod --type='json' -p='[{"op":"replace","path":"/spec/template/spec/containers/0/resources/limits/memory","value":"3Gi"}]'
```

### Root Cause

- Analyze the heap dump with Eclipse MAT or VisualVM. Look for dominator trees with unexpected retention.
- Common causes in payment-service: unbounded caches for payment session objects, connection objects not returned to pool, or large collections held in `@SessionScope` beans.
- Verify JVM flags include `-XX:+UseG1GC -Xmx2g -Xms2g -XX:MaxGCPauseMillis=200`.
- Check if `spring.cache.caffeine.spec` has appropriate `maximumSize` and `expireAfterWrite` values.
- Review thread dumps for threads holding large object references: `kubectl exec -n shopfast-prod deploy/payment-service -- jcmd 1 Thread.print`

## Escalation

| Condition                                            | Action                                         |
|------------------------------------------------------|-------------------------------------------------|
| OOMKilled more than 3 times in 1 hour               | Page payment-service dev team on-call           |
| Heap dump shows clear leak in application code       | Create P1 JIRA for payment-service team         |
| Memory usage re-saturates within 30 min of restart   | Rollback deployment, escalate to P1             |
| Leak suspected in framework/library dependency       | Engage Platform Engineering for triage          |
