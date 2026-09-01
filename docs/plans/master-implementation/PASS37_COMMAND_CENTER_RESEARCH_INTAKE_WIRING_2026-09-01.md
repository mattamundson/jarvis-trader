# PASS37 - Command Center Research Intake Wiring

## Scope

- Completed backlog task `P9-005`.
- Replaced static Research Intake placeholder rows in Command Center with normalized rows from `dashboard/lib/researchIntake.ts`.
- Preserved the rule that Research Intake is non-authorizing and cannot imply readiness.

## Files

- `dashboard/components/command-center/CanonicalSections.tsx`
  - Imports `commandCenterResearchIntakeRows()`.
  - Renders PR/issue row references and dispositions from the normalized source.
- `dashboard/tests/e2e/command-center-responsive.spec.ts`
  - Asserts `/command-center` renders `#749 pr keep` and `#754 pr reference` in the Research Intake panel.
- `docs/plans/master-implementation/IMPLEMENTATION_BACKLOG.json`
  - Marks `P9-005` done.

## Validation

- `node --test --experimental-strip-types --import ./tests/_register-alias.mjs tests/researchIntake.node.test.ts` passed.
  - Result: 3 tests passed.
  - Node emitted the existing module-type warning for TS ESM parsing.
- `pnpm run typecheck` passed.
- `pnpm run guards` passed.
- First isolated Command Center E2E attempt completed `next build` but the Playwright phase exited with Windows exit code `3221226505` before test output; no `test-results` directory was produced.
- Rerun passed:
  - `pnpm run test:e2e:isolated -- tests/e2e/command-center-responsive.spec.ts --project=golden-path --workers=1`
  - Build passed.
  - Result: 2 Playwright tests passed.
  - Isolated artifacts were archived under `C:\Users\mattm\Archive\2026\jarvis-temp-build-artifacts\`.
- `git diff -- dashboard/next-env.d.ts dashboard/tsconfig.json` showed no generated-file residue.
- `git diff --check` passed.

## Next Task

- Implement `P9-006`: add Command Center drilldown navigation for Operations, Daily Brief, and Trust Audit.
