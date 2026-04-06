#!/usr/bin/env python3
"""Generate mock K8s manifests for ShopFast services."""

import yaml
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent

SERVICES = {
    "api-gateway": {
        "image": "shopfast/api-gateway:1.4.2",
        "port": 8080,
        "replicas": 3,
        "cpu_request": "200m", "cpu_limit": "500m",
        "mem_request": "256Mi", "mem_limit": "512Mi",
        "env": {
            "CATALOG_SERVICE_URL": "http://catalog-service:8081",
            "CART_SERVICE_URL": "http://cart-service:8082",
            "ORDER_SERVICE_URL": "http://order-service:8083",
            "PAYMENT_SERVICE_URL": "http://payment-service:8084",
            "REDIS_HOST": "redis.shopfast-prod.svc.cluster.local",
            "LOG_LEVEL": "info",
        },
        "config": {"rate_limit_rps": "1000", "cors_origins": "*", "auth_jwt_secret_ref": "api-gateway-secrets"},
        "hpa": {"min": 3, "max": 10, "cpu_target": 70},
    },
    "catalog-service": {
        "image": "shopfast/catalog-service:2.1.0",
        "port": 8081,
        "replicas": 3,
        "cpu_request": "100m", "cpu_limit": "300m",
        "mem_request": "128Mi", "mem_limit": "256Mi",
        "env": {
            "INVENTORY_SERVICE_URL": "http://inventory-service:8086",
            "ELASTICSEARCH_URL": "http://opensearch.shopfast-prod.svc.cluster.local:9200",
            "DATABASE_URL": "postgresql://catalog_user@shopfast-db.shopfast-prod.svc.cluster.local:5432/shopfast_catalog",
            "LOG_LEVEL": "info",
        },
        "config": {"cache_ttl_seconds": "300", "search_index": "products"},
        "hpa": {"min": 2, "max": 6, "cpu_target": 75},
    },
    "cart-service": {
        "image": "shopfast/cart-service:1.8.1",
        "port": 8082,
        "replicas": 2,
        "cpu_request": "100m", "cpu_limit": "250m",
        "mem_request": "128Mi", "mem_limit": "256Mi",
        "env": {
            "CATALOG_SERVICE_URL": "http://catalog-service:8081",
            "REDIS_HOST": "redis.shopfast-prod.svc.cluster.local",
            "REDIS_PORT": "6379",
            "REDIS_POOL_MAX": "50",
            "LOG_LEVEL": "info",
        },
        "config": {"cart_ttl_hours": "72", "max_items_per_cart": "50"},
        "hpa": {"min": 2, "max": 5, "cpu_target": 75},
    },
    "order-service": {
        "image": "shopfast/order-service:3.2.1",
        "port": 8083,
        "replicas": 3,
        "cpu_request": "200m", "cpu_limit": "500m",
        "mem_request": "256Mi", "mem_limit": "512Mi",
        "env": {
            "PAYMENT_SERVICE_URL": "http://payment-service:8084",
            "INVENTORY_SERVICE_URL": "http://inventory-service:8086",
            "NOTIFICATION_SERVICE_URL": "http://notification-service:8085",
            "DATABASE_URL": "postgresql://order_user@shopfast-db.shopfast-prod.svc.cluster.local:5432/shopfast_orders",
            "RABBITMQ_URL": "amqp://guest:guest@rabbitmq.shopfast-prod.svc.cluster.local:5672",
            "DB_POOL_MAX": "20",
            "LOG_LEVEL": "info",
        },
        "config": {"order_timeout_seconds": "30", "retry_max_attempts": "3"},
        "hpa": {"min": 3, "max": 8, "cpu_target": 70},
    },
    "payment-service": {
        "image": "shopfast/payment-service:2.0.4",
        "port": 8084,
        "replicas": 2,
        "cpu_request": "300m", "cpu_limit": "1000m",
        "mem_request": "512Mi", "mem_limit": "2048Mi",
        "env": {
            "DATABASE_URL": "postgresql://payment_user@shopfast-db.shopfast-prod.svc.cluster.local:5432/shopfast_payments",
            "RABBITMQ_URL": "amqp://guest:guest@rabbitmq.shopfast-prod.svc.cluster.local:5672",
            "PAYMENT_GATEWAY_URL": "https://api.stripe.com/v1",
            "DB_POOL_MAX": "15",
            "JVM_HEAP_MAX": "2048m",
            "LOG_LEVEL": "info",
        },
        "config": {"gateway_timeout_ms": "30000", "idempotency_key_ttl_hours": "24"},
        "hpa": {"min": 2, "max": 6, "cpu_target": 65},
    },
    "inventory-service": {
        "image": "shopfast/inventory-service:1.5.3",
        "port": 8086,
        "replicas": 2,
        "cpu_request": "100m", "cpu_limit": "300m",
        "mem_request": "128Mi", "mem_limit": "256Mi",
        "env": {
            "DATABASE_URL": "postgresql://inventory_user@shopfast-db.shopfast-prod.svc.cluster.local:5432/shopfast_inventory",
            "DB_POOL_MAX": "15",
            "LOG_LEVEL": "info",
        },
        "config": {"stock_cache_ttl_seconds": "60", "low_stock_threshold": "10"},
        "hpa": {"min": 2, "max": 5, "cpu_target": 75},
    },
    "notification-service": {
        "image": "shopfast/notification-service:1.2.0",
        "port": 8085,
        "replicas": 2,
        "cpu_request": "50m", "cpu_limit": "200m",
        "mem_request": "64Mi", "mem_limit": "128Mi",
        "env": {
            "RABBITMQ_URL": "amqp://guest:guest@rabbitmq.shopfast-prod.svc.cluster.local:5672",
            "SMTP_HOST": "ses.us-east-1.amazonaws.com",
            "LOG_LEVEL": "info",
        },
        "config": {"email_from": "noreply@shopfast.com", "batch_size": "100"},
        "hpa": {"min": 1, "max": 4, "cpu_target": 80},
    },
}

def make_deployment(name, spec):
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": name, "namespace": "shopfast-prod", "labels": {"app": name}},
        "spec": {
            "replicas": spec["replicas"],
            "selector": {"matchLabels": {"app": name}},
            "template": {
                "metadata": {"labels": {"app": name}},
                "spec": {
                    "containers": [{
                        "name": name,
                        "image": spec["image"],
                        "ports": [{"containerPort": spec["port"]}],
                        "env": [{"name": k, "value": v} for k, v in spec["env"].items()],
                        "envFrom": [{"configMapRef": {"name": f"{name}-config"}}],
                        "resources": {
                            "requests": {"cpu": spec["cpu_request"], "memory": spec["mem_request"]},
                            "limits": {"cpu": spec["cpu_limit"], "memory": spec["mem_limit"]},
                        },
                        "readinessProbe": {
                            "httpGet": {"path": "/health", "port": spec["port"]},
                            "initialDelaySeconds": 10, "periodSeconds": 5,
                        },
                        "livenessProbe": {
                            "httpGet": {"path": "/health", "port": spec["port"]},
                            "initialDelaySeconds": 30, "periodSeconds": 10,
                        },
                    }],
                },
            },
        },
    }

def make_service(name, spec):
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": name, "namespace": "shopfast-prod"},
        "spec": {
            "selector": {"app": name},
            "ports": [{"port": spec["port"], "targetPort": spec["port"], "protocol": "TCP"}],
            "type": "ClusterIP",
        },
    }

def make_configmap(name, spec):
    return {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {"name": f"{name}-config", "namespace": "shopfast-prod"},
        "data": spec["config"],
    }

def make_hpa(name, spec):
    return {
        "apiVersion": "autoscaling/v2",
        "kind": "HorizontalPodAutoscaler",
        "metadata": {"name": f"{name}-hpa", "namespace": "shopfast-prod"},
        "spec": {
            "scaleTargetRef": {"apiVersion": "apps/v1", "kind": "Deployment", "name": name},
            "minReplicas": spec["hpa"]["min"],
            "maxReplicas": spec["hpa"]["max"],
            "metrics": [{"type": "Resource", "resource": {"name": "cpu", "target": {"type": "Utilization", "averageUtilization": spec["hpa"]["cpu_target"]}}}],
        },
    }

if __name__ == "__main__":
    for name, spec in SERVICES.items():
        for kind, factory in [("deployment", make_deployment), ("service", make_service), ("configmap", make_configmap), ("hpa", make_hpa)]:
            path = OUTPUT_DIR / f"{name}-{kind}.yaml"
            with open(path, "w") as f:
                yaml.dump(factory(name, spec), f, default_flow_style=False)
            print(f"  Created {path.name}")
    print(f"\nGenerated {len(SERVICES) * 4} manifests in {OUTPUT_DIR}")
