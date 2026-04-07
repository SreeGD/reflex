# SOP-101: Clinical Incident Response

| Field         | Value                          |
|---------------|--------------------------------|
| **Status**    | Approved                       |
| **Version**   | 4.0                            |
| **Last Updated** | 2026-02-15                  |
| **Owner**     | Clinical IT / Compliance       |
| **Approved By** | Chief Medical Information Officer (CMIO) |
| **Review Cycle** | Quarterly                   |

## Purpose

This Standard Operating Procedure defines the incident response process for clinical IT systems at MedFlow Health. It addresses patient safety protocols, HIPAA breach notification requirements, and severity classification specific to healthcare IT incidents.

## Scope

Applies to all incidents affecting:
- Electronic Health Record (EHR) systems
- Clinical Decision Support (CDS) systems
- Medication management and pharmacy systems
- Patient scheduling and bed management
- Billing and revenue cycle systems
- Clinical alerting and communication systems

## Severity Classification

### SEV-1: Critical - Patient Safety Risk

**Definition:** Incident directly impacts patient safety or clinical decision-making.

**Examples:**
- EHR completely unavailable (patient records inaccessible)
- Drug interaction checking system down
- Clinical alerts not being delivered
- Medication dispensing system failure during active orders

**Response:**
- Automatic page to: Clinical IT On-Call + Chief Medical Officer (CMO) + CMIO
- Activate clinical downtime procedures within 5 minutes
- War room opened in #medflow-sev1 Slack channel
- Status updates every 10 minutes to clinical leadership
- MTTR target: <30 minutes

### SEV-2: High - Clinical Workflow Disrupted

**Definition:** Significant clinical workflow disruption but patient safety workarounds exist.

**Examples:**
- Patient record lookups slow (>5s) but functional
- Billing/insurance verification down (no patient safety impact)
- Scheduling system unavailable
- Single service degradation with working fallbacks

**Response:**
- Page Clinical IT On-Call
- Notify department heads for affected workflows
- Status updates every 30 minutes
- MTTR target: <60 minutes

### SEV-3: Medium - Minor Disruption

**Definition:** Localized issue with minimal clinical impact.

**Examples:**
- Report generation delayed
- Non-critical dashboard unavailable
- Single pod failure (auto-recovered by Kubernetes)
- Performance degradation within acceptable SLA

**Response:**
- Slack notification to #medflow-incidents
- Investigated during business hours (unless escalating)
- MTTR target: <4 hours

### SEV-4: Low - Informational

**Definition:** No user-facing impact. Proactive alert or maintenance.

**Examples:**
- Disk usage warning (not critical)
- Certificate expiry >7 days out
- Non-production environment issue

**Response:**
- Ticket created, prioritized in next sprint
- No immediate action required

## Patient Safety Protocols

### Clinical Downtime Procedures

When EHR systems are unavailable, clinical staff must follow downtime procedures:

1. **Activate Downtime:** Clinical IT lead announces downtime via overhead page and Vocera broadcast
2. **Paper-Based Workarounds:**
   - Patient identification: Use paper wristbands with MRN, name, DOB
   - Medication orders: Verbal orders with dual-nurse verification (read-back protocol)
   - Documentation: Paper-based nursing notes and physician orders
   - Lab orders: Phone orders to laboratory with verbal confirmation
3. **Medication Safety:**
   - Pharmacy performs manual drug interaction checks using Lexicomp reference
   - Controlled substance dispensing requires pharmacist + witness signature on paper log
   - High-alert medications require independent double-check (no system support)
4. **Recovery:** After system restored, all paper records must be entered into EHR within 4 hours

### Patient Notification

If an incident results in delayed care delivery:
- Document in patient safety event reporting system (RL6)
- Notify Risk Management within 24 hours
- If harm occurred, activate Serious Safety Event protocol

## HIPAA Breach Notification

### Assessment

Any incident involving PHI requires a HIPAA breach risk assessment:

1. **Determine if PHI was involved:** Did the incident expose, alter, or destroy PHI?
2. **Assess the four factors:**
   - Nature and extent of PHI involved
   - Who accessed the PHI (unauthorized party identity)
   - Whether PHI was actually acquired or viewed
   - Extent of risk mitigation
3. **Document the assessment** in the incident ticket (label: `hipaa-assessment`)

### Notification Requirements

If a breach is confirmed:

| Affected Individuals | Notification Deadline | Method |
|---------------------|----------------------|--------|
| <500                | Within 60 days       | Written notification to each individual |
| >=500               | Within 60 days       | Written notification + media notification + HHS OCR |
| Any                 | Within 60 days       | Report to HHS Office for Civil Rights (OCR) |

### HIPAA Breach Response Team

| Role                    | Contact                              |
|-------------------------|--------------------------------------|
| HIPAA Privacy Officer   | privacy@medflow.com                  |
| HIPAA Security Officer  | security@medflow.com                 |
| Legal Counsel           | legal@medflow.com                    |
| Chief Compliance Officer| compliance@medflow.com               |

## Incident Response Workflow

### 1. Detection (0-5 minutes)

- Automated alert fires via Prometheus Alertmanager
- On-call engineer receives PagerDuty notification
- Acknowledge alert within 5 minutes (auto-escalate if unacknowledged)

### 2. Triage (5-15 minutes)

- Assess severity using classification above
- Determine if patient safety is impacted
- Activate clinical downtime procedures if SEV-1
- Open incident channel in Slack

### 3. Investigation (15-45 minutes)

- Follow relevant runbook (RB-101 through RB-105)
- Gather metrics, logs, and traces
- Identify root cause or sufficient information to remediate

### 4. Remediation (varies by severity)

- Execute remediation action (restart, scale, rollback)
- Verify service restored
- Verify clinical workflows functional
- Stand down clinical downtime procedures

### 5. Post-Incident (within 48 hours)

- Complete post-incident review (PIR)
- Document timeline, root cause, patient impact
- Create follow-up action items
- Update runbooks if needed
- File HIPAA breach assessment if PHI involved
- Report to Patient Safety Committee if clinical impact

## Communication Templates

### Internal Notification (Slack)

```
:rotating_light: [SEV-X] [Service Name] - [Brief Description]
Impact: [Clinical workflow affected]
Patient Safety: [Yes/No - if yes, downtime procedures activated]
Current Status: [Investigating/Mitigating/Resolved]
Lead: [On-call engineer name]
Channel: #medflow-incidents
```

### Clinical Staff Notification (Vocera/Overhead)

```
Attention clinical staff: [Service name] is currently experiencing [brief issue].
[Workaround instructions].
IT is actively working to resolve. Updates will follow every [X] minutes.
```

## Audit and Compliance

- All incident actions logged in PagerDuty + Jira
- PHI access during incident response is logged via pgaudit
- Incident postmortems archived for 7 years (HIPAA retention requirement)
- Quarterly incident metrics reported to Compliance Committee
- Annual incident response drill (tabletop exercise)
