# VBT MES 54-Combo Parameter Sweep — Benchmark & Results

Date: 2026-08-18
Script: `engine/backtest/vbt_mes_sweep.py`
Cross-check: `engine/backtest/validate_vbt_vs_engine.py`
Dep file: `engine/requirements-vbt.txt`
Status: VERIFIED — PASS, target < 5 min

## Purpose

Benchmark vectorbt as the parameter-sweep engine for the MES SMA-trend strategy,
replacing the slow per-combo Python loop (`trend_signals.py`) with a vectorized,
column-broadcast grid. Target: 54 combos on the MES 1h deep cache in under
5 minutes wall time.

## Method

- Data: `engine/backtest/cache/MES_2015-01-01_2026-08-16_1h.csv`
  (42,826 bars, 2019-05-05 → 2026-08-14, 7.28 yr span)
- Grid: fast=[40,50,60] x slow=[100,150,200,250,300,350] x atr_mult=[1.5,2.0,2.5] = 54
  combos (includes certified live champion 50/200/2.0)
- Signal logic: exact port of `trend_signals.generate_sma_trend_signals`
  (golden-cross LONG entry, death-cross OR ratcheting ATR(14) trail exit;
  same bar ordering, same slow-SMA-validity guard)
- Execution: `vbt.Portfolio.from_signals`, longonly, 1 contract, $0.62 fixed
  fee/side, close-of-bar fills
- Metrics: honest CAGR (real span), honest Sharpe (deflated by actual
  trades/yr), PF, win rate, max DD — per JARVIS 2026-08-17 metric audit
- Venv: Python 3.12 + numpy 1.26.4 + numba 0.59.1 + vectorbt 0.28.2
  (see `requirements-vbt.txt`; vectorbt is intentionally NOT in
  requirements-core.txt — engine modules guard the import)

## Validation

Bar-by-bar entry/exit match vs engine `trend_signals.py` (run
`backtest/validate_vbt_vs_engine.py`):

| combo | entries | exits | match |
|-------|---------|-------|-------|
| 50/200/2.0 | 136 | 136 | PASS |
| 60/200/2.0 | 122 | 122 | PASS |
| 40/100/1.5 | 229 | 229 | PASS |

Note: signal sets match exactly; absolute PnL/CAGR conventions differ from the
engine backtester (close fills, no R:R≥1.2 filter, no T1/T2/T3 static targets,
vectorbt equity model). These are IN-SAMPLE sweep numbers for screening, NOT
gate-v2-certified verdicts — DSR must be re-deflated at the true campaign
trial count before any promotion (JARVIS metric-defect audit, 2026-08-17).

## Timing

Steady state (numba cache warm), 42,826 bars x 54 combos:

| phase | seconds |
|-------|---------|
| load | 0.67 |
| signals | 4.25 |
| portfolio_build | 25.69 |
| metrics | 9.55 |
| **total** | **40.22** |

First run (cold, includes vectorbt numba JIT): 86.75s total.
Target < 300s: **PASS** (40.2s steady state, 4.2x headroom).

## Results (sorted by honest CAGR)

Full table: `docs/reports/vbt_mes_54combo_results.csv`.

Top 5:

| fast | slow | atr_mult | total_return | honest_cagr | trades | win_rate | PF | honest_sharpe | max_dd |
|------|------|----------|--------------|-------------|--------|----------|-----|---------------|--------|
| 50 | 200 | 2.0 | 1.16% | 0.158% | 136 | 49.3% | 1.91 | 0.98 | -0.18% |
| 40 | 200 | 2.0 | 1.07% | 0.146% | 142 | 47.2% | 1.93 | 0.98 | -0.27% |
| 60 | 200 | 2.0 | 1.03% | 0.140% | 122 | 50.0% | 2.04 | 1.03 | -0.19% |
| 60 | 200 | 2.5 | 0.83% | 0.114% | 122 | 48.4% | 1.63 | 0.75 | -0.29% |
| 40 | 150 | 2.0 | 0.82% | 0.112% | 164 | 43.3% | 1.50 | 0.68 | -0.35% |

Bottom: fast=100-window combos are the worst (60/100/2.5: -0.047% CAGR,
PF 0.90). Slow=100 combos lose across the board.

### Reading

- The whole grid is economically marginal: honest CAGR within ±0.5%, best
  honest Sharpe ≈ 1.03 (60/200/2.0) — consistent with the 2026-08-17 audit
  finding that no MES config has a true Sharpe > 1; DSR at campaign trial
  count collapses these.
- The certified live champion (50/200/2.0) sits at the top of the grid by
  honest CAGR — good sanity signal that the sweep reproduces the known edge
  ranking (engine fixed-params CAGR for 50/200/2.0 is -0.26% under the
  engine's stricter fill/filter convention; sign difference is convention,
  not signal — see Validation note).
- Runtime: vectorbt broadcasts all 54 combos as columns of one Portfolio;
  the Python state-machine loop (signals phase, 4.3s) is the only non-vectorbt
  code and dominates less than the portfolio build.
