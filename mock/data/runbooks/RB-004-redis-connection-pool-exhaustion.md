# RB-004: Redis Connection Pool Exhaustion

| Field         | Value                                                    |
|---------------|----------------------------------------------------------|
| **Service**   | cart-service                                             |
| **Severity**  | P1 - Critical                                            |
| **Last Updated** | 2026-02-27                                            |
| **Author**    | Platform Engineering / ShopFast SRE                      |
| **Alert**     | `RedisPoolExhausted`                                     |

## Symptoms

- **Alert fires:** `RedisPoolExhausted` with labels `service=cart-service`, `namespace=shopfast-prod` when all 50 connections in the Lettuce/Jedis pool are in use
- **Grafana dashboard:** "ShopFast / Redis Connections" shows active connections at pool max (50) and pending requests climbing
- **Metrics:**
  - `redis_pool_active_connections{service="cart-service"} >= 50`
  - `redis_pool_idle_connections{service="cart-service"} == 0`
  - `redis_command_timeout_total{service="cart-service"}` rate > 0
  - `redis_pool_wait_duration_seconds{quantile="0.99"} > 5`
- **User impact:** Cart operations fail or time out. Customers see "Unable to load cart" or "Add to cart failed" errors. Cart data is temporarily inaccessible.
- **Logs:** `io.lettuce.core.RedisCommandTimeoutException: Command timed out after 5 second(s)` or `redis.clients.jedis.exceptions.JedisExhaustedPoolException: Could not get a resource from the pool`

## Investigation Steps

### 1. Confirm which pods are affected

```bash
kubectl get pods -n shopfast-prod -l app=cart-service -o wide
kubectl logs -n shopfast-prod -l app=cart-service --tail=50 | grep -i "timeout\|redis\|pool\|exhausted"
```

### 2. Check Redis server health

```bash
# Connect to Redis pod or use redis-cli from a cart-service pod
kubectl exec -n shopfast-prod deploy/cart-service -- redis-cli -h redis-cart.shopfast-prod.svc.cluster.local -p 6379 INFO clients
kubectl exec -n shopfast-prod deploy/cart-service -- redis-cli -h redis-cart.shopfast-prod.svc.cluster.local -p 6379 INFO memory
kubectl exec -n shopfast-prod deploy/cart-service -- redis-cli -h redis-cart.shopfast-prod.svc.cluster.local -p 6379 INFO stats
```

### 3. Check connected client count and maxclients

```bash
kubectl exec -n shopfast-prod deploy/cart-service -- redis-cli -h redis-cart.shopfast-prod.svc.cluster.local -p 6379 CONFIG GET maxclients
kubectl exec -n shopfast-prod deploy/cart-service -- redis-cli -h redis-cart.shopfast-prod.svc.cluster.local -p 6379 CLIENT LIST | wc -l
```

### 4. Identify long-running or blocked clients

```bash
kubectl exec -n shopfast-prod deploy/cart-service -- redis-cli -h redis-cart.shopfast-prod.svc.cluster.local -p 6379 CLIENT LIST --sort-by idle | tail -20
kubectl exec -n shopfast-prod deploy/cart-service -- redis-cli -h redis-cart.shopfast-prod.svc.cluster.local -p 6379 SLOWLOG GET 20
```

### 5. Check for blocking commands or large key scans

```bash
kubectl exec -n shopfast-prod deploy/cart-service -- redis-cli -h redis-cart.shopfast-prod.svc.cluster.local -p 6379 INFO commandstats | grep -E "keys|scan|blpop|brpop"
```

### 6. Check application pool configuration

```bash
kubectl get configmap cart-service-config -n shopfast-prod -o yaml | grep -i "redis\|pool\|max\|timeout"
kubectl get deployment cart-service -n shopfast-prod -o jsonpath='{.spec.template.spec.containers[0].env}' | jq '.[] | select(.name | test("REDIS"; "i"))'
```

## Remediation

### Immediate (restore service)

1. **Rolling restart of cart-service to reset connection pools:**

```bash
kubectl rollout restart deployment/cart-service -n shopfast-prod
kubectl rollout status deployment/cart-service -n shopfast-prod --timeout=120s
```

2. **If Redis maxclients is too low, increase it:**

```bash
kubectl exec -n shopfast-prod deploy/cart-service -- redis-cli -h redis-cart.shopfast-prod.svc.cluster.local -p 6379 CONFIG SET maxclients 500
```

3. **Kill idle client connections on Redis server:**

```bash
# Kill clients idle for more than 300 seconds
kubectl exec -n shopfast-prod deploy/cart-service -- redis-cli -h redis-cart.shopfast-prod.svc.cluster.local -p 6379 CLIENT NO-EVICT ON
kubectl exec -n shopfast-prod deploy/cart-service -- redis-cli -h redis-cart.shopfast-prod.svc.cluster.local -p 6379 CONFIG SET timeout 300
```

4. **Scale cart-service if traffic spike is the cause (but beware this adds more Redis connections):**

```bash
# Only scale if Redis server has headroom
kubectl scale deployment/cart-service -n shopfast-prod --replicas=4
```

### Root Cause

- Check if the cart-service replica count was recently increased without adjusting the per-pod pool size. Each pod with pool max=50 and 4 replicas = 200 connections to Redis.
- Verify `spring.redis.lettuce.pool.max-active=50`, `max-idle=10`, `min-idle=5`, and `max-wait=5000ms` are correctly set.
- Look for SUBSCRIBE/PSUBSCRIBE commands that hold connections indefinitely.
- Check if a slow Lua script or `KEYS *` command is blocking the Redis event loop, causing all clients to queue.
- Review if the Redis instance needs vertical scaling (check `used_memory` vs `maxmemory`).

## Escalation

| Condition                                              | Action                                        |
|--------------------------------------------------------|-----------------------------------------------|
| Redis server itself is unresponsive                    | Page Database/Cache on-call immediately       |
| Pool exhaustion recurs within 30 min of restart        | Engage cart-service dev team                  |
| Redis memory usage > 80% of maxmemory                 | Page Database/Cache on-call                   |
| Multiple services affected (not just cart-service)     | Escalate to P0, page Platform Engineering     |
