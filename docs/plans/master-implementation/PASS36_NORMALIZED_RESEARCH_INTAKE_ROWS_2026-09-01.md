# PASS36 - Normalized Research Intake Rows

## Scope

- Completed backlog task `P9-004`.
- Added a checked-in normalized Research Intake source for Command Center and research-log consumers.
- Added tests proving rows remain non-authorizing intake.

## Files

- `dashboard/lib/researchIntake.ts`
  - Defines Research Intake row types.
  - Exposes `RESEARCH_INTAKE_ROWS` from the PR/issue/spike disposition matrix.
  - Exposes `summarizeResearchIntake()` and `commandCenterResearchIntakeRows()`.
- `dashboard/tests/researchIntake.node.test.ts`
  - Verifies row normalization.
  - Verifies all rows have `readiness_impact: "none"`.
  - Verifies summary disposition counts.
- `docs/plans/master-implementation/IMPLEMENTATION_BACKLOG.json`
  - Marks `P9-004` done.
  - Unblocks `P9-005`.

## Validation

- `node --test --experimental-strip-types --import ./tests/_register-alias.mjs tests/researchIntake.node.test.ts` passed.
  - Result: 3 tests passed.
  - Node emitted the existing module-type warning for TS ESM parsing.
- `pnpm run typecheck` passed.
- `pnpm run guards` passed.

## Next Task

- Implement `P9-005`: wire the Command Center Research Intake panel to `commandCenterResearchIntakeRows()` instead of static placeholder rows.
