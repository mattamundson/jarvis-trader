# PASS75 - Daily Brief Route Static Audit

## Scope

Completed P14-006 through P14-009 by updating route-consolidation documentation, auditing `/today` references, and recording the current browser-evidence blocker.

## Changes

- Updated `COMMAND_CENTER_ROUTE_CONSOLIDATION_PLAN_2026-09-01.md` so `/today` is documented as demoted to the Daily Brief drilldown.
- Marked `/today` first-screen facts as migrated into Command Center.
- Preserved `/today` as the detailed chart and market context strip surface.

## Audit

```powershell
rg -n "Today at a Glance|/today|Daily Brief|today drilldown|command-center-daily-brief-summary" dashboard/app dashboard/components dashboard/tests docs/plans/master-implementation -g "*.ts" -g "*.tsx" -g "*.md" -g "*.json"
```

Intentional residual references remain in:

- `dashboard/app/today/page.tsx`, the detailed Daily Brief route.
- Sidebar and Command Center drilldown links labeled `Daily Brief`.
- Route-consolidation E2E and route inventory, where `/today` remains reachable as a drilldown.
- Historical PASS/backlog records.

## Browser Evidence Blocker

[RISK] Focused browser rerun is intentionally gated behind historical artifact cleanup approval because C: free space is below 1 GB and `C:\Users\mattm\Archive\2026\jarvis-temp-build-artifacts` is 19.46 GB.

The P13 runner fix prevents new successful isolated E2E runs from permanently growing the archive by default, but the historical artifact root still needs explicit approval before cleanup.
