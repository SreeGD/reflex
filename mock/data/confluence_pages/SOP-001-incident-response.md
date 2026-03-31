# ShopFast Incident Response Procedure

**Last Updated:** 2026-02-05 | **Owner:** Platform Team | **Status:** Current

## Severity Definitions

| Severity | Definition | Examples | Response Time |
|----------|-----------|----------|---------------|
| SEV-1 | Revenue-impacting outage. Core customer-facing functionality broken. | Checkout down, site unreachable, data breach | 5 min acknowledge, 15 min war room |
| SEV-2 | Degraded experience. Feature partially broken or significantly slow. | High error rates, elevated latency, one service down | 15 min acknowledge, 30 min investigation |
| SEV-3 | Minor impact. Non-critical feature affected. Workaround available. | Email delays, search slow, admin panel error | 30 min acknowledge, 4h investigation |
| SEV-4 | Cosmetic or informational. No user impact. | UI glitch, log noise, non-critical alert | Next business day |

## Response Time SLAs

| Severity | Acknowledge | First Update | Resolution Target | Status Page Update |
|----------|------------|--------------|-------------------|--------------------|
| SEV-1 | 5 min | 15 min | 1 hour | Immediately |
| SEV-2 | 15 min | 30 min | 4 hours | Within 30 min |
| SEV-3 | 30 min | 2 hours | 24 hours | Not required |
| SEV-4 | Next BD | Next BD | 1 week | Not required |

## Incident Lifecycle

### 1. Detection
- PagerDuty alert fires (automated) or manual report via Slack #shopfast-incidents
- On-call engineer receives page via PagerDuty (phone call for SEV-1, push notification for SEV-2+)

### 2. Triage
- On-call acknowledges in PagerDuty within SLA
- Assess severity based on definitions above
- For SEV-1/SEV-2: Create incident channel in Slack (#inc-YYYYMMDD-brief-description)

### 3. Investigation
- Open Grafana Platform Overview dashboard to assess scope
- Check recent deployments in ArgoCD (last 2 hours)
- Review error logs in Kibana for affected service(s)
- Correlate with known issues (check #shopfast-incidents history)

### 4. Mitigation
- Apply the fastest available fix (rollback, config change, restart, scale)
- Mitigation does NOT need to be the root cause fix — stop the bleeding first
- Document all actions taken in the incident Slack channel with timestamps

### 5. Resolution
- Confirm metrics return to baseline for at least 5 minutes
- Update status page (SEV-1/SEV-2)
- Post summary in incident channel
- Resolve PagerDuty incident

### 6. Follow-up
- SEV-1: Postmortem required within 48 hours (see PM-001 template)
- SEV-2: Postmortem required within 1 week
- SEV-3/SEV-4: Action items tracked in JIRA, no formal postmortem required

## Communication Protocol

### War Room (SEV-1 only)
- Zoom bridge: https://shopfast.zoom.us/j/incident-warroom (always-on link)
- Incident Commander: on-call engineer until a senior engineer joins
- Scribe: second person in the room documents timeline in Slack channel
- Stakeholder updates every 15 minutes in #shopfast-incidents

### Status Page
- URL: https://status.shopfast.com (Statuspage.io)
- On-call has credentials in 1Password vault "ShopFast Operations"
- SEV-1: Update within 5 minutes of confirmed impact
- SEV-2: Update within 30 minutes

### Slack Channels
- #shopfast-incidents — all incident discussions, automated PagerDuty posts
- #shopfast-alerts — Prometheus/Alertmanager notifications
- #inc-{date}-{topic} — per-incident channel for SEV-1/SEV-2

## Escalation Matrix

| Escalation | Contact | When |
|-----------|---------|------|
| Database issues | DBA team (dba-oncall@shopfast.com) | Pool exhaustion, replication lag, slow queries |
| Infrastructure/AWS | Platform team (platform-oncall@shopfast.com) | EKS, networking, IAM, RDS instance issues |
| Payment failures | Payments team lead (dave@shopfast.com) | Payment provider outages, transaction failures |
| Security incident | Security team (security@shopfast.com) | Any suspected breach, unauthorized access |
| Executive notification | VP Engineering (vp-eng@shopfast.com) | SEV-1 lasting > 30 min, data breach |

## Postmortem Requirements

All SEV-1 and SEV-2 incidents require a blameless postmortem using template PM-001. Postmortems must include: timeline, root cause analysis (5 Whys), contributing factors, and action items with owners and due dates. Postmortems are reviewed in the weekly operations meeting (Thursday 10:00 UTC).
