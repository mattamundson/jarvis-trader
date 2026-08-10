# JARVIS TRADER — Strategy Research Summary

*Version 2.7 | Updated: 2026-03-30 | Status: MCL 1h + MNQ 1h APPROVED for paper trading*

---

## TL;DR

The STC-based strategy has genuine in-sample edge on 4 of 12 instrument/timeframe combinations. Walk-forward validation clears **2 instruments for paper trading**: **MCL 1h WFE=0.82 (EXCELLENT)** using static params, and **MNQ 1h WFE=0.57 (GOOD)** using adaptive regime mode only. MTF and volume filters were tested but REJECTED — both degrade MNQ WFE significantly. MGC 1d WFE=0.14 remains HALTED.

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
| **F** | Regime-adaptive STC: RegimeClassifier (EMA spread + BBWidth + ATR voting) | MGC 1d WFE 0.27 to 0.88 (EXCELLENT); MNQ 1h 0.24 to 0.57 (post-bugfix) |
| **G** | Signal filter testing: volume filter, MTF, trailing stop | MTF filter REJECTED (MNQ 0.57→0.17); volume filter REJECTED (0.57→-0.23) |
| **H** | Paper trading approval: MCL 1h (WFE=0.82) + MNQ 1h (WFE=0.57 adaptive) | 2 instruments APPROVED for paper trading |

---

## Corrected Performance (In-Sample, Full Period)

| Rank | Symbol | TF | Trades | WR% | PF | Sharpe | Return | MaxDD | Status |
|------|--------|-----|--------|-----|------|--------|--------|-------|--------|
| 1 | MCL | 1h | 65 | 60.0 | 1.83 | 0.15 | +0.2% | — | **Paper trading APPROVED** (WFE=0.82) |
| 2 | MNQ | 1h | 86 | 47.7 | 1.46 | 0.19 | +13.6% | 0.1% | **Paper trading APPROVED** (WFE=0.57 adaptive) |
| 3 | MGC | 1d | 47 | 51.1 | 2.60 | 2.04 | +34.4% | 3.0% | HALTED — WFE=0.14 OVERFIT |
| 4 | SPY | 1h | 23 | 52.2 | 3.79 | -1.43 | +0.0% | 0.1% | DO NOT TRADE |
| 5 | MES | 1h | 23 | 34.8 | 1.69 | 0.09 | +0.1% | 0.1% | DO NOT TRADE |

*Test period: Jun 2024 -- Mar 2026 (1h) / Jan 2025 -- Mar 2026 (1d). Returns gross of commissions ($2.50/contract + 1 tick slippage).*

---

## Walk-Forward Efficiency Summary

This is the critical table — what generalizes vs what is curve-fit.

| Symbol | TF | Config | WFE | OOS Profitable | Verdict |
|--------|-----|--------|-----|----------------|---------|
| MCL | 1h | Static | **0.82** | 5/6 (83%) | **EXCELLENT — Paper trading APPROVED** |
| MNQ | 1h | Adaptive regime | **0.57** | 4/6 (67%) | **GOOD — Paper trading APPROVED** |
| MNQ | 1h | + MTF filter | 0.17 | — | REJECTED — MTF filter HURTS (0.57→0.17) |
| MNQ | 1h | + Volume filter | -0.23 | — | REJECTED — Volume filter HURTS (0.57→-0.23) |
| MGC | 1d | Static (15-window) | 0.14 | 6/15 (40%) | OVERFIT — HALTED |
| MES | 1h | Static | 0.09 | 1/6 (17%) | OVERFIT — DO NOT TRADE |
| MCL | 1h | Adaptive | -0.31 | — | REJECTED — Adaptive HURTS MCL |

**WFE thresholds:** > 0.70 = Excellent | 0.50-0.70 = Good | 0.30-0.50 = Marginal | < 0.30 = OVERFIT

> **v2.7 correction (2026-03-30):** MNQ adaptive WFE corrected 0.48→0.57 (latest confirmed run 2026-03-29T23:46). MCL static WFE confirmed 0.82 (run 2026-03-29T23:41). Both MCL and MNQ clear the 0.50 GOOD threshold — paper trading APPROVED. MTF filter run confirmed HURTS MNQ: 0.57→0.17. Volume filter also HURTS: 0.57→-0.23.

> **v2.6 correction:** Optimizer kwarg bug fixed. Previous WFEs were invalid due to silent TypeError causing all optimization calls to return None. Corrected: MGC 0.27→0.14, MNQ static 0.34→0.24.

**Key finding:** MCL 1h static params generalize exceptionally well (WFE=0.82). MNQ adaptive regime improves generalization vs static (0.24→0.57). Adding filters over-constrains the model — adaptive regime alone is the optimal MNQ configuration.

---

## Signal Improvement Results

| # | Improvement | Module | MNQ 1h Impact | MGC 1d Impact | Keep? |
|---|-------------|--------|---------------|---------------|-------|
| 1 | Regime-adaptive STC | `regime.py` | WFE 0.24→0.57 (+138%) | Anti-predictive for MGC daily (OFF) | **YES for MNQ** |
| 2 | Multi-timeframe (4h alignment) | `mtf_filter.py` | WFE 0.57→0.17 (-70%) — HURTS | N/A (daily TF) | **NO — REJECTED** |
| 3 | Volume filter (20-SMA gate) | `signals.py` | WFE 0.57→-0.23 — HURTS | OFF (unreliable daily vol) | **NO — REJECTED** |
| 4 | News/event blackout (81 events) | `signals.py` | ~1% signals blocked | ~1% signals blocked | LIVE ONLY |
| 5 | Trailing ATR stop | `backtester.py` | Not tested | No config beats baseline | **NO** |

---

## Paper Trading Status

**2 instruments APPROVED. 1 HALTED. Paper trading ACTIVE as of 2026-03-30.**

### MCL 1h — ACTIVE (WFE=0.82 EXCELLENT)
| Parameter | Value |
|-----------|-------|
| Capital | $25,000 |
| Risk/trade | 0.25% |
| Config | Static params, regime_filter=ON, adaptive_regime=OFF |
| STC | OS=15, OB=83, Stop=0.90 ATR, T1=1.50 ATR |
| Kill switch | -3% monthly OR 3 consecutive losses |

### MNQ 1h — ACTIVE (WFE=0.57 GOOD)
| Parameter | Value |
|-----------|-------|
| Capital | $25,000 |
| Risk/trade | 0.25% |
| Config | Adaptive regime=ON, volume_filter=OFF, mtf_filter=OFF |
| STC | OS=15, OB=92, Stop=0.70 ATR, T1=1.00 ATR |
| Kill switch | -3% monthly OR 3 consecutive losses |

### MGC 1d — HALTED (WFE=0.14 OVERFIT)
WFE=0.14 below 0.30 threshold. MTF filter tested and REJECTED (no improvement). Suspended indefinitely.

---

## Do Not Trade List

| Symbol | TF | PF | WFE | Reason |
|--------|-----|----|-----|--------|
| M2K | 1h | 0.64 | N/A | Consistently losing; Russell unsuitable for STC |
| M2K | 1d | 0.60 | N/A | Negative both timeframes |
| MCL | 1d | 0.21 | N/A | Zero target hits on daily crude |
| MES | 1d | 0.75 | N/A | 36/51 trades exit at EOD — targets unreachable |
| MES | 1h | 1.69 | 0.09 | WFE=0.09 OVERFIT — only 1/6 OOS windows profitable |
| MGC | 1d | 2.60 | 0.14 | WFE=0.14 OVERFIT — paper trading HALTED |
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

> **MNQ 1h OOS stable param zone (Agent AC finding):** OS=23, OB=88, stop=0.70 ATR, T1=2.00 ATR — identified as the most parameter-stable region across walk-forward windows.

---

## Walk-Forward Result Files (12 completed runs)

| File | Description |
|------|-------------|
| `WF_MCL_1h_walk_forward.json` | MCL hourly, static params **(WFE 0.82 EXCELLENT — APPROVED)** |
| `WF_MNQ_1h_adaptive_walk_forward.json` | MNQ hourly, adaptive regime **(WFE 0.57 GOOD — APPROVED)** |
| `WF_MNQ_1h_adaptive_mtf_walk_forward.json` | MNQ hourly, adaptive + MTF filter (WFE 0.17 — REJECTED) |
| `WF_MNQ_1h_adaptive_volume_walk_forward.json` | MNQ hourly, adaptive + volume filter (WFE -0.23 — REJECTED) |
| `WF_MCL_1h_adaptive_walk_forward.json` | MCL hourly, adaptive regime (WFE -0.31 — adaptive HURTS MCL) |
| `WF_MGC_1d_walk_forward.json` | MGC daily, static params (WFE 0.14 OVERFIT — HALTED) |
| `WF_MNQ_1h_walk_forward.json` | MNQ hourly, static params (WFE 0.24 OVERFIT) |
| `WF_MES_1h_walk_forward.json` | MES hourly, static params (WFE 0.09 OVERFIT) |
| `WF_MGC_1d_adaptive_walk_forward.json` | MGC daily, adaptive regime (WFE 0.14 post-bugfix) |
| `WF_MGC_1d_adaptive_volume_walk_forward.json` | MGC daily, adaptive + volume filter |
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

**Paper trading is LIVE** for MCL 1h (WFE=0.82) and MNQ 1h (WFE=0.57 adaptive).

Active monitoring priorities:
1. **MCL 1h**: monitor da