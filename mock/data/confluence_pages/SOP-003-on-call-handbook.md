# ShopFast On-Call Handbook

**Last Updated:** 2026-02-10 | **Owner:** Platform Team | **Status:** Current

## On-Call Responsibilities

The on-call engineer is the first responder for all production alerts during their rotation. Rotations are weekly (Monday 09:00 UTC to Monday 09:00 UTC). Each team maintains its own rotation in PagerDuty.

### Primary Responsibilities
- Acknowledge PagerDuty alerts within SLA (see SOP-001)
- Triage and assess severity of incidents
- Perform initial investigation and mitigation
- Escalate to specialists when needed (database team, payment team, etc.)
- Document actions taken in incident Slack channel
- Hand off unresolved issues at end of rotation with written context

### What On-Call is NOT
- On-call is not expected to fix root causes during an incident — mitigate first
- On-call does not handle feature requests or non-urgent bugs
- On-call is not expected to be awake 24/7 — PagerDuty will page for real alerts

## Production Access

### VPN Setup
1. Install Cisco AnyConnect (download from https://internal.shopfast.com/vpn-client)
2. Connect to vpn.shopfast.com using Okta SSO credentials
3. VPN grants access to internal dashboards and kubectl API server

### kubectl Access
1. Ensure AWS CLI configured with shopfast-prod profile
2. Update kubeconfig: `aws eks update-kubeconfig --name shopfast-prod --region us-east-1`
3. Verify access: `kubectl get pods -n shopfast-prod`
4. Your IAM role grants read access by default; write access requires assuming the `shopfast-oncall-role`
5. Assume oncall role: `aws sts assume-role --role-arn arn:aws:iam::123456789:role/shopfast-oncall-role`

### Key Tools Access
| Tool | URL | Auth |
|------|-----|------|
| Grafana | https://grafana.internal.shopfast.com | Okta SSO |
| Kibana | https://kibana.internal.shopfast.com | Okta SSO |
| ArgoCD | https://argocd.internal.shopfast.com | Okta SSO |
| PagerDuty | https://shopfast.pagerduty.com | PagerDuty account |
| LaunchDarkly | https://app.launchdarkly.com | Okta SSO |
| RabbitMQ Management | https://rabbitmq.internal.shopfast.com | Credentials in 1Password |
| Jaeger | https://jaeger.internal.shopfast.com | Okta SSO |

## Common First-Response Actions

### Service returning 5xx errors
1. Check Grafana Service Detail dashboard for the affected service
2. Look at recent deployments in ArgoCD (last 2 hours)
3. Check pod status: `kubectl get pods -n shopfast-prod -l app={service}`
4. Check logs: `kubectl logs -n shopfast-prod -l app={service} --tail=100`
5. If recent deploy: consider rollback (see SOP-002)

### Pod CrashLoopBackOff
1. Check pod events: `kubectl describe pod {pod-name} -n shopfast-prod`
2. Look for OOMKilled in last termination reason
3. Check previous container logs: `kubectl logs {pod-name} -n shopfast-prod --previous`
4. If OOMKilled: check memory limits vs JVM heap settings (ref: OPS-1299)
5. If application error: check recent config changes and deployments

### Database Connection Issues
1. Check DB Pool Utilization dashboard in Grafana
2. Check RDS metrics in AWS Console (connections, CPU, memory)
3. If pool exhaustion: identify the leaking service from per-service pool metrics
4. Emergency: restart affected service pods to reclaim connections
5. Escalate to DBA team if RDS-level issue (dba-oncall@shopfast.com)

### Redis Issues
1. Check Redis Health dashboard in Grafana
2. ElastiCache console: memory usage, evictions, connection count
3. If OOM: check key patterns (`redis-cli --scan --pattern 'prefix:*' | head`)
4. If connection pool exhaustion: check client-side Jedis pool config
5. Reference: OPS-1312 (pool config), OPS-1278 (memory/TTL)

### Payment Failures
1. Check Stripe status page (https://status.stripe.com)
2. Check payment-service error logs in Kibana
3. If external provider issue: check circuit breaker status in actuator endpoint
4. Escalate to Payments team lead (dave@shopfast.com)
5. If circuit breaker not deployed: reduce client timeout as emergency measure (ref: OPS-1301)

## Escalation Decision Guide

**Page the Database Team when:**
- PostgreSQL connection count > 180 (near max_connections limit)
- Replication lag > 30 seconds
- RDS CPU > 90% sustained
- Any data integrity concern

**Page the Platform Team when:**
- EKS node issues (NotReady, resource pressure)
- Networking problems (DNS, ingress, service discovery)
- ArgoCD sync failures
- AWS service issues

**Page the Security Team when:**
- Unusual access patterns or potential breach indicators
- Certificate issues
- Unexpected IAM permission errors

## Handoff Protocol

At end of rotation:
1. Post a summary in #shopfast-oncall: active issues, pending action items, things to watch
2. Brief the incoming on-call engineer (15-minute sync or async written handoff)
3. Transfer any open PagerDuty incidents
4. Update the on-call log in Confluence (link: On-Call Weekly Log)
