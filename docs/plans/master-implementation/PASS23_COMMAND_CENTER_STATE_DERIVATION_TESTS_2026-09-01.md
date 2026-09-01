# PASS23 - Command Center State Derivation Tests

## Scope

- Completed backlog task `P8-002`.
- Added `dashboard/lib/commandCenterState.ts` for pure Command Center state mapping.
- Added `dashboard/tests/commandCenterState.node.test.ts` to cover state-strip and shell-region derivations without rendering `/command-center`.

## Files

- `dashboard/lib/commandCenterState.ts`
  - Derives engine, broker, safety, and data strip cells.
  - Derives canonical shell region labels, metrics, details, and tones.
  - Owns `compactCount` so UI and tests share one formatter.
- `dashboard/app/command-center/page.tsx`
  - Calls pure derivation helpers, then attaches icons for `CanonicalShellMap`.
- `dashboard/components/command-center/CanonicalSections.tsx`
  - Reuses `compactCount` from the pure state module.
- `dashboard/tests/commandCenterState.node.test.ts`
  - Covers pending, offline, verified, halted, stale, live, and degraded cases.

## Validation

- Targeted pure node test passed:
  - `node --test --experimental-strip-types --import ./tests/_register-alias.mjs tests/commandCenterState.node.test.ts`
  - Result: 6 passed.
- `pnpm run guards` passed.
- `pnpm run typecheck` passed.
- `NEXT_DIST_DIR=.next-codex-p8 pnpm run build` passed.
- Focused Command Center E2E passed:
  - `pnpm exec playwright test -c playwright.fresh.config.ts tests/e2e/command-center.spec.ts tests/e2e/command-center-golden-path.spec.ts --project=golden-path`
  - Result: 5 passed.

## Known Unrelated Blocker

- `pnpm run test:unit` currently fails five existing active-symbol/baseline assertions:
  - `tests/instrument-validation-scope-gap.node.test.ts`
  - `tests/scorecard-baseline-active-pair.node.test.ts`
- These failures are outside the Command Center derivation files touched here.

## Artifact Hygiene

- Next.js rewrote `next-env.d.ts` and `tsconfig.json` during isolated builds; both generated references were restored.
- Build/test artifacts were archived under `C:\Users\mattm\Archive\2026\jarvis-temp-build-artifacts\`.
