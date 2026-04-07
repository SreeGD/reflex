# ARCH-101: MedFlow Health Platform Architecture

| Field         | Value                          |
|---------------|--------------------------------|
| **Status**    | Current                        |
| **Version**   | 3.2                            |
| **Last Updated** | 2026-03-01                  |
| **Owner**     | Platform Engineering           |
| **Classification** | Internal - Confidential   |

## Overview

MedFlow Health Platform is a cloud-native Electronic Health Record (EHR) system built on microservices architecture. It provides patient management, clinical workflows, medication management, scheduling, billing, and clinical alerting capabilities. The platform is HIPAA-compliant and follows HL7 FHIR R4 standards for interoperability.

## Service Architecture

### Tier 1 - Critical Patient-Facing Services

| Service | Port | Tech Stack | Team | Description |
|---------|------|-----------|------|-------------|
| **ehr-gateway** | 9080 | Java 17 / Spring Boot 3.2 | Platform Engineering | Patient portal, clinician API gateway, FHIR facade. Routes all external requests. |
| **patient-service** | 9083 | Java 17 / Spring Boot 3.2 | Patient Records Team | Patient demographics, admissions, medical record numbers (MRN), FHIR Patient/Encounter resources. |
| **billing-service** | 9084 | Java 17 / Spring Boot 3.2 | Revenue Cycle IT | Claims processing, insurance verification, EDI 837/835 transactions, pre-authorization. |

### Tier 2 - Clinical Workflow Services

| Service | Port | Tech Stack | Team | Description |
|---------|------|-----------|------|-------------|
| **medication-service** | 9081 | Java 17 / Spring Boot 3.2 | Pharmacy IT | Drug catalog (NDC/RxNorm), formulary management, drug interaction checking, FHIR MedicationRequest. |
| **scheduling-service** | 9082 | Java 17 / Spring Boot 3.2 | Clinical Operations IT | Appointment booking, bed management, resource scheduling, patient check-in. |
| **pharmacy-service** | 9086 | Java 17 / Spring Boot 3.2 | Pharmacy IT | Medication dispensing, inventory management, automated cabinet integration (Pyxis/Omnicell). |

### Tier 3 - Support Services

| Service | Port | Tech Stack | Team | Description |
|---------|------|-----------|------|-------------|
| **alert-service** | 9085 | Java 17 / Spring Boot 3.2 | Clinical IT | Clinical alerts, pager integration, nurse call routing, escalation workflows. |

## HIPAA Compliance Zones

### PHI Data Zone (Restricted)

All services that store or process Protected Health Information operate within the PHI data zone:

- **Network:** Dedicated VPC subnet (`10.100.0.0/16`) with no internet egress
- **Encryption:** AES-256 at rest (AWS KMS), TLS 1.3 in transit
- **Access:** IAM roles with least-privilege, audit logging on all PHI access
- **Services in PHI zone:** patient-service, medication-service, pharmacy-service, billing-service

### Non-PHI Zone

Services that do not directly handle PHI:

- **Network:** Standard VPC subnet (`10.200.0.0/16`)
- **Services in non-PHI zone:** ehr-gateway (routes but does not persist PHI), scheduling-service (appointment slots, no clinical data), alert-service (alert metadata only)

### Data Flow Between Zones

```
[External] --TLS 1.3--> [ehr-gateway (non-PHI)] --mTLS--> [patient-service (PHI)]
                                                  --mTLS--> [billing-service (PHI)]
                                                  --mTLS--> [scheduling-service (non-PHI)]
```

All cross-zone traffic uses mutual TLS (mTLS) with service mesh (Istio).

## HL7 FHIR Standards

- **FHIR Version:** R4 (4.0.1)
- **Supported Resources:** Patient, Encounter, MedicationRequest, MedicationDispense, Appointment, Claim, Coverage, AllergyIntolerance, Condition
- **Capability Statement:** Available at `GET /fhir/r4/metadata` on ehr-gateway
- **Authentication:** OAuth 2.0 + SMART on FHIR for third-party app integration
- **Bulk Data:** FHIR Bulk Data Access (Flat FHIR) for analytics and reporting

## Infrastructure

### Kubernetes (AWS EKS)

- **Cluster:** `medflow-prod-eks` in `us-east-1`
- **Namespace:** `medflow-prod`
- **Node Groups:**
  - `phi-compute`: m6i.2xlarge (8 vCPU, 32GB) - for PHI zone services
  - `general-compute`: m6i.xlarge (4 vCPU, 16GB) - for non-PHI zone services
- **Service Mesh:** Istio 1.20 with mTLS strict mode
- **Ingress:** AWS ALB Ingress Controller with WAF

### Database (AWS RDS PostgreSQL 15)

- **Instance:** `medflow-prod-db` (db.r6g.2xlarge, Multi-AZ)
- **Encryption:** AES-256 via AWS KMS (key: `medflow-prod-rds-key`)
- **Schemas:** Per-service isolation (medflow_patients, medflow_medications, medflow_pharmacy, medflow_billing, medflow_scheduling)
- **Audit Logging:** pgaudit enabled for all PHI tables
- **Backup:** Automated daily snapshots, 35-day retention, cross-region replication to us-west-2

### Caching (Redis / ElastiCache)

- **Clusters:**
  - `redis-sessions`: Patient portal session cache (ehr-gateway)
  - `redis-scheduling`: Appointment slot cache and booking locks (scheduling-service)
  - `redis-pharmacy`: Formulary cache and dispensing queue (pharmacy-service)
- **Encryption:** In-transit and at-rest encryption enabled
- **No PHI in Redis:** Only session tokens, cache keys, and non-PHI operational data

### Message Broker (Amazon MSK / Kafka)

- **Cluster:** `medflow-prod-kafka`
- **Topics:** `patient-events`, `medication-orders`, `clinical-alerts`, `billing-claims`, `audit-log`
- **Encryption:** TLS in transit, KMS at rest
- **Retention:** 7 days for operational topics, 365 days for audit-log

## Service Dependencies

```
ehr-gateway --> patient-service (patient context)
ehr-gateway --> medication-service (drug lookups)
ehr-gateway --> scheduling-service (appointments)
ehr-gateway --> billing-service (coverage checks)
ehr-gateway --> alert-service (clinical alerts)

patient-service --> medication-service (admission medication review)
patient-service --> billing-service (insurance verification on admission)

medication-service --> pharmacy-service (dispensing requests)

billing-service --> [External: Clearinghouse API] (EDI 837/835)
billing-service --> [External: Payer APIs] (real-time eligibility)

pharmacy-service --> medication-service (formulary validation)
pharmacy-service --> [External: Pyxis/Omnicell API] (cabinet integration)

alert-service --> [External: PagerDuty] (on-call paging)
alert-service --> [External: Vocera] (nurse call)
```

## Monitoring and Observability

- **Metrics:** Prometheus + Grafana (dashboards per service + cross-service)
- **Logs:** ELK stack (Elasticsearch, Logstash, Kibana) with PHI field masking
- **Traces:** OpenTelemetry + Jaeger
- **Alerting:** Prometheus Alertmanager -> PagerDuty + Slack (#medflow-incidents)
- **Audit:** All PHI access logged to dedicated audit Kafka topic + S3 long-term storage

## Compliance and Security

- **HIPAA:** Business Associate Agreement (BAA) with AWS
- **SOC 2 Type II:** Annual audit
- **HITRUST CSF:** Certification in progress
- **Penetration Testing:** Quarterly external pen tests
- **Vulnerability Scanning:** Daily Trivy scans on all container images
- **Access Reviews:** Quarterly IAM access reviews for PHI zone
