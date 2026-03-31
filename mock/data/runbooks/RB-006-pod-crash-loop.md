# RB-006: Pod CrashLoopBackOff

| Field         | Value                                                    |
|---------------|----------------------------------------------------------|
| **Service**   | Any ShopFast microservice                                |
| **Severity**  | P1 - Critical (if multiple pods), P2 - High (if single) |
| **Last Updated** | 2026-03-20                                            |
| **Author**    | Platform Engineering / ShopFast SRE                      |
| **Alert**     | `KubePodCrashLooping`                                    |

## Symptoms

- **Alert fires:** `KubePodCrashLooping` with labels `pod=<pod-name>`, `namespace=shopfast-prod` when a pod has restarted more than 3 times in the last 10 minutes
- **Grafana dashboard:** "ShopFast / Kubernetes Overview" shows restart count climbing for the affected pod(s)
- **Metrics:**
  - `kube_pod_container_status_restarts_total{namespace="shopfast-prod"}` increasing
  - `kube_pod_status_phase{phase="Running"}` may drop as pods cycle through CrashLoopBackOff
  - `container_oom_events_total{namespace="shopfast-prod"}` increasing (if OOM-related)
- **User impact:** Reduced capacity for the affected service. If all replicas are crash-looping, the service is fully down.
- **kubectl output:** Pod status shows `CrashLoopBackOff` or `Error` with increasing restart counts and exponential backoff intervals

## Investigation Steps

### 1. Identify the crashing pods

```bash
kubectl get pods -n shopfast-prod | grep -E "CrashLoop|Error|BackOff"
kubectl get pods -n shopfast-prod -o wide | grep <service-name>
```

### 2. Check the pod's last termination reason

```bash
kubectl describe pod <pod-name> -n shopfast-prod | grep -A10 "Last State\|State:\|Reason:\|Exit Code"
# Exit Code 137 = OOMKilled (SIGKILL), Exit Code 1 = Application error, Exit Code 143 = SIGTERM
```

### 3. Check container logs (current and previous)

```bash
# Current attempt logs (may be empty if crash is immediate)
kubectl logs <pod-name> -n shopfast-prod --tail=100

# Previous container instance logs (usually more useful)
kubectl logs <pod-name> -n shopfast-prod --previous --tail=200
```

### 4. Check for OOMKilled events

```bash
kubectl get events -n shopfast-prod --field-selector reason=OOMKilling | grep <service-name>
kubectl describe pod <pod-name> -n shopfast-prod | grep -B2 -A5 "OOMKilled"

# Check memory limits vs actual usage
kubectl get pod <pod-name> -n shopfast-prod -o jsonpath='{.spec.containers[0].resources}' | jq .
kubectl top pod <pod-name> -n shopfast-prod
```

### 5. Check liveness and readiness probe configuration

```bash
kubectl get deployment <service-name> -n shopfast-prod -o jsonpath='{.spec.template.spec.containers[0].livenessProbe}' | jq .
kubectl get deployment <service-name> -n shopfast-prod -o jsonpath='{.spec.template.spec.containers[0].readinessProbe}' | jq .
# Common issue: initialDelaySeconds too short for JVM services (need 30-60s for Spring Boot)
```

### 6. Check if crash correlates with a recent deployment

```bash
kubectl rollout history deployment/<service-name> -n shopfast-prod
kubectl get replicasets -n shopfast-prod -l app=<service-name> --sort-by='.metadata.creationTimestamp'
```

### 7. Check node health (crash may be node-related)

```bash
NODE=$(kubectl get pod <pod-name> -n shopfast-prod -o jsonpath='{.spec.nodeName}')
kubectl describe node $NODE | grep -A10 "Conditions\|Allocatable\|Allocated"
```

### 8. Check if ConfigMap or Secret is missing or malformed

```bash
kubectl describe pod <pod-name> -n shopfast-prod | grep -A5 "Environment\|Volumes\|Mounts"
kubectl get configmap -n shopfast-prod | grep <service-name>
kubectl get secret -n shopfast-prod | grep <service-name>
```

## Remediation

### Immediate (restore service)

1. **If OOMKilled, increase memory limits:**

```bash
kubectl patch deployment <service-name> -n shopfast-prod --type='json' \
  -p='[{"op":"replace","path":"/spec/template/spec/containers/0/resources/limits/memory","value":"2Gi"}]'
```

2. **If caused by a bad deployment, rollback:**

```bash
kubectl rollout undo deployment/<service-name> -n shopfast-prod
kubectl rollout status deployment/<service-name> -n shopfast-prod --timeout=180s
```

3. **If liveness probe is too aggressive, patch it:**

```bash
kubectl patch deployment <service-name> -n shopfast-prod --type='json' \
  -p='[{"op":"replace","path":"/spec/template/spec/containers/0/livenessProbe/initialDelaySeconds","value":60},{"op":"replace","path":"/spec/template/spec/containers/0/livenessProbe/timeoutSeconds","value":10}]'
```

4. **If a ConfigMap/Secret change broke the config, revert it:**

```bash
kubectl get configmap <service-name>-config -n shopfast-prod -o yaml > /tmp/configmap-backup.yaml
# Edit and reapply the previous version
kubectl apply -f /tmp/configmap-backup-previous.yaml
kubectl rollout restart deployment/<service-name> -n shopfast-prod
```

### Root Cause

- **OOMKilled (exit code 137):** Application memory usage exceeds container limit. See RB-003 for JVM-specific investigation.
- **Application error (exit code 1):** Check logs for stack traces. Typical causes: missing env vars, bad config, failed database migration, incompatible dependency version.
- **Liveness probe failure:** The application starts slower than the probe's `initialDelaySeconds`. Common after adding startup dependencies or increasing dataset size.
- **Missing volume/secret:** A required ConfigMap, Secret, or PVC was deleted or renamed.

## Escalation

| Condition                                              | Action                                          |
|--------------------------------------------------------|------------------------------------------------|
| All replicas of a service are crash-looping            | P0 escalation, page owning team + SRE lead     |
| Crash loop persists after rollback                     | Engage Platform Engineering                    |
| OOMKilled with no recent code change                   | Investigate traffic spike or data growth        |
| Node-level issue suspected (multiple pods on same node)| Page Infrastructure / Kubernetes platform team |
