# Testing Rules — JARVIS TRADER

## Requirements (non-negotiable)

- **Engine**: `cd engine && pytest tests/ -v` must pass with 0 failures before any PR
- **Dashboard**: `cd dashboard && pnpm run build` must produce 16/16 routes, 0 TypeScript errors
- **Safety layer tests are sacred**: `engine/tests/test_safety_layer.py` must always pass — never skip or comment out
- **Integration tests**: `engine/tests/test_integration.py` — 28 tests, all must pass

## Test Locations

- `engine/tests/` — 7 test files covering safety, pipeline, signals, database, integration
- Dashboard has no tests yet — add when making breaking changes

## Running Tests

```bash
# Full engine test suite
cd engine && .venv/Scripts/python -m pytest tests/ -v

# Single test file
cd engine && .venv/Scripts/python -m pytest tests/test_safety_layer.py -v

# Dashboard build check (equivalent to type check)
cd dashboard && pnpm run build
```

## No look-ahead bias (point-in-time discipline)

Every backtest, walk-forward, and WFE run must use only data that was actually
available at the simulated decision time. "Time travel is cheating" — a strategy that
reads a bar, a news item, an earnings print, or a regime label from the future is not a
strategy, it is a leak, and any Sharpe it produces is curve-fit noise.

- **Indicators / signals**: a decision at bar `t` may only use bars `≤ t`. No
  centered windows, no `shift(-n)`, no full-series `.fit()` before the split.
- **News / events**: gate on publish timestamp, not event date. We already enforce
  pieces of this — see `engine/backtest/news_blackout.py` and the regime gating in
  `engine/backtest/regime.py` — but the invariant applies everywhere, not just there.
- **Labels / outcomes**: realized P&L and outcome hygiene
  (`engine/analytics/outcome_hygiene.py`) are training/evaluation targets only; they
  must never feed back into a same-bar decision.
- **Live vs. backtest parity**: prefer live/forward evaluation
  (`engine/backtest/forward_test.py`, `paper_tracker.py`) when a backtest result looks
  too good — out-of-sample live is the honest scoreboard.

Source: DeepFund, "Time Travel is Cheating: Going Live with DeepFund for Real-Time Fund
Investment Benchmarking" (arXiv 2505.11065, HKUSTDial, 2025), surfaced via the
`LLMQuant/awesome-trading-agents` list.

## When Adding New Features

1. Add test for the new functionality first (TDD where practical)
2. Run full suite before declaring done
3. Safety-related code always needs a test — no exceptions
