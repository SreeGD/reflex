# ShopFast Deployment Procedures

**Last Updated:** 2026-01-25 | **Owner:** Platform Team | **Status:** Current

## Overview

All ShopFast services are deployed via ArgoCD syncing from GitHub repositories. Container images are built by GitHub Actions and pushed to Amazon ECR. Deployments follow a staged approach with mandatory monitoring windows.

## Pre-Deployment Checklist

Before initiating any production deployment:

- [ ] All CI checks passing (unit tests, integration tests, linting, SAST)
- [ ] PR approved by at least 2 reviewers (1 must be team lead)
- [ ] Docker image built and pushed to ECR with git SHA tag
- [ ] Deployment manifest updated with new image tag
- [ ] Feature flags configured in LaunchDarkly for any new features (default: OFF)
- [ ] Database migrations tested in staging (if applicable)
- [ ] Rollback plan documented in the PR description
- [ ] No active SEV-1 or SEV-2 incidents
- [ ] Deployment window: weekdays 09:00-16:00 UTC (no Friday deploys without VP approval)

## Deployment Strategies

### api-gateway: Canary Deployment
1. ArgoCD deploys canary pod (10% traffic via Nginx weight)
2. Monitor for 5 minutes: error rate, latency, 4xx/5xx ratio
3. Promote to 50% traffic
4. Monitor for 5 minutes
5. Promote to 100% (full rollout)
6. If any step shows degradation: automatic rollback via ArgoCD Rollouts

### Backend Services: Blue-Green Deployment
1. ArgoCD creates new ReplicaSet (green) alongside existing (blue)
2. Green pods must pass readiness probes (health check + dependency check)
3. Traffic switched from blue to green via Service selector update
4. Blue pods kept for 15 minutes (fast rollback window)
5. Blue pods terminated after monitoring window passes

## Rollback Procedure

### Automated Rollback
- ArgoCD Rollouts monitors error rate and latency during canary/blue-green
- If error rate > 5% or p99 latency > 3x baseline: automatic rollback triggers
- Notification sent to #shopfast-deploys Slack channel

### Manual Rollback
1. In ArgoCD UI: select the application, click "History", select previous version, click "Rollback"
2. Or via CLI: `argocd app rollback <app-name> <revision>`
3. Or emergency: `kubectl set image deployment/<service> <service>=<previous-ecr-image> -n shopfast-prod`
4. After rollback: verify metrics in Grafana, post in #shopfast-deploys

## Feature Flags (LaunchDarkly)

- All new features must be behind a LaunchDarkly feature flag
- Flag naming convention: `{service}.{feature-name}` (e.g., `payment-service.adyen-fallback`)
- Default state for new flags: OFF in production, ON in staging
- Progressive rollout: 5% -> 25% -> 50% -> 100% over minimum 48 hours
- Kill switch: any flag can be turned OFF instantly via LaunchDarkly dashboard

## Post-Deployment Monitoring Window

**Duration: 15 minutes after deployment completes**

During the monitoring window, the deploying engineer must:
1. Watch Grafana Service Detail dashboard for the deployed service
2. Check error logs in Kibana (filter by service and last 15 minutes)
3. Verify key business metrics (order rate, payment success rate) are stable
4. If deploying database migration: check DB Pool Utilization dashboard
5. Post "deployment healthy" or "rolling back" in #shopfast-deploys

## Shared Configuration Changes

Shared ConfigMaps (e.g., shopfast-common) require special handling:
1. Disable ArgoCD auto-sync for the shared config
2. Apply to a single service first (preferably the least critical)
3. Monitor for 10 minutes
4. Apply to remaining services in batches of 2
5. Re-enable auto-sync only after all services are confirmed healthy

This process was established after incident OPS-1178 where a bad shared config caused a cross-service outage.

## Database Migrations

- Migrations run automatically on service startup via Flyway
- Large migrations (>1M rows affected) must run as a background job, not blocking startup
- Schema changes must be backward-compatible (service N-1 must work with schema N)
- Index creation must use CONCURRENTLY to avoid table locks
- Post-migration: monitor DB Pool Utilization dashboard for 15 minutes (ref: OPS-1056)

## Emergency Deployments

For hotfixes during active incidents:
1. Skip the deployment window restriction
2. Still require 1 PR reviewer (can be any senior engineer)
3. Must have rollback plan
4. Notify #shopfast-incidents before deploying
5. Extended monitoring window: 30 minutes post-deploy
