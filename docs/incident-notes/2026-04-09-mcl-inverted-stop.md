# Incident — MCL inverted stop on 2026-04-09

## Summary
An MCL paper long position was persisted with `stop_loss=$86.00` above `entry_price=$84.20`. For a long, the stop must be **below** entry — otherwise the stop logic fires at a guaranteed-loss price on the first normal tick, or (in paper mode where stops aren't yet simulated) the position has no downside protection at all. The actual stop for this trade should have been $82.40 (entry − 1.5 ATR).

Current state of the system (verified 2026-04-16):
- The affected MCL position has been corrected; DB now shows `stop_loss=$82.40`.
- `engine/tests/test_stop_loss_invariants.py` scans all SQLite and JSONL records on every run — zero inverted stops present.

This note exists so the next auditor doesn't re-trace the same paths from scratch.

## Code paths audited

| Path | Verdict |
|---|---|
| `engine/backtest/composite_signals.py:285` (long branch) + `:317` (short branch) | Safe. Long subtracts ATR, short adds ATR. |
| `engine/agents/trader.py:1073-1107` | Safe. Detects inverted LLM output, corrects from ATR or nulls. |
| `engine/backtest/paper_runner.py:99-111` | Safe. Pass-through mapper; doesn't originate stops. |
| `engine/database/_mixins_trades.py` `insert_paper_trade` | **Was a gap.** Accepted any `stop_loss` without direction check. Now guarded via `utils.trade_invariants.is_inverted_stop` — raises `ValueError` on violation. |
| `engine/routers/portfolio_router.py` `PATCH /paper/positions/{trade_id}` | **Was a gap.** Same acceptance-without-check. Now returns HTTP 422 on violation. |

## Most-likely origin of the April 9 value

The calculation code (composite_signals.py) branches correctly. The LLM output path (trader.py:1073+) has defensive correction. The only remaining ways to get an inverted stop into the DB were:

1. A direct PATCH from a user/tool that supplied the wrong value (e.g. a manual typo or a misrouted script).
2. An older `insert_paper_trade` call from code that has since been removed or corrected.

Neither path had a directional check at the DB boundary. That's now closed.

## What was added to prevent recurrence

1. **Shared invariants module** — `engine/utils/trade_invariants.py` exposes `LONG_SIDES`, `SHORT_SIDES`, and `is_inverted_stop(side, entry_price, stop_loss)`. Single source of truth used by both guards and tests.
2. **Guard at INSERT** — `_mixins_trades.insert_paper_trade` raises `ValueError` with a pointer to this note when an inverted stop is passed.
3. **Guard at PATCH** — `portfolio_router.update_position` returns `HTTP 422` on an inverted update.
4. **Regression tests** — `test_stop_loss_invariants.py` now includes targeted unit tests for both guards in addition to the existing full-DB scan.

## If the regression tests fail in the future

1. Run `.venv\Scripts\python -m pytest engine/tests/test_stop_loss_invariants.py -v` to see which specific invariant fired.
2. If the full-DB scan fires, query the violating `trade_id` and trace how it was written: `SELECT * FROM paper_trades WHERE trade_id='<id>';` then check `entry_time` against recent `engine.log` lines.
3. Identify which write path leaked. Candidates now narrow to: new code that imports `_mixins_trades` directly, a raw SQL INSERT added somewhere, or a test fixture bypassing the guard intentionally.
4. Fix the caller. Do not weaken the guard.
