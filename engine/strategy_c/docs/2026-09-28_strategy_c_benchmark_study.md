# Strategy C+ — Corrected Backtest vs Benchmark Allocations

Date: 2026-09-28 (revision 3, after two PR #960 review rounds) · Window: 2017-03-17 → 2026-09-25 (498 weekly bars)
Driver: `docs/ablation/benchmarks.py` → `docs/ablation/benchmarks_results.json`
Follows `2026-09-27_vol_estimator_lookahead_audit.md` (one-week overlay lookahead).

## Method

- **Strategies.** Both engines run with overlays lagged one week (`overlay_lag_weeks=1`) and start on 2016-02-26, so the 53-week momentum WARMUP (100% SHY) ends before the comparison window opens.
  - **v1** = `engine.py` with the exact production `live_signal.py` config.
  - **v2** = `engine_v2.py` full stack. Its absolute-momentum gate and the regime consumed by its controls are lagged too.
- **Costs.**
  - v1 has no native cost model. The harness charges it 2 bps per unit of effective turnover (about 29 bps/yr), the same as the benchmarks.
  - v2 uses its `TransactionCostModel`: spread and slippage on turnover of post-scale weights. Expense ratios are off, because auto-adjusted prices already net them out.
  - Every rule-based benchmark trades on data through Friday t-1.
- **Primary metric: excess Sharpe over SHY.** SHY is the cash leg; raw Sharpe flatters any allocation that is about 50% SHY.
- **Vol-matched view.** Each series' excess over SHY is scaled to v2's realized vol (7.93%).
- **Drawdowns.** Computed on the full equity curve, keeping the pre-window peak.
- **Significance.** 8-week block bootstrap, 2,000 resamples.
- **OOS.** 2021-05 onward.

## Results (vol-matched to 7.93%)

| Series | CAGR | Excess Sharpe | MDD | DD 2020 | DD 2022 | OOS excess Sharpe |
|---|---|---|---|---|---|---|
| 40/60 XLK/SHY † | 9.77 | 0.999 | -14.92 | -9.96 | -14.92 | 0.892 |
| **C+ v1 (production, corrected)** | 8.19 | 0.812 | -12.16 | -6.32 | -12.16 | 0.752 |
| SPY buy&hold | 7.96 | 0.783 | -14.58 | -14.58 | -13.60 | 0.789 |
| 40/60 SPY/SHY | 7.92 | 0.783 | -14.48 | -14.48 | -13.54 | 0.789 |
| SPY 200d SMA timing | 8.01 | 0.780 | -12.22 | -7.64 | -10.88 | 0.830 |
| SPY vol-target 7% (21d) | 7.85 | 0.771 | -13.04 | -8.63 | -13.04 | 0.748 |
| 60/40 SPY/IEF | 7.57 | 0.753 | -16.79 | -13.34 | -16.79 | 0.642 |
| **C+ v2 (corrected)** | 7.47 | 0.731 | -11.22 | -6.09 | -10.64 | 0.688 |
| Risk parity SPY/IEF | 5.90 | 0.609 | -20.79 | -5.64 | -20.79 | 0.331 |
| Dual momentum GEM (12m) | 3.81 | 0.292 | -21.82 | -11.14 | -20.14 | 0.196 |

† XLK was chosen after the fact because it was the decade's best sector. Treat it as a hindsight ceiling.

Raw values for C+: v1 CAGR 9.28%, vol 9.31%, MDD -13.37%; v2 CAGR 7.47%, vol 7.93%, MDD -11.22%.

## Significance (excess Sharpe, strategy minus X)

| X | v1 − X (95% CI) | P(v1 better) | v2 − X (95% CI) | P(v2 better) |
|---|---|---|---|---|
| 40/60 SPY/SHY | -0.005 [-0.486, +0.486] | 0.49 | -0.091 [-0.645, +0.437] | 0.38 |
| SPY vol-target 7% (21d) | +0.019 [-0.360, +0.376] | 0.55 | -0.066 [-0.465, +0.299] | 0.38 |
| SPY 200d SMA timing | +0.017 [-0.416, +0.437] | 0.53 | -0.068 [-0.518, +0.361] | 0.38 |
| 60/40 SPY/IEF | +0.026 [-0.484, +0.535] | 0.54 | -0.060 [-0.622, +0.492] | 0.42 |
| C+ v1 | — | — | -0.085 [-0.269, +0.098] | 0.19 |

## Conclusions

1. **v1 matches simple allocations; it does not beat them.** Once the lookahead, warm-up and costs are handled, v1's excess Sharpe is 0.812.
   - That is statistically identical to 40/60 SPY/SHY (0.783) and SPY vol-target 7% (0.771): every difference is within ±0.03, with CIs of about ±0.4–0.5.
   - Its 2020 drawdown was shallower at equal vol (-6.3% vs -14.5%). 2022 was similar (-12.2% vs -13.5%).
   - That is one independent stress event: weak evidence of a defensive property, not alpha.
2. **Do not promote v2.** v2 − v1 = -0.085 [-0.269, +0.098], P(v2 better) = 0.19. The data can't separate them, so v2's five extra layers show no benefit, and they carry the known unfixed defects listed in PR #960. Absent evidence of improvement, the simpler engine stays live.
3. **The as-built backtests were heavily biased.** Before costs, v1's native `run_backtest` falls from raw Sharpe 1.79 / CAGR 14.6% to 0.85 / 7.28% once overlays are lagged. Previously published C+ metrics (dashboard `/v1/strategy_c/metrics`, earlier docs) overstate performance by roughly 2x.
4. **Next research step (not in this PR).** Pre-register "SPY vol-target 7% (21d)" as the hurdle. Any C+ layer must beat it out of sample with a bootstrap CI that excludes 0. So far nothing does. The honest framing of C+ today is "a reasonable defensive allocation with more moving parts than its equal-performing simple alternatives".

## Revision log

- **rev 1** (initial): v2 − v1 was -0.33 [-0.52, -0.12], and v1 was reported with 2020 and 2022 drawdown edges.
- **rev 2** (review round 1):
  - v2 cost model: execution cost moved to turnover and post-scale weights.
  - v2 absolute-momentum gate lagged.
  - v1 charged turnover costs.
  - Drawdowns computed from the full curve.
  - Result: v2 − v1 = -0.18 [-0.37, +0.01].
- **rev 3** (review round 2):
  - The comparison window previously contained the strategies' 53-week WARMUP (100% SHY). This was the largest single bias, and it was against both strategies.
  - v2 controls consumed the unlagged regime.
  - The v2 cost model double-counted expense ratios.
  - Research drivers now pass `save_results=False` (they previously overwrote the live-signal JSON).
  - Result: the numbers above.

## Caveats

- yfinance auto-adjusted closes. No tax or borrow modelling.
- One path, 9.5 years, and about 3 real stress episodes.
- [Assumption] The COT layer (live-only, not vectorized) is neutral on average; it is excluded from all backtests.
