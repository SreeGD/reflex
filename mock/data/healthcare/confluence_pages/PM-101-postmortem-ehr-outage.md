# PM-101: Postmortem - EHR Patient Service Outage (2026-01-20)

| Field         | Value                                      |
|---------------|--------------------------------------------|
| **Incident**  | EHR-1001                                   |
| **Severity**  | SEV-2                                      |
| **Duration**  | 49 minutes (03:02 - 03:51 UTC)             |
| **Services**  | patient-service, ehr-gateway (downstream)  |
| **Lead**      | Dr. Sarah Chen (Clinical IT On-Call)       |
| **Status**    | Complete                                   |

## Executive Summary

On January 20, 2026, at 03:02 UTC, the patient-service experienced a database connection pool exhaustion that rendered patient record access unavailable for 49 minutes. The Emergency Department was forced to operate on paper-based workarounds during the outage. Root cause was a connection leak in the `PatientRepository.findByMRN()` method introduced in v2.1.0, deployed the previous evening. No patient safety events were reported, but the incident exposed gaps in our post-deployment monitoring for overnight releases.

## Impact

### Clinical Impact
- **ER:** 12 patients triaged using paper-based identification during the outage. All records retroactively entered after resolution.
- **Inpatient:** Night shift nursing unable to view patient records for medication verification. 3 medication administrations delayed by 15-20 minutes (no adverse outcomes).
- **Medication Ordering:** Blocked for 49 minutes. 2 verbal orders placed with dual-nurse verification protocol.

### Technical Impact
- **patient-service:** 100% error rate on FHIR Patient endpoints for 49 minutes
- **ehr-gateway:** 65% error rate (requests routing to patient-service failed, other routes functional)
- **medication-service:** Unable to validate patient references, drug interaction checks degraded
- **Requests Failed:** Approximately 3,200 patient record requests returned HTTP 500

### Business Impact
- No HIPAA breach (PHI was inaccessible, not exposed)
- 3 patient complaints about registration delays
- Estimated cost: 2.5 hours of clinical staff time on paper workarounds

## Timeline

| Time (UTC) | Event |
|------------|-------|
| 22:00 (prev day) | patient-service v2.1.0 deployed via ArgoCD. Deployment successful, health checks pass. |
| 22:15 | Deployment monitoring window ends. On-call confirms green dashboards. |
| 01:30 | Connection pool utilization begins slow climb (invisible at this point, baseline noise). |
| 02:45 | Pool utilization crosses 80% on 2 of 3 pods. No alert configured at 80%. |
| 03:00 | Pool reaches 19/20 on all pods. Wait queue forming. |
| 03:02 | **Alert fires:** `EHRConnectionPoolExhausted` on patient-service. PagerDuty pages Dr. Sarah Chen. |
| 03:05 | Sarah acknowledges. Opens laptop, connects to VPN. |
| 03:08 | Confirms pool at 20/20 on Grafana. Error rate 50% and climbing. |
| 03:10 | ER charge nurse calls Clinical IT hotline: "Patient lookup is down." |
| 03:12 | Sarah activates clinical downtime procedures for ER. Paper workarounds begin. |
| 03:18 | Searches Confluence for runbook. Finds RB-101. |
| 03:22 | Checks pg_stat_activity: 60 connections, 18 in "idle in transaction" state. |
| 03:25 | Reviews deployment history. Finds v2.1.0 deployed at 22:00. Checks diff. |
| 03:30 | Identifies `PatientRepository.findByMRN()` refactor. New code path opens connection but does not close on null result (patient not found). |
| 03:32 | Checks Jira: ER has high volume of "patient not found" lookups during overnight registration (new patients). Each lookup leaks a connection. |
| 03:38 | Terminates idle-in-transaction connections via psql. |
| 03:42 | Runs `kubectl rollout restart deployment/patient-service -n medflow-prod`. |
| 03:46 | New pods healthy. Pool utilization at 8/20 (normal). Error rate dropping. |
| 03:48 | Verifies FHIR Patient endpoint: `GET /fhir/r4/Patient?identifier=MRN123` returns 200. |
| 03:51 | ER confirms electronic patient lookup restored. Paper records queued for entry. Incident resolved. |
| 04:15 | Sarah creates EHR-1001 ticket with full timeline and root cause. |
| 04:30 | Notifies ER Medical Director and Night Supervisor of resolution. |

## Root Cause Analysis

### Direct Cause

Connection leak in `PatientRepository.findByMRN()`. The method was refactored in v2.1.0 to add FHIR search parameter support. The new code path:

```java
// BUGGY CODE (v2.1.0)
public Patient findByMRN(String mrn) {
    Connection conn = dataSource.getConnection();
    PreparedStatement ps = conn.prepareStatement("SELECT * FROM patients WHERE mrn = ?");
    ps.setString(1, mrn);
    ResultSet rs = ps.executeQuery();
    if (rs.next()) {
        Patient patient = mapRow(rs);
        conn.close();  // Only closes on successful lookup
        return patient;
    }
    return null;  // Connection never closed on null result!
}
```

When a patient MRN is not found (common during ER registration of new patients), the connection is acquired but never returned to the pool.

### Contributing Factors

1. **No 80% pool utilization alert:** Alert only fired at 95%, giving minimal lead time.
2. **Overnight deployment with short monitoring window:** v2.1.0 deployed at 22:00 with only 15 minutes of post-deploy monitoring. The leak manifests slowly (hours to exhaust pool under normal load).
3. **Integration tests do not test null-result paths with real connections:** Unit tests mock the database layer. Integration tests only test successful patient lookups.
4. **No connection leak detection configured:** HikariCP `leak-detection-threshold` was not set.

### 5 Whys

1. **Why were patient records unavailable?** DB connection pool exhausted on patient-service.
2. **Why was the pool exhausted?** Connections were leaking on "patient not found" lookups.
3. **Why were connections leaking?** `findByMRN()` refactor in v2.1.0 did not close connections on the null result path.
4. **Why wasn't this caught before production?** Integration tests only cover successful lookup paths; no test for MRN-not-found scenario.
5. **Why no safety net in production?** No connection leak detection and no early warning alert at 80% utilization.

## Action Items

| ID | Action | Owner | Priority | Status |
|----|--------|-------|----------|--------|
| 1 | Fix connection leak in `PatientRepository.findByMRN()` using try-with-resources | Patient Records Team | P0 | Complete (PR #2104) |
| 2 | Add connection pool alert at 80% threshold | Platform Engineering | P1 | Complete |
| 3 | Configure HikariCP `leak-detection-threshold: 60000` | Patient Records Team | P1 | Complete |
| 4 | Add integration tests for null-result paths with real DB connections | Patient Records Team | P1 | In Progress (EHR-1003) |
| 5 | Extend post-deployment monitoring window to 2 hours for overnight deploys | Platform Engineering | P2 | Complete |
| 6 | Deploy pgbouncer for connection multiplexing | Database Engineering | P2 | Planned (INFRA-892) |
| 7 | Add static analysis rule to detect unclosed connections (SpotBugs) | Platform Engineering | P2 | In Progress |
| 8 | Review all repository methods for similar connection handling patterns | Patient Records Team | P2 | Planned |

## Lessons Learned

### What went well
- Clinical downtime procedures activated quickly (within 10 minutes of alert)
- ER staff smoothly transitioned to paper workarounds
- Root cause identified within 28 minutes
- No patient safety events despite 49-minute outage
- Runbook RB-101 was accurate and helpful

### What could be improved
- 49 minutes MTTR is too long for a Tier 1 clinical service
- Alert at 95% gives almost no lead time; should alert at 80%
- Overnight deployments need longer monitoring windows
- Connection leak detection should be a default configuration
- Need automated connection pool remediation (restart on sustained saturation)

### What was lucky
- Outage occurred at 03:00 when patient volume was low
- If this had happened during morning admission rush (07:00-09:00), impact would have been much worse
- No controlled substance administrations were affected

## References

- EHR-1001: Incident ticket
- EHR-1003: Follow-up - integration test coverage for null-result paths
- RB-101: EHR Connection Pool Exhaustion Runbook
- ARCH-102: Database Architecture (connection pool budgets)
