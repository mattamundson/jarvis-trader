# JARVIS TRADER -- Executive Strategy Briefing
*Updated: 2026-04-01 v2.9 | Strategy: STC (Schaff Trend Cycle) + ATR Stops/Targets + Regime Filter*

## The Verdict: CONDITIONAL GO — 2 Instruments Approved for Paper Trading

The STC-based strategy clears walk-forward validation on **2 of 5 instruments** after fixing all bugs. **MCL 1h WFE=0.82 (EXCELLENT)** and **MNQ 1h WFE=0.57 (GOOD, adaptive regime only)** both exceed the 0.50 GOOD threshold. MGC 1d, MES 1h, and SPY 1h are all **CLOSED** — strategy redesign required for each. MES 1h specifically confirmed definitively incompatible with STC+ATR in both static (WFE=0.09) and adaptive (WFE=0.00) modes.

*v1.0 verdict was CONDITIONAL GO based on in-sample results and MGC walk-forward only. v2.0 revises to NO-GO after completing walk-forward validation for all 5 instruments.*

*v2.1 update: Regime-adaptive STC implemented. MNQ 1h WFE improved 0.24→0.34 (41% gain). Target WFE >0.40 before paper trading.*

*v2.2 update: Adaptive walk-forward completed for all 3 viable instruments. MGC 1d WFE surged 0.27→0.88 (EXCELLENT). MCL 1h worsened -0.16→-0.31. MGC 1d now qualifies for paper trading under adaptive regime mode.*

*v2.3 update: Combined filters tested. MNQ adaptive+volume WFE=-0.23 (volume filter destroys 1h futures signals — removes too many trades). SPY adaptive WFE improved -1.11→-0.71 but still overfit. Confirmed: MNQ best config remains adaptive-only at WFE=0.34. Volume filter: keep OFF for all futures 1h signals.*

*v2.4 update: Extended history validation reveals MGC 1d WFE=0.27 with 15 windows (2022-2026). Previous WFE=0.88 was small-sample bias (3 windows, 2025 gold bull run only). Bear market data (2022-2023) exposes underlying parameter instability. Paper trading downgraded from EXCELLENT to CONDITIONAL-CAUTION. Continuing at 0.25% risk with 3-month monitoring period.*

*v2.5 update: SPY 1h and MES 1h re-optimized (US-005/US-007). SPY PF 3.00->3.79, Sharpe -1.55->-1.43 (T2 tightened 1.80->1.618). MES PF 0.96->1.69, Sharpe -0.12->0.09, return -4.0%->+0.1% (stop 0.70->0.50, T1 1.00->2.00, regime OFF). INSTRUMENT_PARAMS in signals.py now includes per-instrument regime_filter as 7th tuple element.*

*v2.6 update: CRITICAL — Optimizer kwarg bug discovered and fixed. Extra kwargs (adaptive_regime, volume_filter, mtf_filter) were silently passed to _compute_signals() causing TypeError on every call, caught by bare except → None returns for ALL walk-forward runs after these kwargs were added to walk_forward.py. With bug fixed: MGC 1d corrected WFE=0.14 (was 0.27 — OVERFIT confirmed, paper trading HALTED). MNQ 1h corrected WFE=0.48 with extended start 2024-04-26 (was 0.34 from buggy run — now ACCEPTABLE, crossed 0.40 threshold). MGC paper trading suspended pending MTF filter validation.*

*v2.8 update (2026-03-30): SPY 1h re-run with corrected optimizer (post kwarg-bug fix). All 6 optimization windows returned SKIP (no valid parameter combinations for SPY on hourly data). WFE corrected from -1.11 → 0.00. Finding: the prior -1.11 result was partially optimizer noise. True result is zero viable windows. SPY 1h strategy is fundamentally incompatible with STC+ATR on hourly equity data. CLOSED — no further testing.*

*v2.9 update (2026-04-01): MGC 1d extended walk-forward (2022-01-01 to 2026-03-27, 14 windows, 9-month IS / 3-month OOS). Result: WFE=0.00, 0/14 valid windows. All 14 optimization windows returned SKIP — no valid parameter combinations found in the FAST_GRID. This is stronger evidence than the prior WFE=0.14 (which had 15 windows with a few valid): the STC+ATR strategy produces zero viable signals on MGC daily data across any market regime from 2022 through 2026 (bear market, recovery, bull run). MGC 1d strategy redesign required before any reconsideration. See: `engine/backtest/fetch_mgc_history_2022.py` and `WF_MGC_1d_walk_forward.json`.*

*v2.10 update (2026-04-01): MES 1h adaptive regime walk-forward completed (2024-04-01 to 2026-03-27, 6 windows). Result: WFE=0.00, 0/6 valid windows. All 6 training windows returned SKIP — the RegimeClassifier over-filters MES to below 3 trades per window on every parameter combination, producing -999 score across all 162 FAST_GRID combos. Root cause: the adaptive mode is anti-predictive for S&P 500 intraday because MES STC signals predominantly occur in EXHAUSTED/COMPRESSION regimes (the very regimes the adaptive classifier blocks most aggressively). This is now the second independent confirmation of framework incompatibility: static WFE=0.09 (overfit, 4/6 profitable), adaptive WFE=0.00 (0/6 valid). Combined with SPY 1h WFE=0.00, the STC+ATR strategy is definitively unsuitable for S&P 500 hourly data in any configuration. MES strategy redesign required. See: `engine/backtest/results/WF_MES_1h_adaptive_walk_forward.json`.*

*v2.11 update (2026-04-02): MES ORB (Opening Range Breakout) walk-forward tested (2024-04-26 to 2026-03-27, 5 windows, 6-month IS / 3-month OOS). The ORB as implemented on 1-hour close bars produced raw WFE=0.61 (APPROVED_GOOD by naive formula), but this result is deceptive: both avg IS PnL ($-3,429) and avg OOS PnL ($-2,074) are consistently negative across all 5 windows. OOS profitable windows: 0/5. Avg OOS profit factor: 0.43 (well below 1.0). Root cause: 1h close-bar entry is structurally too late — by the time the 09:30-10:30 bar closes above OR High, price has already moved 1-2× OR range and mean-reversion dominates. The WFE formula is corrected in v2.11 to force WFE=0.0 when avg IS PnL < 0 (both IS and OOS losing money — no edge to measure). Verdict: ORB on 1h bars REJECTED. See: `engine/backtest/results/WF_MES_1h_ORB_walk_forward.json`.*

*v2.12 update (2026-04-02): MES ORB 15-minute proof-of-concept tested on 60-day window (Feb 3 – Apr 2, 2026, 3,813 bars, 53 trades). Yahoo Finance 15m data is limited to 60 days — insufficient for a multi-window walk-forward. POC result: WR=58.5%, PF=0.56, Net PnL=$-1,413. Root cause: T2 hit rate = 0% and avg_win=$58 << avg_loss=$147. MES/ES is strongly mean-reverting — after breaking OR, price reliably reverts before reaching T2. ORB assumes momentum continuation; MES is a mean-reverting instrument. **Pivot to VWAP Deviation Reversion strategy.***

*v2.13 update (2026-04-02): MES VWAP Deviation Reversion walk-forward tested (2024-01-01 to 2026-03-27, 5 windows, 6-month IS / 3-month OOS). Strategy: enter when price deviates ≥ band_mult × ATR from session VWAP with 1-bar reversal filter; full exit at VWAP (T1). Grid: 3 band_mult × 3 stop_mult × 2 reversal × 2 regime_filter = 36 combinations. Results: Avg IS PnL = $+1,794 (consistently profitable IS ✅), Avg OOS PnL = $+35 (barely positive), WFE = 0.02–0.11 across both with/without regime filter. Profitable windows: 2/5. The Oct 2025–Jan 2026 OOS window (post-election trending period) was the systematic failure: OOS PnL = -$444 to -$777 regardless of parameter choice. Verdict: REJECTED (WFE < 0.30). **VWAP is the most promising MES strategy yet** — IS signal is confirmed, OOS instability is regime-dependent. The failure is concentrated in one post-election period of extreme directional movement. Future path: (1) Dynamic circuit breaker — halt MES VWAP when VIX > 25 or when regime is TRENDING; (2) 3-month IS / 1-month OOS walk-forward for faster adaptation; (3) Requires paid intraday data (Polygon/Alpaca) and 2+ years of 15-minute data for a proper 15m VWAP study. Files: `engine/backtest/vwap_signals.py`, `engine/backtest/vwap_backtester.py`, `engine/backtest/vwap_walk_forward.py`, `engine/backtest/results/WF_MES_1h_VWAP_walk_forward.json`.*

**MES Summary (April 2, 2026): All tested strategies REJECTED. MCL (WFE=0.82) and MNQ (WFE=0.57) remain the only approved paper trading instruments. MES research is PAUSED pending (a) paid data for 15m study, or (b) VIX-based circuit breaker implementation.**

*v2.7 update (2026-03-30): MNQ adaptive WFE corrected 0.48→0.57 (latest confirmed run 2026-03-29T23:46). MCL static WFE confirmed 0.82 (run 2026-03-29T23:41). Both MCL and MNQ clear the 0.50 GOOD threshold — paper trading APPROVED for both. MTF filter walk-forward confirms MNQ WFE DEGRADES 0.57→0.17 — filter REJECTED. Volume filter also HURTS: 0.57→-0.23 — REJECTED. Best MCL config: static params only (adaptive WFE=-0.31). Best MNQ config: adaptive regime only, NO MTF, NO volume filter.*

---

## Corrected Performance (In-Sample, Per-Instrument Optimized)

| Rank | Symbol | TF | Trades | WR% | PF | Sharpe | Return | MaxDD | WFE | Verdict |
|------|--------|-----|--------|-----|------|--------|--------|-------|-----|---------|
| 1 | MCL | 1h | 65 | 60.0 | 1.83 | 0.15 | +0.2% | — | **0.82** | **EXCELLENT — Paper trading APPROVED** |
| 2 | MNQ | 1h | 86 | 47.7 | 1.46 | 0.19 | +13.6% | 0.1% | **0.57** | **GOOD — Paper trading APPROVED (adaptive)** |
| 3 | MGC | 1d | 47 | 51.1 | 2.60 | 2.04 | +34.4% | 3.0% | **0.14** | **OVERFIT — HALTED** (v2.7 corrected) |
| 4 | MES | 1h | 23 | 34.8 | 1.69 | 0.09 | +0.1% | 0.1% | 0.09 | **CLOSED** — static 0.09, adaptive 0.00, 0/6 valid (v2.10) |
| 5 | SPY | 1h | — | — | — | — | — | — | **0.00** | **CLOSED** — 0 valid windows (v2.8) |

*Test period: Jun 2024 -- Mar 2026 (1h) / Jan 2025 -- Mar 2026 (1d). All returns gross of commissions ($2.50/contract + 1 tick slippage applied).*

---

## Walk-Forward Validation — Final Results

| Symbol | TF | Windows | OOS Profitable | Avg IS Return | Avg OOS Return | WFE | Verdict |
|--------|-----|---------|----------------|---------------|----------------|------|---------|
| MCL | 1h | 6 | 5/6 (83%) | — | — | **0.82** | EXCELLENT — APPROVED (static params) |
| MNQ | 1h | 6 | 4/6 (67%) | — | — | **0.57** | GOOD — APPROVED (adaptive regime only) |
| MNQ | 1h | 6 | — | — | — | **0.17** | REJECTED (adaptive + MTF filter) |
| MNQ | 1h | 6 | — | — | — | **-0.23** | REJECTED (adaptive + volume filter) |
| MGC | 1d | 15 | 6/15 (40%) | +6.7% | +1.8% | **0.14** | FAIL — HALTED (extended history, v2.7 corrected) |
| MGC | 1d | 14 | 0/14 (0%) | 0.0% | 0.0% | **0.00** | FAIL — **CLOSED** (2022–2026 full range, 0 valid windows, v2.9) |
| MCL | 1h | 6 | — | — | — | **-0.31** | FAIL (adaptive regime HURTS MCL) |
| MES | 1h | 6 | 1/6 (17%) | — | — | **0.09** | FAIL — OVERFIT (static) |
| MES | 1h | 0 | 0/0 (0%) | 0.0% | 0.0% | **0.00** | FAIL — **CLOSED** (adaptive, all 6 windows SKIP, v2.10) |
| SPY | 1h | 6 | 0/6 (0%) | 0.0% | 0.0% | **0.00** | FAIL — CLOSED (0 valid windows, v2.8 corrected) |

**WFE thresholds:** >0.70 = Excellent, 0.50-0.70 = Good, 0.30-0.50 = Marginal, <0.30 = OVERFIT

**Key finding:** 73-90% of in-sample edge evaporates on unseen data across all instruments. The optimizer is exploiting historical market regimes (gold's 2024-2025 bull run, Nasdaq volatility surges) that do not persist across rolling 3-month periods.

### Adaptive Regime Results (with RegimeClassifier)

| Symbol | TF | Static WFE | Adaptive WFE | Change | OOS Sharpe | OOS PF | Verdict |
|--------|-----|-----------|--------------|--------|------------|--------|---------|
| MGC | 1d | 0.27 (extended: 0.27) | **0.88** (3-window, 2025 only) / **0.27** (15-window, 2022-2026) | +226% (3-win) / 0% (15-win) | 0.89 | 2.55 | **CONDITIONAL-CAUTION** — WFE=0.88 was 3-window small-sample result. Extended 15-window = 0.27 |
| MNQ | 1h | 0.24 | **0.57** | +138% | — | — | GOOD — APPROVED (adaptive only; +MTF → 0.17; +Vol → -0.23) |
| MCL | 1h | **0.82** | -0.31 | N/A | — | — | EXCELLENT (static wins; adaptive HURTS) |
| SPY | 1h | -1.11 | **-0.71** | +36% | -3.84 | 1.04 | FAIL -- Adaptive slightly better but still deeply overfit |
| MES | 1h | 0.09 | **0.00** | -100% | 0.00 | 0.00 | FAIL — Adaptive kills all signals (0/6 windows valid, over-filters to <3 trades/window) |

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

| Param | MGC 1d | MNQ 1h | MCL 1h | SPY 1h | MES 1h |
|-------|--------|--------|--------|--------|--------|
| STC_OS | 17 | 15 | 15 | 15 | 15 |
| STC_OB | 88 | 92 | 83 | 88 | 83 |
| Stop ATR | 0.30 | 0.70 | 0.90 | 0.30 | 0.50 |
| T1 ATR | 1.50 | 1.00 | 1.50 | 1.00 | 2.00 |
| T2 ATR | 2.618 | 1.80 | 2.618 | 1.618 | 3.236 |
| Regime Filter | **OFF** (anti-predictive for gold daily) | ON | ON | ON | **OFF** |

*SPY and MES params updated 2026-03-29 via optimizer consensus (US-005/US-007). MES regime_filter=OFF per optimizer -- structure-based entries in EXHAUSTED/COMPRESSION regimes improve MES PF from 0.96 to 1.69.*

*MGC regime_filter=ON found to be anti-predictive per 15-window walk-forward analysis: regime=ON windows avg OOS -1.7% (7/8 lost money), regime=OFF windows avg OOS +5.9% (5/7 profitable). Recommend regime_filter=OFF for MGC 1d.*

These profiles are live in `engine/backtest/signals.py::INSTRUMENT_PARAMS` (7-element tuples including regime_filter) and used by `run_backtest.py`. They represent the best-known in-sample parameters but should NOT be treated as validated for live trading until walk-forward efficiency improves.

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

## Paper Trading Recommendation (Updated v2.7)

**MCL 1h (WFE=0.82) and MNQ 1h (WFE=0.57 adaptive) are both APPROVED for paper trading.**

1. **MCL 1h — ACTIVE**: Static params, regime_filter=ON, adaptive_regime=OFF. 0.25% risk/trade.
2. **MNQ 1h — ACTIVE**: Adaptive regime only (no MTF, no volume filter). 0.25% risk/trade.
3. **Kill threshold** — halt if -3% monthly or 3 consecutive losses on either instrument
4. **Do NOT add filters** — MTF and volume filters confirmed to degrade MNQ WFE
5. **MGC 1d — HALTED** — WFE=0.14, OVERFIT. Requires fundamental signal redesign.

---

## Paper Trading — ACTIVE (as of 2026-03-30)

### MCL 1h — ACTIVE
| Parameter | Value |
|-----------|-------|
| Capital | $25,000 |
| Risk/trade | 0.25% |
| Config | Static params, regime_filter=ON, adaptive=OFF |
| Stop/T1 | 0.90 ATR / 1.50 ATR |
| Kill switch | -3% monthly OR 3 consecutive losses |

### MNQ 1h — ACTIVE
| Parameter | Value |
|-----------|-------|
| Capital | $25,000 |
| Risk/trade | 0.25% |
| Config | adaptive_regime=ON, mtf_filter=OFF, volume_filter=OFF |
| Stop/T1 | 0.70 ATR / 1.00 ATR |
| Kill switch | -3% monthly OR 3 consecutive losses |

### MGC 1d — CLOSED (v2.9)
WFE=0.00 (2022–2026 extended, 0/14 valid windows). Strategy fundamentally incompatible with MGC daily data. Signal redesign required — STC+ATR does not produce viable parameter sets on gold daily across any market regime. Do not attempt paper trading until redesign validated.

**Config file:** `engine/backtest/paper_config.py`
**Approval doc:** `PAPER_TRADING_APPROVAL.md`

---

## What NOT to Trade (Permanently Removed)

| Symbol | TF | PF | WFE | Reason |
|--------|-----|----|-----|--------|
| M2K | 1h | 0.64 | N/A | Consistently losing; Russell unsuitable for STC |
| M2K | 1d | 0.60 | N/A | Negative both timeframes |
| MCL | 1d | 0.21 | N/A | Catastrophic PF; zero targets hit on daily crude |
| MES | 1d | 0.75 | N/A | PF<1.0 on daily; S&P daily trend-following incompatible with STC |
| MES | 1h | 1.69 | **0.00** | Static WFE=0.09 (overfit), adaptive WFE=0.00 (0/6 windows). **CLOSED** — STC+ATR definitively incompatible with S&P 500 1h. Redesign required: ORB or VWAP strategy recommended (v2.10) |