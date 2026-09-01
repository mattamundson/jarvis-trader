# PASS47 - Command Center Summary Component Split

## Scope

- Completed `P10-004`.
- Moved the three drilldown summary panels from `dashboard/components/command-center/CanonicalSections.tsx` into `dashboard/components/command-center/SummarySections.tsx`.
- Updated `dashboard/app/command-center/page.tsx` to import summary panels from the new module.
- Left shell, status strip, trade queue, and operations-grid components in `CanonicalSections.tsx`.

## Evidence

- The summary panels continue to render from the pure row derivations added in `P10-003`.
- `P10-010` now depends only on the remaining sidebar consolidation task `P10-008`.

## Validation

- `node --test --experimental-strip-types --import ./tests/_register-alias.mjs tests/commandCenterState.node.test.ts` passed: 12 tests.
- `pnpm run typecheck` passed.
- `pnpm run guards` passed.
- `pnpm run test:e2e:isolated -- tests/e2e/command-center-responsive.spec.ts --project=golden-path --workers=1` passed: 2 tests.

## Next Action

- Continue with `P10-005`: add an explicit engine response model for `/system/data-integrity`.
