# ShopFast Postmortem Template

**Last Updated:** 2026-01-10 | **Owner:** Platform Team | **Status:** Current

## When to Use This Template

- Required for all SEV-1 incidents (within 48 hours)
- Required for all SEV-2 incidents (within 1 week)
- Optional but encouraged for SEV-3 incidents with interesting learnings
- Postmortems are blameless — focus on systems and processes, not individuals

---

# Postmortem: [Incident Title]

**Date:** YYYY-MM-DD
**Severity:** SEV-X
**Incident Commander:** [name]
**Author:** [name]
**JIRA Ticket:** OPS-XXXX
**Duration:** X hours Y minutes (from detection to resolution)

## Summary

[2-3 sentence summary. What happened, what was the customer impact, how was it resolved.]

## Impact

- **Duration:** HH:MM to HH:MM UTC (X minutes total)
- **Users Affected:** [number or percentage]
- **Revenue Impact:** [estimated, if applicable]
- **Orders Affected:** [count of failed/delayed orders]
- **SLA Impact:** [any SLA breaches]
- **Data Loss:** [yes/no, details if yes]

## Detection

- **How detected:** [PagerDuty alert / customer report / monitoring / manual observation]
- **Alert that fired:** [alert name and condition]
- **Time to detect:** [minutes from incident start to first alert]
- **Gap:** [any detection gaps — e.g., alert should have fired earlier]

## Timeline

All times in UTC.

| Time | Event |
|------|-------|
| HH:MM | [First sign of issue — may predate detection] |
| HH:MM | [Alert fires / incident detected] |
| HH:MM | [On-call acknowledges] |
| HH:MM | [Investigation begins — what was checked first] |
| HH:MM | [Root cause identified] |
| HH:MM | [Mitigation applied] |
| HH:MM | [Service restored] |
| HH:MM | [Incident resolved — metrics confirmed stable] |

## Root Cause Analysis (5 Whys)

1. **Why** did [the user-visible symptom] happen?
   Because [direct technical cause].

2. **Why** did [direct technical cause] happen?
   Because [deeper cause].

3. **Why** did [deeper cause] happen?
   Because [process/design cause].

4. **Why** did [process/design cause] exist?
   Because [organizational/historical reason].

5. **Why** was [organizational/historical reason] not addressed?
   Because [systemic gap].

## Contributing Factors

List factors that did not directly cause the incident but made it worse or more likely:

- [Factor 1 — e.g., missing monitoring]
- [Factor 2 — e.g., known tech debt]
- [Factor 3 — e.g., insufficient testing]
- [Factor 4 — e.g., documentation gap]

## What Went Well

- [Things that worked during the response]
- [Good decisions that reduced impact]
- [Tools or processes that helped]

## What Went Poorly

- [Things that slowed response]
- [Gaps in tooling or knowledge]
- [Communication breakdowns]

## Action Items

| ID | Action | Owner | Priority | Due Date | Status |
|----|--------|-------|----------|----------|--------|
| 1 | [Specific, actionable item] | [person] | P1/P2/P3 | YYYY-MM-DD | Open |
| 2 | [Specific, actionable item] | [person] | P1/P2/P3 | YYYY-MM-DD | Open |
| 3 | [Specific, actionable item] | [person] | P1/P2/P3 | YYYY-MM-DD | Open |

### Action Item Guidelines
- Each item must have a single owner (not a team)
- Each item must have a due date
- P1 items must be completed before the next on-call rotation
- P2 items within 2 weeks
- P3 items within 1 quarter
- Track action items in JIRA with label "postmortem-action"

## Lessons Learned

[1-3 paragraphs summarizing what the team learned. Focus on systemic improvements, not individual mistakes. Consider: What would have prevented this? What would have reduced MTTR? What knowledge gap existed?]

## Review

- [ ] Reviewed by incident commander
- [ ] Reviewed by service team lead
- [ ] Reviewed by platform team
- [ ] Presented in weekly operations meeting
- [ ] Action items created in JIRA
- [ ] Runbook updated if applicable
