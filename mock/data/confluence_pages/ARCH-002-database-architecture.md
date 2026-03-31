# ShopFast Database Architecture

**Last Updated:** 2026-01-18 | **Owner:** Platform Team | **Status:** Current

## Overview

ShopFast uses a shared Amazon RDS PostgreSQL 15.4 instance (db.r6g.xlarge) with per-service schemas. Each service owns its schema and manages migrations independently via Flyway. Cross-schema queries are prohibited by convention and enforced via per-service database users with schema-level GRANT restrictions.

## Instance Configuration

- **Engine:** PostgreSQL 15.4
- **Instance:** db.r6g.xlarge (4 vCPU, 32 GB RAM)
- **Storage:** 500 GB gp3, 3000 IOPS
- **Multi-AZ:** Enabled (synchronous standby in us-east-1b)
- **Read Replicas:** 1 replica (db.r6g.large) for reporting and read-heavy queries
- **max_connections:** 200 (RDS default for this instance class)
- **Maintenance Window:** Sunday 04:00-05:00 UTC

## Schema Layout

| Schema | Owner Service | Approx Size | Key Tables |
|--------|--------------|-------------|------------|
| orders | order-service | 45 GB | orders, order_items, order_status_history |
| payments | payment-service | 18 GB | transactions, refunds, payment_methods |
| inventory | inventory-service | 8 GB | stock_levels, warehouses, reservations |
| catalog | catalog-service | 12 GB | products, categories, product_attributes |
| notifications | notification-service | 3 GB | notification_log, templates |

Note: cart-service and api-gateway do not use PostgreSQL. Cart data is in Redis; api-gateway is stateless.

## Connection Pool Configuration

Each JVM-based service uses HikariCP. Connection pools are configured per-pod:

| Service | Pool Size (per pod) | Pod Count | Total Connections | DB User |
|---------|-------------------|-----------|-------------------|---------|
| order-service | 20 | 4 | 80 | shopfast_orders |
| payment-service | 15 | 3 | 45 | shopfast_payments |
| inventory-service | 15 | 3 | 45 | shopfast_inventory |
| catalog-service | 10 | 3 | 30 | shopfast_catalog |
| notification-service | 5 | 2 | 10 | shopfast_notifications |

**Total production connections: ~210** (exceeds max_connections of 200 under full load)

### HikariCP Settings (common across services)
- connectionTimeout: 30000ms
- idleTimeout: 600000ms (10 min)
- maxLifetime: 1800000ms (30 min)
- leakDetectionThreshold: 60000ms (1 min)

## Known Issue: No Connection Pooler

**INFRA-445 (Open, Priority: High)**

There is no pgbouncer or PgCat connection pooler between application pods and PostgreSQL. This means:

1. Each pod maintains direct TCP connections to PostgreSQL
2. Scaling pods linearly increases PostgreSQL connections
3. Total pool capacity across all services (210) exceeds max_connections (200)
4. Pod restarts cause connection storms as all connections re-establish simultaneously
5. Flash sales or traffic spikes that trigger HPA scaling can exhaust PostgreSQL connections

**Mitigation until pgbouncer is deployed:** HPA max replicas are capped, and services are configured with conservative pool sizes. Teams must coordinate before scaling any database-connected service.

## Backup Strategy

- **Automated Snapshots:** RDS automated backups, 7-day retention, taken daily at 03:00 UTC
- **Point-in-Time Recovery:** Enabled, 5-minute RPO via WAL archiving
- **Cross-Region:** Daily snapshot copy to us-west-2 for DR
- **Logical Backups:** pg_dump of each schema weekly, stored in S3 (shopfast-db-backups)
- **Recovery Testing:** Quarterly restore drill to staging environment

## Migration Process

1. Developer creates Flyway migration in service repository (V{version}__{description}.sql)
2. PR review requires approval from service team lead AND platform team for DDL changes
3. Migrations run automatically on service startup (Flyway baseline-on-migrate=true)
4. Large data migrations (>1M rows) must be run as background jobs, not in Flyway
5. All DDL must use CREATE INDEX CONCURRENTLY for index creation on production tables

## Monitoring

- RDS Performance Insights enabled for slow query analysis
- pg_stat_statements extension enabled for query statistics
- CloudWatch alarms: CPU > 80%, FreeableMemory < 2GB, DatabaseConnections > 180
- Custom Prometheus metrics via postgres_exporter for pool utilization per service
