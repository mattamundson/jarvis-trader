# Pass 17 - Command Center API Helpers

Date: 2026-09-01

## Scope

This pass implemented P7-004: Command Center-specific proxy helper contracts.

## Changes

- Added `dashboard/lib/commandCenterApi.ts`.
- Moved `/command-center` endpoint types and fetch helpers out of the page component.
- The page now consumes named helpers for:
  - health
  - safety
  - portfolio
  - recent decisions
  - scheduler
  - macro snapshot
  - paper status
  - strategy ledger
  - data integrity
  - trade history
  - journal stats
  - bars and per-symbol regime
  - kill-switch activation/deactivation
- The helpers call `fetchEngine`, existing `lib/api.ts` wrappers, or `toggleKillSwitch`; no direct browser engine URL or bare fetch was introduced.

## Verification

- `pnpm run guards` passed.
- `pnpm run typecheck` passed.
- `NEXT_DIST_DIR=.next-codex-p7 pnpm run build` passed against an isolated dist directory.
- `NEXT_DIST_DIR=.next-codex-p7 pnpm exec playwright test -c playwright.fresh.config.ts tests/e2e/command-center.spec.ts tests/e2e/command-center-golden-path.spec.ts --project=golden-path` passed: 3/3.

## Artifact Hygiene

- The isolated build directory and Playwright results were archived to:
  - `C:\Users\mattm\Archive\2026\jarvis-temp-build-artifacts\.next-codex-p7-20260901-065443`
  - `C:\Users\mattm\Archive\2026\jarvis-temp-build-artifacts\test-results-20260901-065443`

## Backlog Impact

- P7-004 is done.
- P7-005, P7-006, P7-007, P7-008, and P7-009 are now ready.
- P7-010 remains blocked until those five panels are implemented.
