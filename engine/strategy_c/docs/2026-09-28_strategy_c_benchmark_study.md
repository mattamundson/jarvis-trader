# Strategy C+ — Corrected Backtest vs Benchmark Allocations

Date: 2026-09-28 (revised after PR #960 review) · Window: 2017-03-17 → 2026-09-25 (498 weekly bars)
Driver: `docs/ablation/benchmarks.py` → `docs/ablation/benchmarks_results.json`
Follows `2026-09-27_vol_estimator_lookahead_audit.md` (one-week overlay lookahead).

## Method

- **Strategies.** Both engines run with overlays lagged one week (`overlay_lag_weeks=1`).
  - **v1** = `engine.py` with the exact production `live_signal.py` config (vol target 8%, 10d, floor 6, factor tilt, macro filter; COT is live-only).
  - **v2** = `engine_v2.py` full stack. Its absolute-momentum gate is now lagged too (review fix).
- **Costs.**
  - v1 has no native cost model. The harness charges it 2 bps per unit of effective (post-scale, incl. SHY) turnover, about 30 bps/yr, matching the benchmarks.
  - v2 uses its own `TransactionCostModel`. As of the review fix, spread and slippage apply to turnover, not position size, on post-scale weights.
  - Every rule-based benchmark trades on data through Friday t-1 and pays 2 bps per unit of turnover.
- **Primary metric: excess Sharpe over SHY.** SHY is the cash leg; SHY alone has a raw Sharpe of about 1.2, so raw Sharpe flatters any allocation that is about 50% SHY.
- **Vol-matched view.** Each series' excess over SHY is scaled to v2's realized vol (7.46%).
- **Drawdowns.** Computed on the full equity curve, so the 2020 and 2022 windows keep their pre-window peak (review fix).
- **Significance.** 8-week block bootstrap, 2,000 resamples.
- **OOS.** 2021-05 onward.

## Results (vol-matched to 7.46%)

| Series | CAGR | Excess Sharpe | MDD | DD 2020 | DD 2022 | OOS excess Sharpe |
|---|---|---|---|---|---|---|
| 40/60 XLK/SHY † | 9.30 | 0.999 | -14.34 | -9.29 | -14.34 | 0.892 |
| SPY buy&hold | 7.60 | 0.783 | -13.65 | -13.65 | -13.08 | 0.789 |
| 40/60 SPY/SHY | 7.57 | 0.783 | -13.56 | -13.56 | -13.03 | 0.789 |
| SPY 200d SMA timing | 7.65 | 0.780 | -11.71 | -7.14 | -10.48 | 0.830 |
| SPY vol-target 7% (21d) | 7.50 | 0.771 | -12.57 | -8.00 | -12.57 | 0.748 |
| 60/40 SPY/IEF | 7.23 | 0.753 | -16.11 | -12.49 | -16.11 | 0.642 |
| **C+ v1 (production, corrected)** | 6.27 | 0.620 | -12.24 | -6.40 | -12.24 | 0.752 |
| Risk parity SPY/IEF | 5.67 | 0.609 | -19.93 | -5.29 | -19.93 | 0.331 |
| **C+ v2 (corrected)** | 4.80 | 0.434 | -11.03 | -8.52 | -11.03 | 0.583 |
| Dual momentum GEM (12m) | 3.70 | 0.292 | -20.74 | -10.41 | -19.29 | 0.196 |

† XLK was chosen after the fact because it was the decade's best sector. Treat it as a hindsight ceiling, not an investable benchmark.

The raw, un-matched values are in `benchmarks_results.json`. For C+: v1 CAGR 6.96%, vol 8.67%, MDD -13.37%; v2 CAGR 4.80%, vol 7.46%, MDD -11.03%.

## Significance (excess Sharpe, strategy minus X)

| X | v1 − X (95% CI) | P(v1 better) | v2 − X (95% CI) | P(v2 better) |
|---|---|---|---|---|
| 40/60 SPY/SHY | -0.196 [-0.698, +0.290] | 0.23 | -0.378 [-0.855, +0.106] | 0.07 |
| SPY vol-target 7% (21d) | -0.172 [-0.617, +0.239] | 0.22 | -0.354 [-0.762, +0.050] | 0.04 |
| SPY 200d SMA timing | -0.173 [-0.610, +0.266] | 0.22 | -0.356 [-0.787, +0.071] | 0.06 |
| 60/40 SPY/IEF | -0.165 [-0.657, +0.337] | 0.26 | -0.347 [-0.832, +0.166] | 0.09 |
| C+ v1 | — | — | -0.182 [-0.369, +0.007] | 0.03 |

## Conclusions

1. **Do not promote v2 to live.** Corrected v2 trails corrected v1 by 0.18 excess Sharpe. The CI just includes 0, and P(v2 better) is 0.03. v2 also trails every simple risk-matched benchmark except dual momentum. It adds five layers of complexity for a probable loss.
2. **v1 has no demonstrated alpha.** v1 is statistically indistinguishable from 40/60 SPY/SHY and from SPY vol-targeting; its point estimate is about 0.17–0.20 lower and P(v1 better) ≈ 0.22.
   - Its one measured edge is the 2020 crash: -6.4% vs -13.6% for 40/60 at equal vol.
   - In 2022 it was no better (-12.2% vs -13.0%).
   - That is one independent stress event. Treat it as weak evidence of a defensive property, not an edge.
3. **The as-built v1 backtest was also biased.** Before costs, v1 raw Sharpe falls from 1.79 to 0.85 and CAGR from 14.6% to 7.28% once overlays are lagged. Any v1 metric published before this change (dashboard `/v1/strategy_c/metrics`, earlier docs) overstates it by roughly 2x.
4. **Next research step (not in this PR).** Pre-register "SPY vol-target 7% (21d)" as the hurdle. Any C+ layer must beat it out of sample on excess Sharpe with a bootstrap CI that excludes 0. If v1 can't clear it, the honest production choice is the simpler benchmark.

## Revision log

- **2026-09-28 (initial).** v2 excess Sharpe was 0.328 and v2 − v1 was -0.33 [-0.52, -0.12], a significant gap. v1 was reported with a 2022 drawdown edge. Both were affected by defects found in review:
  - The v2 cost model charged execution cost on whole positions. That biased against v2; fixing it raises v2 by about 0.1.
  - v2's absolute-momentum gate was unlagged, biasing for v2.
  - v1 was run without costs, biasing for v1.
  - Crisis-window drawdowns dropped the pre-window peak, understating 2020 and 2022 drawdowns for every series.

## Caveats

- yfinance auto-adjusted closes. No tax or borrow modelling.
- One path, 9.5 years, and about 3 real stress episodes.
- [Assumption] The COT layer (live-only, not vectorized) is neutral on average; it is excluded from all backtests.
- Known v2 defects that remain unfixed are listed in PR #960 (live-path only, or spec deviations; v2 is research-only).
