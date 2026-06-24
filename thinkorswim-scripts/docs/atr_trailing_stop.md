# ATR Trailing Stop — ThinkorSwim built-in

**File**: _none_ — this is a ThinkorSwim **built-in** study, not a custom `.ts` in this repo
**Author**: ThinkorSwim built-in (Sylvain Vervoort ATR stop-and-reverse method)
**Chart legend**: `ATRTrailingStop (modified, 5, 3.5, long, WILDERS)`
**JARVIS Layer**: Layer 5 Sizing (the stop line) + Layer 4 Entry (the bounce hypothesis)
**Status**: Ported (2026-06-24)
**Python counterpart**: `engine/backtest/indicators.py::atr_trailing_stop`
**Signal module**: `engine/backtest/atr_trail_bounce_signals.py`
**Panel**: Upper (price chart)

## Why this doc exists

This is the **dotted blue line** on Matt's /ES 5m chart that price was observed
bouncing off precisely (2026-06-24). It was the only major study in that view
with no engine counterpart — every other study (Saty ATR Levels, Corey
Tscore/TPO, Keltner 3.01) was already ported. This doc and the two modules
above close that gap and, more importantly, make the "price bounces off the
line" claim **testable** instead of visual.

It is intentionally **not** an entry in `registry.yaml`: that file is keyed on
real shareable `.ts` files (its schema requires a `file:` path and its loader
test locks the script count), and this is a ThinkorSwim built-in with no `.ts`.
This doc is its home in the bridge.

## What the line is

A stop-and-reverse trailing stop. It trails **below** price while long (acting
as support) and **above** price while short (acting as resistance), flipping
state when price closes through it. The "modified" variant uses TOS's
HiLo/HRef/LRef true-range formulation; `WILDERS` is the smoothing.
`engine/backtest/indicators.py::atr_trailing_stop` reproduces this faithfully
so the engine's line matches the chart bar-for-bar.

## The alpha hypothesis (and how it is being tested)

Hypothesis: the line is dynamic S/R; a tag-and-reclaim is a high-probability
entry. This is exactly the kind of claim that survives in *random* data (a
trailing stop hugs price by construction), so it is gated, not trusted:

- **Signal** (`atr_trail_bounce_signals.py`): long when a bar wicks to/through
  the line while in long state **and** closes back above it (`touch + reclaim`),
  **and** the line stays in long state for `hold_bars` afterward (Matt's "does
  it stay above after 5 min" confirmation). Mirror for shorts. Stop = the line.
  Targets = {1.5, 2.618} x ATR(14) (Saty convention). Point-in-time clean:
  decision at bar `i` reads only bars `<= i` (enforced by a truncation-invariance
  unit test).
- **Validation** (`run_atr_trail_bounce.py`): grid-search the locked spec, run
  the event-driven `Backtester`, then bar-permutation MCPT
  (`analytics.permutation_test.validate_strategy`). PASS requires in-sample
  MCPT `p < 0.01` and walk-forward MCPT `p < 0.05`. A REJECT means **discard**,
  not re-tune (see `.claude/rules/ml-pitfalls-defense.md`).

## TOS Inputs (match these to reproduce the chart line)

| Input | Chart value | Notes |
|---|---|---|
| `trailType` | modified | HiLo/HRef/LRef true range |
| `ATRPeriod` | 5 | fast — hugs price closely |
| `ATRFactor` | 3.5 | band width multiplier |
| `firstTrade` | long | seeds initial state |
| `averageType` | WILDERS | Wilder smoothing |

## Locked param grid for MCPT

`factor in {3.0, 3.5, 4.0}`, `hold_bars in {0, 1, 2}`,
`touch_tol_atr in {0.0, 0.10}`, `atr_period = 5` (fixed). Lock before running;
do not iterate against the p-value.

## How to run (locally — needs data + venv)

```bash
cd engine
.venv/Scripts/python -m backtest.run_atr_trail_bounce --symbol MES --timeframe 1h
.venv/Scripts/python -m backtest.run_atr_trail_bounce --symbol MES --timeframe 5m \
    --data-file backtest/cache/MES_..._5m.csv
```

The web/CI container has no bars, so this is a local run. Unit tests
(`engine/tests/test_atr_trail_bounce_signals.py`) run anywhere — synthetic data.
