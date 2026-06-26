# ES-NQ Spread Mean-Reversion — Backtest Verdict

**Date:** 2026-06-24
**Module:** `engine/backtest/spread_backtest.py` (standalone, TDD'd, 19 unit tests)
**Status:** **NO_TRADE — non-stationary edge (regime-concentrated, unproven persistence)**

## Hypothesis

MES and MNQ (both US equity-index futures) are cointegrated, so the log-spread
`ln(ES) - ln(NQ)` mean-reverts. Trade it dollar-neutral: when `|z|` is stretched,
short the rich leg / long the cheap leg; exit on reversion; hard-stop on divergence.

## Method (honesty controls)

- **Execution-agnostic**: dollar-neutral +-$1 long/short return book, so the measured
  edge is the spread's reversion, not contract granularity or fill modeling.
- **No look-ahead**: `z[t]` uses data through `t`; the implied position is *held into*
  `t+1` (`held = desired.shift(1)`).
- **FIXED a-priori params** (no per-window grid search): window=40, entry=2.0,
  exit=0.5, stop=4.0. Grid-mining is exactly what manufactures the small-sample
  mirages the family-FDR campaign keeps killing.
- **Realistic per-leg cost** in bps, charged on every position change, on both legs.
- **Two timeframes**: 1h (2024-04-26..2026-06-22, 12,339 aligned bars) and
  1d (2022-01-01..2026-03-28, 1,065 bars).

## Results

### Daily (1d) — sample-starved, no edge
Full-sample PF 1.01, Sharpe -0.04, 23 trades. WFO: 28 OOS trades total, median 2/window
— **far below** the 30-aggregate / 5-per-window floors. Verdict: INSUFFICIENT_SAMPLE.
Classic pairs runs daily, but ES-NQ at 2-sigma simply doesn't fire often enough on
4.2y of daily bars.

### Hourly (1h) — adequate sample, but the edge is non-stationary

| Metric | Value | Gate-v2 | Nominal |
|---|---|---|---|
| Pooled-OOS PF | 3.44 | — | — |
| pf_ci_lower (5000x bootstrap) | 2.45 | >=1.10 | PASS |
| p_edge (P[mean>0]) | 1.00 | >=0.95 | PASS |
| OOS trades | 256 (median 38/window) | >=30 | PASS |

**All three pooled thresholds PASS — but the pooled bootstrap is the wrong test here.**
The chronological split exposes why:

| Half | Period | n | PF | sum |
|---|---|---|---|---|
| H1 | 2024-07..2025-04 | 128 | **0.91** | **-0.022** |
| H2 | 2025-04..2026-01 | 128 | **7.96** | **+0.902** |

**100% of the profit is in the back half. The first ~9 OOS months lose money.**
Per-window: 2024-07 (PF 0.38) and 2024-10 (0.83) lose; the edge appears only from
2025-01 and explodes in 2025-07 (9.7), 2025-10 (6.8), 2026-01 (inf).

This is **not** a fat-tail / data-artifact mirage:
- Winsorizing top/bottom 2% keeps PF at 3.75 (edge is broad, not 1-2 spikes).
- Top-5 winners = only 19% of total P&L; winners are broadly ~+0.03 each.
- The time-concentration is **structural, not a parameter artifact** — H1 loses / H2
  wins across window=20 (H2 PF 4.8), 40 (7.96), and 60 (10.0).

So the H2 edge is a genuine, broad-based mean-reversion regime — but it exists **only
in the second half of the available sample.** With 26 months of 1h data (7 WFO windows)
we cannot distinguish a persistent structural shift in ES-NQ co-movement from a lucky
9-month run. The pooled bootstrap "passes" purely because it treats all 256 trades as
exchangeable, discarding the non-stationarity that the subperiod-stability gate exists
to catch.

### Cost sensitivity (1h)
p_edge (window-level) falls 0.71 -> 0.57 going from 2 -> 4 bp/leg; H2 PF degrades but
stays >1. Realistic all-in for a 2-leg micro spread is ~4-6 bp/leg, so even the H2 edge
is meaningfully cost-exposed.

## Verdict

**NO_TRADE.** The ES-NQ spread is the *most promising* thing tested in this campaign —
it's the first strategy with **both** adequate sample **and** a broad-based (non-thin)
edge — but it fails the spirit of the gate: the edge is non-stationary and its
persistence is unproven on the available history. Deploying on a back-loaded 9-month
run would be curve-fitting to a regime.

## What would resolve it (empirical, not more analysis)

1. **More 1h history** for ES-NQ to get >2 independent post-2025-07 windows — blocked
   by the same IB micro-futures ~26mo data-depth ceiling found in the cache-coverage
   work (Amo-gated IB Gateway backfill; deep 1h pulls return nothing for dated
   front-months).
2. **Forward paper dry-run** (dark) — the persistence question is about out-of-sample
   *time*, which only the calendar provides.
3. Optionally test 30m/15m to trade the same reversion with more bars inside the same
   26-month window (more trades, but same non-stationarity risk).

Reproduce:
```
.venv/Scripts/python -m backtest.spread_backtest --tf 1h        # full eval + splits
.venv/Scripts/python -m backtest.spread_backtest --tf 1h --cost-bps 6.0
.venv/Scripts/python -m backtest.spread_backtest --tf 1d
```
