# ShopFast Observability Stack

**Last Updated:** 2026-02-01 | **Owner:** Platform Team | **Status:** Current

## Overview

ShopFast uses a Prometheus + Grafana + ELK observability stack with OpenTelemetry for distributed tracing. All services expose metrics on `/actuator/prometheus` (JVM services) or `/metrics` (Node.js/Python). Logs are collected via Fluentd and shipped to Elasticsearch.

## Metrics: Prometheus + Grafana

### Prometheus Configuration
- **Deployment:** kube-prometheus-stack Helm chart in `monitoring` namespace
- **Scrape Interval:** 15s for application metrics, 30s for infrastructure
- **Retention:** 30 days local, Thanos sidecar for long-term storage in S3
- **Service Discovery:** Kubernetes service monitor CRDs per service

### Key Alert Rules

| Alert | Condition | Severity | Target |
|-------|-----------|----------|--------|
| HighErrorRate | 5xx rate > 1% for 5min | SEV-2 | Per-service |
| HighLatency | p99 > 2s for 5min | SEV-2 | Per-service |
| PodCrashLoop | restart count > 3 in 10min | SEV-2 | All pods |
| DBPoolExhaustion | pool_active / pool_max > 0.95 for 2min | SEV-2 | JVM services |
| DBPoolHigh | pool_active / pool_max > 0.80 for 5min | SEV-3 | JVM services |
| RedisMemoryHigh | used_memory / maxmemory > 0.85 | SEV-2 | Redis |
| RabbitQueueDepth | queue_messages > 10000 for 5min | SEV-3 | RabbitMQ |
| NodeMemoryPressure | node_memory_available < 10% | SEV-2 | EKS nodes |
| PodOOMKilled | kube_pod_container_status_last_terminated_reason="OOMKilled" | SEV-2 | All pods |
| CertificateExpiry | cert_expiry_days < 14 | SEV-3 | Ingress |

### Grafana Dashboards

| Dashboard | URL | Description |
|-----------|-----|-------------|
| Platform Overview | /d/shopfast-overview | All services RED metrics, cluster health |
| Service Detail | /d/shopfast-service-{name} | Per-service RED metrics, JVM stats, pod resources |
| DB Pool Utilization | /d/shopfast-db-pools | HikariCP pool metrics across all services |
| PostgreSQL Health | /d/shopfast-postgres | RDS metrics, connections, query performance |
| Redis Health | /d/shopfast-redis | Memory, connections, hit rate, evictions |
| RabbitMQ | /d/shopfast-rabbitmq | Queue depths, consumer rates, publish rates |
| JVM Health | /d/shopfast-jvm | Heap, GC pauses, thread counts per service |
| Kubernetes Cluster | /d/shopfast-k8s | Node resources, pod scheduling, HPA status |

Access: https://grafana.internal.shopfast.com (SSO via Okta)

## Logs: ELK Stack

### Pipeline
1. **Collection:** Fluentd DaemonSet on each EKS node, tails container logs from /var/log/containers
2. **Parsing:** Fluentd parses JSON-structured logs, enriches with Kubernetes metadata (pod, namespace, labels)
3. **Shipping:** Fluentd outputs to Elasticsearch via HTTP bulk API
4. **Storage:** Elasticsearch 8.11 cluster (3 data nodes), index per service per day
5. **Retention:** 14 days hot, 30 days warm (ILM policy), archived to S3 after 30 days

### Log Format (standardized)
All services must output JSON logs with these fields:
- `timestamp`, `level`, `service`, `traceId`, `spanId`, `message`, `logger`
- Additional context fields vary by service (e.g., `orderId`, `userId`, `sku`)

### Kibana Access
- URL: https://kibana.internal.shopfast.com
- Saved searches: "Production Errors (last 1h)", "Slow Queries", "Payment Failures"
- Index patterns: `shopfast-{service}-*`

## Tracing: OpenTelemetry

- **Collector:** OpenTelemetry Collector deployed as DaemonSet
- **SDK:** OpenTelemetry Java agent (auto-instrumentation) for JVM services, manual instrumentation for Node.js and Python
- **Backend:** Jaeger (all-in-one) in monitoring namespace
- **Sampling:** 10% head-based sampling in production, 100% for error traces
- **Trace Propagation:** W3C TraceContext headers via api-gateway

### Key Trace Queries
- Checkout flow: api-gateway -> order-service -> payment-service -> notification-service
- Product search: api-gateway -> catalog-service -> inventory-service (+ Elasticsearch)
- Cart operations: api-gateway -> cart-service (Redis)

## Alerting Pipeline

1. Prometheus evaluates alert rules every 15s
2. Firing alerts sent to Alertmanager
3. Alertmanager routes by severity:
   - SEV-1/SEV-2: PagerDuty integration (immediate page)
   - SEV-3: Slack #shopfast-alerts channel
   - SEV-4: Slack #shopfast-alerts-low (business hours only)
4. Alert grouping: by service and alert type (5-minute group window)
5. Repeat interval: SEV-1 every 5min, SEV-2 every 15min, SEV-3 every 1h

## On-Call Access

Grafana, Kibana, and Jaeger are accessible via VPN (vpn.shopfast.com). No public endpoints. On-call engineers must have VPN configured before rotation starts. See SOP-003 for access setup.
