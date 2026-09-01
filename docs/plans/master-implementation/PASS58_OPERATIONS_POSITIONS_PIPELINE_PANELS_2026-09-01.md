# PASS58 - Operations Positions And Pipeline Panels

Date: 2026-09-01
Backlog item: P11-004

## Scope

Mounted the mission-control positions/performance and signals/pipeline panels inside `/command-center?view=operations`.

## Changes

- Added `PositionsPerformancePanel` to the Command Center operations view.
- Added `SignalsPipelinePanel` to the Command Center operations view.
- Kept both panels behind `WidgetErrorBoundary` wrappers.
- Hardened `PositionsPerformancePanel` to accept either a bare positions array or a `{ positions: [...] }` wrapper for `/portfolio/paper/positions/unrealized`.

## Validation

```powershell
pnpm run typecheck
pnpm run typecheck:tests
pnpm run guards
pnpm run test:e2e:isolated -- tests/e2e/command-center-route-consolidation.spec.ts --project=golden-path --workers=1
```

Results:

- Typecheck passed.
- Test typecheck passed.
- Dashboard guards passed.
- Isolated route-consolidation E2E passed: 6 tests passed on `golden-path`.

## Notes

The first E2E run exposed a real robustness bug: the positions panel assumed `/portfolio/paper/positions/unrealized` always returned a bare array. The panel now preserves the no-position state when the endpoint returns an object wrapper.
