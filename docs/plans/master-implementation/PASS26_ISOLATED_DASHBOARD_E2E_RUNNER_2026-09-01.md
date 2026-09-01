# PASS26 - Isolated Dashboard E2E Runner

## Scope

- Completed backlog task `P8-005`.
- Added a reusable dashboard runner that performs the isolated production-build plus Playwright verification flow.
- Unblocked `P8-006`.

## Files

- `dashboard/scripts/run-isolated-e2e.mjs`
  - Snapshots `next-env.d.ts` and `tsconfig.json`.
  - Runs `pnpm run build` with `NEXT_DIST_DIR` defaulting to `.next-codex-isolated`.
  - Runs `pnpm exec playwright test -c playwright.fresh.config.ts ...args`.
  - Restores the two Next-generated files in `finally`.
  - As of PASS71, handles generated artifacts through `JARVIS_E2E_ARTIFACT_MODE`.
- `dashboard/scripts/isolated-e2e-artifacts.mjs`
  - Provides artifact mode validation and dashboard-root-bounded archive/cleanup helpers.
- `dashboard/package.json`
  - Adds `test:e2e:isolated`.

## Validation

- `pnpm run test:e2e:isolated -- tests/e2e/command-center-routes.spec.ts --project=golden-path --workers=1` passed.
  - Build passed.
  - Route-contract E2E passed: 3 tests.
  - Script restored generated Next metadata.
  - At the time of PASS26, script archived:
    - `C:\Users\mattm\Archive\2026\jarvis-temp-build-artifacts\.next-codex-isolated-20260901-164331`
    - `C:\Users\mattm\Archive\2026\jarvis-temp-build-artifacts\test-results-20260901-164331`
- Post-run checks:
  - `git diff -- dashboard/next-env.d.ts dashboard/tsconfig.json` showed no diff.
  - `pnpm run typecheck` passed.
  - `pnpm run guards` passed.

## Notes

- Artifact retention is now bounded by default:
  - `JARVIS_E2E_ARTIFACT_MODE=on-failure` is the default: failed runs archive evidence; successful runs remove only current-run reproducible temp outputs.
  - `JARVIS_E2E_ARTIFACT_MODE=always` preserves the original archive-every-run behavior.
  - `JARVIS_E2E_ARTIFACT_MODE=never` removes current-run reproducible temp outputs even on failed runs.
- The runner defaults dashboard auth environment variables to empty only when they are absent, matching the current local focused-E2E workflow.
