# PASS29 - Strategy Ledger Backend Fields

## Scope

- Completed backlog task `P8-008`.
- Added backend-owned strategy-ledger freshness and next-gate fields.
- Updated the Command Center strategy-ledger panel so it reads next-gate state from `/strategy/ledger` instead of deriving it from `PASS` or `FAIL` in the frontend.

## Files

- `engine/routers/strategy_ledger_router.py`
  - Adds per-entry `source_file_mtime`, `freshness_status`, `freshness_basis`, `next_gate`, and `next_gate_reason`.
  - Adds response-level `ledger_freshness`.
  - Preserves the existing `entries`, `total`, `n_pass`, `n_fail`, and `generated_at` fields.
- `engine/tests/test_strategy_ledger_and_full_review.py`
  - Covers per-entry next-gate and freshness metadata.
  - Covers response-level freshness summary.
- `dashboard/lib/api.ts`
  - Adds TypeScript fields for the expanded strategy-ledger response.
- `dashboard/components/command-center/CanonicalSections.tsx`
  - Displays `row.next_gate` and `row.freshness_status`.
  - Falls back to `not reported` / `freshness unknown` when older engine responses omit the fields.
- `dashboard/tests/e2e/command-center-fixtures.ts`
  - Updates Command Center fixtures to include the expanded backend shape.
- `dashboard/tests/e2e/_engineMock.ts`
  - Updates the generic strategy-ledger mock with an empty freshness block.
- `dashboard/tests/e2e/command-center-responsive.spec.ts`
  - Asserts the Command Center renders backend-provided `next_gate` and `freshness_status` text.

## Validation

- `C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\.venv312-codex-loop\Scripts\python.exe -m pytest tests/test_strategy_ledger_and_full_review.py -q` passed.
  - Result: 5 tests passed.
- `pnpm run typecheck` passed.
- `pnpm run guards` passed.
- `pnpm run test:e2e:isolated -- tests/e2e/command-center-responsive.spec.ts --project=golden-path --workers=1` passed.
  - Build passed.
  - Result: 2 Playwright tests passed.
  - Isolated artifacts were archived under `C:\Users\mattm\Archive\2026\jarvis-temp-build-artifacts\`.
- `git diff -- dashboard/next-env.d.ts dashboard/tsconfig.json` showed no generated-file residue.
- `git diff --check` passed.

## Notes

- The frontend fallback is intentionally non-authoritative: older engine responses can still render, but the Command Center no longer invents `forward proof`, `repair thesis`, or `gate-v2 rerun` from the verdict alone.
