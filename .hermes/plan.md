# Plan — Repair Baseline Fast-Test Failures

## Finish line

Restore the five `origin/master` fast-suite failures that block PR #967 without changing production trading behavior, broker routing, risk controls, symbol gates, or kill-switch logic.

## Scope

1. Update the IB market-data test double to accept and record the production connector's existing `readonly` keyword without changing connector behavior.
2. Make the Kronos calibration fixture's timestamps relative to the test run so its synthetic bars remain inside the configured lookback window.
3. Keep all edits test-only.
4. Deliver through a separate focused PR; do not merge or deploy.

## Verification

- Reproduce the five failures before editing.
- Run both affected test modules after editing.
- Run targeted Ruff and `git diff --check`.
- Run the complete fast/non-slow test suite and compare the result with the previous five-failure baseline.
- Push and open a focused PR with exact verification evidence.
- Do not merge either this PR or safety-review PR #967 without explicit approval.

## Evidence

- RED: reproduced exactly five failures from `origin/master` (one expired Kronos fixture and four stale IB test-double signatures).
- GREEN: both affected modules passed, `22 passed`.
- Targeted Ruff, full engine Ruff, and `git diff --check`: passed.
- Scope guard: `TEST_ONLY_SCOPE_PASS files=3`; only this plan and two test modules differ from `origin/master`.
- Independent Codex review was attempted but unavailable because its Windows sandbox failed with `helper_sandbox_lock_failed`; no review pass is claimed.
- Full non-slow suite: `9522 passed, 29 skipped, 184 deselected, 1 xfailed` in 1164.25 seconds; exit `0`.
