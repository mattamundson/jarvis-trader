# PASS28 - Data Integrity Backend Contract

## Scope

- Completed backlog task `P8-007`.
- Defined the expanded `/system/data-integrity` response contract needed by the Command Center.
- Kept the work docs-only so runtime behavior remains unchanged until the backend implementation task.

## Files

- `docs/plans/master-implementation/COMMAND_CENTER_DATA_INTEGRITY_CONTRACT_2026-09-01.md`
  - Captures the current endpoint shape.
  - Specifies cache age, provider tier, bar freshness, source parity, and trade-enable fields.
  - Defines status enums and backward-compatibility rules.
  - States the UI claim rules that keep values at `unknown` or `not_wired` until backend fields are present.
- `docs/plans/master-implementation/IMPLEMENTATION_BACKLOG.json`
  - Marks `P8-007` done.
  - Unblocks `P8-008`.

## Validation

- Reviewed current `/system/data-integrity` implementation in `engine/routers/health_router.py`.
- Reviewed current dashboard consumer in `dashboard/app/data-integrity/page.tsx`.
- Reviewed stale-threshold tests in `engine/tests/test_data_integrity_stale_threshold.py`.
- Verified the backlog JSON parses.
- Verified the touched documentation has no whitespace errors with `git diff --check`.

## Next Task

- Implement `P8-008`: add backend fields for strategy-ledger freshness and next-gate state so the Command Center can stop inferring those values in the frontend.
