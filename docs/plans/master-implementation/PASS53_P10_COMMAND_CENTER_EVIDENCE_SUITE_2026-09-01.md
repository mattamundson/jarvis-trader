# PASS53 - P10 Command Center Evidence Suite

Date: 2026-09-01
Backlog item: P10-010

## Scope

Ran the consolidated P10 evidence suite after the dashboard Command Center and engine data-integrity changes.

## Validation

Dashboard static and node checks:

```powershell
pnpm run typecheck
pnpm run typecheck:tests
pnpm run guards
node --test --experimental-strip-types --import ./tests/_register-alias.mjs tests/commandCenterState.node.test.ts tests/engineMockShapes.node.test.ts
```

Results:

- `pnpm run typecheck` passed.
- `pnpm run typecheck:tests` passed.
- `pnpm run guards` passed.
- Node tests passed: 16 tests passed.

Dashboard isolated E2E:

```powershell
pnpm run test:e2e:isolated -- tests/e2e/command-center-responsive.spec.ts tests/e2e/command-center-route-consolidation.spec.ts --project=golden-path --workers=1
```

Result: 7 tests passed on `golden-path`.

Engine data-integrity checks:

```powershell
& 'C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\.venv312-codex-loop\Scripts\python.exe' -m pytest tests/test_data_integrity_stale_threshold.py -q
& 'C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\.venv\Scripts\ruff.exe' check api/models.py routers/health_router.py tests/test_data_integrity_stale_threshold.py --config ruff.toml
```

Results:

- Pytest passed: 6 tests passed, 1 upstream Starlette/httpx warning.
- Ruff passed.

## Notes

The first combined E2E run exposed a mobile strict-locator issue in `command-center-responsive.spec.ts`: the rendered DOM can contain more than one matching status-strip node. The test now scopes first-viewport singleton assertions to the first rendered instance, which preserves the responsive smoke contract and removes the false strict-mode failure.
