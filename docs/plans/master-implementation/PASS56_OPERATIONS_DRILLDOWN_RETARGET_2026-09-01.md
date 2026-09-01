# PASS56 - Operations Drilldown Retarget

Date: 2026-09-01
Backlog item: P11-002

## Scope

Retargeted Operations navigation to the canonical Command Center operations view.

## Changes

- Command Center drilldown `Operations` now links to `/command-center?view=operations`.
- Sidebar `Operations` now links to `/command-center?view=operations`.
- `/mission-control` remains directly reachable and covered by route-consolidation tests until operations parity is complete.

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
