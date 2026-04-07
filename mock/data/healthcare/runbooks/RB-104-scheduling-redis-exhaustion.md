# RB-104: Scheduling Service Redis Pool Exhaustion

| Field         | Value                                                    |
|---------------|----------------------------------------------------------|
| **Service**   | scheduling-service                                       |
| **Severity**  | SEV-3 - Medium                                           |
| **Last Updated** | 2026-03-10                                            |
| **Author**    | MedFlow Platform Engineering / Clinical Operations IT    |
| **Alert**     | `SchedulingRedisPoolExhausted`                           |
| **Operational Impact** | Appointment booking and bed management degraded |

## Symptoms

- **Alert fires:** `SchedulingRedisPoolExhausted` with labels `service=scheduling-service`, `namespace=medflow-prod`
- **Grafana dashboard:** "MedFlow / Redis Connections" shows scheduling-service Redis pool at 50/50
- **Metrics:**
  - `redis_pool_active{service="scheduling-service"} >= 50`
  - `redis_pool_wait_seconds{service="scheduling-service"} > 2`
  - `scheduling_appointment_errors_total` increasing
- **User impact:** Appointment booking fails for patients. Bed management dashboard displays stale occupancy data. Patient check-in kiosks return errors. Scheduling coordinators unable to book, reschedule, or cancel appointments.
- **Logs:** `redis.clients.jedis.exceptions.JedisExhaustedPoolException: Could not get a resource from the pool` or `SchedulingSessionCache: Redis connection timeout after 5000ms`

## Investigation Steps

### 1. Confirm scheduling-service pod health

```bash
kubectl get pods -n medflow-prod -l app=scheduling-service -o wide
kubectl top pods -n medflow-prod -l app=scheduling-service
```

### 2. Check Redis connection pool metrics

```bash
kubectl exec -n medflow-prod deploy/scheduling-service -- curl -s localhost:9082/actuator/metrics/redis.pool.active | jq .
kubectl exec -n medflow-prod deploy/scheduling-service -- curl -s localhost:9082/actuator/metrics/redis.pool.idle | jq .
kubectl exec -n medflow-prod deploy/scheduling-service -- curl -s localhost:9082/actuator/metrics/redis.pool.wait | jq .
```

### 3. Check Redis server health

```bash
kubectl exec -n medflow-prod deploy/redis-scheduling -- redis-cli INFO clients
kubectl exec -n medflow-prod deploy/redis-scheduling -- redis-cli INFO memory
kubectl exec -n medflow-prod deploy/redis-scheduling -- redis-cli CLIENT LIST | wc -l
```

### 4. Check appointment booking status

```bash
kubectl exec -n medflow-prod deploy/scheduling-service -- curl -s localhost:9082/api/v1/appointments/health | jq .
kubectl exec -n medflow-prod deploy/scheduling-service -- curl -s localhost:9082/api/v1/beds/occupancy | jq '.lastUpdated'
```

### 5. Check for connection leak pattern

```bash
# Look for connections in TIME_WAIT state
kubectl exec -n medflow-prod deploy/scheduling-service -- ss -s | grep -i time
```

## Remediation

### Immediate (restore appointment booking)

1. **Rolling restart of scheduling-service:**

```bash
kubectl rollout restart deployment/scheduling-service -n medflow-prod
kubectl rollout status deployment/scheduling-service -n medflow-prod --timeout=120s
```

2. **Verify Redis connections return to normal:**

```bash
kubectl exec -n medflow-prod deploy/scheduling-service -- curl -s localhost:9082/actuator/metrics/redis.pool.active | jq .
```

3. **Verify appointment booking works:**

```bash
kubectl exec -n medflow-prod deploy/scheduling-service -- curl -s -o /dev/null -w "%{http_code}" localhost:9082/api/v1/appointments/available?date=2026-04-01&department=primary-care
```

4. **If connections leak rapidly, flush Redis scheduling keys (safe - session data only):**

```bash
kubectl exec -n medflow-prod deploy/redis-scheduling -- redis-cli --scan --pattern "scheduling:session:*" | xargs -L 100 kubectl exec -n medflow-prod deploy/redis-scheduling -- redis-cli DEL
```

### Root Cause

- Connection leak in the session cache handler. When a patient session expires naturally (TTL), the Redis pub/sub listener for key expiration events opens a new connection to clean up associated booking locks, but fails to return the connection to the pool.
- Under normal load (50-100 concurrent sessions), this manifests slowly over hours. During high-traffic periods (Monday morning scheduling rush), the pool exhausts in under 30 minutes.

## Operational Impact Assessment

| Impact Area                    | Severity | Workaround                              |
|--------------------------------|----------|-----------------------------------------|
| Appointment booking            | High     | Phone-based booking with manual entry   |
| Patient check-in kiosk         | High     | Manual check-in at front desk           |
| Bed management dashboard       | Medium   | Manual whiteboard tracking              |
| Scheduling reports             | Low      | Reports delayed until service restored  |

## Escalation

| Condition                                            | Action                                          |
|------------------------------------------------------|-------------------------------------------------|
| Booking unavailable >20 minutes                      | Notify Clinical Operations Manager              |
| ER bed management stale during surge                 | Page ER Charge Nurse + Bed Management           |
| Redis server itself unhealthy                        | Page Database on-call                           |
| Not resolved within 25 minutes                       | Escalate to SEV-2                               |

## References

- EHR-1005: Previous scheduling Redis exhaustion incident
- Redis Connection Pooling Guide: https://wiki.medflow.com/engineering/redis-pooling
- Scheduling Downtime SOP: https://wiki.medflow.com/sop/scheduling-downtime
