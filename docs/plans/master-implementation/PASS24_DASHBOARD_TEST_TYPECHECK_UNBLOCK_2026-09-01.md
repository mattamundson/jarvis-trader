# PASS24 - Dashboard Test Typecheck Unblock

## Scope

- Completed backlog task `P8-003`.
- Added the missing component modules expected by the existing safety component tests:
  - `dashboard/components/CircuitBreakerPanel.tsx`
  - `dashboard/components/KillSwitch.tsx`

## Files

- `dashboard/components/CircuitBreakerPanel.tsx`
  - Reads `/safety/circuit-breakers` through `fetchEngine`.
  - Renders explicit unavailable/loading states.
  - Shows daily P&L and drawdown gauges as `NORMAL` or `TRIPPED`.
  - Shows `All Clear` vs `HALTED` and kill-switch active/inactive state.
- `dashboard/components/KillSwitch.tsx`
  - Renders state from props only.
  - Requires confirmation before activation.
  - Calls `postEngine("/safety/kill-switch/activate", { reason: "manual_dashboard" })`.
  - Calls `postEngine("/safety/kill-switch/deactivate")`.
  - Does not call `onToggle` when either POST fails.

## Validation

- Initial reproduction:
  - `pnpm run typecheck:tests` failed on missing `@/components/CircuitBreakerPanel` and `@/components/KillSwitch`.
- Fixed validation:
  - `pnpm run typecheck:tests` passed.
  - `pnpm exec vitest run tests/component/CircuitBreakerPanel.test.tsx tests/component/KillSwitch.test.tsx` passed: 2 files, 6 tests.
  - `pnpm run test:component` passed: 11 files, 48 tests.
  - `pnpm run typecheck` passed.
  - `pnpm run guards` passed.

## Notes

- Vitest still emits its existing Vite native config warning about ESM syntax in `vitest.config.ts`; it does not fail the suite.
