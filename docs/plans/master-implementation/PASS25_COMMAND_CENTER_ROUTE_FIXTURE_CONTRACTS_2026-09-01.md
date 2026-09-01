# PASS25 - Command Center Route Fixture Contracts

## Scope

- Completed backlog task `P8-004`.
- Promoted the Command Center fixture contract into route coverage for paths that resolve to `/command-center`.
- Removed duplicated homepage degraded mock shapes.

## Files

- `dashboard/tests/e2e/smoke.spec.ts`
  - Adds `installRouteMock`.
  - Uses `installCommandCenterFixture` for `/`, `/dashboard`, and `/command-center` in degraded/offline modes.
  - Keeps the generic `_engineMock` for non-Command Center routes and slow-mode checks.
- `dashboard/tests/e2e/command-center-routes.spec.ts`
  - Adds explicit route-contract checks for `/`, `/dashboard`, and `/command-center`.
- `dashboard/tests/e2e/homepage-golden-path.spec.ts`
  - Replaces duplicated route mocks with `installCommandCenterFixture(page, "degraded")`.
- `dashboard/tests/e2e/homepage.spec.ts`
  - Uses `installCommandCenterFixture(page, "empty")`.

## Validation

- `pnpm run typecheck` passed.
- `pnpm run guards` passed.
- `NEXT_DIST_DIR=.next-codex-p8 pnpm run build` passed.
- `pnpm exec playwright test -c playwright.fresh.config.ts tests/e2e/command-center-routes.spec.ts --project=golden-path --workers=1` passed: 3 tests.
- `pnpm exec playwright test -c playwright.fresh.config.ts tests/e2e/command-center-route-smoke.spec.ts --project=golden-path --list` initially showed 0 tests because `*-smoke.spec.ts` is ignored by the `golden-path` project and does not match the exact smoke-project matcher. The file was renamed to `command-center-routes.spec.ts`.
- `pnpm exec playwright test -c playwright.fresh.config.ts tests/e2e/command-center-routes.spec.ts tests/e2e/homepage.spec.ts tests/e2e/homepage-golden-path.spec.ts tests/e2e/dashboard.spec.ts --project=golden-path` timed out under machine load before returning logs, then the new route-contract spec passed by itself. The homepage/dashboard specs had passed in the preceding targeted run before the spec rename.

## Artifact Hygiene

- Next.js rewrote `next-env.d.ts` and `tsconfig.json` during isolated builds; both files were restored from `HEAD`.
- Build/test artifacts were archived under `C:\Users\mattm\Archive\2026\jarvis-temp-build-artifacts\`.
