# PASS30 - Research Intake Contract

## Scope

- Completed backlog task `P8-009`.
- Defined the source files, normalized row shape, allowed categories, and UI rules for Research Intake.
- Cleared the final blocker for route-consolidation planning.

## Files

- `docs/plans/master-implementation/RESEARCH_INTAKE_CONTRACT_2026-09-01.md`
  - Lists canonical source files.
  - Defines normalized Research Intake rows.
  - Defines allowed kinds and dispositions.
  - Captures initial rows from the PR/issue/spike disposition matrix.
  - States UI rules that prevent intake rows from implying readiness.
- `docs/plans/master-implementation/IMPLEMENTATION_BACKLOG.json`
  - Marks `P8-009` done.
  - Marks `P8-010` ready.

## Validation

- Reviewed `PR_ISSUE_SPIKE_DISPOSITION_2026-09-01.md`.
- Reviewed CC-007 in `COMMAND_CENTER_IMPLEMENTATION_TICKETS_2026-09-01.md`.
- Reviewed existing `/strategy/research-candidates` fields in `engine/routers/strategy_ledger_router.py` and `dashboard/lib/api.ts`.
- Verified the backlog JSON parses.
- Verified the touched documentation has no whitespace errors with `git diff --check`.

## Next Task

- Implement `P8-010`: plan duplicate route consolidation now that the Command Center canonical shell, backend contracts, and research-intake contract are defined.
