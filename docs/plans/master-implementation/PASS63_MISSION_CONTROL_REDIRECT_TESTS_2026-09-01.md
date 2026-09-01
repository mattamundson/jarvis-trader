# PASS63 - Mission-Control Redirect Tests

Date: 2026-09-01
Backlog item: P11-009

## Scope

Updated route-consolidation E2E expectations for the final `/mission-control` redirect state.

## Coverage

- `/mission-control` redirects to `/command-center?view=operations`.
- The redirected operations view renders after navigation.
- `/today` remains directly reachable as the Daily Brief drilldown.
- `/trust-pane` remains directly reachable as the Trust Audit drilldown.
- Populated and degraded operations-view parity checks remain in the same focused suite.

## Validation

```powershell
pnpm run test:e2e:isolated -- tests/e2e/command-center-route-consolidation.spec.ts --project=golden-path --workers=1
```

Result: 7 tests passed on `golden-path`.
