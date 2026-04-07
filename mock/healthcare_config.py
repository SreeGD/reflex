"""MedFlow Health Platform — healthcare EHR service definitions.

Parallel to ShopFast (config.py). Activated via MOCK_SYSTEM=healthcare.
7 microservices modeling a hospital EHR/clinical operations platform.
"""

from __future__ import annotations

from mock.config import ServiceDef, ServiceType, Endpoint

HEALTHCARE_SERVICES = {
    "ehr-gateway": ServiceDef(
        name="ehr-gateway",
        display_name="EHR Gateway",
        service_type=ServiceType.PYTHON_FASTAPI,
        port=9080,
        replicas=3,
        namespace="medflow-prod",
        dependencies=["medication-service", "scheduling-service", "patient-service"],
        baseline_rps=(400.0, 60.0),
        baseline_latency_p50_ms=(15.0, 3.0),
        baseline_latency_p99_ms=(80.0, 15.0),
        endpoints=[
            Endpoint("/api/v1/patients", "GET", 150.0, 12.0, 60.0),
            Endpoint("/api/v1/appointments", "POST", 60.0, 18.0, 90.0),
            Endpoint("/api/v1/medications", "GET", 80.0, 10.0, 50.0),
            Endpoint("/api/v1/orders", "POST", 40.0, 45.0, 200.0),
        ],
    ),
    "medication-service": ServiceDef(
        name="medication-service",
        display_name="Medication Service",
        service_type=ServiceType.GO,
        port=9081,
        replicas=3,
        namespace="medflow-prod",
        dependencies=["pharmacy-service"],
        baseline_rps=(250.0, 40.0),
        baseline_latency_p50_ms=(8.0, 2.0),
        baseline_latency_p99_ms=(40.0, 8.0),
        endpoints=[
            Endpoint("/api/v1/drugs", "GET", 200.0, 6.0, 30.0),
            Endpoint("/api/v1/interactions", "POST", 50.0, 15.0, 80.0),
        ],
    ),
    "scheduling-service": ServiceDef(
        name="scheduling-service",
        display_name="Scheduling Service",
        service_type=ServiceType.NODEJS,
        port=9082,
        replicas=2,
        namespace="medflow-prod",
        dependencies=["medication-service"],
        redis_pool_max=50,
        baseline_latency_p50_ms=(10.0, 2.0),
        baseline_latency_p99_ms=(50.0, 10.0),
        endpoints=[
            Endpoint("/api/v1/appointments", "GET", 60.0, 8.0, 40.0),
            Endpoint("/api/v1/appointments", "POST", 40.0, 12.0, 60.0),
        ],
    ),
    "patient-service": ServiceDef(
        name="patient-service",
        display_name="Patient Service",
        service_type=ServiceType.PYTHON_FASTAPI,
        port=9083,
        replicas=3,
        namespace="medflow-prod",
        dependencies=["billing-service", "pharmacy-service", "alert-service"],
        db_pool_max=20,
        baseline_latency_p50_ms=(45.0, 8.0),
        baseline_latency_p99_ms=(200.0, 30.0),
        endpoints=[
            Endpoint("/api/v1/patients", "POST", 50.0, 45.0, 200.0),
            Endpoint("/api/v1/patients", "GET", 80.0, 15.0, 60.0),
            Endpoint("/api/v1/admissions", "POST", 30.0, 50.0, 250.0),
        ],
    ),
    "billing-service": ServiceDef(
        name="billing-service",
        display_name="Billing Service",
        service_type=ServiceType.JAVA_SPRING,
        port=9084,
        replicas=2,
        namespace="medflow-prod",
        dependencies=[],
        db_pool_max=15,
        jvm_heap_max_mb=2048,
        baseline_latency_p50_ms=(80.0, 15.0),
        baseline_latency_p99_ms=(300.0, 50.0),
        endpoints=[
            Endpoint("/api/v1/claims", "POST", 40.0, 80.0, 300.0),
            Endpoint("/api/v1/verify-insurance", "POST", 30.0, 100.0, 400.0),
        ],
    ),
    "alert-service": ServiceDef(
        name="alert-service",
        display_name="Alert Service",
        service_type=ServiceType.PYTHON_FASTAPI,
        port=9085,
        replicas=2,
        namespace="medflow-prod",
        dependencies=[],
        baseline_latency_p50_ms=(5.0, 1.0),
        baseline_latency_p99_ms=(20.0, 5.0),
        endpoints=[
            Endpoint("/api/v1/clinical-alerts", "POST", 50.0, 5.0, 20.0),
            Endpoint("/api/v1/pager", "POST", 20.0, 3.0, 15.0),
        ],
    ),
    "pharmacy-service": ServiceDef(
        name="pharmacy-service",
        display_name="Pharmacy Service",
        service_type=ServiceType.GO,
        port=9086,
        replicas=2,
        namespace="medflow-prod",
        dependencies=[],
        db_pool_max=15,
        baseline_latency_p50_ms=(12.0, 3.0),
        baseline_latency_p99_ms=(50.0, 10.0),
        endpoints=[
            Endpoint("/api/v1/dispense", "POST", 40.0, 15.0, 60.0),
            Endpoint("/api/v1/stock", "GET", 80.0, 10.0, 40.0),
        ],
    ),
}

HEALTHCARE_DEPENDENCY_GRAPH = {
    "ehr-gateway": ["medication-service", "scheduling-service", "patient-service"],
    "scheduling-service": ["medication-service"],
    "medication-service": ["pharmacy-service"],
    "patient-service": ["billing-service", "pharmacy-service", "alert-service"],
    "billing-service": [],
    "alert-service": [],
    "pharmacy-service": [],
}

HEALTHCARE_SERVICE_TIERS = {
    "patient-service": 1,
    "billing-service": 1,
    "ehr-gateway": 1,
    "medication-service": 2,
    "scheduling-service": 2,
    "pharmacy-service": 2,
    "alert-service": 3,
}

HEALTHCARE_USER_JOURNEYS = {
    "patient_admission": ["ehr-gateway", "patient-service", "billing-service", "pharmacy-service", "alert-service"],
    "medication_order": ["ehr-gateway", "medication-service", "pharmacy-service"],
    "appointment_booking": ["ehr-gateway", "scheduling-service", "medication-service"],
}

HEALTHCARE_SCENARIOS = {
    "ehr_db_pool_exhaustion": "mock.scenarios.ehr_db_pool_exhaustion",
    "billing_timeout_cascade": "mock.scenarios.billing_timeout_cascade",
    "pharmacy_memory_leak": "mock.scenarios.pharmacy_memory_leak",
    "scheduling_redis_storm": "mock.scenarios.scheduling_redis_storm",
    "medication_slow_query": "mock.scenarios.medication_slow_query",
}

HEALTHCARE_SCENARIO_LABELS = {
    "ehr_db_pool_exhaustion": "EHR DB Connection Pool Exhaustion",
    "billing_timeout_cascade": "Billing/Insurance API Timeout Cascade",
    "pharmacy_memory_leak": "Pharmacy Service Memory Leak",
    "scheduling_redis_storm": "Scheduling Redis Connection Storm",
    "medication_slow_query": "Medication Slow Query Cascade",
}
