# PASS35 - Data Integrity Drilldown Contract

## Scope

- Completed backlog task `P9-003`.
- Updated `/data-integrity` to render the expanded backend contract while preserving the existing source cards.
- Added focused E2E coverage for the expanded drilldown states.

## Files

- `dashboard/app/data-integrity/page.tsx`
  - Adds a compact summary for cache age, provider tier, bar freshness, source parity, and trade enablement.
  - Keeps existing stream/source cards compatible with the older `source`, `last_update`, `latency_sec`, and `status` fields.
  - Adds provider/freshness fallbacks so missing expanded fields render unknown states instead of false success.
- `dashboard/tests/e2e/data-integrity-contract.spec.ts`
  - Mocks `/api/engine/system/data-integrity`.
  - Verifies expanded contract fields render on `/data-integrity`.
- `docs/plans/master-implementation/IMPLEMENTATION_BACKLOG.json`
  - Marks `P9-003` done.

## Validation

- `pnpm run typecheck` passed.
- `pnpm run guards` passed.
- `pnpm run test:e2e:isolated -- tests/e2e/data-integrity-contract.spec.ts --project=golden-path --workers=1` passed.
  - Build passed.
  - Result: 1 Playwright test passed.
  - Isolated artifacts were archived under `C:\Users\mattm\Archive\2026\jarvis-temp-build-artifacts\`.
- `git diff -- dashboard/next-env.d.ts dashboard/tsconfig.json` showed no generated-file residue.
- `git diff --check` passed.

## Next Task

- Implement `P9-004`: create normalized Research Intake source rows from the disposition matrix.
