# ARCH-102: MedFlow Database Architecture

| Field         | Value                          |
|---------------|--------------------------------|
| **Status**    | Current                        |
| **Version**   | 2.1                            |
| **Last Updated** | 2026-02-20                  |
| **Owner**     | Database Engineering           |
| **Classification** | Internal - Confidential   |

## Overview

MedFlow uses a shared PostgreSQL 15 cluster (AWS RDS Multi-AZ) with per-service schema isolation. All schemas containing Protected Health Information (PHI) use column-level encryption, row-level security, and comprehensive audit logging via pgaudit.

## Database Instance

| Property            | Value                                               |
|---------------------|-----------------------------------------------------|
| **Engine**          | PostgreSQL 15.4                                     |
| **Instance**        | db.r6g.2xlarge (8 vCPU, 64GB RAM)                 |
| **Storage**         | 2TB gp3, 12,000 IOPS, 500 MB/s throughput         |
| **Multi-AZ**        | Enabled (synchronous replication)                  |
| **Encryption**      | AES-256 via AWS KMS (`medflow-prod-rds-key`)       |
| **max_connections**  | 400                                                |
| **SSL Mode**        | verify-full (mandatory)                            |

## Per-Service Schemas

### medflow_patients (patient-service)

Primary store for patient demographics, encounters, and medical records.

**Key Tables:**
- `patients` - Patient demographics (MRN, name, DOB, SSN-encrypted, address)
- `encounters` - Admissions, discharges, transfers (ADT)
- `patient_allergies` - Allergy and adverse reaction records
- `patient_conditions` - Active problem list / diagnoses (ICD-10)
- `clinical_documents` - CDA/FHIR Document References

**PHI Columns (column-level encryption):**
- `patients.ssn` - AES-256-GCM via `pgcrypto`
- `patients.date_of_birth` - AES-256-GCM via `pgcrypto`
- `patients.address_line_1`, `patients.address_line_2` - AES-256-GCM

**Connection Pool:** 20 connections per pod, 3 pods = 60 total

### medflow_medications (medication-service)

Drug catalog, formulary, and interaction data.

**Key Tables:**
- `drugs` - NDC drug database (180K+ entries, indexed by `ndc_code`, `rxnorm_code`)
- `formulary` - Hospital formulary with tier assignments
- `drug_interactions` - Interaction pairs with severity levels
- `medication_orders` - Prescriber orders (linked to patient via FHIR reference)

**PHI Columns:**
- `medication_orders.patient_reference` - FHIR Patient reference (encrypted)
- `medication_orders.prescriber_notes` - Free-text clinical notes (encrypted)

**Connection Pool:** 15 connections per pod, 2 pods = 30 total

### medflow_pharmacy (pharmacy-service)

Dispensing records and inventory management.

**Key Tables:**
- `dispense_records` - Medication dispensing events
- `pharmacy_inventory` - Drug stock levels by location
- `cabinet_sync_log` - Pyxis/Omnicell synchronization audit
- `controlled_substance_log` - DEA Schedule II-V tracking

**PHI Columns:**
- `dispense_records.patient_mrn` - Medical record number (encrypted)
- `controlled_substance_log.patient_id` - Patient identifier (encrypted)
- `controlled_substance_log.witness_id` - Witness for controlled substances

**Connection Pool:** 15 connections per pod, 2 pods = 30 total

### medflow_billing (billing-service)

Claims, insurance, and revenue cycle data.

**Key Tables:**
- `claims` - Insurance claims (837 Professional/Institutional)
- `remittance` - Payment remittance (835)
- `coverage` - Patient insurance coverage records
- `pre_authorizations` - Prior authorization requests and approvals
- `charge_master` - Hospital charge description master (CDM)

**PHI Columns:**
- `claims.patient_id` - Patient identifier (encrypted)
- `claims.diagnosis_codes` - ICD-10 codes (encrypted, as they constitute PHI)
- `coverage.subscriber_id` - Insurance subscriber ID (encrypted)
- `coverage.group_number` - Insurance group (encrypted)

**Connection Pool:** 15 connections per pod, 3 pods = 45 total

### medflow_scheduling (scheduling-service)

Appointment and bed management data.

**Key Tables:**
- `appointments` - Scheduled appointments
- `appointment_slots` - Available time slots by provider/department
- `beds` - Bed inventory and current occupancy
- `bed_assignments` - Patient-to-bed assignments

**PHI Columns:**
- `appointments.patient_id` - Patient identifier (encrypted)
- `bed_assignments.patient_id` - Patient identifier (encrypted)

**Connection Pool:** 10 connections per pod, 2 pods = 20 total

## Audit Logging

All PHI access is logged via PostgreSQL `pgaudit` extension:

```sql
-- pgaudit configuration
ALTER SYSTEM SET pgaudit.log = 'read, write, ddl';
ALTER SYSTEM SET pgaudit.log_catalog = off;
ALTER SYSTEM SET pgaudit.log_relation = on;
ALTER SYSTEM SET pgaudit.log_parameter = on;
```

Audit logs are:
1. Streamed to CloudWatch Logs in real-time
2. Forwarded to the `audit-log` Kafka topic
3. Archived to S3 (`s3://medflow-audit-logs/`) with 7-year retention (HIPAA requirement)

## Row-Level Security

PHI tables implement row-level security (RLS) to ensure service accounts can only access data within their scope:

```sql
-- Example: patient-service can only read its own patients
ALTER TABLE patients ENABLE ROW LEVEL SECURITY;
CREATE POLICY patient_service_read ON patients
  FOR SELECT TO patient_service_user
  USING (true);  -- patient-service has full read access

-- billing-service can only access patient coverage data
CREATE POLICY billing_service_read ON patients
  FOR SELECT TO billing_service_user
  USING (false);  -- billing-service cannot directly read patients table
```

## Backup and Recovery

| Property              | Value                                    |
|-----------------------|------------------------------------------|
| **Automated Backup**  | Daily at 02:00 UTC, 35-day retention    |
| **Point-in-Time**     | 5-minute RPO via WAL archiving          |
| **Cross-Region**      | Async replication to us-west-2          |
| **Backup Encryption** | Same KMS key as primary                 |
| **Recovery Testing**  | Monthly restore test to staging         |

## Connection Management

Total connection budget across all services:

| Schema               | Per Pod | Pods | Total | Service Account          |
|----------------------|---------|------|-------|--------------------------|
| medflow_patients     | 20      | 3    | 60    | `patient_svc_user`       |
| medflow_medications  | 15      | 2    | 30    | `medication_svc_user`    |
| medflow_pharmacy     | 15      | 2    | 30    | `pharmacy_svc_user`      |
| medflow_billing      | 15      | 3    | 45    | `billing_svc_user`       |
| medflow_scheduling   | 10      | 2    | 20    | `scheduling_svc_user`    |
| **Reserved**         | -       | -    | 15    | DBA, monitoring, migration|
| **Total**            | -       | -    | **200** | (max_connections = 400) |

**Note:** Current utilization is at 50% of max_connections. PgBouncer deployment is planned (INFRA-892) to provide connection multiplexing and allow service scaling without hitting PostgreSQL limits.

## Performance Monitoring

- **pg_stat_statements:** Enabled for query performance tracking
- **pg_stat_activity:** Monitored via Prometheus postgres_exporter
- **Alerting Thresholds:**
  - Connection utilization >80%: Warning
  - Connection utilization >95%: Critical (pages on-call)
  - Slow queries >5s: Warning
  - Replication lag >10s: Critical
