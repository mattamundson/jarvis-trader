# JARVIS TRADER -- Executive Strategy Briefing
*Updated: 2026-03-29 v2.3 | Strategy: STC (Schaff Trend Cycle) + ATR Stops/Targets + Regime Filter*

## The Verdict: NO-GO (Signal Redesign Required)

The STC-based strategy shows genuine in-sample edge on 4 instruments after fixing 8 critical backtesting bugs. However, **walk-forward validation fails on all 5 tested instruments** — every tested symbol shows Walk-Forward Efficiency below the 0.30 minimum threshold. The strategy is curve-fit to the 2024–2026 historical window and does not reliably generalize to new data. Live or paper trading is not recommended without fundamental signal improvements.

*v1.0 verdict was CONDITIONAL GO based on in-sample results and MGC walk-forward only. v2.0 revises to NO-GO after completing walk-forward validation for all 5 instruments.*

*v2.1 update: Regime-adaptive STC implemented. MNQ 1h WFE improved 0.24→0.34 (41% gain). Target WFE >0.40 before paper trading.*

*v2.2 update: Adaptive walk-forward completed for all 3 viable instruments. MGC 1d WFE surged 0.27→0.88 (EXCELLENT). MCL 1h worsened -0.16→-0.31. MGC 1d now qualifies for paper trading under adaptive regime mode.*

*v2.3 update: Combined filters tested. MNQ adaptive+volume WFE=-0.23 (volume filter destroys 1h futures signals — removes too many trades). SPY adaptive WFE improved -1.11→-0.71 but still overfit. Confirmed: MNQ best config remains adaptive-only at WFE=0.34. Volume filter: keep OFF for all futures 1h signals.*

---

## Corrected Performance (In-Sample, Per-Instrument Optimized)

| Rank | Symbol | TF | Trades | WR% | PF | Sharpe | Return | MaxDD | WFE | Verdict |
|------|--------|-----|--------|-----|------|--------|--------|-------|-----|---------|
| 1 | MGC | 1d | 47 | 51.1 | 2.60 | 2.04 | +34.4% | 3.0% | 0.27 | **OVERFIT** |
| 2 | SPY | 1h | 23 | 65.2 | 3.00 | -1.55 | +0.7% | 5.0% | -1.11 | **OVERFIT** |
| 3 | MNQ | 1h | 86 | 47.7 | 1.46 | 0.19 | +13.6% | 0.1% | 0.24 | **OVERFIT** |
| 4 | MCL | 1h | 65 | 60.0 | 1.83 | 0.15 | +0.2% | — | -0.16 | **OVERFIT** |
| 5 | MES | 1h | 21 | 42.9 | 0.96 | -0.12 | -4.0% | 0.1% | -0.17 | **OVERFIT** |

*Test period: Jun 2024 -- Mar 2026 (1h) / Jan 2025 -- Mar 2026 (1d). All returns gross of commissions ($2.50/contract + 1 tick slippage applied).*

---

## Walk-Forward Validation — Final Results

| Symbol | TF | Windows | OOS Profitable | Avg IS Return | Avg OOS Return | WFE | Verdict |
|--------|-----|---------|----------------|---------------|----------------|------|---------|
| MGC | 1d | 7 | 3/7 (43%) | +10.1% | +2.7% | **0.27** | FAIL (below 0.30) |
| MNQ | 1h | 6 | 3/6 (50%) | +19.8% | +4.8% | **0.24** | FAIL (below 0.30) |
| MCL | 1h | 6 | 2/6 (33%) | +6.1% | -1.0% | **-0.16** | FAIL (negative) |
| MES | 1h | 6 | 1/6 (17%) | +8.3% | -1.4% | **-0.17** | FAIL (negative) |
| SPY | 1h | 6 | 2/6 (33%) | +0.1% | -0.1% | **-1.11** | FAIL (deeply negative) |

**WFE thresholds:** >0.70 = Excellent, 0.50-0.70 = Good, 0.30-0.50 = Marginal, <0.30 = OVERFIT

**Key finding:** 73-90% of in-sample edge evaporates on unseen data across all instruments. The optimizer is exploiting historical market regimes (gold's 2024-2025 bull run, Nasdaq volatility surges) that do not persist across rolling 3-month periods.

### Adaptive Regime Results (with RegimeClassifier)

| Symbol | TF | Static WFE | Adaptive WFE | Change | OOS Sharpe | OOS PF | Verdict |
|--------|-----|-----------|--------------|--------|------------|--------|---------|
| MGC | 1d | 0.27 | **0.88** | +226% | 0.89 | 2.55 | EXCELLENT -- Paper-trade ready |
| MNQ | 1h | 0.24 | **0.34** | +41% | -0.06 | 1.05 | ACCEPTABLE -- Needs more work |
| MCL | 1h | -0.16 | **-0.31** | -94% | -0.48 | 0.81 | FAIL -- Adaptive hurts MCL |
| SPY | 1h | -1.11 | **-0.71** | +36% | -3.84 | 1.04 | FAIL -- Adaptive slightly better but still deeply overfit |

**Takeaway:** Regime-adaptive mode is highly effective for trending instruments (MGC gold). It improves MNQ modestly. It actively *hurts* MCL -- crude oil's regime transitions are too noisy for the current RegimeClassifier to capture. MCL should remain on the DO NOT TRADE list.

**MGC 1d adaptive detail:** 3 windows, 2/3 profitable OOS. Avg OOS return +6.7%, avg OOS Sharpe 0.89, avg OOS PF 2.55. Window 1 was exceptional (PF 5.97, Sharpe 4.45, +19.6% OOS). Window 3 had only 2 trades (insufficient data for the Jan-Mar 2026 period).

---

## Why the Strategy Fails Walk-Forward

1. **Regime dependency** — STC crossover signals are most effective during sustained trending periods. The optimizer selects parameters that work for the in-sample trend but the OOS period is often a different regime.

2. **Parameter instability** — Optimal STC thresholds shift dramatically window-to-window (e.g., MNQ Window 1 finds STC_OB=92 optimal; Window 2 finds STC_OB=83, regime_filter=false, completely opposite). No single parameter set generalizes.

3. **Thin trade counts** — 6-86 trades per 6-month window provides insufficient statistical power for the optimizer to distinguish signal from noise. With ~20 trades/window, the optimizer is essentially fitting to 5-10 independent observations.

4. **Single entry trigger** — STC crossover alone lacks the robustness of multi-factor confirmation. A regime filter exists but it's binary (on/off), not adaptive.

---

## Per-Instrument Parameter Profiles (Implemented in signals.py)

| Param | MGC 1d | MNQ 1h | MCL 1h | SPY 1h |
|-------|--------|--------|--------|--------|
| STC_OS | 17 | 15 | 15 | 15 |
| STC_OB | 88 | 92 | 83 | 88 |
| Stop ATR | 0.30 | 0.70 | 0.90 | 0.30 |
| T1 ATR | 1.50 | 1.00 | 1.50 | 1.00 |
| T2 ATR | 2.618 | 1.80 | 2.618 | 1.80 |
| Regime Filter | ON | ON | ON | ON |

These profiles are live in `engine/backtest/signals.py::INSTRUMENT_PARAMS` and used by `run_backtest.py`. They represent the best-known in-sample parameters but should NOT be treated as validated for live trading until walk-forward efficiency improves.

---

## Required Improvements Before Paper Trading

| Priority | Improvement | Addresses |
|----------|-------------|-----------|
| **1** | ✅ **Regime-adaptive parameter switching** — RegimeClassifier built. MGC 1d WFE 0.27→0.88 (EXCELLENT), MNQ 1h 0.24→0.34 (ACCEPTABLE), MCL 1h -0.16→-0.31 (STILL FAILS). Note: volume filter tested as combined filter — counterproductive for 1h futures (MNQ WFE drops 0.34→-0.23) | Root cause addressed for trending instruments |
| **2** | **Multi-timeframe confirmation** — require 4h/daily trend alignment before 1h entry | Counter-trend noise |
| **3** | ✅ **Volume confirmation** — Implemented (volume_filter=True available in walk-forward). Note: hurts 1h futures — not recommended for MNQ/MGC. MNQ adaptive+volume WFE=-0.23 vs adaptive-only 0.34 | Low-conviction signals |
| **4** | ✅ **News/event blackout** — Implemented (news_blackout.py, 81 events, low impact on WFE) | Gap-and-reverse losses |
| **5** | ✅ **Trailing ATR stop** — Investigated; grid search confirms no improvement for MGC 1d | 74% EOD exits leaving profits on table |

---

## Paper Trading Recommendation (Updated v2.2)

**MGC 1d with adaptive regime mode now qualifies for paper trading.** WFE=0.88 exceeds the 0.70 "Excellent" threshold.

1. **Trade MGC 1d adaptive only** — WFE 0.88, OOS Sharpe 0.89, OOS PF 2.55, max DD 1.5%
2. **Size at 0.50% risk/trade** (half standard 1%) for initial validation
3. **Kill threshold** — halt if 2 consecutive months show negative OOS return or WFE drops below 0.50
4. **Monitor WFE rolling** — recalculate WFE monthly with latest 3 windows
5. **Do NOT trade MCL or MNQ yet** — MCL adaptive WFE is deeply negative; MNQ is improving but not yet above 0.40

---

## Paper Trading — MGC 1d ACTIVE (as of 2026-03-29)

**APPROVED**: MGC 1d adaptive regime cleared walk-forward threshold.

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Capital | $25,000 | Micro gold sizing |
| Risk/trade | 0.25% | Conservative start |
| Stop | 0.30 ATR | Validated in WF |
| T1 Target | 1.00 ATR | Intraday reachable |
| Adaptive Regime | ON | Key to WFE=0.88 |
| Kill threshold | 3 consecutive months >50% below IS | Safety gate |

**Performance benchmark (in-sample):** Avg IS return 7.6%/3-month window.
Kill trigger: any 3-month window below 3.8% return (50% of 7.6% baseline).

**Config file:** `engine/backtest/paper_config.py` (MGC_PAPER_CONFIG)
**Tracker:** `engine/backtest/paper_tracker.py` (PaperTradeTracker)
**Trade log:** `engine/backtest/results/paper_trades_MGC.json`

---

## What NOT to Trade (Permanently Removed)

| Symbol | TF | PF | WFE | Reason |
|--------|-----|----|-----|--------|
| M2K | 1h | 0.64 | N/A | Consistently losing; Russell unsuitable for STC |
| M2K | 1d | 0.60 | N/A | Negative both timeframes |
| MCL | 1d | 0.21 | N/A | Catastrophic PF; zero targets hit on daily crude |
| MES | 1d | 0.75 | N/A | 36/51 trades exit at EOD — targets unreachable |
| MNQ | 1d | 0.79 | N/A | 43/57 EOD exits; daily NQ too volatile for intraday targets |
| MGC | 1h | 0.77 | N/A | Gold works daily only; hourly loses money |
| MES | 1h | 0.96 | -0.17 | Only 1/6 OOS windows profitable |
| SPY | 1h | 3.00 | -0.71 | Adaptive improved from -1.11 but still deeply overfit |

---

## Immediate Next Steps

1. **MNQ 1h needs WFE > 0.40 for paper trading approval** — currently 0.34. Close but not yet over the threshold.

2. **MTF filter walk-forward in progress** — multi-timeframe confirmation may push MNQ above the 0.40 threshold. This is the most promising remaining lever.

3. **Monitor MGC 1d paper trading performance monthly** — WFE=0.88 is excellent but real-world slippage/execution effects need validation.

4. **Consider extending history to 2022** — bear market data would provide more robust validation. Current 2024-2026 window is predominantly bull market, biasing parameters toward trend-following STC thresholds.

---

*Source data: 55+ result files in `engine/backtest/results/`. Includes optimizer JSONs, corrected backtests, sensitivity analysis (3 instruments), Monte Carlo (4 instruments, 10k sims each), and walk-forward validation (5 instruments, 6-7 windows each).*
