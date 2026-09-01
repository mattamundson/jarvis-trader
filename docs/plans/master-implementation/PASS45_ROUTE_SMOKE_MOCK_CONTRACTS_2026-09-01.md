# PASS45 - Route Smoke Mock Contracts

## Scope

- Completed `P10-002`.
- Promoted P9 Command Center endpoint contracts into the generic route-smoke engine mock:
  - `/portfolio/stats/session-today`
  - `/analytics/bar-quality`
  - `/reports/edge-ledger`
  - `/system/data-integrity`
- Exported `bodyFor` from `dashboard/tests/e2e/_engineMock.ts` for focused mock-shape regression coverage.

## Evidence

- Added `dashboard/tests/engineMockShapes.node.test.ts` to assert each promoted endpoint keeps the real object wrappers and nested degraded-state fields.

## Validation

- `node --test --experimental-strip-types --import ./tests/_register-alias.mjs tests/engineMockShapes.node.test.ts` passed: 4 tests.
- `pnpm run typecheck:tests` passed.
- `pnpm run guards` passed.
- Supporting run: `pnpm run test:e2e:isolated -- tests/e2e/smoke.spec.ts --project=smoke --workers=1` passed the affected routes:
  - `/trust-pane` degraded/offline/slow
  - `/today` degraded
  - `/data-integrity` degraded
- Known unrelated failures in that full smoke run:
  - `/settings` degraded crashes on an existing missing mock shape (`toLocaleString` on undefined).
  - `/backtest`, `/hidden-pivots`, and `/domflow` exploratory-banner assertions fail due existing banner visibility/absence issues.

## Next Action

- Continue with `P10-003`: add pure derivation tests for the Command Center summary rows.
