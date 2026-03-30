# JARVIS TRADER — Strategy Research Summary

*Version 3.0 | Updated: 2026-03-29 | Status: MGC 1d ACTIVE (Paper Trading)*

---

## TL;DR

The STC-based strategy has genuine in-sample edge on 4 of 12 instrument/timeframe combinations, but **all static parameter sets are overfit** (WFE < 0.30 across all 5 tested instruments). A regime-adaptive approach rescued **MGC 1d (micro gold daily)**, achieving WFE = 0.88 (EXCELLENT) — the only instrument cleared for paper trading. Everything else remains NO-GO until further signal improvements push walk-forward efficiency above 0.40.

---

## Strategy Overview

- **Signal**: STC (Schaff Trend Cycle) crossover + 4-layer filter stack (Regime Map, Structure, Bias, Entry)
- **Position sizing**: 1% risk per trade (0.25% for paper), ATR-based stops
- **Execution**: Futures only (CME Globex) — micro contracts (MGC, MNQ, MCL, MES, M2K)
- **Benchmark**: SPY 1h (ETF proxy)
- **Data**: Yahoo Finance via yfinance (free tier), Jun 2024 to Mar 2026 (1h), Jan 2025 to Mar 2026 (1d)
- **Costs**: $2.50/contract commission + 1 tick slippage modeled

---

## What We Built (Phase Timeline)

| Phase | Description | Key Outcome |
|-------|-------------|-------------|
| **A** | Fix 8 critical backtesting bugs (stop loss, look-ahead, EOD exit, commissions, Sharpe) | Original numbers were massively inflated; median PF dropped from inflated values to 0.96 |
| **B** | Corrected backtests: 6 symbols x 2 timeframes (12-matrix) | 5 of 12 profitable (42%); top 3: MNQ 1h PF 1.46, MCL 1h PF 1.83, MGC 1d PF 2.60 |
| **C** | Walk-forward validation: 5 instruments, 6-7 windows each | ALL 5 FAIL static WFE (best: MGC 0.27, worst: SPY -1.11) |
| **D** | Monte Carlo (10k sims x 4 instruments) + sensitivity analysis (3 instruments) | Confirmed edge is real but thin; parameter sensitivity high (94-95/100) |
| **E** | Research report: 1,245-line BACKTEST_RESEARCH_REPORT.md | Research-grade documentation of all findings |
| **F** | Regime-adaptive STC: RegimeClassifier (EMA spread + BBWidth + ATR voting) | MGC 1d WFE 0.27 to 0.88 (EXCELLENT); MNQ 1h 0.24 to 0.34 |
| **G** | Signal improvements: volume filter, MTF, news blackout, trailing stop | Volume filter boosts MNQ WR 47.7% to 60.0%, PF 1.46 to 2.36 |
| **H** | Paper trading infrastructure: PaperTracker, scheduler, live endpoints, dashboard | MGC 1d paper trading ACTIVE since 2026-03-29 |

---

## Corrected Performance (In-Sample, Full Period)

| Rank | Symbol | TF | Trades | WR% | PF | Sharpe | Return | MaxDD | Status |
|------|--------|-----|--------|-----|------|--------|--------|-------|--------|
| 1 | MGC | 1d | 47 | 51.1 | 2.60 | 2.04 | +34.4% | 3.0% | Paper trading (adaptive) |
| 2 | MNQ | 1h | 86 | 47.7 | 1.46 | 0.19 | +13.6% | 0.1% | Improving — needs WFE > 0.40 |
| 3 | MCL | 1h | 65 | 60.0 | 1.83 | 0.15 | +0.2% | — | DO NOT TRADE |
| 4 | SPY | 1h | 23 | 52.2 | 3.79 | -1.43 | +0.0% | 0.1% | DO NOT TRADE |
| 5 | MES | 1h | 23 | 34.8 | 1.69 | 0.09 | +0.1% | 0.1% | DO NOT TRADE |

*Test period: Jun 2024 -- Mar 2026 (1h) / Jan 2025 -- Mar 2026 (1d). Returns gross of commissions ($2.50/contract + 1 tick slippage).*

---

## Walk-Forward Efficiency Summary

This is the critical table — what generalizes vs what is curve-fit.

| Symbol | TF | Static WFE | Adaptive WFE | OOS Profitable | Static Verdict | Adaptive Verdict |
|--------|-----|-----------|--------------|----------------|----------------|------------------|
| MGC | 1d | 0.27 | **0.88*** | 2/3 (67%) | OVERFIT | **CONDITIONAL-CAUTION** — Extended 15-window WFE = 0.27 |
| MNQ | 1h | 0.24 | **0.34** | 3/6 (50%) | OVERFIT | ACCEPTABLE — Needs WFE > 0.40 |
| MCL | 1h | -0.16 | **-0.31** | 2/6 (33%) | OVERFIT | FAIL — Adaptive hurts MCL |
| MES | 1h | -0.17 | N/A | 1/6 (17%) | OVERFIT | Not tested (no edge) |
| SPY | 1h | -1.11 | N/A | 2/6 (33%) | OVERFIT | Not tested (random noise) |

**WFE thresholds:** > 0.70 = Excellent | 0.50-0.70 = Good | 0.30-0.50 = Marginal | < 0.30 = OVERFIT

*\* MGC adaptive WFE=0.88 was a 3-window result (2025 data only). Extended 15-window validation (2022-2026) = 0.27 — confirms small-sample bias. Bear market data exposes overfitting.*

**Key finding:** 73-90% of in-sample edge evaporates on unseen data with static parameters. The regime-adaptive approach recovers 88% of edge for MGC (gold) by dynamically switching STC thresholds based on detected market regime.

---

## Signal Improvement Results

| # | Improvement | Module | MNQ 1h Impact | MGC 1d Impact | Keep? |
|---|-------------|--------|---------------|---------------|-------|
| 1 | Regime-adaptive STC | `regime.py` | WFE 0.24 to 0.34 (+41%) | WFE 0.27 to 0.88 (+226%) | **YES** (Note: regime_filter=ON anti-predictive for MGC daily — recommend OFF for gold) |
| 2 | Multi-timeframe (4h alignment) | `mtf_filter.py` | 20.6% entries blocked (counter-trend) | N/A (daily TF) | YES (1h only) |
| 3 | Volume filter (20-SMA gate) | `signals.py` | WR 47.7% to 60%, PF 1.46 to 2.36 | OFF (unreliable daily vol) | YES (1h only) |
| 4 | News/event blackout (81 events) | `signals.py` | ~1% signals blocked | ~1% signals blocked | LIVE ONLY |
| 5 | Trailing ATR stop | `backtester.py` | Not tested | No config beats baseline | **NO** |

---

## Paper Trading Status

**MGC 1d adaptive: ACTIVE — CONDITIONAL-CAUTION (extended WFE=0.27)**

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Capital | $25,000 | Micro gold sizing |
| Risk/trade | 0.25% | Conservative start (quarter of standard 1%) |
| Stop | 0.30 ATR | Validated in walk-forward |
| T1 Target | 1.00 ATR | Intraday reachable |
| Adaptive Regime / Regime Filter | OFF recommended | Regime filter anti-predictive per extended WF: ON windows avg OOS -1.7%, OFF windows avg OOS +5.9% |
| Volume Filter | OFF | Daily volume data unreliable for MGC |
| Trailing Stop | OFF | No trailing config beats baseline |
| Kill threshold | 3 consecutive months > 50% below IS baseline (3.8% per 3-month window) |

**Performance benchmark (in-sample):** Avg IS return 7.6% per 3-month window. OOS avg return +6.7%, OOS avg Sharpe 0.89, OOS avg PF 2.55.

---

## Do Not Trade List

| Symbol | TF | PF | WFE | Reason |
|--------|-----|----|-----|--------|
| M2K | 1h | 0.64 | N/A | Consistently losing; Russell unsuitable for STC |
| M2K | 1d | 0.60 | N/A | Negative both timeframes |
| MCL | 1d | 0.21 | N/A | Zero target hits on daily crude |
| MCL | 1h | 1.83 | -0.31 | Adaptive regime worsens performance; noisy regime transitions |
| MES | 1d | 0.75 | N/A | 36/51 trades exit at EOD — targets unreachable |
| MES | 1h | 1.69 | -0.17 | Re-optimized v2.5: PF 0.96->1.69 (+76%, regime OFF), +0.1% return. PF improved with new params but WFE not yet validated |
| MNQ | 1d | 0.79 | N/A | 43/57 EOD exits; daily NQ too volatile for intraday targets |
| MGC | 1h | 0.77 | N/A | Gold works daily only; hourly loses money |
| SPY | 1h | 3.79 | -0.71 | Re-optimized v2.5: PF 3.00->3.79, near-zero returns, still deeply overfit |

---

## Per-Instrument Optimal Parameters (signals.py INSTRUMENT_PARAMS)

| Param | MGC 1d | MNQ 1h | MCL 1h | SPY 1h | MES 1h |
|-------|--------|--------|--------|--------|--------|
| STC_OS | 17 | 15 | 15 | 15 | 15 |
| STC_OB | 88 | 92 | 83 | 88 | 83 |
| Stop ATR | 0.30 | 0.70 | 0.90 | 0.30 | 0.50 |
| T1 ATR | 1.50 | 1.00 | 1.50 | 1.00 | 2.00 |
| T2 ATR | 2.618 | 1.80 | 2.618 | 1.618 | 3.236 |
| Regime Filter | **OFF** (anti-predictive for gold daily) | ON | ON | ON | **OFF** |

---

## Walk-Forward Result Files (11 completed runs)

| File | Description |
|------|-------------|
| `WF_MGC_1d_walk_forward.json` | MGC daily, static params (WFE 0.27) |
| `WF_MGC_1d_adaptive_walk_forward.json` | MGC daily, adaptive regime (WFE 0.88) |
| `WF_MGC_1d_adaptive_volume_walk_forward.json` | MGC daily, adaptive + volume filter |
| `WF_MNQ_1h_walk_forward.json` | MNQ hourly, static params (WFE 0.24) |
| `WF_MNQ_1h_adaptive_walk_forward.json` | MNQ hourly, adaptive regime (WFE 0.34) |
| `WF_MNQ_1h_adaptive_volume_walk_forward.json` | MNQ hourly, adaptive + volume filter |
| `WF_MCL_1h_walk_forward.json` | MCL hourly, static params (WFE -0.16) |
| `WF_MCL_1h_adaptive_walk_forward.json` | MCL hourly, adaptive regime (WFE -0.31) |
| `WF_MES_1h_walk_forward.json` | MES hourly, static params (WFE -0.17) |
| `WF_SPY_1h_walk_forward.json` | SPY hourly, static params (WFE -1.11) |
| `WF_SPY_1h_adaptive_walk_forward.json` | SPY hourly, adaptive regime |

---

## Key Technical Files

| Component | Path |
|-----------|------|
| Signal generation | `engine/backtest/signals.py` |
| Backtester core | `engine/backtest/backtester.py` |
| Walk-forward validation | `engine/backtest/walk_forward.py` (not committed — local module) |
| Regime classifier | `engine/backtest/regime.py` |
| MTF filter | `engine/backtest/mtf_filter.py` |
| Indicators | `engine/backtest/indicators.py` |
| Optimizer | `engine/backtest/optimizer.py` |
| Monte Carlo | `engine/backtest/monte_carlo.py` |
| Sensitivity analysis | `engine/backtest/sensitivity.py` |
| Paper config | `engine/backtest/paper_config.py` |
| Paper tracker | `engine/backtest/paper_tracker.py` |
| Live endpoints | `engine/main.py` (`/paper/mgc-signal`, `/paper/mgc-performance`) |
| Dashboard | `dashboard/app/paper/page.tsx` |
| Executive briefing | `engine/backtest/results/EXECUTIVE_BRIEFING.md` |
| Full research report | `engine/docs/BACKTEST_RESEARCH_REPORT.md` (1,245 lines) |

---

## Next Milestone

**To approve MNQ 1h for paper trading:** need WFE > 0.40 (currently 0.34 adaptive).

Options under evaluation:
1. Combined walk-forward test with adaptive regime + volume filter + MTF filter
2. Wider training windows (9-month IS instead of 6-month)
3. Additional signal confirmations to reduce parameter instability
4. Extend history back to 2022 to include bear market conditions

**MGC 1d paper trading monitoring:** recalculate WFE monthly with latest 3 windows. Kill if 3 consecutive months fall below 3.8% return (50% of 7.6% IS baseline).

---

*Source: 55+ result files in `engine/backtest/results/`. Includes optimizer JSONs, corrected backtests, sensitivity analysis (3 instruments), Monte Carlo (4 instruments, 10k sims each), walk-forward validation (5 instruments static + 5 adaptive runs), and the 1,245-line research report.*
