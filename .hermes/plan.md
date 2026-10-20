# Plan — [safety-review] MGC Active-Contract Freshness Repair

## Finish line

Prepare an isolated, reviewable fix that selects IBKR's active continuous futures contract for read-only historical data instead of the nearest non-expired serial contract, with regression coverage and no execution, risk, symbol-gate, kill-switch, or live-order changes.

## Scope

- Work only in `safety-review/ib4001-mgc-front-month-20261020` based on `origin/master`.
- Preserve `127.0.0.1:4001` as the only operational Gateway endpoint; do not alter execution routing.
- Add a failing regression test proving MGC prefers IBKR's active continuous contract over a nearer but inactive serial expiry.
- Implement continuous-contract resolution using the repository's existing `export_ibkr_history.py` pattern, with the current expiry-list resolver retained as a fail-safe fallback.
- Run targeted tests, full affected-file tests, Ruff, and independent review.
- Do not deploy or merge. Open a `[safety-review]` PR only if verification passes.

## Finish-line evidence

1. RED test fails against the current nearest-expiry resolver for the expected reason.
2. GREEN test passes after the minimal resolver change.
3. Existing `test_market_data_ibkr.py` coverage passes.
4. Ruff passes on changed Python files.
5. Full non-slow engine suite is attempted; any unrelated baseline failures are reported exactly.
6. Independent reviewer reports no blocking logic or security issue.
7. PR is explicitly labeled `[safety-review]` and states live Gateway validation is still blocked until interactive IBKR 2FA/login restores local port 4001.

## Verification record — 2026-10-20

- RED: the new MGC regression selected `MGCV6` instead of the expected active `MGCZ6` before the implementation.
- GREEN: the focused regression and all of `tests/test_market_data_ibkr.py` passed after the resolver change.
- Static gates: changed-file Ruff, full engine Ruff, and `git diff --check` passed.
- Full non-slow engine suite: `9519 passed, 28 skipped, 184 deselected, 1 xfailed, 5 failed` in 773.42 seconds.
- All five failures were reproduced unchanged from a clean `origin/master` archive: one Kronos fixture-data failure and four stale `_FakeIB.connectAsync` signature failures in `test_ib_market_data_type.py` caused by the existing `readonly` argument.
- Independent Codex review: `No discrete correctness, safety, or maintainability defects were identified in the current changes.`
- Live validation remains blocked: Gateway was restored only to its Paper Trading login screen; no credential or verification code was handled, and port 4001 is not yet authenticated.
- Delivery boundary remains PR-only. Do not deploy or merge from this worktree.
