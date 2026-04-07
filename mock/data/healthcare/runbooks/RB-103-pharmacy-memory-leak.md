# RB-103: Pharmacy Service Memory Leak

| Field         | Value                                                    |
|---------------|----------------------------------------------------------|
| **Service**   | pharmacy-service                                         |
| **Severity**  | SEV-2 - High                                             |
| **Last Updated** | 2026-03-05                                            |
| **Author**    | MedFlow Platform Engineering / Pharmacy IT               |
| **Alert**     | `PharmacyHighHeapUsage`                                  |
| **Patient Safety** | Medication dispensing delays                         |

## Symptoms

- **Alert fires:** `PharmacyHighHeapUsage` with labels `service=pharmacy-service`, `namespace=medflow-prod`
- **Grafana dashboard:** "MedFlow / JVM Metrics" shows heap usage >85% of 4GB limit
- **Metrics:**
  - `jvm_memory_used_bytes{area="heap", service="pharmacy-service"} / jvm_memory_max_bytes > 0.85`
  - `jvm_gc_pause_seconds_max{service="pharmacy-service"} > 1.0`
  - `pharmacy_dispense_latency_p99 > 5s`
- **User impact:** Medication dispensing queue delayed. Pharmacy technicians see timeout errors on dispensing terminals. GC pauses causing intermittent 503 errors on medication order APIs. Automated dispensing cabinets (Pyxis/Omnicell) failing to sync.
- **Logs:** `java.lang.OutOfMemoryError: GC overhead limit exceeded` or `WARN GC pause exceeded threshold: 1.5s (Full GC)` or `DrugInteractionCache eviction failed: insufficient heap`

## Investigation Steps

### 1. Confirm pharmacy-service pod resource usage

```bash
kubectl get pods -n medflow-prod -l app=pharmacy-service -o wide
kubectl top pods -n medflow-prod -l app=pharmacy-service
```

### 2. Check JVM heap metrics

```bash
kubectl exec -n medflow-prod deploy/pharmacy-service -- curl -s localhost:9086/actuator/metrics/jvm.memory.used | jq '.measurements[] | select(.statistic=="VALUE") | .value'
kubectl exec -n medflow-prod deploy/pharmacy-service -- curl -s localhost:9086/actuator/metrics/jvm.memory.max | jq '.measurements[] | select(.statistic=="VALUE") | .value'
kubectl exec -n medflow-prod deploy/pharmacy-service -- curl -s localhost:9086/actuator/metrics/jvm.gc.pause | jq .
```

### 3. Capture heap dump (if time allows)

```bash
# Capture heap dump for later analysis (WARNING: may cause additional GC pressure)
kubectl exec -n medflow-prod deploy/pharmacy-service -- jmap -dump:live,format=b,file=/tmp/heap_dump.hprof 1
kubectl cp medflow-prod/$(kubectl get pod -n medflow-prod -l app=pharmacy-service -o jsonpath='{.items[0].metadata.name}'):/tmp/heap_dump.hprof ./heap_dump.hprof
```

### 4. Check dispensing queue status

```bash
kubectl exec -n medflow-prod deploy/pharmacy-service -- curl -s localhost:9086/api/v1/dispensing/queue/status | jq .
```

### 5. Check recent deployments

```bash
kubectl rollout history deployment/pharmacy-service -n medflow-prod
```

## Remediation

### Immediate (restore dispensing capability)

1. **Rolling restart of pharmacy-service:**

```bash
kubectl rollout restart deployment/pharmacy-service -n medflow-prod
kubectl rollout status deployment/pharmacy-service -n medflow-prod --timeout=120s
```

2. **Verify heap returns to normal:**

```bash
kubectl exec -n medflow-prod deploy/pharmacy-service -- curl -s localhost:9086/actuator/metrics/jvm.memory.used | jq '.measurements[] | select(.statistic=="VALUE") | .value'
```

3. **Verify dispensing operations resume:**

```bash
# Check dispensing endpoint
kubectl exec -n medflow-prod deploy/pharmacy-service -- curl -s -o /dev/null -w "%{http_code}" localhost:9086/api/v1/dispensing/health

# Check formulary lookup
kubectl exec -n medflow-prod deploy/pharmacy-service -- curl -s -o /dev/null -w "%{http_code}" localhost:9086/api/v1/formulary/search?q=metformin
```

4. **If leak recurs rapidly, increase heap temporarily:**

```bash
kubectl set env deployment/pharmacy-service -n medflow-prod JVM_HEAP_MAX=6144m
```

### Root Cause

- Memory leak in `DrugInteractionCache`. The cache stores computed interaction results for drug pairs but the eviction policy fails under concurrent access. Each cache miss allocates a new `InteractionResult` object that is never garbage collected due to a strong reference in the eviction listener.
- The leak accelerates when high volumes of formulary lookups occur (e.g., during morning medication pass at 06:00-08:00).
- Fix requires patching the cache eviction listener to use weak references (tracked in EHR-1004).

## Patient Safety Assessment

| Impact Area                    | Severity | Workaround                              |
|--------------------------------|----------|-----------------------------------------|
| Medication dispensing          | High     | Manual dispensing with pharmacist verify |
| Drug interaction checks        | High     | Pharmacist manual review of interactions |
| Automated cabinet sync         | Medium   | Manual override on Pyxis/Omnicell units  |
| Formulary lookups              | Low      | Reference printed formulary guide         |

## Escalation

| Condition                                            | Action                                          |
|------------------------------------------------------|-------------------------------------------------|
| Dispensing down >15 minutes                          | Page Chief Pharmacist + Pharmacy Director       |
| OOM crash (pod restart count >2)                     | Escalate to SEV-1, engage Platform Engineering  |
| Drug interaction checks unavailable                  | Activate manual interaction review protocol     |
| Not resolved within 20 minutes                       | Notify Chief Medical Officer                    |

## References

- EHR-1004: Pharmacy OOM incident and DrugInteractionCache leak
- JVM Tuning Guide: https://wiki.medflow.com/engineering/jvm-tuning
- Pharmacy Downtime SOP: https://wiki.medflow.com/sop/pharmacy-downtime
