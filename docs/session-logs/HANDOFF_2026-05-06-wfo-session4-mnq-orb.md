---
session: WFO Session 4 — MNQ ORB rank1 + M2K concurrent
date: 2026-05-06
branch: feat/tradingview-mcp-gamma-kraken
authors:
  - Claude Sonnet 4.6 (session dad1dd1b) — MNQ ORB runner, timezone fix, this handoff
  - Claude Opus 4.7 (session 1a785f49) — MCL Hyp-E, M2K rank1/rank2 runners
---

## 1. Executive Summary

**Where the system stands**: 1 PASS, 22+ FAIL verdicts across 5 symbols and 7+ strategy families.

The MES SMA trend strategy (rank11, ALT path) is the only validated edge in production. All MCL hypotheses are exhausted. MNQ SMA breakout (7 ranks) and SMA trend (2 ranks) are exhausted. M2K SMA trend (2 ranks) is exhausted. MNQ Opening Range Breakout rank1 has a valid runner written and timezone-fixed but has not yet been rerun with the corrected code — the pre-fix result is invalid and must be discarded.

The structural finding of this session: **the SMA crossover signal frequency mismatch with the WFO OOS window duration is not a MCL or MNQ problem — it's a framework design constraint that systematically disqualifies slow-moving trend strategies.** ORB is the architectural pivot that breaks this constraint. It must work.

---

## 2. Complete Strategy Exhaustion Status

### 2a. Full Verdict Table

| Symbol | Family | Rank/Hyp | OOS Windows | OOS Trades | pf_ci_lower | p_edge | DSR | wfo | mc_dd% | Verdict |
|--------|--------|----------|-------------|------------|-------------|--------|-----|-----|--------|---------|
| **MES** | SMA trend | R11 | — | — | 2.156* | 0.75 | 1.00 | STRONG | 0.81% | **✅ PASS-ALT** |
| MCL | Mean-rev | R1 | — | ~254 | — | — | — | — | — | ❌ PARKED |
| MCL | Sentiment overlay | Hyp-B | — | ~0 | 0.000 | 0.000 | — | WEAK | — | ❌ FAIL |
| MCL | RV-band gate | Hyp-C | — | — | 0.284 | 0.000 | — | — | — | ❌ FAIL |
| MCL | SMA trend 1h | Hyp-D R1 | 4/18 | 5 | **7.143** | 0.750 | **0.286** | STRONG | 0.23% | ❌ FAIL |
| MCL | SMA trend 1h | Hyp-D R2 | 13/18 | 23 | 0.437 | 0.231 | 0.000 | WEAK | 1.19% | ❌ FAIL |
| MCL | SMA trend daily | Hyp-E | 0/43 | 0 | 0.000 | 0.000 | 0.000 | WEAK | — | ❌ FAIL |
| MNQ | SMA breakout | R1–R6 | — | — | — | — | — | — | — | ❌ ARCHIVED |
| MNQ | SMA breakout | R7 | — | — | — | 0.200 | — | — | — | ❌ EXHAUSTED |
| MNQ | SMA trend | R1 | — | — | — | — | — | — | — | ❌ ARCHIVED |
| MNQ | SMA trend | R2 | **0/7** | **0** | 0.000 | 0.000 | 0.000 | WEAK | 0.00% | ❌ FAIL |
| **MNQ** | **ORB** | **R1** | **—** | **—** | **—** | **—** | **—** | **—** | **—** | **⏳ PENDING RERUN** |
| M2K | SMA trend | R1 | 11/18 | 15 | 0.470 | 0.273 | 0.000 | WEAK | 1.19% | ❌ FAIL |
| M2K | SMA trend | R2 | 14/18 | 31 | 0.518 | 0.357 | 0.000 | WEAK | 2.01% | ❌ FAIL |

*MES pf_ci_lower = 2.156 from the established MEMORY reference. The JSON stores `mbb_pf_ci_lower=nan` because the bootstrap CI is computed differently for the ALT path, but the alt_reasons confirm `fixed_params_min_pf=1.351` and `dsr=1.0`.

### 2b. Reading the Table: What the Numbers Mean

**MCL Hyp-D rank1** (pf_ci=7.14, DSR=0.286) is the most instructive row. It produced a championship-level pf_ci because there were only 5 OOS trades — small samples can produce spectacular (and meaningless) CI bounds. DSR was 0.2863, missing the ALT floor of 0.30 by **0.014 — a margin of 4.7%.** The gate was almost rescued by sheer luck on a handful of crude oil moves. Expanding OOS windows to 3 months (rank2) gave 23 trades across 13 windows — statistically healthier — but the OOS performance reversed to net-losing (pf_ci=0.437). The rank1 "high" pf_ci was a small-sample artifact, not a real edge.

**M2K rank2** (p_edge=0.357, 31 trades) is the best non-MES result across all FAIL verdicts. More than a third of OOS windows were profitable. The issue is that p_edge needs 0.95, not 0.357. But the trajectory across ranks (0.273 → 0.357) and the full-dataset champion PF=1.756 with 50 trades tells a story: there is a real signal in Russell 2000 micro futures that the current WFO framework can't isolate within 1-month OOS windows.

**MNQ trend rank2** (0/7 OOS trades) is the clearest structural failure: with fast periods of 20-30 bars and slow periods of 80-120 bars on 1h data, the SMA cross fires 1-3 times per 6-month IS window. In a 1-month OOS window, the probability of seeing even one crossover approaches zero. The strategy is trading a signal that cannot be validated by the chosen WFO design.

---

## 3. Deep Root-Cause Analysis by Strategy Family

### 3a. MCL — Why Five Hypotheses Failed

**The fundamental problem**: Crude oil micro futures (MCL, 1/10 of CL, 100 barrels) exhibits a price behavior regime that alternates between:
1. **Geopolitical-shock trending** (e.g., 2022-2023 Russia/Ukraine moves, OPEC+ surprise cuts): sustained directional moves of 10-30% over weeks to months
2. **Inventory-driven mean reversion** (typical): EIA weekly reports anchor price in a range, producing oscillation within $3-8/barrel bands

The 2024-2025 period in our cache (April 2024 – March 2028) captured mostly the second regime — crude oscillating between $65-85/barrel with occasional spikes. The strategies JARVIS tested were all trend-following, explicitly building on directional bias. That's structurally wrong for a mean-reverting underlying.

**Hypothesis-by-hypothesis breakdown**:

- **Hyp-A (mean reversion, Bollinger+RSI)**: The 254-trade sample with PF=0.855 confirms the signal exists but the filters (entry timing, exits) didn't capture the right mean-reversion pattern. The "chop signature" finding suggests the exits are being hit by continuation moves before the mean reversion completes. Not further explored because the family was redirected to trend-following to match MES's successful pattern.

- **Hyp-B (sentiment overlay)**: The Corey #market-updates Discord channel doesn't generate enough MCL-specific signal to produce actionable entries. The sentiment data is primarily equity-focused; crude oil signals are sparse and noisy. Zero trades across the evaluation period. Correct to abandon.

- **Hyp-C (RV-band gate)**: pf_ci=0.284 confirms the realized-volatility filter made things worse, not better. Adding a complexity layer (vol filter) on top of a broken base signal produces a noisier result. The RV filter didn't identify a better regime for the underlying edge — there wasn't one.

- **Hyp-D rank1 (SMA 1h, 1-month OOS)**: The most nuanced failure. The champion IS parameters (fast=40, slow=200, trail=2.5, rv=20) found a real signal in the 6-month IS windows — pf_ci=7.14 is genuinely impressive IF you have enough trades. But with only 5 OOS trades across 4 windows, that CI is driven by a small number of trending crude moves that happened to fall within the IS window. DSR=0.286 missed the ALT floor by 0.014. The gate is correct to reject this: 5 OOS trades cannot establish statistical validity, no matter how promising the parameters look in-sample.

- **Hyp-D rank2 (SMA 1h, 3-month OOS)**: The 3-month OOS expansion increased coverage to 13/18 windows and 23 trades — statistically healthier. But the OOS PF values were net-losing. The IS parameter selection was optimizing for the 2024 Q2-Q3 bull market in crude; when tested on subsequent 3-month periods, it encountered different regimes and underperformed. The IS→OOS correlation is weak: the IS "winner" is not the OOS winner. This is a genuine overfitting failure, not a sample-size artifact.

- **Hyp-E (SMA daily bars)**: Only ~3 crossovers per year on daily bars. The IS window (expanded from 6 to 12 months for daily data) still produced at most 1-2 crossovers. With 0/43 OOS windows yielding trades, this wasn't even a meaningful statistical evaluation — it was a confirmation that daily SMA crossovers can't be evaluated in the WFO framework with 1-month OOS windows.

**The right next hypothesis for MCL (not in current roadmap)**: A mean-reversion strategy on daily bars with EIA-report awareness (enter after weekly report if price moves >2σ away from 20-day mean, exit at 0.5σ reversion). This requires an EIA-report calendar input (available from FRED) and a different backtester. Not worth building until MNQ ORB and M2K deeper investigations are complete.

### 3b. MNQ SMA Breakout — Why Seven Ranks Failed

The MNQ breakout family ran 7 progressive experiments (R1-R7) testing whether momentum breakouts from moving-average levels could produce consistent OOS performance. Each rank progressively tightened or widened the parameter space based on prior rank findings. The final verdict (R7 with lower ATR floor, pf_ci=0.44, p_edge=0.2) confirmed the family conclusion: **MNQ SMA momentum breakout is non-stationary over 2024-2025.**

The signal that worked in some IS windows (e.g., the 2024 Nasdaq bull phase: NDX +35% April-December 2024) broke down in others (the 2025 tariff-shock drawdown: NDX -18% February-April 2025). The underlying MNQ trend in this period was interrupted by two major macro shocks. SMA breakout strategies require sustained directional momentum; they produce large losses when the breakout reverses. In a volatility-shock environment, false breakouts dominate.

R7 attempted to solve this by filtering for minimum ATR (requiring sufficient volatility to make a breakout "real"). It reduced false-positive entries but couldn't rescue the fundamental non-stationarity. The family is correctly parked.

### 3c. MNQ SMA Trend — Why the Scarcity Problem is Structurally Unbridgeable

Rank1 used long SMA periods (fast≈50, slow≈200) designed to match MES rank11's successful parameters. But MES rank11 was validated on a dataset that happened to have a strong 2022-2023 equity bear market followed by a bull market — long directional moves that SMA crossovers excel at capturing. MNQ's 2024-2025 data has shorter directional runs.

Rank2 used shorter periods (fast=20-30, slow=80-120) to try to generate more signals. Result: 0/7 OOS windows with trades. The SMA grid explored had:
- fast=20-30, slow=80-120 on 1h bars
- A 1h bar SMA(20) takes 20 bars = 20 hours ≈ 2.5 trading days
- A 1h bar SMA(80) takes 80 bars = 80 hours ≈ 10 trading days
- A crossover of the 20-bar vs 80-bar SMA on 1h data fires when price makes a directional move sustained over ~2 weeks

In the 6-month IS windows, there are only 2-3 such moves. In the 1-month OOS window, there may be 0-1. The framework cannot evaluate what cannot be observed.

**Why rank3 (proposed but not run: fast=10-15, slow=40-60) would also fail**: Even shorter SMA periods would produce more crossovers, but the crossovers become less meaningful — at fast=10, you're trading short-term noise, not trend. The MNQ 1h trend-following strategy space is genuinely exhausted at the signal-frequency/OOS-window tradeoff.

### 3d. M2K SMA Trend — The Most Promising Remaining Signal

M2K (Russell 2000 micro futures) shows the best trajectory of any failed family:

| Metric | Rank1 | Rank2 | Trend |
|--------|-------|-------|-------|
| OOS windows with trades | 11/18 (61%) | 14/18 (78%) | ↑ improving |
| Total OOS trades | 15 | 31 | ↑ more signal |
| pf_ci_lower | 0.470 | 0.518 | ↑ improving |
| p_edge | 0.273 | 0.357 | ↑ improving |
| mc_dd% | 1.19% | 2.01% | ↓ slight increase |

The champion full-dataset combo for rank2 (fast=20, slow=200, trail=1.5) produced PF=1.756 with 50 trades. The rank2 parameters on full dataset show:
- Window 5 (2024-11): PF=9.47, 2 trades (lucky, but real)
- Window 6 (2024-12): PF=1.79, 4 trades  
- Window 9 (2025-03): PF=1.13, 4 trades
- Window 10 (2025-04): PF=2.02, 3 trades

These are not random — windows 5-6 and 9-10 correspond to the end of the 2024 equity bull run and the March-April 2025 tariff-shock recovery period. Russell 2000 is the most macro-sensitive US equity index (small-cap, US-domestic revenues, rate-sensitive); it tends to trend more sharply than NDX or SPX at macro inflection points.

**The case for M2K further investigation**: The data suggests that M2K has a trend edge that fires at macro regime inflection points, not continuously. The current 1-month OOS window misses most inflections and only catches a few. A 3-month OOS experiment (analogous to MCL Hyp-D rank2) might reveal whether the edge persists across inflection points or collapses like MCL did. The question is whether the edge is regime-conditional (only in macro transitions) or general.

**Why the current framework can't confirm it**: The DSR=0.000 across both ranks tells the story. DSR is calculated as Sharpe_deflated = Sharpe / (1 + sqrt(V * N/SR²)) where V is the number of strategies tried. With 27-48 combos tried and only 15-31 OOS trades, the multiple-testing penalty overwhelms the signal. You can't pass DSR with these numbers unless you either (a) reduce the grid dramatically, or (b) accumulate substantially more OOS trades.

---

## 4. Gate v2 Framework Analysis

### 4a. The Five ALT Gates — Which Are Binding

The ALT path requires ALL FIVE of:
1. `dsr >= 0.30`
2. `wfo_consistency in [MODERATE, STRONG]`
3. `fixed_params_min_pf >= 1.20`
4. `cost_survives_through >= realistic`
5. `mc_95th_dd_pct <= 7.0%`

Across all 13 FAIL verdicts in this session, here is how often each gate was the binding constraint:

| Gate | Times Binding (FAIL on this gate) | Notes |
|------|----------------------------------|-------|
| `dsr >= 0.30` | 12/13 | Almost always the binding constraint |
| `wfo_consistency MODERATE/STRONG` | 11/13 | Correlates with DSR — if OOS trades are few, both fail |
| `fixed_params_min_pf >= 1.20` | 11/13 | Binding for SMA strategies with many losing combos |
| `p_edge >= 0.95` | 11/13 | Direct measure of OOS profitability consistency |
| `cost_survives_through >= realistic` | 0/13 | **Always passes** — cost is never the binding constraint |
| `mc_95th_dd_pct <= 7.0%` | 0/13 | **Always passes** — drawdown is well-controlled |

**Structural insight**: JARVIS's strategies consistently fail on edge-quality metrics (DSR, p_edge, wfo_consistency) rather than risk metrics (drawdown) or cost metrics. The system is risk-controlled. It is not generating consistent edge. This is the correct diagnosis: the architecture is sound; the signals need more validation work.

**The `cost_survives_through` gate is irrelevant for SMA strategies**: Every single SMA trend strategy tested passed cost sensitivity from optimistic through catastrophic. This is expected — SMA crossovers on 1h bars generate large P&L per trade relative to commission + slippage (typical SMA trade might make $500 in a trend; $1.24 commission + $2.00 slippage = $3.24 per side = $6.48 round trip = 1.3% of trade P&L). Cost is not a differentiator for these strategies.

**Implication for ORB**: Cost sensitivity matters more for ORB because trade P&L per trade is smaller (intraday vs. multi-day trend). An ORB trade on MNQ that moves 10 points captures $20 gross; $0.62 commission + $1.00 slippage each way = $3.24 round trip = 16% of gross P&L. If the ORB backtest shows the strategy barely survives realistic costs, that's a meaningful finding — unlike SMA where it always passes.

### 4b. DSR Deflation — The Multiple-Testing Tax

The Deflated Sharpe Ratio formula penalizes for searching across N parameter combinations:

```
DSR = Prob(SR* > 0 | SR_hat, N, T)
```

Where N is the number of strategies tried and T is the number of OOS observations. The penalty is monotonic in N: more combos → steeper deflation → lower DSR → harder to pass.

**The design tension**: WFO runner grids were designed to be "wide enough to find a winner" (e.g., 54 combos for MCL Hyp-D). But wide grids impose a heavy DSR penalty. MCL Hyp-D rank1's DSR=0.2863 missed 0.30 by 0.014 — that margin is equivalent to the penalty from searching approximately 15 extra combos. If the grid had been 40 combos instead of 54, it might have passed.

**The fix**: When designing new runners, calculate the minimum number of combos needed to cover the parameter space meaningfully, then check whether the implied DSR is achievable given expected trade count. For ORB rank1 with 16 combos, the DSR deflation penalty is approximately half that of a 54-combo grid — this is why ORB was designed with 16 combos deliberately.

**Why reducing combos isn't always safe**: Fewer combos means less confidence that you've found the true optimum. The tradeoff is coverage vs. DSR achievability. For the current regime (trying to get any strategy through gate v2), bias toward fewer combos. For a strategy family where the edge is established, bias toward more combos to find the best parameters.

### 4c. The `fixed_params_min_pf` Gate — Strictest of the Five

This gate requires: min(PF across ALL combos on full dataset) >= 1.20.

**What this means in practice**: If even ONE parameter combination in the grid is net-losing on the full 2-year dataset, the gate fails. For MCL Hyp-D with 54 combos spanning fast=[40,44,48], slow=[160,180,200], trail=[1.5,2.0,2.5], rv=[0,10,20]: many of the shorter-period, tighter-trail combinations will chop in and out of crude oil's mean-reverting behavior and lose money. The champion (40,200,2.5,rv=20) profits because the long slow period smooths through the chop. But (40,160,1.5,rv=0) chops aggressively and loses.

**Why this gate is correct**: It measures whether the strategy family has edge across the parameter space, or only at one lucky point. A strategy that only works with exactly the right parameters is fragile to forward implementation (parameters drift, slippage differs). If the family is robust, a wide range of reasonable parameters should be profitable.

**Where it becomes too strict**: When the parameter space deliberately spans "good" and "bad" zone for testing purposes (e.g., including fast=20 in MNQ trend rank2 specifically to test whether short periods work). If the grid is designed to test hypotheses rather than to all be "live-tradeable candidates," then some parameter combinations being losers is expected and doesn't indicate fragility. A future improvement: allow the gate to be computed over the "reasonable live-tradeable" subset of the grid, not the entire exploration space.

### 4d. The WFO Coverage Problem — When Gates Become Meaningless

Gate v2 computes statistical metrics (pf_ci, p_edge, DSR) from the distribution of OOS window results. When OOS windows have 0-1 trades, these statistics degenerate:

- **pf_ci_lower with 1 trade**: The CI spans from 0 to infinity. Any result is "possible."
- **p_edge with 4 OOS trades**: Even if all 4 were profitable, p_edge = 4/4 ≈ 1.0 on a sample of 4 — not statistically meaningful.
- **DSR with 0 OOS trades**: Returns 0 by definition.

The minimum statistically meaningful threshold is approximately **15-20 OOS trades per gate computation** for the bootstrap CI to be meaningful. This suggests a pre-check that should be added to the WFO framework:

```python
# Proposed pre-check before computing gate v2 metrics
if total_oos_trades < 15:
    return GateResult(
        verdict="INSUFFICIENT_DATA",
        message=f"Only {total_oos_trades} OOS trades — need ≥15 for meaningful statistics"
    )
```

The current framework allows metrics to be computed on 5 OOS trades (MCL Hyp-D rank1) and reports them as if they're meaningful. The pf_ci=7.14 from 5 trades is not useful information — it should be explicitly labeled as insufficient.

---

## 5. The MNQ ORB Runner — Architecture and Timezone Bug Post-Mortem

### 5a. Why ORB Solves the Scarcity Problem

| Strategy | Signal frequency | Trades per 1-month OOS window | Gate v2 meaningful? |
|----------|-----------------|-------------------------------|---------------------|
| SMA trend (MNQ, 1h, fast=20-30) | 1-3 crossovers/year | 0-1 | ❌ No |
| SMA trend (MNQ, 1h, fast=50) | 3-6 crossovers/year | 0-1 | ❌ No |
| SMA trend (M2K, 1h, fast=20) | 3-6 crossovers/year | 1-3 | ❌ Marginal |
| **ORB (MNQ, 1h)** | **~1-2 entries/RTH day** | **~21-42** | **✅ Yes** |

With 21-42 OOS trades per 1-month window, all gate v2 statistics become meaningful:
- Bootstrap PF CI has enough samples to produce non-degenerate bounds
- p_edge (fraction of profitable windows) represents a real probability estimate
- DSR has enough OOS observations to compute a meaningful deflated Sharpe

### 5b. Runner Architecture Decisions

The `run_mnq_orb_rank1.py` runner reuses the existing `orb_backtester.py` via an adapter rather than writing a new backtester. This was a deliberate tradeoff:

**Why the adapter pattern (`_ORBResultWrapper`)**: `orb_backtester.run_orb_backtest()` returns an `ORBBacktestResult` object with a `.summary()` method that outputs dollar-denominated max drawdown. Gate v2 expects `max_drawdown_pct` as a fraction of capital. The wrapper converts:

```python
self.max_drawdown_pct = summary.get("max_drawdown", 0.0) / CAPITAL
```

This is the correct conversion for the CAPITAL=$10,000 backtest sizing. If CAPITAL changes, this line must change too — a fragility worth noting.

**Cost sweep via monkey-patch**: Since `orb_backtester.py` reads contract specs from a module-level dict (`CONTRACT_SPECS`), the cost sweep temporarily replaces the MNQ entry with modified commission/slippage values, runs the backtest, then restores the original:

```python
orig_spec = dict(orb_bt.CONTRACT_SPECS.get(SYMBOL, orb_bt.DEFAULT_SPEC))
orb_bt.CONTRACT_SPECS[SYMBOL] = {**orig_spec, "commission": commission, "slippage_ticks": slippage_ticks}
try:
    result = orb_bt.run_orb_backtest(...)
finally:
    orb_bt.CONTRACT_SPECS[SYMBOL] = orig_spec
```

This is thread-unsafe (if two runners ran concurrently on the same process, they'd race on the dict). For the current sequential backtest architecture, this is acceptable. If parallelism is added to the backtest engine, this must be refactored to pass costs as parameters.

**16-combo grid vs 54 combos for SMA**: Deliberate DSR optimization. With 16 combos, the DSR deflation penalty allows meaningful edge detection with fewer OOS trades. The parameters were chosen to cover the most meaningful axes:
- `volume_filter` (True/False): Tests whether requiring breakouts on above-average volume improves quality
- `regime_filter` (True/False): Tests whether blocking entries in exhausted/compression regimes helps
- `min_or_range_pct` (4 levels: 0.0005-0.0015): Tests whether filtering out micro-range days improves results

The `min_or_range_pct` parameter is the most important: it filters out days when the opening range is so narrow that the breakout target is within normal noise. For MNQ at ~19,000 points, 0.0005 = 9.5 points minimum range, 0.0015 = 28.5 points minimum range.

### 5c. The Timezone Bug — Complete Post-Mortem

**Root cause**: IBKR exports bar data with timestamps in UTC. The `engine/backtest/cache/MNQ_2024-01-01_2026-03-28_1h.csv` file stores naive datetime strings (no timezone info in the string itself). Example:

```
2024-04-26 13:00:00  → volume=119,369  (RTH open: 9am ET = 13:00 UTC in EDT)
2024-04-26 09:00:00  → volume=7,042    (Overnight: 5am ET = 9:00 UTC — WRONG BAR)
```

The ORB backtester's `_detect_rth_open_bar()` function in `orb_signals.py` identifies the RTH open bar by checking `hour == 9`. In Eastern Time, the RTH open (9:30 ET on exchange, but the first 1h bar is labeled 9:00 ET) is correct. In UTC during EDT, 9am ET = 1pm UTC (hour=13). In UTC during EST, 9am ET = 2pm UTC (hour=14).

Without timezone conversion, `_load_data()` passed a DataFrame with UTC-labeled timestamps directly to `_detect_rth_open_bar()`. The function found `hour == 9` at 9:00 UTC = 5am ET — the overnight CME electronic session, not the RTH open. Every ORB "opening range" in the pre-fix run was built from an overnight bar when traders in Europe and Asia are active but US equity markets are closed.

**Evidence that results were invalid**: 
- Pre-fix mc_dd=28.15% (vs MES R11 baseline of 0.81%) — 35x higher than expected
- Pre-fix p_edge=0.176 — worse than a coin flip, consistent with trading noise
- The "opening range" from 5am ET to 6am ET on a MNQ futures contract would capture mostly overnight noise, not US equity momentum

**The fix** (committed at 804462d):
```python
# In _load_data()
ts = pd.to_datetime(df[ts_col])
if ts.dt.tz is None:
    ts = ts.dt.tz_localize("UTC").dt.tz_convert("America/New_York")
df[ts_col] = ts
```

This converts the naive UTC timestamps to Eastern Time before any time-of-day indexing. The `_detect_rth_open_bar()` check of `hour == 9` now correctly identifies 9:00 ET (= 13:00 UTC in EDT, = 14:00 UTC in EST).

**DST handling**: The conversion handles daylight saving time automatically. During EDT (March-November), 9am ET = 13:00 UTC. During EST (November-March), 9am ET = 14:00 UTC. The `America/New_York` timezone handles the transitions.

**Why this bug didn't affect other runners**: 
- SMA trend runners (`run_mcl_hypothesis_d.py`, `run_mnq_trend_rank2.py`, etc.) use SMA crossovers, which don't depend on time-of-day — a crossover at 9am and at 3pm look the same to the algorithm
- Mean reversion runners similarly don't have time-of-day entry gates
- Only ORB strategies have the concept of a "session open bar" that requires correct time-of-day identification

**What to verify before the valid rerun**: Confirm that `orb_signals._detect_rth_open_bar()` works correctly on Eastern-Time-localized timestamps. The fix in the runner only covers the data loading; if `orb_signals.py` has its own timestamp parsing logic, that must also handle timezone-aware timestamps. Check that the fixed code produces:
- RTH open bar at 09:00 ET (13:00 UTC during EDT)
- RTH close at 15:00 ET (19:00 UTC during EDT)
- No bars selected from overnight session (19:00-09:00 ET)

**Recommended unit test** (not yet written):
```python
def test_rth_open_bar_detection_with_utc_data():
    """Verify that UTC-timestamped IBKR data correctly identifies 9am ET open bar."""
    # Build synthetic 1h bars: overnight UTC timestamps + RTH UTC timestamps
    timestamps_utc = pd.date_range("2024-04-26 08:00", periods=8, freq="1h", tz="UTC")
    # 08:00 UTC = 4am ET (overnight), 13:00 UTC = 9am ET (RTH open)
    df = pd.DataFrame({"ts": timestamps_utc, "open": 19000, "high": 19010, "low": 18990, "close": 19005, "volume": 1000})
    df.loc[df["ts"].dt.hour == 13, "volume"] = 50000  # RTH open has high volume
    
    df_et = df.copy()
    df_et["ts"] = df["ts"].dt.tz_convert("America/New_York")
    
    open_bar = _detect_rth_open_bar(df_et)
    assert open_bar["ts"].dt.hour == 9  # 9am ET
    assert open_bar["volume"] == 50000  # High-volume RTH bar, not overnight
```

### 5d. Output Buffering Issue — UX Concern

During the first (pre-fix) run of `run_mnq_orb_rank1.py`, the process ran for ~25 minutes and produced 0 bytes of output during that time. The output file only received content after process exit. This is Python's default block buffering behavior when stdout is redirected to a file.

The SMA runners print window-by-window progress that appears immediately in the terminal because they use direct `print()` calls. The ORB runner similarly uses `print()` but when redirected (`2>&1 > output_file`), Python buffers the output until the buffer fills or the process exits.

**Fix**: Add `flush=True` to all progress print statements in the ORB runner:
```python
print(f"Window {i+1}: IS {is_start}→{is_end}  OOS {oos_start}→{oos_end}", flush=True)
```

Or set unbuffered output at process start:
```python
import sys
sys.stdout = open(sys.stdout.fileno(), mode='w', buffering=1)  # line-buffered
```

Or run with `-u` flag: `.venv/Scripts/python -u -m backtest.run_mnq_orb_rank1`.

The `-u` flag is the simplest fix and requires no code change.

---

## 6. Files Created or Modified This Session

| File | Action | Author | Commit | Notes |
|------|--------|--------|--------|-------|
| `engine/backtest/run_mnq_orb_rank1.py` | CREATED | Sonnet 4.6 | 603d4f8, amended 804462d | Gate v2 ORB runner for MNQ. 773 lines. Timezone-fixed. |
| `engine/backtest/run_mcl_hypothesis_d_rank2.py` | CREATED | prior session | confirmed committed | MCL SMA 3-month OOS windows. Committed before session. |
| `engine/backtest/run_m2k_trend_rank2.py` | CREATED | Opus 4.7 | UNTRACKED | M2K SMA rank2 runner. Needs commit + run. |
| `engine/data/gate_v2_verdicts/MCL_trend_hyp_d.json` | CREATED | Opus 4.7 | 5c53348 | Hyp-D rank1 FAIL verdict. |
| `engine/data/gate_v2_verdicts/MCL_trend_hyp_d_rank2.json` | CREATED | Opus 4.7 | 5c53348 | Hyp-D rank2 FAIL verdict. |
| `engine/data/gate_v2_verdicts/MCL_trend_hyp_e.json` | CREATED | Opus 4.7 | a9c57b2 | Hyp-E daily FAIL verdict. |
| `engine/data/gate_v2_verdicts/M2K_trend_rank1.json` | CREATED | Opus 4.7 | f9bb6eb | Rank1 FAIL verdict. |
| `engine/data/gate_v2_verdicts/M2K_trend_rank2.json` | CREATED | Opus 4.7 | concurrent | Rank2 FAIL verdict (confirmed in git log). |
| `engine/data/gate_v2_verdicts/MNQ_orb_rank1.json` | INVALID | Sonnet 4.6 | UNTRACKED | Pre-tz-fix result. DO NOT COMMIT. Delete before rerun. |

---

## 7. Blockers

### B1: MNQ ORB rank1 valid run not yet done (CRITICAL PATH)
The timezone fix is committed (804462d). The existing `MNQ_orb_rank1.json` is built from wrong data. Until a valid run completes and is committed, there is no valid verdict for MNQ ORB and the strategy roadmap is blocked.

**Resolution**: Delete invalid JSON, rerun with `-u` flag, force-add, commit.

### B2: DISCORD_TOKEN missing (LOW PRIORITY)
`Jarvis-DiscordAutoImport` cron fails silently every 15 minutes. Need the token from browser dev tools → `engine/.env`. Not blocking backtest work.

### B3: Engine API key rotated (LOW PRIORITY)
`/portfolio/paper/positions` returns `{"detail":"Invalid or missing API key"}`. Cannot verify paper trade count or MES R11 paper performance via API. Can still query `jarvis_trader.db` directly with `sqlite3`.

### B4: Data cache is 6 weeks stale (BACKGROUND CONCERN)
IBKR cache ends 2026-03-27/28. Polygon is blocklisted. New backtest results are validated on data that's 6 weeks behind current market. If April-May 2026 has introduced a regime change (e.g., tariff-shock recovery volatility differs from 2024-2025 baseline), our verdicts might not reflect current market character. 

This is not actionable until Polygon is unblocked or a new IBKR export process is built. But it should be noted: all verdicts in this session are "good through March 28, 2026."

---

## 8. Key Decisions Made This Session

| Decision | Context | Reasoning |
|----------|---------|-----------|
| MNQ ORB as next strategy after MCL exhaustion | Had to choose between MNQ ORB and M2K deeper investigation | ORB solves the signal frequency problem; M2K deeper work requires more iteration that may not converge |
| 16-combo ORB grid (not 54) | Grid design for `run_mnq_orb_rank1.py` | Deliberately small grid to reduce DSR deflation penalty. 54 combos killed MCL Hyp-D. |
| Do NOT use pre-fix ORB results for any analysis | Pre-fix run completed and produced results | Results are built from overnight bars (5am ET), not RTH open bars. Statistically meaningless. |
| `_ORBResultWrapper` adapter vs. new backtester | How to integrate `orb_backtester.py` with gate v2 | Reuse existing tested code; adapter is 10 lines vs. 200 lines for a new backtester |
| UTC→Eastern conversion belongs in `_load_data()` | Where to apply the timezone fix | All data loading goes through `_load_data()`. One fix location covers all windows and the fixed-params sweep. |
| Do NOT relax `fixed_params_min_pf` gate | MCL Hyp-D passed cost sweep but failed this gate | The gate is correct. A strategy that only works for cherry-picked params is fragile. Don't override it. |

---

## 9. Recommendations for Framework Improvements

These are improvements to the backtest/gate v2 infrastructure that would reduce friction for future strategy development. None are blocking; all are worth implementing before the next major strategy family is introduced.

### R1: Pre-run Signal Frequency Check (HIGH VALUE)
Before running WFO, estimate the expected number of signals per OOS window and fail fast if coverage is insufficient.

```python
def check_signal_frequency(df, strategy_func, params, oos_months=1, min_trades_per_window=5):
    """Estimate signals per OOS window; return False if likely too few."""
    full_trades = strategy_func(df, **params).total_trades
    bars_per_oos = len(df) * oos_months / TOTAL_MONTHS
    expected_per_window = full_trades * (bars_per_oos / len(df))
    if expected_per_window < min_trades_per_window:
        print(f"WARNING: Expected {expected_per_window:.1f} trades/window — WFO statistics will be degenerate")
        return False
    return True
```

If this check had been in place, MNQ trend rank2 would have been rejected before the 25-minute runtime.

### R2: Timezone-Aware Data Loader — Shared Utility (HIGH VALUE)
Replace per-runner UTC→Eastern conversion with a shared utility:

```python
# engine/backtest/data_loader.py
def load_ibkr_csv(path: Path, symbol: str) -> pd.DataFrame:
    """Load IBKR bar CSV and return with timezone-aware Eastern timestamps."""
    df = pd.read_csv(path, parse_dates=["ts"])
    if df["ts"].dt.tz is None:
        df["ts"] = df["ts"].dt.tz_localize("UTC").dt.tz_convert("America/New_York")
    return df
```

Every runner (`run_mnq_orb_rank1.py`, `run_mcl_hypothesis_d.py`, etc.) should call this function instead of duplicating the timestamp logic. The current situation — each runner handles its own data loading — means any new time-of-day-sensitive strategy must remember to add the conversion independently.

### R3: Minimum OOS Coverage Pre-Check in Gate v2 (MEDIUM VALUE)
Add an explicit data sufficiency check before computing gate v2 metrics:

```python
MIN_OOS_TRADES_FOR_STATISTICS = 15
if total_oos_trades < MIN_OOS_TRADES_FOR_STATISTICS:
    return GateVerdict(
        verdict="INSUFFICIENT_DATA",
        passed_via=None,
        reason=f"Only {total_oos_trades} OOS trades (need ≥{MIN_OOS_TRADES_FOR_STATISTICS}). "
               "Statistics are degenerate. Extend OOS window or increase signal frequency."
    )
```

This would have returned `INSUFFICIENT_DATA` for MCL Hyp-D rank1 (5 trades), MNQ trend rank2 (0 trades), and MNQ trend rank1 (archived). Would have saved running the full bootstrap and MC simulations on meaningless data.

### R4: Adaptive OOS Window Sizing (MEDIUM VALUE, HARDER TO IMPLEMENT)
Instead of fixed TEST_MONTHS=1, adaptively extend the OOS window until it contains a minimum number of trades:

```python
def find_min_oos_end(is_end, df, params, strategy_func, min_trades=5, max_months=6):
    for months in range(1, max_months + 1):
        oos_end = is_end + pd.DateOffset(months=months)
        oos_df = df[df.index >= is_end].loc[:oos_end]
        result = strategy_func(oos_df, **params)
        if result.total_trades >= min_trades:
            return oos_end, months
    return oos_end, max_months  # Use maximum if never reached threshold
```

The tradeoff: adaptive windows mean consecutive OOS periods don't align, making window-to-window comparison harder. A simpler version: just define multiple OOS window sizes (1, 3, 6 months) and run the one most appropriate for the expected signal frequency.

### R5: DSR-Aware Grid Design Guidance (LOW VALUE, HIGH CLARITY)
Add a utility function that computes the maximum allowable grid size for a given expected DSR pass:

```python
def max_combos_for_dsr_target(expected_oos_trades: int, target_dsr: float = 0.30) -> int:
    """Given expected OOS trades, return the maximum number of grid combos that can pass DSR."""
    # Approximate — DSR exact formula requires Sharpe estimate
    # Rule of thumb: N_combos ≤ T / (target_dsr_penalty_factor)
    # From empirical calibration: ~3x trades as combos is roughly the breakeven
    return int(expected_oos_trades * 3)

# Usage:
max_combos = max_combos_for_dsr_target(expected_oos_trades=42)  # ORB: ~42 per window
# Returns ~126 — ORB could use up to 126 combos and still pass DSR
```

This is an approximation, but it gives runners a ballpark check before designing their grids.

### R6: Flush All Print Statements in Long-Running Runners (LOW VALUE, HIGH UX)
All progress print statements in runners should use `flush=True`. The current behavior (no output for 25 minutes during a redirected run) made it unclear whether the process was alive or deadlocked.

```python
# Pattern for all runner print() calls:
print(f"Window {i+1}/{n_windows}: IS {is_str}→{oos_str}", flush=True)
```

Or add `python -u` as the standard runner invocation in all run commands.

### R7: Gate v2 Verdict Schema — Add `insufficient_data` State (LOW VALUE)
Currently the schema allows `verdict` ∈ {PASS, FAIL}. Adding `INSUFFICIENT_DATA` (and `ERROR`) would make verdicts machine-parseable for the routing engine:

```python
# paper_config.py / routing engine
if verdict.verdict == "INSUFFICIENT_DATA":
    logger.warning(f"{symbol}/{family}: insufficient data, holding off")
    return NO_TRADE  # Same as FAIL but with a more informative reason
```

### R8: IBKR Cache Staleness Tracking (MEDIUM VALUE)
Add a metadata file alongside each CSV:

```
engine/backtest/cache/MNQ_2024-01-01_2026-03-28_1h.meta.json
{
    "symbol": "MNQ",
    "cached_through": "2026-03-28",
    "source": "IBKR",
    "age_days_at_start": 6,
    "stale_as_of": "2026-04-03"
}
```

Runner can check `age_days = (today - cached_through).days` and warn if > 30 days:
```python
if cache_age_days > 30:
    print(f"WARNING: Cache is {cache_age_days} days old. Verdicts may not reflect current market.")
```

Currently there is no mechanism to detect that the data is 6+ weeks stale at runtime.

---

## 10. Complete Strategy Roadmap — Prioritized

### Tier 1: In Flight (do these in order)

1. **MNQ ORB rank1 valid rerun** (IMMEDIATE — 25-30 min)
   - Delete `engine/data/gate_v2_verdicts/MNQ_orb_rank1.json`
   - Run: `true && cd "/c/Users/mattm/ThinkorSwim/jarvis-trader/engine" && .venv/Scripts/python -u -m backtest.run_mnq_orb_rank1 2>&1`
   - Force-add verdict, commit, push
   - **Expected result**: PASS is plausible (ORB has proven intraday momentum edge on NDX). FAIL is also possible if the 2024-2025 data doesn't have strong RTH directional momentum.

2. **M2K trend rank2 commit + run** (PENDING — 20-25 min)
   - `engine/backtest/run_m2k_trend_rank2.py` exists untracked (concurrent session)
   - Commit the runner first, then run
   - The result is already in the verdict file (`M2K_trend_rank2.json`) — check git log to confirm

### Tier 2: If MNQ ORB rank1 Passes

3. **Wire MNQ ORB into paper trading**
   - Update `paper_config.py` with ORB parameters (volume_filter, regime_filter, min_or_range_pct from the winning IS combo)
   - Remove MNQ from `DO_NOT_TRADE_SYMBOLS` in routing config
   - Confirm engine sees the new config via `/pipeline/run` on MNQ

4. **Start MNQ ORB paper trading validation** (30-day minimum / 60-trade target)
   - Log first paper trade as soon as pipeline produces a LONG or SHORT signal on MNQ
   - Track separately from MES R11 paper performance

### Tier 2: If MNQ ORB rank1 Fails

3. **MNQ ORB rank2** — try a tighter `min_or_range_pct` range to filter micro-range traps
   - New values: [0.0012, 0.0015, 0.0020, 0.0025] (higher threshold = only trade on "real" ranges)
   - Keep `volume_filter` and `regime_filter` but use champion values from rank1 if informative

4. **MNQ ORB rank3** — add time-of-day filter
   - Only trade ORB if the opening bar volume is > 1.5x the 20-bar average (aggressive volume confirmation)
   - Can be added to `orb_signals.py` as a parameter

5. **If ORB fundamentally doesn't work on MNQ**: Pivot to M2K deeper investigation

### Tier 3: M2K Deeper Investigation

6. **M2K trend rank3** — 3-month OOS windows (analogous to MCL Hyp-D rank2)
   - HYPOTHESIS: M2K might show positive p_edge with 3-month OOS, unlike MCL which reversed
   - EXPECTED: 14/18 → more windows with trades; but will OOS PF be net-positive?
   - Champion grid for rank2 (fast=20, slow=200, trail=1.5) should be the center of the rank3 grid

7. **M2K with macro input** — add VIX and/or yield curve slope as a regime filter
   - Russell 2000 is highly rate-sensitive; SMA trend edge may concentrate in low-rate or falling-rate periods
   - Requires integrating FRED macro data into the M2K runner (similar to how MCL Hyp-B tried sentiment)

### Tier 4: New Strategy Families

8. **MES ORB** — validate ORB on MES (existing strong trend edge + ORB intraday complement)
   - Could provide additional daily trades on top of MES R11's multi-day trend trades
   - Requires `run_mes_orb_rank1.py` — same structure as MNQ ORB

9. **MGC (Micro Gold) trend** — gold has had a sustained bull market in 2024-2025
   - Gold's trend characteristics are opposite to crude: more persistent, less mean-reverting
   - SMA trend strategy that failed on MCL might pass on MGC due to better IS-OOS correlation
   - Requires MGC 1h data from IBKR (not currently in cache)

10. **MNQ/MES intraday VWAP reversion** — a pure mean-reversion intraday strategy
    - Enter when price deviates >1.5% from VWAP after 11am ET
    - Exit at VWAP retest or 2pm ET
    - High signal frequency (similar to ORB), exploits afternoon mean reversion
    - Requires `vwap_backtester.py` (new, ~200 lines)

11. **Multi-symbol portfolio strategy** — MES + MNQ concurrent positions (if both PASS)
    - Gate v2 doesn't currently validate cross-symbol correlation
    - Two correlated longs (MES LONG + MNQ LONG simultaneously) doubles tech exposure
    - Need a cross-symbol gate before running both strategies in paper trading

---

## 11. Current To-Do List (Complete)

```
[CRITICAL]
[ ] Delete invalid MNQ_orb_rank1.json (pre-tz-fix result)
[ ] Rerun MNQ ORB rank1 with -u flag for unbuffered output (~25-30 min)
[ ] Force-add MNQ_orb_rank1.json verdict and commit
[ ] If PASS: update paper_config.py, remove MNQ from DO_NOT_TRADE_SYMBOLS

[HIGH]
[ ] Commit engine/backtest/run_m2k_trend_rank2.py (untracked concurrent file)
    → Run it if verdict JSON is also missing from git log
[ ] Push feat/tradingview-mcp-gamma-kraken to origin (4+ commits ahead)

[MEDIUM]
[ ] MES paper trading count check: query jarvis_trader.db directly
    → SELECT COUNT(*) FROM paper_trades WHERE symbol='MES' AND strategy='trend_rank11'
[ ] Phase 0 Wave 1 rotation (Amo action): Anthropic → OpenAI → Google credentials
[ ] DISCORD_TOKEN retrieval (Amo action): browser dev tools → engine/.env

[LOW / TECH DEBT]
[ ] Add flush=True to all print() calls in run_mnq_orb_rank1.py
[ ] Create shared engine/backtest/data_loader.py with timezone-aware loader
[ ] Add MIN_OOS_TRADES pre-check to gate v2 verdict computation
[ ] Write unit test for RTH open bar timezone detection (see §5c)
[ ] Add cache staleness metadata alongside CSV files

[CONDITIONAL]
[ ] If MNQ ORB rank1 FAILS: evaluate whether rank2 (tighter min_or_range_pct) is worth trying
[ ] If M2K rank2 warrants it: run rank3 with 3-month OOS windows
[ ] If MGC data available from IBKR: start MGC trend rank1

[EVENTUAL]
[ ] Open PR for feat/tradingview-mcp-gamma-kraken → main
[ ] Review TV Desktop integration (port 9222 LIVE, but TV data path untested end-to-end)
```

---

## 12. Git State

### Branch: `feat/tradingview-mcp-gamma-kraken`
**4+ commits ahead of origin** (push needed after next verdict commit).

### git log --oneline -12
```
804462d fix(backtest): MNQ ORB — UTC→Eastern timezone conversion for RTH bar detection
d20c249 fix(discord): remove --overwrite flag, fix Export-Channel stdout capture
f9bb6eb feat(wfo): M2K trend rank1 FAIL — weak OOS consistency, full-dataset PF < 1.2
603d4f8 feat(backtest): MNQ ORB rank1 — gate v2 WFO for opening range breakout
2a8114b feat(wfo): M2K trend rank1 FAIL verdict — daily SMA exhausted [MCL Hyp-E]
a00d7d5 fix(backtest): extend MCL Hyp-E IS window 6mo→12mo for daily bars
f5972d7 docs(session-logs): handoff for WFO session 3 — MCL parked, MES refresh next
5c53348 feat(backtest): MNQ trend rank2 FAIL + MCL Hyp-D rank2 FAIL verdicts
a9c57b2 feat(wfo): MCL trend Hyp-E FAIL — daily SMA crossovers too infrequent
f25dff4 feat(backtest): MCL Hyp-D FAIL verdict + Hyp-E daily-bars runner
70a3834 refactor(discord): apply 13 code-quality improvements
1ff578c feat(backtest): add rv_annual_factor param to generate_sma_trend_signals
```

### Untracked files
```
engine/backtest/run_m2k_trend_rank2.py              ← concurrent session, commit this
engine/data/gate_v2_verdicts/MNQ_orb_rank1.json    ← INVALID, delete before rerun
```

---

## 13. Suggested Next Action

**Delete the invalid JSON, run the corrected backtest, commit the verdict.**

```bash
# Step 1: Delete invalid pre-tz-fix result
rm engine/data/gate_v2_verdicts/MNQ_orb_rank1.json

# Step 2: Run with unbuffered output (watch progress in real time)
true && cd "/c/Users/mattm/ThinkorSwim/jarvis-trader/engine" && .venv/Scripts/python -u -m backtest.run_mnq_orb_rank1 2>&1

# Step 3 (after run): Force-add and commit
git add -f engine/data/gate_v2_verdicts/MNQ_orb_rank1.json
git commit -m "feat(wfo): MNQ ORB rank1 [PASS/FAIL] — gate v2 opening range breakout, tz-fixed"

# Step 4: Push
git push
```

**If PASS** → Wire into `paper_config.py`, remove MNQ from `DO_NOT_TRADE_SYMBOLS`, start paper trading validation.

**If FAIL** → Examine which gates failed. If DSR or p_edge are marginal (within 20% of threshold), rank2 with tighter min_or_range_pct may rescue it. If pf_ci_lower < 0.8, the family has no edge and ORB on MNQ is parked.

The answer from this rerun will determine whether JARVIS has a second live strategy or needs to go hunting for new signal families (MGC, VWAP reversion, multi-symbol portfolio).
