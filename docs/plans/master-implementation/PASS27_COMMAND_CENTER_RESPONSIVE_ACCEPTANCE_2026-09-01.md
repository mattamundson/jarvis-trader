# PASS27 - Command Center Responsive Acceptance

## Scope

- Completed backlog task `P8-006`.
- Added desktop and mobile responsive acceptance checks for `/command-center`.
- Tightened the mobile canonical shell/status layout so the trade queue starts in the first mobile viewport.

## Files

- `dashboard/tests/e2e/command-center-responsive.spec.ts`
  - Checks desktop `1440x900` and mobile `390x844`.
  - Asserts the flagship heading, status strip, canonical shell, and trade queue are visible.
  - Asserts no horizontal viewport overflow.
  - Asserts critical panels do not vertically overlap.
  - Attaches viewport screenshots to Playwright test artifacts.
- `dashboard/components/command-center/CanonicalSections.tsx`
  - Uses a two-column mobile status strip.
  - Uses a three-column mobile canonical shell.
  - Reduces mobile shell card height and typography density while keeping desktop layout unchanged.

## Validation

- First responsive run failed on mobile because the trade queue started below the first `390x844` viewport (`y=1364.75`).
- After the layout adjustment:
  - `pnpm run typecheck` passed.
  - `pnpm run guards` passed.
  - `pnpm run test:e2e:isolated -- tests/e2e/command-center-responsive.spec.ts --project=golden-path --workers=1` passed.
  - Result: 2 tests passed.

## Artifact Hygiene

- The isolated runner restored Next metadata and archived:
  - `C:\Users\mattm\Archive\2026\jarvis-temp-build-artifacts\.next-codex-isolated-20260901-165218`
  - `C:\Users\mattm\Archive\2026\jarvis-temp-build-artifacts\test-results-20260901-165218`
