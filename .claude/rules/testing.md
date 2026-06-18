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

Every backtest, walk-forward, and WFE run must use **only data that was available at the
decision timestamp**. No future bars, no revised fundamentals, no end-of-day values applied
intrabar, no indicator warmed up on data the live agent would not yet have seen. A signal
computed at bar `t` may read bars `≤ t` only.

This is an invariant, not a guideline: a strategy that "wins" by peeking at the future is
curve-fit noise that will not survive paper trading. We already enforce pieces of it
(`engine/backtest/news_blackout.py`, regime gating, walk-forward splits) — this rule names
the whole. When in doubt, ask: "would the live pipeline have had this value at this instant?"
If no, the backtest is cheating.

Source: DeepFund, "Time Travel is Cheating: Going Live with DeepFund for Real-Time Fund
Investment Benchmarking" (arXiv 2505.11065, 2025), surfaced via the
`LLMQuant/awesome-trading-agents` list.

## When Adding New Features

1. Add test for the new functionality first (TDD where practical)
2. Run full suite before declaring done
3. Safety-related code always needs a test — no exceptions
