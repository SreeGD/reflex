#!/usr/bin/env python3
"""Generate mock K8s manifests for MedFlow Health Platform services."""

import yaml
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent

SERVICES = {
    "ehr-gateway": {
        "image": "medflow/ehr-gateway:3.2.0",
        "port": 9080,
        "replicas": 3,
        "cpu_request": "300m", "cpu_limit": "1000m",
        "mem_request": "512Mi", "mem_limit": "1024Mi",
        "env": {
            "PATIENT_SERVICE_URL": "http://patient-service:9083",
            "MEDICATION_SERVICE_URL": "http://medication-service:9081",
            "SCHEDULING_SERVICE_URL": "http://scheduling-service:9082",
            "BILLING_SERVICE_URL": "http://billing-service:9084",
            "ALERT_SERVICE_URL": "http://alert-service:9085",
            "REDIS_HOST": "redis-sessions.medflow-prod.svc.cluster.local",
            "FHIR_BASE_URL": "http://ehr-gateway:9080/fhir/r4",
            "HL7_VERSION": "FHIR_R4",
            "SMART_ON_FHIR_ENABLED": "true",
            "OAUTH2_ISSUER_URL": "https://auth.medflow.com/realms/medflow",
            "LOG_LEVEL": "info",
        },
        "config": {
            "rate_limit_rps": "500",
            "cors_origins": "https://portal.medflow.com",
            "auth_jwt_secret_ref": "ehr-gateway-secrets",
            "fhir_capability_statement_cache_ttl": "3600",
            "smart_app_launch_enabled": "true",
        },
        "hpa": {"min": 3, "max": 10, "cpu_target": 70},
    },
    "medication-service": {
        "image": "medflow/medication-service:2.3.1",
        "port": 9081,
        "replicas": 2,
        "cpu_request": "200m", "cpu_limit": "500m",
        "mem_request": "256Mi", "mem_limit": "512Mi",
        "env": {
            "PHARMACY_SERVICE_URL": "http://pharmacy-service:9086",
            "DATABASE_URL": "postgresql://medication_svc_user@medflow-db.medflow-prod.svc.cluster.local:5432/medflow_medications",
            "DB_POOL_MAX": "15",
            "FHIR_BASE_URL": "http://ehr-gateway:9080/fhir/r4",
            "HL7_VERSION": "FHIR_R4",
            "NDC_DATABASE_VERSION": "2026-Q1",
            "RXNORM_API_URL": "https://rxnav.nlm.nih.gov/REST",
            "FORMULARY_CACHE_TTL_SECONDS": "1800",
            "LOG_LEVEL": "info",
        },
        "config": {
            "interaction_check_timeout_ms": "5000",
            "formulary_tier_count": "5",
            "ndc_update_schedule": "0 2 * * 0",
            "drug_interaction_severity_levels": "contraindicated,severe,moderate,minor",
        },
        "hpa": {"min": 2, "max": 6, "cpu_target": 75},
    },
    "scheduling-service": {
        "image": "medflow/scheduling-service:1.9.2",
        "port": 9082,
        "replicas": 2,
        "cpu_request": "100m", "cpu_limit": "300m",
        "mem_request": "128Mi", "mem_limit": "256Mi",
        "env": {
            "PATIENT_SERVICE_URL": "http://patient-service:9083",
            "REDIS_HOST": "redis-scheduling.medflow-prod.svc.cluster.local",
            "REDIS_PORT": "6379",
            "REDIS_POOL_MAX": "50",
            "DATABASE_URL": "postgresql://scheduling_svc_user@medflow-db.medflow-prod.svc.cluster.local:5432/medflow_scheduling",
            "DB_POOL_MAX": "10",
            "FHIR_BASE_URL": "http://ehr-gateway:9080/fhir/r4",
            "LOG_LEVEL": "info",
        },
        "config": {
            "appointment_slot_duration_minutes": "15",
            "max_advance_booking_days": "90",
            "bed_management_refresh_seconds": "30",
            "checkin_kiosk_timeout_seconds": "120",
        },
        "hpa": {"min": 2, "max": 5, "cpu_target": 75},
    },
    "patient-service": {
        "image": "medflow/patient-service:2.1.0",
        "port": 9083,
        "replicas": 3,
        "cpu_request": "300m", "cpu_limit": "1000m",
        "mem_request": "512Mi", "mem_limit": "1024Mi",
        "env": {
            "MEDICATION_SERVICE_URL": "http://medication-service:9081",
            "BILLING_SERVICE_URL": "http://billing-service:9084",
            "DATABASE_URL": "postgresql://patient_svc_user@medflow-db.medflow-prod.svc.cluster.local:5432/medflow_patients",
            "DB_POOL_MAX": "20",
            "FHIR_BASE_URL": "http://ehr-gateway:9080/fhir/r4",
            "HL7_VERSION": "FHIR_R4",
            "PHI_ENCRYPTION_KEY_REF": "patient-service-phi-key",
            "PHI_AUDIT_ENABLED": "true",
            "MRN_GENERATION_STRATEGY": "sequential",
            "KAFKA_BOOTSTRAP_SERVERS": "medflow-kafka.medflow-prod.svc.cluster.local:9092",
            "KAFKA_TOPIC_PATIENT_EVENTS": "patient-events",
            "LOG_LEVEL": "info",
        },
        "config": {
            "phi_encryption_algorithm": "AES-256-GCM",
            "audit_log_retention_days": "2555",
            "fhir_patient_search_max_results": "100",
            "admission_workflow_timeout_seconds": "60",
            "hipaa_access_log_enabled": "true",
        },
        "hpa": {"min": 3, "max": 8, "cpu_target": 70},
    },
    "billing-service": {
        "image": "medflow/billing-service:3.1.0",
        "port": 9084,
        "replicas": 3,
        "cpu_request": "200m", "cpu_limit": "500m",
        "mem_request": "256Mi", "mem_limit": "512Mi",
        "env": {
            "PATIENT_SERVICE_URL": "http://patient-service:9083",
            "DATABASE_URL": "postgresql://billing_svc_user@medflow-db.medflow-prod.svc.cluster.local:5432/medflow_billing",
            "DB_POOL_MAX": "15",
            "CLEARINGHOUSE_URL": "https://api.clearinghouse.example.com/v2",
            "INSURANCE_VERIFY_TIMEOUT_MS": "25000",
            "EDI_837_ENDPOINT": "https://edi.clearinghouse.example.com/837",
            "EDI_835_ENDPOINT": "https://edi.clearinghouse.example.com/835",
            "PHI_ENCRYPTION_KEY_REF": "billing-service-phi-key",
            "KAFKA_BOOTSTRAP_SERVERS": "medflow-kafka.medflow-prod.svc.cluster.local:9092",
            "KAFKA_TOPIC_BILLING_CLAIMS": "billing-claims",
            "LOG_LEVEL": "info",
        },
        "config": {
            "claims_queue_max_depth": "10000",
            "edi_837_version": "005010X222A1",
            "edi_835_version": "005010X221A1",
            "insurance_verify_retry_max": "3",
            "charge_master_refresh_schedule": "0 1 * * *",
        },
        "hpa": {"min": 3, "max": 8, "cpu_target": 70},
    },
    "alert-service": {
        "image": "medflow/alert-service:1.5.0",
        "port": 9085,
        "replicas": 2,
        "cpu_request": "50m", "cpu_limit": "200m",
        "mem_request": "64Mi", "mem_limit": "128Mi",
        "env": {
            "PATIENT_SERVICE_URL": "http://patient-service:9083",
            "PAGERDUTY_API_URL": "https://events.pagerduty.com/v2",
            "PAGERDUTY_ROUTING_KEY_REF": "alert-service-pagerduty-key",
            "VOCERA_API_URL": "https://vocera.medflow.internal/api/v1",
            "KAFKA_BOOTSTRAP_SERVERS": "medflow-kafka.medflow-prod.svc.cluster.local:9092",
            "KAFKA_TOPIC_CLINICAL_ALERTS": "clinical-alerts",
            "LOG_LEVEL": "info",
        },
        "config": {
            "alert_escalation_timeout_minutes": "5",
            "nurse_call_integration_enabled": "true",
            "critical_alert_sms_enabled": "true",
            "alert_deduplication_window_seconds": "300",
        },
        "hpa": {"min": 2, "max": 4, "cpu_target": 80},
    },
    "pharmacy-service": {
        "image": "medflow/pharmacy-service:2.4.0",
        "port": 9086,
        "replicas": 2,
        "cpu_request": "200m", "cpu_limit": "500m",
        "mem_request": "512Mi", "mem_limit": "4096Mi",
        "env": {
            "MEDICATION_SERVICE_URL": "http://medication-service:9081",
            "PATIENT_SERVICE_URL": "http://patient-service:9083",
            "DATABASE_URL": "postgresql://pharmacy_svc_user@medflow-db.medflow-prod.svc.cluster.local:5432/medflow_pharmacy",
            "DB_POOL_MAX": "15",
            "REDIS_HOST": "redis-pharmacy.medflow-prod.svc.cluster.local",
            "JVM_HEAP_MAX": "4096m",
            "PHI_ENCRYPTION_KEY_REF": "pharmacy-service-phi-key",
            "PYXIS_API_URL": "https://pyxis.medflow.internal/api/v2",
            "OMNICELL_API_URL": "https://omnicell.medflow.internal/api/v1",
            "KAFKA_BOOTSTRAP_SERVERS": "medflow-kafka.medflow-prod.svc.cluster.local:9092",
            "KAFKA_TOPIC_MEDICATION_ORDERS": "medication-orders",
            "CONTROLLED_SUBSTANCE_AUDIT_ENABLED": "true",
            "LOG_LEVEL": "info",
        },
        "config": {
            "dispensing_queue_max_size": "500",
            "drug_interaction_cache_max_entries": "10000",
            "cabinet_sync_interval_seconds": "60",
            "controlled_substance_dual_verify": "true",
            "formulary_cache_ttl_seconds": "1800",
        },
        "hpa": {"min": 2, "max": 6, "cpu_target": 70},
    },
}

def make_deployment(name, spec):
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": name, "namespace": "medflow-prod", "labels": {"app": name}},
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
        "metadata": {"name": name, "namespace": "medflow-prod"},
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
        "metadata": {"name": f"{name}-config", "namespace": "medflow-prod"},
        "data": spec["config"],
    }

def make_hpa(name, spec):
    return {
        "apiVersion": "autoscaling/v2",
        "kind": "HorizontalPodAutoscaler",
        "metadata": {"name": f"{name}-hpa", "namespace": "medflow-prod"},
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
