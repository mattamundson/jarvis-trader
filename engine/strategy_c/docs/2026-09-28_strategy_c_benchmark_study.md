# Strategy C+ — Corrected Backtest vs Benchmark Allocations

Date: 2026-09-28 · Window: 2017-03-17 → 2026-09-25 (498 weekly bars) · Driver: `docs/ablation/benchmarks.py` → `docs/ablation/benchmarks_results.json`
Follows `2026-09-27_vol_estimator_lookahead_audit.md` (one-week overlay lookahead).

## Method

- **Strategies.** Both engines run with overlays lagged one week (`overlay_lag_weeks=1`).
  - **v1** = `engine.py` with the exact production `live_signal.py` config (vol target 8%, 10d, floor 6, factor tilt, macro filter; COT is live-only).
  - **v2** = `engine_v2.py` full stack, with the lag in-engine.
- **Benchmarks.** Every rule-based benchmark trades on data through Friday t-1 only and pays 2 bps per unit of weekly turnover.
- **Primary metric: excess Sharpe over SHY.** SHY is the strategy's cash leg, and SHY alone has a raw Sharpe of about 1.2. Raw Sharpe therefore flatters any allocation that is about 50% SHY, including C+. The 2026-09-27 doc used raw Sharpe; the numbers below supersede it.
- **Vol-matched view.** Each series' excess over SHY is scaled to v2's realized vol (7.39%), so CAGR and drawdown compare at equal risk.
- **Significance.** Excess-Sharpe differences use an 8-week block bootstrap with 2,000 resamples.
- **OOS.** 2021-05 onward.

## Results (vol-matched to 7.39%)

| Series | CAGR | Excess Sharpe | MDD | DD 2020 | DD 2022 | OOS excess Sharpe |
|---|---|---|---|---|---|---|
| 40/60 XLK/SHY † | 9.23 | 0.999 | -14.26 | -8.55 | -12.72 | 0.892 |
| SPY buy & hold | 7.55 | 0.783 | -13.52 | -13.15 | -12.17 | 0.789 |
| 40/60 SPY/SHY | 7.52 | 0.783 | -13.43 | -13.06 | -12.12 | 0.789 |
| SPY 200d SMA timing | 7.60 | 0.780 | -11.64 | -6.43 | -9.29 | 0.830 |
| SPY vol-target 7% (21d) | 7.45 | 0.771 | -12.51 | -7.27 | -10.93 | 0.748 |
| 60/40 SPY/IEF | 7.19 | 0.753 | -16.01 | -12.16 | -14.81 | 0.642 |
| **C+ v1 (production, corrected)** | 6.50 | **0.654** | -12.06 | **-5.14** | **-8.32** | 0.789 |
| Risk parity SPY/IEF | 5.63 | 0.609 | -19.80 | -5.24 | -17.83 | 0.331 |
| **C+ v2 (corrected)** | 3.96 | **0.328** | -10.88 | -7.45 | -6.82 | 0.443 |
| Dual momentum GEM (12m) | 3.69 | 0.292 | -20.59 | -9.78 | -18.25 | 0.196 |

† XLK was chosen after the fact because it was the decade's best sector. Treat it as a hindsight ceiling, not an investable benchmark.

The raw, un-matched table is in `benchmarks_results.json`. The raw numbers for C+ are: v1 CAGR 7.28%, vol 8.67%, MDD -13.24%; v2 CAGR 3.96%, vol 7.39%, MDD -10.88%.

## Significance (excess Sharpe, strategy minus X)

| X | v1 − X (95% CI) | P(v1 better) | v2 − X (95% CI) | P(v2 better) |
|---|---|---|---|---|
| 40/60 SPY/SHY | -0.161 [-0.663, +0.326] | 0.27 | -0.486 [-0.983, +0.007] | 0.03 |
| SPY vol-target 7% | -0.137 [-0.583, +0.271] | 0.27 | -0.461 [-0.897, -0.042] | 0.01 |
| SPY 200d SMA | -0.139 [-0.578, +0.304] | 0.27 | -0.463 [-0.904, -0.035] | 0.02 |
| 60/40 SPY/IEF | -0.130 [-0.623, +0.372] | 0.31 | -0.455 [-0.965, +0.067] | 0.04 |
| C+ v2 | **+0.325 [+0.119, +0.522]** | 1.00 | — | — |

## Conclusions

1. **Do not promote v2 to live.** Once corrected, v2 is significantly worse than corrected v1. It is also worse than every simple risk-matched benchmark except dual momentum. The v2 layers (Kalman, risk parity, the DD breaker replacing the macro filter) earned their backtest edge largely from the lookahead.
2. **v1 has no demonstrated alpha.** v1 is statistically indistinguishable from simple 40/60 SPY/SHY and from SPY vol-targeting, and its point estimate is about 0.14–0.16 lower. Its one measurable edge is crisis behavior: at equal vol, the 2020 drawdown was -5.1% vs -13.1% for 40/60 and the 2022 drawdown was -8.3% vs -12.1%. That is a defensible reason to keep running it as a defensive allocation, but not evidence of edge.
3. **The as-built v1 backtest was also biased.** The same pattern exists in `engine.py`: with lag 0, raw Sharpe is 1.79 and CAGR 14.6%; with lag 1, it is 0.85 and 7.28%. Any v1 metric published before this change (dashboard `/v1/strategy_c/metrics`, earlier docs) overstates it by roughly 2x.
4. **Next research step (not in this PR).** Pre-register v1 against "SPY vol-target 7% (21d)" as the hurdle. That benchmark is simpler, replicable, and within noise of v1. Any future layer must beat it out of sample on excess Sharpe with a bootstrap CI that excludes 0.

## Caveats

- yfinance auto-adjusted closes. No borrow, slippage, or tax modelling beyond the 2 bps turnover cost.
- One path, 9.5 years, and only about 3 real stress episodes. The drawdown advantage rests on few independent events.
- [Assumption] The COT layer (live-only, not vectorized) is neutral on average; it is excluded from all backtests.
