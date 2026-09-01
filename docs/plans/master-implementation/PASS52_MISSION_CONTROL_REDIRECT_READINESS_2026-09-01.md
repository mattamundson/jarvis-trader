# PASS52 - Mission-Control Redirect Readiness

Date: 2026-09-01
Backlog item: P10-009

## Scope

Documented the readiness checklist for redirecting `/mission-control` into the canonical Command Center route.

## Finding

`/mission-control` is **not ready to redirect**. The canonical shell now has summaries and drilldown links, but the full operational panels still live on `/mission-control`, and `/command-center?view=operations` is not implemented.

## Checklist Added

Updated `COMMAND_CENTER_ROUTE_CONSOLIDATION_PLAN_2026-09-01.md` with explicit blockers for:

- Risk and kill-switch details.
- Trading split-brain reconciliation.
- Paper positions and performance.
- Pipeline and scheduler visibility.
- Validation gates and strategy ledger.
- Engine and broker diagnostics.
- Local fleet and loop state.

## Evidence

Read-only checks:

```powershell
rg -n "searchParams|useSearchParams|view=operations|view" dashboard/app/command-center dashboard/components/command-center dashboard/tests/e2e/command-center-route-consolidation.spec.ts
rg -n "RiskSafetyPanel|PositionsPerformancePanel|SignalsPipelinePanel|ValidationGatesPanel|EngineDataPanel|EnvironmentFleetPanel|TradingStatusReconciliation" dashboard/app/command-center dashboard/components dashboard/app/mission-control
rg -n "apiGet|useSWR|fetch\(|/api/engine|/api/fleet|/safety|/portfolio|/scheduler|/backtest|/system" dashboard/app/mission-control dashboard/components/TradingStatusReconciliation.tsx
```

Validation:

```powershell
node -e "JSON.parse(require('fs').readFileSync('docs/plans/master-implementation/IMPLEMENTATION_BACKLOG.json','utf8')); console.log('backlog json ok')"
```

Result: backlog JSON parsed successfully.
