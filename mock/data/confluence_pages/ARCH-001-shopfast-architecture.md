# ShopFast Platform Architecture

**Last Updated:** 2026-01-20 | **Owner:** Platform Team | **Status:** Current

## Overview

ShopFast is a B2C e-commerce platform processing ~50K orders/day. The platform runs as 7 microservices on AWS EKS in the `shopfast-prod` namespace. All services communicate via synchronous REST for real-time operations and asynchronous RabbitMQ messaging for background workflows.

## Service Registry

| Service | Tech Stack | Team | Repository | Port | Replicas |
|---------|-----------|------|------------|------|----------|
| api-gateway | Node.js 20, Express | Platform | shopfast/api-gateway | 8080 | 3 |
| catalog-service | Java 21, Spring Boot 3.2 | Catalog | shopfast/catalog-service | 8081 | 3 |
| cart-service | Java 21, Spring Boot 3.2 | Commerce | shopfast/cart-service | 8082 | 3 |
| order-service | Java 21, Spring Boot 3.2 | Commerce | shopfast/order-service | 8083 | 4 |
| payment-service | Java 21, Spring Boot 3.2 | Payments | shopfast/payment-service | 8084 | 3 |
| notification-service | Python 3.12, FastAPI | Commerce | shopfast/notification-service | 8085 | 2 |
| inventory-service | Java 21, Spring Boot 3.2 | Catalog | shopfast/inventory-service | 8086 | 3 |

## Infrastructure

- **Kubernetes:** AWS EKS 1.29, managed node groups (m5.xlarge), cluster autoscaler enabled
- **Database:** Amazon RDS PostgreSQL 15.4, db.r6g.xlarge, Multi-AZ, 200 max_connections
- **Cache:** Amazon ElastiCache Redis 7.0, r6g.large, single node (cart-service and catalog-service share instance)
- **Message Broker:** Amazon MQ RabbitMQ 3.12, mq.m5.large, single broker
- **Search:** Amazon OpenSearch (Elasticsearch) 8.11, 3x m5.large.search data nodes
- **CDN:** CloudFront for static assets and product images
- **DNS:** Route53 with health checks

## Service Communication Patterns

### Synchronous (REST over HTTP)
- api-gateway -> all backend services (routing + auth)
- order-service -> payment-service (checkout flow)
- order-service -> inventory-service (stock reservation)
- catalog-service -> inventory-service (availability check)

### Asynchronous (RabbitMQ)
- order-service -> notification-service (order confirmations, shipping updates)
- payment-service -> order-service (payment status callbacks)
- inventory-service -> catalog-service (stock level updates for search)

## Deployment

- **CI:** GitHub Actions — build, test, container image push to ECR
- **CD:** ArgoCD with auto-sync for service-specific configs, manual sync for shared configs
- **Strategy:** Canary deployments for api-gateway (10% -> 50% -> 100%), blue-green for all backend services
- **Feature Flags:** LaunchDarkly for runtime feature toggling
- **Container Registry:** Amazon ECR, images tagged with git SHA

## Network

- All inter-service traffic stays within the EKS cluster (ClusterIP services)
- api-gateway exposed via AWS ALB Ingress Controller
- No service mesh currently deployed (Istio evaluation tracked in INFRA-501)
- Network policies enforce namespace isolation

## Known Gaps

- No connection pooler (pgbouncer) in front of PostgreSQL — see INFRA-445
- No service mesh — limited observability on inter-service traffic
- Redis is shared between cart-service and catalog-service — should be separated
- RabbitMQ is single broker — no HA clustering
