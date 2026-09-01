# PASS34 - Command Center Data Integrity Contract Wiring

## Scope

- Completed backlog task `P9-002`.
- Updated the Command Center Data Integrity panel to render backend-owned data-integrity states.
- Kept older engine responses compatible by falling back to `unknown` and `not wired`.

## Files

- `dashboard/lib/commandCenterApi.ts`
  - Adds the expanded `CommandCenterDataIntegrityResponse` fields for cache age, provider tier, bar freshness, source parity, and trade enablement.
- `dashboard/components/command-center/CanonicalSections.tsx`
  - Uses `integrity.cache_age.status`, `integrity.provider_tier.status`, `integrity.bar_freshness.status`, and `integrity.source_parity.status`.
  - Stops treating any successful `/system/data-integrity` response as `reported` or `current`.
- `dashboard/tests/e2e/command-center-fixtures.ts`
  - Updates populated and empty fixtures to match the expanded backend contract.
- `dashboard/tests/e2e/command-center-responsive.spec.ts`
  - Asserts the Command Center renders backend-provided cache/provider/bar/parity states.

## Validation

- `pnpm run typecheck` passed.
- `pnpm run guards` passed.
- First isolated E2E attempt hit a transient `next build` worker crash with Windows exit code `3221226505`; the runner archived the partial build and left no generated metadata residue.
- Rerun passed:
  - `pnpm run test:e2e:isolated -- tests/e2e/command-center-responsive.spec.ts --project=golden-path --workers=1`
  - Build passed.
  - Result: 2 Playwright tests passed.
  - Isolated artifacts were archived under `C:\Users\mattm\Archive\2026\jarvis-temp-build-artifacts\`.
- `git diff -- dashboard/next-env.d.ts dashboard/tsconfig.json` showed no generated-file residue.

## Next Task

- Implement `P9-003`: update `/data-integrity` drilldown to show the expanded backend contract without breaking the existing source cards.
