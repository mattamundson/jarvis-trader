# MCPT validation runbook (permutation tests)

How to tell a real edge from data-mining bias before trusting a backtest, using the
bar-permutation MCPT (Masters 2020) and the trade-sign permutation (Aronson EBTA ch. 6).

Implemented in:
- `engine/backtest/bar_permute.py` — `get_permutation` / `get_block_permutation`
- `engine/analytics/permutation_test.py` — `run_insample_mcpt`, `run_walkforward_mcpt`,
  `validate_strategy`, `permute_and_score`
- `engine/backtest/run_mcpt.py` — the CLI driver
- `.claude/skills/mcpt-validation/` — interpretation skill

> **Status: DIAGNOSTIC, not a gate.** None of these block trade authorization. The
> forward-test report surfaces a trade-sign p-value (`ts_p`) for observation only. Turning
> any p-value into a blocking graduation/promotion requirement is a separate
> `[safety-review]` + Tier-3 change — see `.claude/rules/ml-pitfalls-defense.md` pitfall #9.

## The two tests

| Test | What it permutes | Question it answers | Pass bar |
|------|------------------|---------------------|----------|
| Bar-permutation MCPT | price bars, then re-optimizes | "would my optimizer find this on noise?" (data-mining bias) | in-sample p < 0.01; walk-forward p < 0.05 (< 0.01 for ≥2yr) |
| Trade-sign permutation | the realized trade P&L signs | "is this trade record better than no-edge luck?" | p < 0.05 |

Bar-permutation is the null for a mechanical optimizer; trade-sign is the null for a
realized trade list (e.g. the LLM-driven live path, which has no optimizer to permute).

## Discipline (non-negotiable)

Lock the strategy spec **before** running. If it fails, **discard the strategy — do not
tweak and re-run.** Iterating against the test data-mines the p-value itself (Masters'
"target-fiddling", the most insidious failure mode). One run per locked spec.

## Running it

All commands from `engine/` with the venv. The `prices` real path needs `API_KEY` set
(it instantiates `config.settings`, like any engine script).

```bash
# 1. Bar-permutation MCPT on a 1h OHLC cache (real Backtester strategy by default)
.venv/Scripts/python -m backtest.run_mcpt prices --symbol MES --long-history
.venv/Scripts/python -m backtest.run_mcpt prices --symbol MES --proxy   # fast SMA approx

# 2. Trade-sign test on closed paper trades (SQLite or CSV with a pnl column)
.venv/Scripts/python -m backtest.run_mcpt trades --db data/jarvis_trader.db --symbol MES
.venv/Scripts/python -m backtest.run_mcpt trades --csv data/closed_trades_export.csv --symbol MGC

# 3. Synthetic sample data to exercise the plumbing (SAMPLE_ prefix, gitignored)
.venv/Scripts/python -m backtest.run_mcpt make-sample --symbol MES
```

`prices` reads `engine/backtest/cache/<SYMBOL>_<start>_<end>_1h.csv`
(columns: `timestamp`/`datetime` + `open,high,low,close`). The real path optimizes over
`config_for(symbol).grid` (fast, slow, atr_trail) via `generate_sma_trend_signals` →
`Backtester.run`. Profit factor is capped at 10.0 so a no-loss permutation cannot make
the null mean infinite.

## Getting the data in (when running on a fresh clone / CI)

Both the price cache and `jarvis_trader.db` are gitignored, so a fresh clone has neither.

```bash
# Closed-trades export (small, fastest path to a real trade-sign verdict)
cd engine
.venv/Scripts/python -c "import sqlite3,csv; c=sqlite3.connect('data/jarvis_trader.db'); \
rows=c.execute(\"SELECT symbol,exit_time,pnl FROM paper_trades WHERE status='closed'\").fetchall(); \
w=csv.writer(open('data/closed_trades_export.csv','w',newline='')); \
w.writerow(['symbol','exit_time','pnl']); w.writerows(rows)"

# Price cache: produce via the IBKR history export (needs IB Gateway up), then it lands at
#   engine/backtest/cache/<SYMBOL>_<start>_<end>_1h.csv
```

Exports contain real account P&L — not secrets, but treat as sensitive; prefer a
throwaway branch if you don't want trade data in mainline history.

## Reading the result

`validate_strategy` is fail-closed and returns a `verdict`:

- `PASS` — cleared all four gates (in-sample excellence → in-sample MCPT → walk-forward →
  walk-forward MCPT). A **candidate**, not a guarantee — confirm across regimes/markets.
- `REJECT (<gate>)` — names the first gate it failed. A high in-sample p means the
  optimizer eats noise as easily as signal: no edge.

Small samples lie: with < ~30 trades the p-value is low-power. MES (~16) / MGC (~67) — a
single pass there is weak evidence; say so when reporting.
