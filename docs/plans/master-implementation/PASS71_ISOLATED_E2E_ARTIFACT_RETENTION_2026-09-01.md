# PASS71 - Isolated E2E Artifact Retention

## Scope

Completed P13-001 through P13-009 by making `test:e2e:isolated` bounded by default and testable without running a browser build.

## Policy

- Default: `JARVIS_E2E_ARTIFACT_MODE=on-failure`.
- Failed runs archive `.next-codex-isolated` and `test-results` under the existing stamped archive root.
- Successful runs remove only the current run's reproducible `.next-codex-isolated` and `test-results` outputs.
- `JARVIS_E2E_ARTIFACT_MODE=always` preserves the old archive-every-run behavior.
- `JARVIS_E2E_ARTIFACT_MODE=never` removes current temp outputs even on failed runs.

## Changes

- Added `dashboard/scripts/isolated-e2e-artifacts.mjs`.
- Updated `dashboard/scripts/run-isolated-e2e.mjs` to use the helper after restoring Next-generated snapshots.
- Added `dashboard/tests/isolatedE2eArtifacts.node.test.mjs`.
- Updated `PASS26_ISOLATED_DASHBOARD_E2E_RUNNER_2026-09-01.md` with the new retention modes.

## Evidence

```powershell
node --test tests/isolatedE2eArtifacts.node.test.mjs
pnpm run typecheck
pnpm run typecheck:tests
pnpm run guards
node -e "JSON.parse(require('fs').readFileSync('docs/plans/master-implementation/IMPLEMENTATION_BACKLOG.json','utf8')); console.log('IMPLEMENTATION_BACKLOG.json ok')"
```

Results:

- Artifact helper tests passed with 5 tests.
- Dashboard typecheck passed.
- Test typecheck passed.
- Dashboard guards passed.
- Backlog JSON parsed successfully.

## Safety Notes

- Cleanup is restricted to current run output paths resolved under the dashboard root.
- The helper refuses to handle the dashboard root itself, parent paths, or absolute paths outside the dashboard root.
- Existing historical archive cleanup is not automated by this pass.
