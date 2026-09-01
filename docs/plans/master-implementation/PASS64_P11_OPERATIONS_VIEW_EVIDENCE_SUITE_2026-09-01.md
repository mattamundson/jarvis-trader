# PASS64 - P11 Operations View Evidence Suite

Date: 2026-09-01
Backlog item: P11-010

## Scope

Ran the consolidated P11 evidence suite after migrating `/mission-control` into `/command-center?view=operations`.

## Validation

Static and node checks:

```powershell
pnpm run typecheck
pnpm run typecheck:tests
pnpm run guards
node --test --experimental-strip-types --import ./tests/_register-alias.mjs tests/commandCenterState.node.test.ts tests/engineMockShapes.node.test.ts
```

Results:

- Typecheck passed.
- Test typecheck passed.
- Dashboard guards passed.
- Node tests passed: 16 tests passed.

Focused isolated E2E:

```powershell
pnpm run test:e2e:isolated -- tests/e2e/command-center-responsive.spec.ts tests/e2e/command-center-route-consolidation.spec.ts --project=golden-path --workers=1
```

Result: 9 tests passed on `golden-path`.

## Notes

The first combined E2E run found a stale responsive assertion that still expected Operations to link to `/mission-control`. The responsive spec now expects `/command-center?view=operations`, matching the canonical route-consolidation state.
