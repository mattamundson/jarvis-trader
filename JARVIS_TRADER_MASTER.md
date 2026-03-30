# JARVIS TRADER — Master Reference Document
*Version 3.0 | 2026-03-30 | THE SINGLE SOURCE OF TRUTH*
*All 40+ project files consolidated. Zero information loss. All conflicts resolved.*

---

## Table of Contents

1. [System Overview & Architecture](#11-system-overview--architecture)
2. [Strategy Framework (Tony Stark 5-Layer)](#12-strategy-framework-tony-stark-5-layer)
3. [Walk-Forward Validation Results (FINAL v2.7)](#13-walk-forward-validation-results-final-v27)
4. [Corrected Backtest Performance](#14-corrected-backtest-performance)
5. [Paper Trading Configuration](#15-paper-trading-configuration)
6. [Risk Management & Safety Layer](#16-risk-management--safety-layer)
7. [VIX Regime Reference (CANONICAL 6-Tier)](#17-vix-regime-reference-canonical-6-tier)
8. [Three-Tier Autonomy Model](#18-three-tier-autonomy-model)
9. [Standing Orders & Proactive Triggers](#19-standing-orders--proactive-triggers)
10. [Matt's Trading Context & Personal Rules](#110-matts-trading-context--personal-rules)
11. [API Surface (Live-Validated)](#111-api-surface-live-validated)
12. [ThinkOrSwim Script Library](#112-thinkorswim-script-library)
13. [Dashboard Architecture](#113-dashboard-architecture)
14. [Infrastructure](#114-infrastructure)
15. [Options Trading System (FULL SPEC)](#115-options-trading-system-full-spec)
16. [Futures Strategies (Detailed)](#116-futures-strategies-detailed)
17. [Go-Live Validation Checklist (CANONICAL)](#117-go-live-validation-checklist-canonical)
18. [Session History & Decision Log](#118-session-history--decision-log)
19. [Known Issues & Pending Work](#119-known-issues--pending-work)
20. [File Reference](#120-file-reference)

---

## 1.1 System Overview & Architecture

### What Is JARVIS TRADER

JARVIS TRADER is an AI-powered autonomous futures trading system built by Matt Morrison. It combines quantitative backtesting with a multi-agent LLM pipeline to generate, validate, and execute trades on CME Globex micro futures contracts. The system runs in paper trading mode by default with hardcoded safety layers that no LLM agent can override.

### 5-Stage Decision Pipeline

The core trading logic follows a 5-stage pipeline with 10 specialized LLM agents:

```
Stage 1: ANALYSIS (4 agents in parallel)
  ├── Technical Analyst   (Sonnet 4.6) — STC signals, regime, structure
  ├── News Analyst        (Sonnet 4.6) — Finnhub news sentiment, event blackouts
  ├── Social Analyst      (Sonnet 4.6) — Market sentiment, positioning data
  └── Fundamental Analyst (Sonnet 4.6) — Macro regime, rate environment

Stage 2: DEBATE (2 agents)
  ├── Bull Advocate       (Opus 4.6)   — Constructs the long case
  └── Bear Advocate       (Opus 4.6)   — Constructs the short case

Stage 3: TRADE DECISION (1 agent)
  └── Trade Decision Maker (Opus 4.6)  — Synthesizes debate → entry/exit/skip

Stage 4: RISK REVIEW (1 agent)
  └── Risk Manager         (Opus 4.6)  — Position sizing, correlation, portfolio exposure

Stage 5: FUND MANAGER (2 agents)
  ├── Fund Manager         (Opus 4.6)  — Final approval / rejection
  └── Kill Switch Monitor  (Haiku 4.5) — Continuous safety monitoring
```

**Model assignments:** Opus 4.6 handles all senior decision-making roles (debate, trade decisions, risk, fund management). Sonnet 4.6 handles analyst-level research and data processing. Haiku 4.5 handles lightweight continuous monitoring tasks.

### Technology Stack

| Component | Technology | Details |
|-----------|-----------|---------|
| **Engine** | FastAPI (Python 3.12) | Port 8010, async, uvicorn |
| **Dashboard** | Next.js 15 + TypeScript | Port 3010, dark terminal aesthetic, Tailwind CSS |
| **Database** | SQLite (primary) + PostgreSQL (optional) | SQLite for backtests/paper, Postgres for production |
| **Cache** | Redis | Native Windows Redis service (v3.0.504) |
| **Market Data** | yfinance (free tier) | Fallback: Yahoo v8 direct API (`_fetch_direct_yahoo()`) |
| **News Data** | Finnhub (free tier) | Sentiment scoring, event detection |
| **Alerts** | Twilio WhatsApp | Kill switch alerts, trade notifications |
| **Broker** | IB Gateway via ib_async | Paper port 4002, live port 4001 |
| **Python Venv** | `engine/.venv/` | Windows Store Python 3.12 |

### Directory Structure

```
C:\Users\mattm\ThinkorSwim\jarvis-trader\
├── engine/                          # FastAPI backend (Python 3.12)
│   ├── main.py                      # Application entry point, all endpoints
│   ├── backtest/                    # Backtesting subsystem
│   │   ├── backtester.py            # Core backtester (8 bugs fixed)
│   │   ├── signals.py               # Signal generation + INSTRUMENT_PARAMS
│   │   ├── indicators.py            # Technical indicators (STC, ATR, KAMA, etc.)
│   │   ├── regime.py                # RegimeClassifier (3-state voting)
│   │   ├── mtf_filter.py            # Multi-timeframe filter (REJECTED)
│   │   ├── optimizer.py             # Parameter optimizer
│   │   ├── walk_forward.py          # Rolling walk-forward validation
│   │   ├── monte_carlo.py           # 10,000-sim Monte Carlo
│   │   ├── sensitivity.py           # Parameter sensitivity analysis
│   │   ├── paper_config.py          # Paper trading configs (MCL, MNQ, MGC)
│   │   ├── paper_tracker.py         # Live paper trade tracker
│   │   ├── run_backtest.py          # CLI backtest runner
│   │   ├── run_all_backtests.py     # Full matrix runner (12 combos)
│   │   ├── test_backtester.py       # Unit tests (5/5 passing)
│   │   └── results/                 # 55+ JSON/MD result files
│   │       └── EXECUTIVE_BRIEFING.md
│   ├── risk/                        # Safety layer (hardcoded, no LLM)
│   │   ├── safety_layer.py          # SafetyLayer class (703 lines)
│   │   ├── loss_tracker.py          # ConsecutiveLossTracker (339 lines)
│   │   └── pnl_monitor.py           # PnLMonitor (439 lines)
│   ├── paper/                       # Paper trading setup docs
│   │   ├── MCL_paper_setup.md
│   │   └── MNQ_paper_setup.md
│   ├── portfolio/                   # Portfolio tracking
│   │   └── tracker.py
│   ├── data_loader.py               # Market data fetching (yfinance + v8 fallback)
│   ├── health_monitor.py            # WhatsApp alert daemon (224 lines)
│   ├── docs/                        # Research documentation
│   │   └── BACKTEST_RESEARCH_REPORT.md  # 1,245-line research report
│   └── .env                         # API keys (Anthropic, Twilio, Finnhub)
├── dashboard/                       # Next.js 15 frontend
│   ├── app/                         # App router pages
│   │   ├── paper/page.tsx           # Paper trading dashboard
│   │   ├── backtest/page.tsx        # Backtest results + equity curves
│   │   └── journal/page.tsx         # Trade journal
│   └── components/                  # Reusable UI components
├── thinkorswim-scripts/             # 21 TOS scripts (5 layers)
│   └── INTEGRATION_GUIDE.md
├── SUMMARY.md                       # Strategy research summary (v2.7)
├── PAPER_TRADING_GUIDE.md           # Paper trading operational guide
├── PAPER_TRADING_APPROVAL.md        # Formal approval document
├── start_jarvis.bat                 # Double-click Windows startup
└── JARVIS_TRADER_MASTER.md          # THIS FILE — single source of truth
```

### Quick Start

**Windows double-click startup:**
```bash
start_jarvis.bat
```

**Manual engine startup (from engine/ directory):**
```bash
.venv/Scripts/python -m uvicorn main:app --reload --port 8010
```

**Dashboard startup:**
```bash
cd dashboard && npm run dev
```

**Run a backtest:**
```bash
cd engine
python -m backtest.run_backtest --symbol MNQ --interval 1h --start 2024-06-01 --end 2026-03-27
```

**Run walk-forward validation:**
```bash
cd engine
python -m backtest.walk_forward --symbol MNQ --interval 1h --adaptive-regime
```

**Run optimizer:**
```bash
cd engine
python -m backtest.optimizer --symbol MNQ --interval 1h
```

### Port Map

| Service | Port | Protocol |
|---------|------|----------|
| Engine (FastAPI) | 8010 | HTTP |
| Dashboard (Next.js) | 3010 | HTTP |
| IB Gateway (paper) | 4002 | TCP |
| IB Gateway (live) | 4001 | TCP |
| Redis | 6379 | TCP |

---

## 1.2 Strategy Framework (Tony Stark 5-Layer)

The trading strategy is built on a 5-layer framework inspired by institutional trading desk architecture. Each layer must pass before a trade is taken. The framework is implemented in `engine/backtest/signals.py` with supporting modules for each layer.

### INSTRUMENT_PARAMS (Source of Truth: `signals.py`)

All per-instrument parameters are stored as 7-element tuples in `INSTRUMENT_PARAMS`:

```
Format: (STC_OS, STC_OB, STOP_ATR, T1_ATR, T2_ATR, T3_ATR, REGIME_FILTER)
```

| Param | MNQ 1h | MCL 1h | MGC 1d | SPY 1h | MES 1h |
|-------|--------|--------|--------|--------|--------|
| **STC_OS** (Oversold) | 15 | 15 | 17 | 15 | 15 |
| **STC_OB** (Overbought) | 92 | 83 | 88 | 88 | 83 |
| **Stop ATR** | 0.70 | 0.90 | 0.30 | 0.30 | 0.50 |
| **T1 ATR** (50% exit) | 1.00 | 1.50 | 1.50 | 1.00 | 2.00 |
| **T2 ATR** (25% exit) | 1.80 | 2.618 | 2.618 | 1.618 | 3.236 |
| **T3 ATR** (25% exit) | 2.618 | 4.00 | 4.00 | 2.618 | 4.00 |
| **Regime Filter** | ON | ON | ON | ON | **OFF** |

**Notes:**
- MNQ: STC_OB=92 filters Nasdaq noise; 86 trades in-sample, PF 1.51
- MCL: Stop=0.90, T1=1.50 gives R:R=1.67; 65 trades in-sample, PF 1.81
- MGC: Tight stop (0.30) + wide T1 (1.50) matches gold trend length
- SPY: Re-optimized v2.5, PF 3.79, 23 trades (DO NOT TRADE — WFE=-1.11)
- MES: Regime filter OFF per optimizer — structure-based entries in EXHAUSTED/COMPRESSION regimes improve MES PF from 0.96 to 1.69 (DO NOT TRADE — WFE=0.09)

### Layer 1 — Regime Map (`regime.py`)

The RegimeClassifier determines the current market regime using a 3-factor voting system:

| Factor | Method | States |
|--------|--------|--------|
| EMA Spread | EMA(8) vs EMA(21) distance | TRENDING / RANGING |
| Bollinger Band Width | BBWidth percentile (20-period) | VOLATILE / NORMAL |
| ATR Ratio | ATR(14) / ATR(50) | EXPANDING / CONTRACTING |

**Output states:** TRENDING, RANGING, VOLATILE (3-state classification)

**Regime filter behavior:** When `regime_filter=True`, entries during EXHAUSTED and COMPRESSION regimes are blocked. This prevents trading during low-conviction environments. When `regime_filter=False` (MES only), all regimes are tradeable.

**Adaptive regime mode:** When `adaptive_regime=True` (MNQ only), the regime classifier dynamically adjusts STC thresholds based on detected regime. This lifts MNQ WFE from 0.24 (static) to 0.57 (adaptive). Adaptive mode is anti-productive for MCL (WFE drops from 0.82 to -0.31) and neutral for MGC.

### Layer 2 — Structure Map

Structure analysis using institutional-grade levels:

- **Initial Balance (IB) levels**: First 60 minutes of session high/low
- **KAMA (Kaufman Adaptive Moving Average)**: Period=10, adapts to volatility
- **TPO (Time Price Opportunity)**: Volume-at-price profile for value area identification
- **Keltner Channels**: Dynamic support/resistance bands

### Layer 3 — Directional Bias (STC Crossover)

The primary signal generator is the **Schaff Trend Cycle (STC)**, a cycle-smoothed MACD that oscillates between 0 and 100:

- **Long signal:** STC crosses UP through the oversold threshold (STC_OS)
- **Short signal:** STC crosses DOWN through the overbought threshold (STC_OB)
- Supporting indicators: CCI, Phase Oscillator, EMA Ribbon, Range Consumed %

### Layer 4 — Entry Timing

Entry execution rules after all layers 1-3 confirm:

**Entry conditions checklist (all 8 must pass):**
1. STC crossover signal fires (Layer 3)
2. Regime filter passes (Layer 1) — unless regime_filter=False
3. Structure alignment confirmed (Layer 2)
4. No duplicate signal on consecutive bars
5. Within trading hours (CME Globex session)
6. No news blackout active (81 scheduled events)
7. Risk budget available (position not at max)
8. Kill switch not active

**Stop placement:** ATR-based, multiplied by per-instrument STOP_ATR parameter.

**Target architecture (scaled exits):**
| Target | ATR Multiple | Position % | Action |
|--------|-------------|-----------|--------|
| T1 | Per-instrument T1_ATR | 50% | Take profit, move stop to breakeven |
| T2 | Per-instrument T2_ATR | 25% | Take profit |
| T3 | Per-instrument T3_ATR | 25% | Final exit |
| EOD | Market close | 100% remaining | Flatten all positions |

**Exit rules:**
- Stop loss: Exact ATR-based stop price (no partial bar P&L credit — bug #2 fix)
- T1 hit: Exit 50%, move stop to breakeven
- T2 hit: Exit 25%
- T3 hit: Exit remaining 25%
- EOD: Flatten all remaining positions at session close
- Kill switch: Immediate market order to flatten all positions

### Layer 5 — Position Sizing

Fixed fractional risk model:

| Mode | Risk Per Trade | Calculation |
|------|---------------|-------------|
| Paper trading | 0.25% | `capital * 0.0025 / (stop_distance * multiplier)` |
| Live (future) | 1.00% | `capital * 0.01 / (stop_distance * multiplier)` |

Position size = `risk_amount / (ATR * stop_mult * contract_multiplier)`, rounded down to whole contracts. Maximum 1 concurrent position per instrument.

---

## 1.3 Walk-Forward Validation Results (FINAL v2.7)

Walk-forward validation is the **only** method used to determine if a strategy generalizes to unseen data. In-sample performance is meaningless without OOS confirmation. This section contains the AUTHORITATIVE results from 12 completed walk-forward runs.

### WFE Formula and Thresholds

```
WFE = Avg OOS Return / Avg IS Return
```

| WFE Range | Rating | Action |
|-----------|--------|--------|
| > 0.70 | EXCELLENT | Approved for paper trading |
| 0.50 - 0.70 | GOOD | Approved for paper trading |
| 0.30 - 0.50 | MARGINAL | Not approved — needs improvement |
| < 0.30 | OVERFIT | DO NOT TRADE — curve-fitted |

### AUTHORITATIVE Walk-Forward Results (12 Completed Runs)

| # | Symbol | TF | Config | Windows | OOS Profitable | WFE | Verdict |
|---|--------|-----|--------|---------|----------------|-----|---------|
| 1 | **MCL** | 1h | Static params | 6 | 5/6 (83%) | **0.82** | **EXCELLENT — APPROVED** |
| 2 | **MNQ** | 1h | Adaptive regime | 6 | 4/6 (67%) | **0.57** | **GOOD — APPROVED** |
| 3 | MNQ | 1h | Adaptive + MTF | 6 | — | 0.17 | REJECTED — MTF HURTS |
| 4 | MNQ | 1h | Adaptive + Volume | 6 | — | -0.23 | REJECTED — Volume HURTS |
| 5 | MCL | 1h | Adaptive regime | 6 | — | -0.31 | REJECTED — Adaptive HURTS MCL |
| 6 | MNQ | 1h | Static params | 6 | — | 0.24 | OVERFIT |
| 7 | MGC | 1d | Static (15-window) | 15 | 6/15 (40%) | 0.14 | OVERFIT — HALTED |
| 8 | MGC | 1d | Adaptive (3-window) | 3 | 2/3 (67%) | 0.88 | SMALL-SAMPLE BIAS — INVALID |
| 9 | MGC | 1d | Adaptive (15-window) | 15 | — | 0.27 | OVERFIT (extended disproves 0.88) |
| 10 | MES | 1h | Static params | 6 | 1/6 (17%) | 0.09 | OVERFIT — DO NOT TRADE |
| 11 | SPY | 1h | Static params | 6 | 2/6 (33%) | -1.11 | DEEPLY OVERFIT |
| 12 | SPY | 1h | Adaptive regime | 6 | — | -0.71 | STILL OVERFIT |

**Result file locations:** All stored in `engine/backtest/results/WF_*.json`

### Version History of Critical Corrections

**v2.7 (2026-03-30):** MNQ adaptive WFE corrected 0.48 to 0.57 (latest confirmed run 2026-03-29T23:46). MCL static WFE confirmed 0.82 (run 2026-03-29T23:41). Both clear the 0.50 GOOD threshold. MTF filter confirmed to HURT MNQ (0.57 to 0.17). Volume filter also HURTS (0.57 to -0.23). Both filters REJECTED permanently.

**v2.6 (2026-03-29):** CRITICAL optimizer kwarg bug discovered and fixed. Extra kwargs (`adaptive_regime`, `volume_filter`, `mtf_filter`) were silently passed to `_compute_signals()` causing TypeError on every walk-forward optimization call. The bare `except` clause caught the error and returned `None`, meaning ALL walk-forward runs after these kwargs were added produced invalid results. Fix: filter kwargs to `signal_keys` in `_run_with_params()` before calling `_compute_signals()`. Post-bugfix corrections: MGC 1d WFE 0.27 to 0.14, MNQ 1h WFE 0.34 to 0.48 (later 0.57).

**v2.4 (2026-03-29):** MGC 1d WFE=0.88 revealed as small-sample bias. The 0.88 result came from only 3 walk-forward windows covering the 2025 gold bull run exclusively. Extended to 15 windows (2022-2026) including bear market data: WFE dropped to 0.27, then to 0.14 post-bugfix. This was the single most important finding — it prevented live deployment of an overfit strategy.

### 8 Backtester Bugs Found and Fixed

| # | Bug | Impact | Fix |
|---|-----|--------|-----|
| 1 | **Look-ahead bias** | Signals used future candle data for entry decisions | Shifted signal generation to use prior-bar close only |
| 2 | **Partial stop exits** | Stop-loss exits credited partial bar P&L instead of exact stop price | Stop exits now use exact stop price, not bar close |
| 3 | **T1 target unreachable** | 1.50 ATR target almost never hit intraday | Reduced default T1 to 1.00 ATR |
| 4 | **Duplicate trade counting** | Same signal could fire on consecutive bars | Added cooldown period after signal |
| 5 | **Equity curve errors** | Compounding applied incorrectly | Fixed cumulative return calculation |
| 6 | **Win rate inflation** | Partial exits counted as wins | Only count full trade outcome |
| 7 | **Sharpe calculation** | Wrong annualization factor | Corrected to sqrt(252) for daily, sqrt(252*6.5) for hourly |
| 8 | **Position sizing** | Fractional contracts not properly rounded | Round down to whole contracts |

**Impact:** Original backtest numbers were massively inflated by bugs #1 and #2. Median PF dropped from inflated values to 0.96 after corrections. Only 5 of 12 instrument/timeframe combinations remained profitable.

### Filter Testing Results

| Filter | Module | MNQ WFE Impact | Verdict |
|--------|--------|----------------|---------|
| **Adaptive regime** | `regime.py` | 0.24 to 0.57 (+138%) | **KEEP for MNQ** |
| **MTF (4h alignment)** | `mtf_filter.py` | 0.57 to 0.17 (-70%) | **REJECTED** |
| **Volume (20-SMA gate)** | `signals.py` | 0.57 to -0.23 (-140%) | **REJECTED** |
| **Trailing ATR stop** | `backtester.py` | Not tested on WFE | **REJECTED** (no improvement in grid search) |
| **News blackout** | `signals.py` | ~1% signals blocked | LIVE ONLY (minimal impact) |

**Key finding:** Adding filters over-constrains the model. Adaptive regime alone is the optimal MNQ configuration. MCL performs best with static params — adaptive mode actively hurts it.

### Why the Strategy Fails Walk-Forward on Most Instruments

1. **Regime dependency** — STC crossover signals work during sustained trends. The optimizer selects parameters for the in-sample trend, but OOS often presents a different regime.

2. **Parameter instability** — Optimal STC thresholds shift dramatically window-to-window (e.g., MNQ Window 1 finds STC_OB=92; Window 2 finds STC_OB=83 with regime_filter=false — completely opposite).

3. **Thin trade counts** — 6-86 trades per 6-month window provides insufficient statistical power. With ~20 trades/window, the optimizer is fitting to 5-10 independent observations.

4. **Single entry trigger** — STC crossover alone lacks multi-factor confirmation robustness.

5. **73-90% of in-sample edge evaporates** on unseen data across all instruments. The optimizer exploits historical market regimes (gold's 2024-2025 bull run, Nasdaq volatility surges) that do not persist.

---

## 1.4 Corrected Backtest Performance

All numbers below reflect the post-bugfix, per-instrument optimized results. These are IN-SAMPLE numbers — walk-forward validation (Section 1.3) determines which are trustworthy.

### Performance Table (In-Sample, Full Period)

| Rank | Symbol | TF | Trades | WR% | PF | Sharpe | Return | MaxDD | WFE | Status |
|------|--------|-----|--------|-----|------|--------|--------|-------|-----|--------|
| 1 | MCL | 1h | 65 | 60.0% | 1.83 | 0.15 | +0.2% | — | **0.82** | **APPROVED** (static) |
| 2 | MNQ | 1h | 86 | 47.7% | 1.46 | 0.19 | +13.6% | 0.1% | **0.57** | **APPROVED** (adaptive) |
| 3 | MGC | 1d | 47 | 51.1% | 2.60 | 2.04 | +34.4% | 3.0% | 0.14 | HALTED — OVERFIT |
| 4 | MES | 1h | 23 | 34.8% | 1.69 | 0.09 | +0.1% | 0.1% | 0.09 | DO NOT TRADE |
| 5 | SPY | 1h | 23 | 52.2% | 3.79 | -1.43 | +0.0% | 0.1% | -1.11 | DO NOT TRADE |

*Test period: Jun 2024 -- Mar 2026 (1h) / Jan 2025 -- Mar 2026 (1d). Returns gross of commissions ($2.50/contract + 1 tick slippage applied).*

### Do Not Trade List (Permanently Removed)

| Symbol | TF | PF | WFE | Reason |
|--------|-----|----|-----|--------|
| M2K | 1h | 0.64 | N/A | Consistently losing; Russell unsuitable for STC |
| M2K | 1d | 0.60 | N/A | Negative both timeframes |
| MCL | 1d | 0.21 | N/A | Catastrophic PF; zero targets hit on daily crude |
| MES | 1d | 0.75 | N/A | 36/51 trades exit at EOD — targets unreachable |
| MES | 1h | 1.69 | 0.09 | WFE=0.09 OVERFIT — only 1/6 OOS windows profitable |
| MNQ | 1d | 0.79 | N/A | 43/57 EOD exits; daily NQ too volatile for intraday targets |
| MGC | 1h | 0.77 | N/A | Gold works daily only; hourly loses money |
| MGC | 1d | 2.60 | 0.14 | WFE=0.14 OVERFIT — paper trading HALTED |
| SPY | 1h | 3.79 | -1.11 | Re-optimized v2.5: PF 3.00 to 3.79, near-zero returns, deeply overfit |

### Monte Carlo Summary (10,000 Simulations x 4 Instruments)

Monte Carlo simulation was run on the corrected backtest results for MNQ, MCL, MGC, and SPY. Key findings:

- Edge is real but thin across all instruments
- Parameter sensitivity is HIGH (94-95 out of 100 sensitivity score)
- Estimated real OOS edge: approximately 2-3% annualized (vs 12-34% in-sample)
- Monte Carlo confirms the strategy is not random, but returns are modest after accounting for regime shifts

### Parameter Sensitivity Summary (3 Instruments Analyzed)

Sensitivity analysis tested parameter perturbation (+/- 10-20% on each STC/ATR parameter) and found:

- All three tested instruments show high sensitivity (94-95/100)
- Small parameter changes produce large performance swings
- This explains why walk-forward fails on most instruments — the optimizer finds a sharp peak, not a broad plateau
- MCL shows the broadest stable zone, consistent with its superior WFE (0.82)

---

## 1.5 Paper Trading Configuration

Paper trading is ACTIVE as of 2026-03-30 for 2 instruments. Configuration is defined in `engine/backtest/paper_config.py`.

### MCL 1h — ACTIVE (WFE=0.82 EXCELLENT)

| Parameter | Value |
|-----------|-------|
| **Symbol** | MCL (Micro Crude Oil) |
| **Interval** | 1h |
| **Enabled** | `True` |
| **Initial Capital** | $25,000 |
| **Risk Per Trade** | 0.25% ($62.50 risk per trade) |
| **Regime Filter** | ON — oil is regime-sensitive |
| **Adaptive Regime** | OFF — adaptive WFE=-0.31, WORSE than static 0.82 |
| **Volume Filter** | OFF — not tested for MCL |
| **MTF Filter** | OFF — not tested for MCL |
| **STC Oversold** | 15 |
| **STC Overbought** | 83 |
| **Stop** | 0.90 ATR |
| **T1** | 1.50 ATR (50% exit) |
| **T2** | 2.618 ATR (25% exit) |
| **T3** | 4.00 ATR (25% exit) |
| **Contract Multiplier** | $100/point (1000 barrels x $0.10 tick) |
| **Tick Size** | 0.01 |
| **Commission** | $2.50/contract |
| **Slippage** | 1 tick |
| **Max Concurrent Positions** | 1 |

**Kill switch thresholds:**
| Trigger | Threshold |
|---------|-----------|
| Consecutive losses | 3 |
| Consecutive months underperform | 3 |
| Monthly loss | -3% |
| Max daily loss | -2% |
| Rolling WFE minimum | 0.40 |

**Walk-forward detail:** 6 windows from 2024-06-01 to 2026-03-27. 5 of 6 windows profitable OOS (83%). Static params outperform adaptive for MCL — do NOT enable adaptive_regime. Result file: `engine/backtest/results/WF_MCL_1h_walk_forward.json`.

### MNQ 1h — ACTIVE (WFE=0.57 GOOD)

| Parameter | Value |
|-----------|-------|
| **Symbol** | MNQ (Micro Nasdaq) |
| **Interval** | 1h |
| **Enabled** | `True` |
| **Initial Capital** | $25,000 |
| **Risk Per Trade** | 0.25% ($62.50 risk per trade) |
| **Regime Filter** | ON — required for adaptive_regime to work |
| **Adaptive Regime** | ON — CRITICAL, lifts WFE from 0.24 to 0.57 |
| **Volume Filter** | OFF — NEVER ENABLE (WFE drops to -0.23) |
| **MTF Filter** | OFF — NEVER ENABLE (WFE drops to 0.17) |
| **STC Oversold** | 15 |
| **STC Overbought** | 92 |
| **Stop** | 0.70 ATR |
| **T1** | 1.00 ATR (50% exit) |
| **T2** | 1.80 ATR (25% exit) |
| **T3** | 2.618 ATR (25% exit) |
| **Contract Multiplier** | $2/point (Micro Nasdaq) |
| **Tick Size** | 0.25 |
| **Commission** | $2.50/contract |
| **Slippage** | 1 tick |
| **Max Concurrent Positions** | 1 |

**Kill switch thresholds:**
| Trigger | Threshold |
|---------|-----------|
| Consecutive losses | 3 |
| Consecutive months underperform | 3 |
| Monthly loss | -3% |
| Max daily loss | -2% |
| Rolling WFE minimum | 0.30 |

**Filter verdicts (FINAL — do not re-test):**

| Config | WFE | Verdict |
|--------|-----|---------|
| Static params | 0.24 | OVERFIT |
| + Adaptive regime | **0.57** | GOOD — APPROVED |
| + Volume filter | -0.23 | REJECTED — HURTS |
| + MTF filter | 0.17 | REJECTED — HURTS |

**Walk-forward detail:** 6 windows from 2024-04-26 to 2026-03-27 (extended start date for more training data). 4 of 6 windows profitable OOS (67%). Adaptive regime is non-negotiable for MNQ — static params are OVERFIT. Result file: `engine/backtest/results/WF_MNQ_1h_adaptive_walk_forward.json`.

**OOS stable param zone (Agent AC finding):** OS=23, OB=88, stop=0.70 ATR, T1=2.00 ATR — identified as the most parameter-stable region across walk-forward windows.

### MGC 1d — HALTED (WFE=0.14 OVERFIT)

| Parameter | Value |
|-----------|-------|
| **Symbol** | MGC (Micro Gold) |
| **Interval** | 1d |
| **Enabled** | `False` — HALTED |
| **Reason** | WFE=0.14, below 0.30 OVERFIT threshold |
| **Initial Capital** | $25,000 |
| **Risk Per Trade** | 0.25% |
| **Regime Filter** | OFF — regime_filter is anti-predictive for gold daily |
| **Adaptive Regime** | OFF — adaptive WFE identical to static (0.27); zero benefit |
| **Volume Filter** | OFF — volume data unreliable on daily timeframe |
| **STC Oversold** | 15 |
| **STC Overbought** | 83 |
| **Stop** | 0.30 ATR |
| **T1** | 1.00 ATR |
| **Contract Multiplier** | $10/point (10 oz gold) |
| **Tick Size** | 0.10 |
| **Commission** | $2.50/contract |
| **Slippage** | 1 tick |

**Kill thresholds (if re-enabled):**
| Trigger | Threshold |
|---------|-----------|
| Consecutive months underperform | 3 |
| Monthly underperform vs IS | > 50% below baseline |
| Rolling WFE minimum | 0.15 |
| Halt if first N months negative | 3 |

**Why halted:** The initial WFE of 0.88 was small-sample bias from only 3 walk-forward windows covering the 2025 gold bull run. Extended to 15 windows (2022-2026) including bear market data, WFE dropped to 0.27, then to 0.14 post-optimizer-bugfix. MGC requires fundamental signal redesign with extended history before reconsidering paper trading.

### Kill Switch Architecture

The kill switch is a global safety mechanism that halts ALL trading activity instantly. It operates independently of the LLM pipeline and cannot be overridden by any agent.

**Activation triggers (any one triggers halt):**
1. Daily loss exceeds -2% of portfolio equity
2. Monthly loss exceeds -3%
3. 3 consecutive losing trades on any single instrument
4. Maximum drawdown exceeds 10%
5. Manual activation via `POST /safety/kill-switch/activate`

**When activated:**
- All open positions are flattened via market order
- All pending orders are cancelled
- WhatsApp alert sent to Matt via Twilio
- No new orders accepted until manual deactivation
- Deactivation requires `POST /safety/kill-switch/deactivate` (Tier 3 authority)

### Re-evaluation Schedule

| Cadence | Action |
|---------|--------|
| Daily | Monitor signal generation for MCL and MNQ |
| Weekly | Review paper trade P&L vs expectations |
| Every 4 weeks | Recalculate rolling WFE with new data appended |
| Quarterly | Full walk-forward revalidation with extended history |
| Ad hoc | Re-evaluate if kill switch activates on either instrument |


---

<!-- Sections 1.6-1.20 follow (previously Part 2) -->

## 1.6 Risk Management & Safety Layer

The safety layer is the most critical subsystem in JARVIS TRADER. It is implemented entirely in hardcoded Python -- no LLM reasoning exists anywhere in the risk path. The design follows the TradeTrap paper principle: portfolio state of record comes from the broker API, never from agent memory. Hard limits cannot be overridden by agent reasoning.

**Source files:**
- `engine/risk/safety_layer.py` -- SafetyLayer class (703 lines)
- `engine/risk/loss_tracker.py` -- ConsecutiveLossTracker class (339 lines)
- `engine/risk/pnl_monitor.py` -- PnLMonitor class (439 lines)
- `engine/health_monitor.py` -- standalone health polling daemon (224 lines)

### 1.6.1 Circuit Breakers (Hardcoded Python, NOT LLM-Controlled)

Every circuit breaker is a deterministic threshold check inside `SafetyLayer.check_order()`. The method runs 9 sequential checks; the first failure returns `RiskCheckResult(approved=False)` and blocks the order from reaching any broker. No LLM has access to modify these thresholds at runtime. They are set via `.env` at engine startup and remain immutable for the session.

**Circuit Breaker 1 -- Kill Switch Gate**
- Threshold: `_kill_switch_active == True`
- Trigger: Any prior activation of the kill switch (manual, automated, or emergency)
- Action: Immediately returns `approved=False` with reason "Kill switch active: {reason}"
- Reset: Manual deactivation only via `POST /safety/kill-switch/deactivate` (Tier 3)
- Code location: `safety_layer.py` line 198

**Circuit Breaker 2 -- Live Trading Gate**
- Threshold: `LIVE_TRADING_ENABLED == False` in settings
- Trigger: Environment variable not set to True
- Action: Returns `approved=False` with reason "Live trading is disabled"
- Reset: Change `LIVE_TRADING_ENABLED=True` in `.env` and restart engine
- Purpose: Prevents any broker submission during paper-only mode
- Code location: `safety_layer.py` line 205

**Circuit Breaker 3 -- Human Approval Gate**
- Threshold: `REQUIRE_HUMAN_APPROVAL == True` in settings
- Trigger: Default configuration requires human confirmation
- Action: Returns `approved=False` with reason "Human approval required"
- Reset: Change `REQUIRE_HUMAN_APPROVAL=False` in `.env` (Tier 3 decision)
- Code location: `safety_layer.py` line 212

**Circuit Breaker 4 -- Daily Loss Limit**
- Threshold: `-2%` of portfolio equity (`MAX_DAILY_LOSS_PCT=0.02`)
- Data source: PnLMonitor (IB Gateway -> SQLite -> in-memory fallback) when available; otherwise `_daily_realized_pnl` in-memory value
- Trigger: `daily_pnl < -(portfolio_equity * 0.02)`
- Action: Activates kill switch with reason `DAILY_LOSS_LIMIT`, returns `approved=False`
- Reset: Manual kill switch deactivation only
- WhatsApp alert: Sent automatically on activation via `get_notifier().alert_kill_switch()`
- Code location: `safety_layer.py` lines 218-232

**Circuit Breaker 5 -- Maximum Drawdown**
- Threshold: `-10%` from peak equity (`MAX_DRAWDOWN_PCT=0.10`)
- Data source: PnLMonitor drawdown calculation (reads from SQLite peak history), or in-memory equity peak comparison
- Trigger: `drawdown > 0.10` (i.e., current equity is 10%+ below peak)
- Action: Activates kill switch with reason `MAX_DRAWDOWN`, returns `approved=False`
- Early warning: At 80% of limit (8% drawdown), a warning is appended but order proceeds
- Reset: Manual kill switch deactivation + investigation required
- Code location: `safety_layer.py` lines 237-266

**Circuit Breaker 6 -- Single Order Value**
- Threshold: `$5,000` per order (`MAX_SINGLE_ORDER_VALUE=5000.0`)
- Trigger: `order.estimated_value > 5000.0`
- Action: Returns `approved=False` with reason showing value vs limit
- Reset: N/A -- submit a smaller order
- Code location: `safety_layer.py` lines 268-273

**Circuit Breaker 7 -- Position Size Limit**
- Threshold: `5%` of portfolio equity (`MAX_POSITION_SIZE_PCT=0.05`)
- Trigger: `(order.estimated_value / portfolio_equity) > 0.05`
- Action: Returns `approved=False` with position pct vs limit
- Reset: N/A -- submit a smaller position
- Code location: `safety_layer.py` lines 275-281

**Circuit Breaker 8 -- Order Rate Throttle (Anti-Runaway)**
- Threshold: `10 orders per minute` (`MAX_ORDERS_PER_MINUTE=10`)
- Implementation: Sliding window of timestamps, pruned to last 60 seconds
- Trigger: `len(recent_timestamps) >= 10` within 60-second window
- Action: Activates kill switch with reason `ANOMALOUS_ORDER_RATE`, returns `approved=False`
- Purpose: Prevents runaway loops from malfunctioning LLM agents
- Reset: Manual kill switch deactivation
- Code location: `safety_layer.py` lines 283-295

**Circuit Breaker 9 -- Futures Contract Limit**
- Threshold: `MAX_CONTRACTS_PER_INSTRUMENT` (configurable, default 2)
- Trigger: `abs(order.quantity) > MAX_CONTRACTS_PER_INSTRUMENT`
- Action: Returns `approved=False` showing requested vs max contracts
- Reset: N/A -- submit fewer contracts
- Code location: `safety_layer.py` lines 297-302

**Circuit Breaker 10 -- Consecutive Loss Halt**
- Threshold: 7 consecutive losses globally (`CONSECUTIVE_LOSS_HALT=7`)
- Trigger: Loss tracker reports `is_halted() == True`
- Action: Returns `approved=False` with halt reason and resume time
- Reset: Wait 24 hours (auto-expiry) OR manual reset via `/safety/loss-tracker/reset`
- Code location: `safety_layer.py` lines 304-311

**Margin Utilization Check**
- Threshold: `40%` of available margin (`MAX_MARGIN_UTILIZATION=0.40`)
- Configured in `.env` as `MAX_MARGIN_UTILIZATION=0.40`
- When IB Gateway is connected, margin data is read from the broker account summary
- If margin utilization exceeds 40%, new orders are blocked

### 1.6.2 Kill Switch Architecture

The kill switch is a binary halt mechanism with three logical states:

| State | Value | Description |
|-------|-------|-------------|
| ARMED | `_kill_switch_active = False` | Normal monitoring -- all circuit breakers active, trading permitted |
| TRIGGERED | `_kill_switch_active = True` | Trading halted -- all orders rejected, reason logged |
| MANUAL_OVERRIDE | N/A (deactivation path) | Emergency bypass -- only via human action, logged with timestamp and reason |

**Kill Switch Reasons (KillSwitchReason enum):**

| Reason | Enum Value | Trigger |
|--------|------------|---------|
| `MANUAL` | `"manual"` | Human activates via API or dashboard |
| `DAILY_LOSS_LIMIT` | `"daily_loss_limit"` | Daily P&L exceeds -2% of equity |
| `MAX_DRAWDOWN` | `"max_drawdown"` | Drawdown exceeds -10% from peak |
| `MARKET_CIRCUIT_BREAKER` | `"market_circuit_breaker"` | Market-wide halt (NYSE/CME) |
| `DATA_FEED_LOSS` | `"data_feed_loss"` | Stale or missing market data |
| `BROKER_DISCONNECT` | `"broker_disconnect"` | IB Gateway connection lost |
| `ANOMALOUS_ORDER_RATE` | `"anomalous_order_rate"` | >10 orders in 60 seconds |

**Activation Flow:**
1. Trigger condition detected (automated) or manual API call
2. `_kill_switch_active` set to `True`
3. `_kill_switch_reason` set to the specific `KillSwitchReason` enum
4. CRITICAL log entry: "KILL SWITCH ACTIVATED: {reason}"
5. Async task: log event to PostgreSQL via `_log_safety_event()`
6. Async task: WhatsApp alert via `get_notifier().alert_kill_switch(reason)`
7. Async task: WebSocket event via `emit_kill_switch_change(active=True, reason=reason)`
8. All subsequent `check_order()` calls return `approved=False` immediately

**Deactivation Flow (Tier 3 -- Human Approval Required):**
1. Matt calls `POST /safety/kill-switch/deactivate` (dashboard button or curl)
2. `deactivate_kill_switch(authorized_by="matt_dashboard")` called
3. `_kill_switch_active` set to `False`, `_kill_switch_reason` cleared
4. INFO log: "Kill switch deactivated by: matt_dashboard"
5. Async task: log deactivation event to PostgreSQL
6. Async task: WebSocket event broadcast
7. Trading resumes on next `check_order()` call

**Critical constraint: No LLM agent has authority to deactivate the kill switch.** The deactivation endpoint is a direct API call that must be initiated by a human. The `authorized_by` parameter is logged for audit trail.

**API Endpoints:**
```
POST /safety/kill-switch/activate?reason=manual_test
POST /safety/kill-switch/deactivate
GET  /safety/status
GET  /safety/circuit-breakers
GET  /safety/config
POST /safety/reset-daily-pnl
GET  /safety/loss-tracker
```

### 1.6.3 Consecutive Loss Tracker

The `ConsecutiveLossTracker` is a persistence-backed module that tracks losing streaks and automatically reduces position sizing as losses accumulate. State is persisted to `engine/data/loss_tracker.json` and survives application restarts.

**Position Size Modulation Rules:**

| Consecutive Losses | Multiplier | Effect | Example (base qty=2) |
|--------------------|------------|--------|----------------------|
| 0-2 | 1.0x | Normal sizing | 2 contracts |
| 3-4 | 0.5x | Half size | 1 contract |
| 5-6 | 0.25x | Quarter size | 1 contract (min 1) |
| 7+ | 0.0x (HALT) | Trading paused 24 hours | 0 contracts -- order rejected |

**Configuration (from `.env`):**
```
CONSECUTIVE_LOSS_HALF_SIZE=3
CONSECUTIVE_LOSS_QUARTER_SIZE=5
CONSECUTIVE_LOSS_HALT=7
CONSECUTIVE_LOSS_HALT_HOURS=24
```

**Tracking Behavior:**
- **Global counter**: Increments on every losing trade across all symbols
- **Per-symbol counter**: Tracks losses per instrument independently
- **Winner resets everything**: A single profitable trade resets both global and per-symbol counters to 0
- **Halt auto-expiry**: After 24 hours, the halt clears automatically; `is_halted()` returns False and the halt_until timestamp is cleared
- **Manual reset**: `POST /safety/loss-tracker/reset` or `safety_layer.reset_loss_tracker()`

**Persistence Format (`loss_tracker.json`):**
```json
{
  "global_consecutive_losses": 3,
  "symbol_losses": {
    "MCL": 2,
    "MNQ": 1
  },
  "last_trade_symbol": "MNQ",
  "last_trade_timestamp": "2026-03-30T14:22:00+00:00",
  "halt_until": null
}
```

**Integration with SafetyLayer:**
- `check_order()` calls `_loss_tracker.is_halted()` first -- if halted, order is rejected
- If not halted, `_loss_tracker.get_position_size_multiplier()` is called
- If multiplier < 1.0, a new `OrderRequest` is created with reduced quantity
- The reduced quantity is clamped to a minimum of 1 (never zero unless halted)
- A warning is appended: "Consecutive losses: {N} -- position size reduced by {pct}"

### 1.6.4 P&L Monitor (PnLMonitor)

The PnLMonitor is the ground-truth P&L data source for the safety layer. It implements a three-tier data priority cascade:

| Priority | Source | Availability | Accuracy |
|----------|--------|-------------|----------|
| 1 (highest) | IB Gateway | When IBKR connected | Real-time broker data |
| 2 | SQLite | Always (after first EOD snapshot) | End-of-day persisted |
| 3 (fallback) | In-memory PortfolioTracker | Always | Session-only paper data |

**Key methods consumed by SafetyLayer:**
- `get_daily_pnl()` -> `float`: Today's realized + unrealized P&L in dollars
- `get_drawdown_pct()` -> `float`: Current drawdown from peak as negative fraction
- `get_peak_balance()` -> `float`: Highest account balance from SQLite history
- `should_halt_trading(daily_loss_limit_pct, drawdown_limit_pct)` -> `(bool, str)`
- `record_eod_snapshot()` -> `bool`: Writes today's P&L to SQLite at market close

**EOD Snapshot Scheduling:**
- Triggered by `EODScheduler` at 4:00 PM ET daily
- Writes to SQLite `daily_pnl` table: date, starting_balance, ending_balance, realized_pnl, unrealized_pnl, total_trades, winning_trades, losing_trades, max_drawdown
- Also triggers WhatsApp EOD summary via the EODScheduler

### 1.6.5 Emergency Protocols (EP-1 through EP-6)

**EP-1: Engine Crash**
- Detection: `health_monitor.py` polls `GET /health` every 60 seconds
- Timeout: 10 seconds per request (`REQUEST_TIMEOUT=10`)
- Alert: If engine unreachable, WhatsApp alert sent within 60 seconds
- Alert cooldown: 5 minutes between repeated DOWN alerts (`ALERT_COOLDOWN=300`)
- Recovery alert: When engine comes back online, sends "JARVIS Engine RECOVERED" via WhatsApp
- Manual restart: `cd engine && .venv\Scripts\python -m uvicorn main:app --port 8010`
- Auto-restart: Not currently implemented -- requires PM2 or systemd (documented in `PAPER_TRADING_RUNBOOK.md`)

**EP-2: IB Gateway Disconnect**
- Detection: `KillSwitchReason.BROKER_DISCONNECT`
- Action: Cancel all pending orders via IB API, log all open positions
- Alert: WhatsApp notification with disconnect timestamp
- Recovery: IB Gateway auto-reconnects; PnLMonitor falls through to SQLite/memory
- Manual intervention: Restart IB Gateway, verify port 7497 reachable

**EP-3: Data Feed Failure**
- Detection: `KillSwitchReason.DATA_FEED_LOSS`
- Action: Halt signal generation -- do NOT trade on stale data
- Threshold: Quote age > 2 seconds triggers data feed loss
- Recovery: Verify Yahoo Finance / Polygon / Finnhub API keys and connectivity
- Kill switch activates: Requires human deactivation after data confirmed fresh

**EP-4: Database Corruption**
- Detection: `db_manager.health_check()` fails during `/health` endpoint
- Action: Log error, continue with in-memory fallback for P&L tracking
- Alert: Health endpoint returns `database: "error"` status
- Recovery: Stop engine, inspect `data/jarvis_trader.db`, restore from backup if needed
- PnLMonitor gracefully degrades: falls through to in-memory PortfolioTracker

**EP-5: Runaway Loss (>-5% in Single Day)**
- Detection: Daily loss exceeds 2x the normal circuit breaker threshold
- Action: Kill switch activates at -2% (EP-5 threshold is the "extreme" case beyond normal -2%)
- Escalation: At -5%, the situation requires a phone call to resume -- this is a standing human rule (not enforced in code, enforced by Matt's personal rules)
- The safety layer has no -5% specific trigger; the -2% kill switch is the automated gate

**EP-6: API Key Compromise**
- Detection: Manual discovery or anomalous API usage
- Action: Immediate engine shutdown, revoke all API keys
- Alert: WhatsApp notification + manual investigation
- Recovery: Rotate Anthropic API key, Twilio credentials, Polygon key
- Prevention: Keys stored in `.env` (gitignored), never committed to repository

### 1.6.6 IB Gateway Safety

**Port Configuration (CRITICAL):**

| Port | Purpose | Status |
|------|---------|--------|
| 7497 | IB Gateway Paper Trading | ALLOWED -- the only connection port during paper phase |
| 7496 | IB Gateway Live Trading | BLOCKED until Phase 2 (June 2026+) |
| 4001 | TWS Live API | BLOCKED -- hardcoded exclusion |
| 4002 | TWS Paper API | BLOCKED -- using IB Gateway instead |

**Environment variables controlling port:**
```
IBKR_HOST=127.0.0.1
IBKR_PORT=7497
IBKR_CLIENT_ID=1
IBKR_PAPER_MODE=True
IB_GATEWAY_HOST=127.0.0.1
IB_GATEWAY_PORT=7497
```

**Paper order submission path:**
1. Signal generated by pipeline -> `submit_paper_order()` called on SafetyLayer
2. Kill switch check (early exit if active)
3. Build `OrderRequest` from parameters
4. Run full `check_order()` with all 10 circuit breaker checks
5. If `_ib_gateway is None`: log as dry-run, return `routed_to_ib=False`
6. If IB Gateway not connected: log error, return `routed_to_ib=False`
7. Call `_ib_gateway.place_paper_order()` on port 7497
8. Return `routed_to_ib=True` with IB order ID

**Futures root detection (heuristic in safety_layer.py):**
```python
_FUTURES_ROOTS = {
    "MES", "MNQ", "M2K", "MCL", "MGC", "MHG", "MSI",
    "ES", "NQ", "RTY", "CL", "GC", "HG",
}
```

### 1.6.7 Safety Event Logging

All safety events are logged to PostgreSQL asynchronously via `_log_safety_event()`. The method is wrapped in try/except and never blocks execution -- if the database is unavailable, the event is logged to the application log only.

Events logged:
- Kill switch activation (with reason and message)
- Kill switch deactivation (with authorized_by)

WhatsApp alerts are sent for:
- Kill switch activation (any reason)
- Daily loss exceeding -1.5% (early warning -- configured in pipeline)
- 3+ consecutive losses (via loss tracker)
- Engine DOWN (via health_monitor.py)
- Engine RECOVERED (via health_monitor.py)
- Trade signals (LONG/SHORT -- via scheduler with 2-hour cooldown)
- MGC daily ENTRY_NOW signals (via scheduled job)
- EOD summary (via EODScheduler)

---

## 1.7 VIX Regime Reference (CANONICAL 6-Tier)

This is the ONE authoritative VIX tier system for JARVIS TRADER. All other documents, dashboards, and configuration files must reference this table. Any conflict between this section and another document is resolved in favor of this table.

### 1.7.1 Canonical VIX Tiers

| Tier | VIX Range | Label | Position Sizing Multiplier | Trading Posture |
|------|-----------|-------|---------------------------|-----------------|
| 1 | < 12 | VERY_LOW | 1.0x (full size) | Watchful calm -- snap reversals common |
| 2 | 12-16 | LOW | 1.0x (full size) | Favorable conditions for STC strategy |
| 3 | 16-20 | NORMAL | 1.0x (full size) | Baseline conditions -- standard operations |
| 4 | 20-25 | ELEVATED | 0.75x (reduce) | Volatility rising -- tighter stops |
| 5 | 25-30 | HIGH | 0.50x (half size) | Liberation Day territory -- caution |
| 6 | > 30 | EXTREME | 0.25x (minimum) | Severe market stress -- survival mode |

### 1.7.2 Per-Regime Trading Notes

**Tier 1 -- VERY_LOW (VIX < 12):**
- Deceptive calm -- historically precedes sharp reversals
- NOT a free pass for aggressive sizing
- Full position size allowed but watch for VIX expansion signals
- STC signals may be less reliable due to compressed ranges
- Mean-reversion signals more likely to work here

**Tier 2 -- LOW (VIX 12-16):**
- Ideal trading conditions for the STC strategy
- Normal stop/target multiples apply (per instrument INSTRUMENT_PARAMS)
- Full-size positions approved
- Most walk-forward windows trained in this environment

**Tier 3 -- NORMAL (VIX 16-20):**
- Baseline operating environment
- All standard parameters apply without modification
- No alerts generated at this level
- Matt does not need to monitor VIX actively

**Tier 4 -- ELEVATED (VIX 20-25):**
- Reduce position size to 0.75x
- Tighten stop losses by 0.5 ATR from baseline
- Avoid counter-trend entries (wait for trend confirmation)
- WhatsApp alert when VIX crosses 20 upward
- Consider skipping midday lull signals entirely
- Regime-adaptive STC may shift parameters in this tier

**Tier 5 -- HIGH (VIX 25-30):**
- "Liberation Day" mode -- named after April 2025 Liberation Day market event
- Position size reduced to 0.50x maximum
- Widen stops by 1.5x from baseline (to accommodate larger swings)
- WhatsApp alert on VIX crossing 25
- Only take signals with very high conviction (confidence > 80%)
- No new positions in first/last 30 minutes of RTH
- Consider pausing automated signals and going to manual-only

**Tier 6 -- EXTREME (VIX > 30):**
- Survival mode -- 0.25x sizing or HALT entirely at Matt's discretion
- WhatsApp alert on VIX crossing 30
- Consider activating kill switch manually
- If already in positions, manage exits only -- no new entries
- Historical events in this tier: COVID crash (Mar 2020), Liberation Day aftermath
- STC strategy has NOT been validated in this regime -- treat with extreme caution

### 1.7.3 VIX Alert Thresholds

| VIX Level | Direction | Action |
|-----------|-----------|--------|
| Crosses 20 upward | Rising | WhatsApp alert: "VIX > 20 -- switching to ELEVATED mode" |
| Crosses 25 upward | Rising | WhatsApp alert: "VIX > 25 -- Liberation Day protocol active" |
| Crosses 30 upward | Rising | WhatsApp alert: "VIX > 30 -- consider HALT" |
| Drops below 20 | Falling | WhatsApp alert: "VIX < 20 -- returning to NORMAL mode" |
| Drops below 25 | Falling | WhatsApp alert: "VIX < 25 -- downgrading from HIGH to ELEVATED" |

### 1.7.4 VIX Data Source

- **Ticker**: `^VIX` via Yahoo Finance (yfinance library)
- **Endpoint**: `GET /macro/snapshot` returns current VIX level in `vix` field
- **Check frequency**: At market open (9:30 AM ET) and every 30 minutes during RTH
- **Fallback**: If Yahoo Finance fails, Finnhub API as secondary source
- **The `/macro/snapshot` response includes**: VIX level, 10Y yield, 2Y yield, DXY, yield curve slope, and macro regime classification

---

## 1.8 Three-Tier Autonomy Model

JARVIS TRADER operates under a strict three-tier autonomy model that governs what the system can do without human involvement. This model exists to prevent runaway losses from LLM errors while allowing JARVIS to be maximally helpful on research and monitoring.

The principle: **conservative autonomy -- research freely, confirm before acting.**

### 1.8.1 Tier 1 -- Fully Autonomous (No Human Approval Needed)

These actions execute continuously without any human intervention. They are read-only or produce only informational output.

| Action | Frequency | Implementation |
|--------|-----------|---------------|
| Engine health checks | Every 60 seconds | `health_monitor.py` polls `GET /health` |
| Market data fetches | Continuous during RTH | `MarketDataManager.initialize()` + scheduled jobs |
| Signal generation and logging | Every 30 minutes | `run_watchlist_analysis()` via APScheduler |
| Paper trade signal evaluation | Per signal | `TradingPipeline.analyze_and_decide()` |
| Performance metric calculations | On demand | `PortfolioTracker.get_performance()` |
| WhatsApp status updates (informational) | Per trigger | `get_notifier().send()` |
| Log rotation and cleanup | Automatic | `RotatingFileHandler` -- 10MB files, 5 backups |
| Walk-forward WFE recalculation | Every 4 weeks | Scheduled or manual trigger |
| Circuit breaker monitoring | Every `check_order()` call | SafetyLayer pre-trade checks |
| VIX level monitoring | Every 30 minutes | `GET /macro/snapshot` in scheduler |
| EOD P&L snapshot | 4:00 PM ET daily | `EODScheduler.record_eod_snapshot()` |
| Decision logging to SQLite | Per pipeline run | `_decision_log.append()` in scheduler |
| Kill switch auto-activation | On threshold breach | SafetyLayer circuit breakers |
| Consecutive loss tracking | Per trade close | `ConsecutiveLossTracker.record_trade()` |

### 1.8.2 Tier 2 -- Recommend-Then-Execute (JARVIS Acts After Confirmation Window)

These actions involve decisions that affect positions or system state. JARVIS generates a recommendation and acts after a brief confirmation window or sends an alert requiring no immediate response.

| Action | Confirmation Window | Mechanism |
|--------|-------------------|-----------|
| New paper trade signals (LONG/SHORT) | 5-minute window to cancel | WhatsApp alert with signal details; if no cancel, proceeds |
| Regime change detections | Alerts, then adjusts sizing | VIX tier change triggers alert + auto-adjust multiplier |
| Kill switch ARM/DISARM recommendations | Alert only -- human decides | WhatsApp recommendation, no auto-action |
| Stop loss adjustments | Pre-approved ATR range only | Adjustments within INSTRUMENT_PARAMS bounds are automatic |
| WhatsApp alerts requiring no action | Immediate | Informational -- VIX changes, EOD summaries, signal logs |
| Position size reduction (consecutive losses) | Immediate | Automatic per loss tracker rules (0.5x, 0.25x) |

### 1.8.3 Tier 3 -- Human Approval Required (NEVER Autonomous)

These actions have material consequences and require explicit human authorization. No LLM, no automated system, and no agent can perform these without Matt's direct involvement.

| Action | Why Human Required | Authorization Method |
|--------|-------------------|---------------------|
| Kill switch deactivation | Resuming trading after emergency halt | `POST /safety/kill-switch/deactivate` via dashboard or curl |
| Live trading activation | Transitioning from paper to real money | Set `LIVE_TRADING_ENABLED=True` + `SCHWAB_READY=True` in `.env` |
| Capital allocation changes | Any modification to base capital amount | Edit `paper_config.py` manually |
| New instrument approval | Adding symbols beyond MCL/MNQ | Walk-forward validation + manual config change |
| API key rotation | Security-sensitive credential changes | Manual `.env` update + engine restart |
| Any action with $ consequence > $500 | Financial impact threshold | Manual review and explicit confirmation |
| Any system config change in paper_config.py | Configuration that affects trading behavior | Manual file edit + engine restart |
| Database schema changes | Structural data changes | Manual migration scripts |
| IB Gateway port change (7497 -> 7496) | Live trading port transition | Manual `.env` update + engine restart |
| Monthly loss tracker reset | Clearing accumulated loss state | `POST /safety/loss-tracker/reset` (manual trigger) |

### 1.8.4 Why This Model

1. **Prevents runaway losses from LLM errors**: Even if an agent hallucinates a "strong buy" signal, the safety layer still gates every order through hardcoded circuit breakers
2. **Preserves human authority over capital at risk**: Matt retains final say on anything that puts real money at risk
3. **Allows JARVIS to be maximally helpful**: Research, monitoring, signal generation, and alerting all run autonomously -- Matt gets the benefit without the risk
4. **Conservative by design**: The system errs on the side of NOT trading rather than trading incorrectly
5. **Audit trail**: Every Tier 2 and Tier 3 action is logged with timestamp, actor, and reason

---

## 1.9 Standing Orders & Proactive Triggers

### 1.9.1 Standing Orders (SO-1 through SO-6)

Standing orders are persistent directives that JARVIS follows every trading day without being asked.

**SO-1: Health Monitoring (Continuous)**
- Frequency: Every 60 seconds, 24/7
- Implementation: `health_monitor.py` daemon
- Polls: `GET http://localhost:8010/health`
- Timeout: 10 seconds per request
- Alert: WhatsApp if engine unreachable for >60 seconds
- Alert cooldown: 5 minutes between repeated DOWN alerts
- Recovery notification: Sends "JARVIS Engine RECOVERED" when engine comes back

**SO-2: Market Scan During RTH (Every 30 Minutes)**
- Frequency: Every 30 minutes, Mon-Fri, 9:00 AM - 3:30 PM CT
- Implementation: APScheduler with CronTrigger `day_of_week="mon-fri", hour="9-15", minute="0,30"`
- Scope: Top 2 futures watchlist symbols + top 3 equities watchlist symbols
- Pipeline: Full 5-stage analysis (Technical -> News -> Social -> Fundamental -> Bull/Bear Debate -> Trade Decision -> Risk Review -> Fund Manager)
- Kill switch check: Skips scan if kill switch is active
- Output: Decision logged to `_decision_log`, WhatsApp alert for non-HOLD signals
- WhatsApp cooldown: 2 hours per symbol to prevent alert flooding

**SO-3: EOD Summary (4:05 PM CT Daily)**
- Frequency: Once daily at 4:05 PM CT on trading days
- Implementation: `EODScheduler` registered on the APScheduler instance
- Content: P&L recap, trade count, win rate, regime status, next-day outlook
- Delivery: WhatsApp message via Twilio
- Also: Writes P&L snapshot to SQLite `daily_pnl` table

**SO-4: Rolling WFE Recalculation (Every 4 Weeks)**
- Frequency: Every 4 weeks (manual trigger or scheduled)
- Scope: MCL 1h (static) and MNQ 1h (adaptive)
- Alert: If WFE drops below 0.40 for either instrument, WhatsApp alert
- Action on WFE drop: If below 0.40, consider pausing paper trading for that instrument
- Re-optimization: If WFE below 0.30, trigger full parameter re-optimization

**SO-5: MGC Daily Signal Scanner (6:00 PM ET / 5:00 PM CT)**
- Frequency: Mon-Fri at 23:00 UTC (6:00 PM ET / 5:00 PM CT)
- Implementation: APScheduler CronTrigger, `run_daily_mgc_signal()` function
- Process: Fetches 90 days of GC=F daily bars, runs `generate_signals()` with adaptive regime
- Output: If ENTRY_NOW signal detected, writes to `engine/backtest/results/pending_signals.json`
- Alert: WhatsApp with direction, entry estimate, stop, target, and regime
- NOTE: MGC paper trading is HALTED (WFE=0.14) -- this scanner runs for research/monitoring only

**SO-6: Kill Switch Monitoring (Continuous)**
- Frequency: Checked on every `check_order()` call (effectively per-trade)
- Scope: Daily P&L, consecutive losses, monthly P&L
- Thresholds: -2% daily loss, 7 consecutive losses, -3% monthly loss
- Auto-activation: Daily loss and consecutive loss triggers are automated
- Monthly loss: Checked manually (not yet automated in code)

### 1.9.2 Proactive Triggers (T-1 through T-24)

Proactive triggers are event-based or time-based actions that fire when specific conditions are met.

#### Time-Based Triggers

**T-1: Futures Pre-Market Check (6:00 AM CT)**
- Action: Check Globex overnight prices for MCL, MNQ, MES
- Data source: `GET /prices/snapshot`
- Purpose: Identify overnight gaps that may affect today's trading
- Delivery: Included in pre-market briefing

**T-2: Pre-Market Briefing (6:30 AM CT)**
- Action: Compile and deliver pre-market intelligence brief
- Content: Overnight futures prices, VIX level, economic calendar, yesterday's performance
- 7-step data collection: Health check, VIX/macro, portfolio review, previous decisions, prices, sentiment, economic calendar
- Delivery: WhatsApp message (automated)
- Matt reviews during his 7-8 AM CT morning window

**T-3: Economic Data Alert (8:30 AM CT)**
- Action: Check for major economic releases (CPI, NFP, FOMC)
- Data source: Economic calendar scan
- If major release: Enable news blackout window (T-20, T-21, T-22)
- If no release: Proceed with normal operations

**T-4: RTH Open -- Activate Signal Scanning (9:30 AM CT / 8:30 AM CT)**
- Action: Scheduler begins 30-minute scan cycle (SO-2)
- First scan fires at 9:00 AM CT (30 min before RTH open)
- Kill switch checked before each scan

**T-5: First 1h Candle Closes -- Initial IB Level Set (9:35 AM CT)**
- Action: First hourly candle closes; STC calculates initial levels
- Purpose: Establishes initial bias, entry zones, IB range
- Signal: May generate first ENTRY_NOW of the day

**T-6: Midday Check (11:30 AM CT)**
- Action: Review open positions, check P&L against daily targets
- Matt's preferred trading window closes at 11:30 AM CT
- Signal quality typically degrades during 11:30 AM - 1:00 PM CT

**T-7: Afternoon Session Opens (1:00 PM CT)**
- Action: Second signal window begins
- Quality: Valid signals but generally lower quality than morning
- Matt's secondary trading window: 1:00 PM - 3:30 PM CT

**T-8: RTH Wind-Down (3:30 PM CT)**
- Action: Begin EOD exit checks for all open 1h positions
- No new entries after 3:30 PM CT
- Exit management only

**T-9: Force-Close All Open Positions (3:59 PM CT)**
- Action: Any open 1h signal positions are closed at market
- Rule: NO overnight holds for 1h signals -- mandatory
- Implementation: EOD exit logic in backtester applies to paper trades

**T-10: EOD Summary Report (4:05 PM CT)**
- Action: Generate and send daily performance summary
- Content: Total P&L, trade count, win rate, max drawdown, regime status
- Delivery: WhatsApp via Twilio
- Database: P&L snapshot written to SQLite

#### Event-Based Triggers

**T-11: VIX Crosses 20 Upward**
- Action: WhatsApp alert, switch to ELEVATED mode (0.75x sizing)
- Priority: Immediate
- Adjustment: Tighter stops, avoid counter-trend entries

**T-12: VIX Crosses 25 Upward**
- Action: WhatsApp alert, Liberation Day protocol (0.50x sizing)
- Priority: Immediate
- Adjustment: Widen stops 1.5x, high-conviction signals only

**T-13: Daily Loss Hits -1.5%**
- Action: Early warning WhatsApp alert
- Priority: High
- Note: This is a warning, not a circuit breaker -- the -2% hard limit triggers kill switch

**T-14: Daily Loss Hits -2%**
- Action: Kill switch auto-activates (circuit breaker 4)
- Priority: CRITICAL
- Recovery: Manual deactivation only (Tier 3)

**T-15: 3 Consecutive Losses**
- Action: Position size reduced to 0.5x automatically
- Alert: WhatsApp notification
- Recovery: Resets on next winning trade

**T-16: Kill Switch Triggers**
- Action: Immediate WhatsApp alert + all trading halted
- Priority: CRITICAL
- Information: Includes reason, timestamp, and current P&L

**T-17: Engine Goes Offline**
- Action: health_monitor.py detects within 60 seconds, WhatsApp alert
- Recovery: Manual restart required
- Alert includes: Failure reason and restart command

**T-18: IB Gateway Disconnects**
- Action: Cancel pending orders, log positions, WhatsApp alert
- Recovery: IB Gateway auto-reconnects or manual restart
- PnLMonitor: Falls through to SQLite/memory sources

**T-19: New Signal Generated (LONG/SHORT)**
- Action: Tier 2 recommendation via WhatsApp
- Content: Symbol, direction, confidence, entry price, stop, target
- Cooldown: 2 hours per symbol (no duplicate alerts)

#### Intelligence Triggers

**T-20: FOMC Meeting Day**
- Action: Auto-enable news blackout for 2-hour window around announcement
- Typical schedule: 1:00 PM CT announcement + press conference
- Blackout window: 12:00 PM - 2:00 PM CT (no new entries)
- Implementation: `engine/backtest/signals.py` news_blackout parameter

**T-21: NFP Friday (Non-Farm Payrolls)**
- Action: Auto-enable news blackout 8:00 AM - 10:00 AM CT
- Frequency: First Friday of each month
- Impact: High-volatility event, avoid entries during initial reaction

**T-22: CPI Release Day**
- Action: Auto-enable news blackout for release window
- Typical schedule: 7:30 AM CT release
- Blackout window: 7:00 AM - 9:00 AM CT

**T-23: Quarter-End (Last Week of Quarter)**
- Action: Reduce sizing to 0.75x (window dressing flows distort price action)
- Affected weeks: Last 5 trading days of March, June, September, December
- Rationale: Institutional rebalancing creates non-fundamental price moves

**T-24: New Month Start**
- Action: Reset monthly loss tracker, send monthly performance summary
- Content: Month P&L, win rate, Sharpe, max drawdown, instrument breakdown
- Delivery: WhatsApp message on first trading day of the month

### 1.9.3 Automated Daily Timeline (Complete Schedule)

All times are Central Time (CT). This schedule applies Monday through Friday on trading days.

```
06:00 CT  Futures pre-market check (T-1)
           - Globex overnight prices: MCL, MNQ, MES
           - Overnight gap detection

06:30 CT  Pre-Market Intelligence Brief delivered (T-2)
           - 7-step data collection runs automatically
           - VIX level, macro regime, economic calendar
           - Yesterday's performance recap
           - Delivered to WhatsApp

07:00 CT  Economic calendar check (T-3)
           - Scan for CPI, NFP, FOMC today
           - If major release: enable news blackout window
           - Matt's morning review window (7:00-8:00 AM CT)

08:00 CT  Matt's active prep window
           - Review WhatsApp briefing
           - Confirm trade plan for the day
           - Check VIX regime tier

08:30 CT  RTH opens (T-4)
           - Scheduler activates signal scanning
           - First scan cycle begins
           - Opening 5-minute avoid period begins (high noise)

09:00 CT  First scheduler scan fires
           - 30-minute cycle begins (SO-2)
           - Pipeline runs on MCL, MNQ

09:35 CT  First 1h candle closes (T-5)
           - Initial STC levels calculated
           - Initial bias determined
           - Matt's primary trading window OPENS

10:05 CT  Second 1h candle signal check
           - Scan fires on schedule

10:35 CT  Third 1h candle signal check
           - Morning session peak activity

11:05 CT  Fourth 1h candle signal check
           - Last scan before midday lull

11:30 CT  Midday lull begins (T-6)
           - P&L check, open position review
           - Signal quality typically degrades
           - Matt's morning window CLOSES
           - Avoid new entries unless strong signal

12:05 CT  Midday scan fires
           - Lower confidence threshold

12:35 CT  Scan fires (midday)

13:00 CT  Afternoon session opens (T-7)
           - Secondary trading window
           - Valid signals but lower quality

13:35 CT  Afternoon signal check

14:05 CT  Fifth 1h candle signal check

14:35 CT  Sixth 1h candle signal check

15:00 CT  Final RTH scan fires

15:30 CT  RTH wind-down begins (T-8)
           - Exit management only
           - No new entries
           - Matt's afternoon window CLOSES

15:59 CT  Force-close all open positions (T-9)
           - Mandatory EOD exit for all 1h signals
           - NO overnight holds

16:05 CT  EOD summary (T-10)
           - P&L recap sent to WhatsApp (SO-3)
           - P&L snapshot written to SQLite
           - Performance metrics calculated

17:00 CT  MGC daily signal scanner (SO-5)
           - Runs at 5:00 PM CT (6:00 PM ET = 23:00 UTC)
           - Research/monitoring only (MGC is HALTED)
```

---

## 1.10 Matt's Trading Context & Personal Rules

### 1.10.1 Trading Windows (All Times Central)

| Window | CT Times | Purpose | Rule |
|--------|----------|---------|------|
| Pre-market | 8:00-8:30 AM | Data check only | NO entries -- review briefing, confirm plan |
| RTH Open avoid | 8:30-9:35 AM | High noise | NO entries -- opening volatility too unpredictable |
| Primary window | 9:35-11:30 AM | PREFERRED | Cleanest price action, highest-quality signals |
| Midday lull | 11:30 AM - 1:00 PM | AVOID | Choppy, low conviction -- skip unless very strong signal |
| Secondary window | 1:00-3:30 PM | Valid but secondary | Lower quality than morning, valid entries acceptable |
| Wind-down | 3:30-3:59 PM | Exit management only | No new entries, manage existing positions for close |
| After-hours | 4:00+ PM | Nothing | All positions closed, review EOD summary when convenient |

### 1.10.2 Absolute Rules (PERMANENT -- NEVER VIOLATE)

These rules are non-negotiable and apply in every market condition, every day, without exception.

1. **Never hold MES/MNQ/MCL/MGC overnight on 1h signals.** EOD exit is mandatory. The 1h strategy is designed for intraday timeframes only. Overnight gaps can blow past stops.

2. **Always respect the -2% daily halt.** No exceptions, no "one more trade," no "I'll get it back." When the circuit breaker trips, trading is done for the day. Period.

3. **Check WhatsApp briefing before any action on signal days.** The pre-market brief (T-2) contains VIX regime, overnight gaps, and economic calendar. No trading without reviewing it first.

4. **Never add to a losing position.** No averaging down on futures. If a trade is losing, the only actions are: hold to stop, exit at market, or tighten stop. Never increase size.

5. **Kill switch authority: Matt alone can deactivate.** No LLM, no agent, no automated system can rearm the kill switch. This is a Tier 3 action requiring human authorization.

6. **Maximum contracts: 2 at any time across ALL instruments combined.** Not 2 per instrument -- 2 total. This limits total portfolio risk exposure.

7. **Paper trading only until June 2026 milestone.** Live trading requires: WFE maintained above thresholds, 30-day forward test passed, 60+ paper trades completed, no EP-3 events in 30 days.

### 1.10.3 Account Phases

**Phase 0 -- Research (COMPLETE)**
- Status: Completed 2026-03-30
- Work done: Walk-forward validation, parameter optimization, 8 backtester bug fixes
- Key results: 2 of 5 instruments cleared (MCL WFE=0.82, MNQ WFE=0.57)
- Duration: ~2 weeks of intensive research
- Deliverables: SUMMARY.md (v2.7), EXECUTIVE_BRIEFING.md (v2.7), BACKTEST_RESEARCH_REPORT.md (1,245 lines)

**Phase 1 -- Paper Trading (CURRENT)**
- Status: Active as of 2026-03-30
- Simulated capital: $25,000 per instrument (MCL and MNQ independent)
- Risk per trade: 0.25% ($62.50 per trade per instrument)
- Instruments: MCL 1h (static params, WFE=0.82) + MNQ 1h (adaptive regime, WFE=0.57)
- Kill switch thresholds: -3% monthly OR 3 consecutive losses on either instrument
- Duration target: 30+ trading days minimum
- Success criteria:
  - Profit Factor > 1.5
  - Sharpe Ratio > 1.0
  - Max Drawdown < 10%
  - Win Rate > 45%
  - Zero unhandled exceptions in 30 days
  - IB Gateway uptime > 99.5%
  - Agent pipeline latency < 30 seconds
- Broker: Interactive Brokers paper account (port 7497)
- Position limit: 1 contract per instrument (MCL, MNQ independent)

**Phase 2 -- Live Phase 1 (Target: June 2026+)**
- Prerequisites (ALL required):
  - 60+ paper trades completed successfully
  - Forward WFE maintained above 0.50 for both instruments
  - No EP-3 (data feed failure) events in last 30 days
  - All success criteria from Phase 1 met
  - Matt reviews and explicitly approves
- Capital: $10,000 real money
- Max position: 1 MES contract (smallest available)
- Risk per trade: 0.25% ($25 per trade)
- Brokerage: Interactive Brokers live account
- Port transition: 7497 (paper) -> 7496 (live) -- requires `.env` change and engine restart
- SCHWAB_READY flag: Must be manually set to True in `.env` (additional safety gate)
- Week 1: 0.25x position size (quarter size)
- Week 2: 0.50x position size (half size)
- Week 3+: 1.00x position size (full)

**Phase 3 -- Scale Up (Target: September 2026+)**
- Prerequisites: Phase 2 shows 3+ consecutive months of profitability
- Add MCL or MNQ at full micro-contract size
- Scale capital based on demonstrated edge
- Gradual increase: one additional instrument or one additional contract per quarter
- Monthly review meetings to evaluate scaling decisions

### 1.10.4 Matt's Instrument Knowledge

- **Primary instruments**: Micro futures only -- MCL (crude oil 1h), MNQ (micro Nasdaq 1h)
- **Familiar with**: ThinkorSwim platform, IBKR TWS/Gateway
- **Uses JARVIS for**: Signal confirmation, automated scanning, performance tracking
- **Does NOT trade**: Forex, cryptocurrency, individual stocks, full-size futures, options (except research)
- **Does NOT hold**: Overnight futures positions (ever, on 1h signals)
- **VIX discipline**: Check VIX before every session, respect regime-based sizing adjustments
- **Preferred style**: Systematic, rules-based -- does not override JARVIS signals with discretion
- **Risk tolerance**: Conservative -- 0.25% per trade, max 2 contracts total, no leverage above micro contracts

### 1.10.5 Work Schedule Context

Matt's primary job is running Greenfield Metal Sales (steel distributor, full-time). Trading is NOT his primary activity -- it is automated and managed by JARVIS TRADER.

**Daily routine:**
- **7:00-8:00 AM CT**: Morning review (before work). Check overnight futures, review WhatsApp pre-market briefing (T-2). This is the primary time Matt interacts with JARVIS TRADER.
- **8:00 AM - 5:00 PM CT**: At work. Matt does NOT sit at a trading desk during regular trading hours. He relies entirely on JARVIS alerts via WhatsApp.
- **After 5:00 PM CT**: Evening review. Check EOD summary (T-10), review next-day outlook, approve any Tier 3 actions if needed.

**Implication for system design:**
- All alerts must be WhatsApp-first (Matt may not see dashboard during RTH)
- Tier 2 actions use a 5-minute confirmation window (default: proceed if no cancel)
- Tier 3 actions wait indefinitely for Matt's response (no timeout)
- EOD summary is the primary daily touchpoint -- must be comprehensive
- Morning briefing must be delivered early enough for Matt to review before work
- Dashboard is for deeper analysis during evening review, not real-time trading

**Approval channels:**
- WhatsApp response to JARVIS alerts (primary -- fastest)
- Dashboard button click (secondary -- during evening review)
- Direct API call via curl (tertiary -- for technical operations)
- Manual `.env` file edit + engine restart (for Phase/config changes only)

### 1.10.6 Paper Trading Configuration Reference

**MCL 1h -- ACTIVE (WFE=0.82 EXCELLENT)**

| Parameter | Value |
|-----------|-------|
| Capital | $25,000 |
| Risk/trade | 0.25% ($62.50) |
| Config | Static params, regime_filter=ON, adaptive_regime=OFF |
| STC_OS | 15 |
| STC_OB | 83 |
| Stop | 0.90 ATR |
| T1 | 1.50 ATR |
| T2 | 2.618 ATR |
| Kill switch | -3% monthly OR 3 consecutive losses |

**MNQ 1h -- ACTIVE (WFE=0.57 GOOD)**

| Parameter | Value |
|-----------|-------|
| Capital | $25,000 |
| Risk/trade | 0.25% ($62.50) |
| Config | adaptive_regime=ON, volume_filter=OFF, mtf_filter=OFF |
| STC_OS | 15 |
| STC_OB | 92 |
| Stop | 0.70 ATR |
| T1 | 1.00 ATR |
| T2 | 1.80 ATR |
| Kill switch | -3% monthly OR 3 consecutive losses |

**Configuration files:**
- `engine/backtest/paper_config.py` -- paper trading parameters
- `engine/backtest/signals.py::INSTRUMENT_PARAMS` -- 7-element tuples per instrument
- `engine/.env` -- risk parameters, broker config, API keys
- `PAPER_TRADING_APPROVAL.md` -- approval documentation
- `PAPER_TRADING_RUNBOOK.md` -- operational procedures

### 1.10.7 Re-Evaluation Schedule

| Interval | Action | Trigger |
|----------|--------|---------|
| Every 4 weeks | Rolling WFE recalculation (SO-4) | Append new data, re-run walk-forward |
| Monthly | Performance review against Phase 1 criteria | First trading day of month (T-24) |
| Quarterly | Full parameter re-optimization if WFE drops below 0.40 | Manual trigger |
| Annually | Full strategy assessment -- consider new signal layers | Manual trigger |
| On demand | If 3 consecutive losing months | Kill switch + full review |

---

*End of Part 2 (Sections 1.6-1.10)*
*Total sections covered: Risk Management, VIX Regime, Autonomy Model, Standing Orders, Personal Rules*
*Source files referenced: safety_layer.py, loss_tracker.py, pnl_monitor.py, health_monitor.py, main.py, SUMMARY.md, EXECUTIVE_BRIEFING.md, PAPER_TRADING_APPROVAL.md, PAPER_TRADING_RUNBOOK.md, TRADING_DAILY_ROUTINE.md*
# JARVIS TRADER MASTER DOCUMENT -- Part 3

**Sections 1.11 through 1.14**
**Generated**: 2026-03-30
**Source of truth**: Live code inspection of `engine/main.py`, `ENDPOINT_REGISTRY.md`, `database/migrations.py`, `monitoring/metrics.py`, `thinkorswim-scripts/INTEGRATION_GUIDE.md`, and `dashboard/app/` directory.

---

## 1.11 API Surface (Live-Validated)

**Base URL**: `http://localhost:8010`
**Framework**: FastAPI 0.x with Pydantic v2 request/response models
**Authentication**: None (internal use only -- bind to `127.0.0.1`)
**API Docs**: `http://localhost:8010/docs` (Swagger UI auto-generated)
**Total Endpoints**: 82 REST + 1 WebSocket
**Status**: All 82 endpoints verified and wired (2026-03-29)

### Health & Diagnostics (3 endpoints)

| Method | Path | Description | Response Model |
|--------|------|-------------|----------------|
| GET | `/health` | Basic health check -- uptime, kill switch state, IBKR connection, paper mode flag | `HealthResponse` |
| GET | `/health/full` | Comprehensive check of all subsystems: API keys, database, IB Gateway, portfolio tracker, scheduler | `FullHealthResponse` |
| GET | `/system/preflight` | Pre-flight validation before accepting trading commands. Verifies API keys, DB, market hours, portfolio state | JSON: `check_count`, `pass_count`, `fail_count`, `warn_count`, detailed results |

### Safety & Risk Management (7 endpoints)

| Method | Path | Description | Response Model |
|--------|------|-------------|----------------|
| POST | `/safety/kill-switch/activate` | Immediately halt all trading. Sends WhatsApp alert + WebSocket broadcast | `KillSwitchToggleResponse` |
| POST | `/safety/kill-switch/deactivate` | Resume trading after kill switch event | `KillSwitchToggleResponse` |
| GET | `/safety/status` | Full safety layer state: kill switch, circuit breakers, daily P&L limits, position tracking | `SafetyStatusResponse` |
| GET | `/safety/circuit-breakers` | Per-breaker status: daily loss, max drawdown, margin utilization thresholds | `CircuitBreakerStatus` |
| GET | `/safety/config` | Read-only risk parameter configuration from `.env` at startup | JSON: `max_daily_loss_pct`, `max_drawdown_pct`, `max_position_size_pct` |
| POST | `/safety/reset-daily-pnl` | Reset in-memory daily P&L counter (testing/manual intervention) | JSON: `status`, `message` |
| GET | `/safety/loss-tracker` | Consecutive loss tracking state, position size multiplier, halt status | JSON: `global_consecutive_losses`, `symbol_losses`, `position_size_multiplier`, `is_halted`, `halt_until`, `config` |

### Strategy Configuration (4 endpoints)

| Method | Path | Description | Response Model |
|--------|------|-------------|----------------|
| GET | `/settings/risk` | Current risk/circuit breaker settings from database | JSON risk parameters |
| POST | `/settings/risk` | Update risk settings with range validation, persist to database | JSON: `updated`, `errors`, `count` |
| GET | `/strategy/params` | Current strategy parameters: EMA periods, ATR settings, filter flags | JSON: `ema_short`, `ema_long`, `ema_smoother`, `atr_length`, `atr_mult_stop`, `atr_mult_target`, filter flags |
| PUT | `/strategy/params` | Update strategy parameters (immediate effect on future backtests/live trading). Validates EMA ordering, ATR ranges, RSI thresholds | JSON: `status`, `old_params`, `new_params` |

### Analysis & Sentiment (5 endpoints)

| Method | Path | Description | Response Model |
|--------|------|-------------|----------------|
| POST | `/analyze/technical` | Run Technical Analyst agent on a symbol for signal generation | `TechnicalAnalysisResponse` |
| GET | `/analyze/bars/{symbol}` | OHLCV bars from market data manager (last 200 bars) | `BarsResponse` |
| GET | `/llm/stats` | LLM API usage and cost statistics -- per-model and per-agent breakdowns | JSON: `total_calls`, `total_cost_usd`, `success_rate`, `avg_latency_ms`, `per_model`, `per_agent` |
| GET | `/sentiment/reddit` | Trending tickers from Reddit via data manager | `RedditSentimentResponse` |
| GET | `/sentiment/news/{symbol}` | News sentiment for a symbol via Finnhub API | `NewsSentimentResponse` |

### Portfolio & Paper Trading (15 endpoints)

| Method | Path | Description | Response Model |
|--------|------|-------------|----------------|
| GET | `/portfolio` | Current portfolio state from broker API or paper tracker | `PortfolioResponse` |
| GET | `/portfolio/paper/positions` | All open paper-trade positions with entry prices, sizes, unrealized P&L | `PaperPositionsResponse` |
| POST | `/portfolio/paper/trade` | Log a completed paper trade to the tracker | `PaperTradeResponse` |
| GET | `/portfolio/paper/performance` | Performance metrics for all closed paper trades | `PaperPerformanceResponse` |
| GET | `/paper/pending-signals` | Pending entry signals from daily MGC scan | `PendingSignalsResponse` |
| GET | `/portfolio/history/trades` | Complete trade history from SQLite | `TradeHistoryResponse` |
| GET | `/portfolio/history/daily-pnl` | Daily P&L snapshots for last N days | `DailyPnLResponse` |
| GET | `/portfolio/history/decisions` | Historical agent decisions with reasoning and outcomes | `DecisionHistoryResponse` |
| GET | `/portfolio/stats/summary` | Aggregate performance: win rate, total P&L, profit factor | `StatsSummaryResponse` |
| GET | `/portfolio/stats/drawdown` | Max drawdown and equity curve data | `DrawdownResponse` |
| GET | `/portfolio/stats/streaks` | Current and maximum win/loss streaks | JSON: `current_streak`, `max_streak`, `streak_type` |
| GET | `/portfolio/stats/session-today` | Today's session stats (Chicago timezone) | JSON: session trades, P&L, commission |
| GET | `/portfolio/stats/commissions` | Estimated total commissions during paper trading | JSON: `total_commissions`, `per_trade_avg`, `per_symbol_breakdown` |
| GET | `/portfolio/stats/weekly` | 7-day rolling performance summary | JSON: `weekly_pnl`, `weekly_trades`, `win_rate`, `profit_factor` |
| POST | `/portfolio/import/trades` | Import trade records from CSV/JSON upload into trade history | JSON: `import_count`, `errors` |

### Paper Trading -- MGC (3 endpoints)

| Method | Path | Description | Response Model |
|--------|------|-------------|----------------|
| GET | `/paper/mgc-signal` | Generate today's MGC signal using walk-forward validated adaptive-regime strategy. Data: GC=F daily bars via yfinance. Scheduled daily at 18:00 ET | JSON: `signal`, `direction`, `entry_estimate`, `stop_level`, `target`, `regime` |
| POST | `/paper/mgc-log-trade` | Log a completed MGC paper trade and return updated cumulative metrics | JSON: `trade_id`, `cumulative_metrics` |
| GET | `/paper/mgc-performance` | Current MGC paper trading performance metrics | JSON: `trade_count`, `win_rate`, `profit_factor`, `total_pnl`, `monthly_summary`, `kill_threshold_breached` |

### Backtesting & Validation (8 endpoints)

| Method | Path | Description | Response Model |
|--------|------|-------------|----------------|
| GET | `/backtest/results` | List all saved backtest result JSON files | JSON: file list with metadata |
| POST | `/backtest/run` | Run a backtest for a symbol over a date range | JSON: trades, summary metrics, equity curve |
| POST | `/backtest/walk-forward` | Walk-forward validation with overlapping train/test windows. Returns WFE metric | JSON: windows array, summary metrics, WFE verdict |
| POST | `/backtest/regime-analysis` | Analyze backtest results broken down by market regime | JSON: `regime_metrics`, `overall_verdict`, `best`/`worst` regimes |
| GET | `/backtest/regime-status` | Current regime classification for tracked symbols (MNQ_1h, MGC_1d) | JSON: `current_regime`, `regime_breakdown_30d` per symbol |
| GET | `/backtest/paper-status` | WFE and paper-trading readiness for each symbol | JSON: `symbol`, `wfe`, `paper_start_date`, `trades_to_date`, `expected_duration` |
| POST | `/backtest/monte-carlo` | Run Monte Carlo simulation (N shuffled trade sequences with optional slippage) | JSON: `percentile_statistics`, `confidence_metrics`, `verdict` |
| POST | `/backtest/monte-carlo/chart` | Generate interactive HTML equity curve fan chart from Monte Carlo results | JSON: `chart_path`, `url` |

### Watchlist & Market Data (7 endpoints)

| Method | Path | Description | Response Model |
|--------|------|-------------|----------------|
| GET | `/watchlist` | Configured watchlists with live prices and daily changes | JSON: `futures_watchlist`, `options_watchlist` arrays |
| POST | `/watchlist` | Add a symbol to a watchlist (in-memory, not persisted) | JSON: `status`, `updated_watchlist` |
| DELETE | `/watchlist/{symbol}` | Remove a symbol from the watchlist | JSON: `status`, `updated_watchlist` |
| GET | `/prices/snapshot` | Current prices and daily change % for comma-separated symbols | JSON: price data per symbol |
| GET | `/market/earnings` | Upcoming earnings events near watched symbols | JSON: earnings calendar |
| GET | `/watchlist/scan` | Run MTF analysis on all watchlist symbols (honors kill switch) | JSON: per-symbol signals, consolidated recommendation |
| GET | `/macro/snapshot` | Macro indicators snapshot (Fed Funds, 10Y Treasury, VIX). 5-minute TTL cache | JSON: macro indicator values |

### Pipeline & Decision Making (6 endpoints)

| Method | Path | Description | Response Model |
|--------|------|-------------|----------------|
| POST | `/pipeline/run` | Full 5-stage AI pipeline: Technical -> News -> Social -> Debate -> Trade Decision | JSON: full decision chain, `final_action`, `final_quantity`, `confidence` |
| GET | `/pipeline/status` | Pipeline availability and last run info | JSON: `is_initialized`, `agent_count`, `last_run_timestamp`, `last_run_symbol` |
| GET | `/pipeline/history` | Historical pipeline run records from SQLite | JSON: runs array |
| GET | `/decisions/recent` | Most recent agent decisions from in-memory log | JSON: decisions array |
| POST | `/decisions/log` | Internal endpoint for agents to log decisions to in-memory feed | JSON: status |
| GET | `/signals/stats` | Webhook signal statistics including deduplication cache hits | JSON: `signal_count`, `unique_symbols`, `cache_hits` |

### Scheduler & Automation (2 endpoints)

| Method | Path | Description | Response Model |
|--------|------|-------------|----------------|
| GET | `/scheduler/status` | Scheduled job status and next run times | JSON: jobs array, running status, `next_run_timestamp` |
| POST | `/scheduler/scan-now` | Manually trigger full watchlist scan immediately (bypasses schedule) | JSON: `status`, `scan_started_at` |

### Notifications & Events (4 endpoints)

| Method | Path | Description | Response Model |
|--------|------|-------------|----------------|
| POST | `/notifications/whatsapp/test` | Test WhatsApp notification configuration | JSON: `status` ("sent" or "failed") |
| POST | `/notifications/vix-alert-check` | Check VIX and send WhatsApp alert if above key thresholds | JSON: `vix_value`, `alert_sent` |
| POST | `/thinkscript/generate` | Generate ThinkScript code from JARVIS analysis results | JSON: `thinkscript_code`, `file_path` |
| GET | `/macro/series/{series_id}` | Historical data for a FRED series (e.g. FEDFUNDS, GS10, UNRATE) | JSON: series data points |

### Analytics & Reporting (10 endpoints)

| Method | Path | Description | Response Model |
|--------|------|-------------|----------------|
| GET | `/analytics/performance` | Forward-test validation report comparing paper trading to backtest targets | JSON: `metrics`, `targets`, `deltas`, `verdict` |
| GET | `/analytics/performance/rolling` | Rolling performance metrics for last N days (7, 14, 30) | JSON: daily metrics array |
| GET | `/analytics/performance/compare` | Current forward-test metrics vs. backtest target benchmarks | JSON: current vs. target comparison |
| GET | `/analytics/mtf` | Multi-timeframe STC analysis for a single symbol (daily, hourly, 5m) | JSON: STC oscillator and trend bias per timeframe |
| GET | `/analytics/trades/by-day` | Day-of-week breakdown of paper trade performance | JSON: per-day stats |
| GET | `/analytics/trades/by-symbol` | Per-symbol breakdown of paper trade performance | JSON: symbol breakdown |
| GET | `/analytics/trades/by-hour` | Hour-of-day trade performance breakdown | JSON: hourly metrics (0-23) |
| GET | `/reports/performance` | Generate self-contained HTML performance report with charts | HTML content |
| GET | `/alerts/history` | Recent alert log entries (default limit 50) | JSON: alerts array |
| GET | `/alerts/stats` | Alert counts grouped by type and status | JSON: counts per type/status |

### WebSocket (2 endpoints)

| Type | Path | Description |
|------|------|-------------|
| WEBSOCKET | `/ws/events` | Real-time trading event stream. Broadcasts: `order_fill`, `kill_switch`, `circuit_breaker`, `pipeline_complete`, `safety_event`, `price_update`, `ping` |
| GET | `/ws/status` | WebSocket manager status: connected client count, connection uptime, `is_running` |

**WebSocket message format:**
```json
{
  "type": "event_type",
  "data": { ... },
  "timestamp": "ISO8601"
}
```

### Additional Routers (mounted separately)

| Router | Prefix | Source Module | Purpose |
|--------|--------|---------------|---------|
| `journal_router` | `/journal` | `routers/journal_router.py` | Trade journal CRUD endpoints for notes, tags, moods, lessons |
| `webhook_router` | `/webhook` | `routers/webhook_router.py` | TradingView webhook receiver for signal ingestion |

### Endpoint Summary by Category

| Category | Count |
|----------|-------|
| Health & Diagnostics | 3 |
| Safety & Risk | 7 |
| Strategy Config | 4 |
| Analysis & Sentiment | 5 |
| Portfolio & Paper Trading | 15 |
| Paper Trading (MGC) | 3 |
| Backtesting & Validation | 8 |
| Watchlist & Market Data | 7 |
| Pipeline & Decision Making | 6 |
| Scheduler & Automation | 2 |
| Notifications & Events | 4 |
| Analytics & Reporting | 10 |
| WebSocket | 2 |
| Journal Router (separate) | ~6 |
| Webhook Router (separate) | ~2 |
| **TOTAL** | **~84** |

---

## 1.12 ThinkOrSwim Script Library

**Source directory**: `C:\Users\mattm\ThinkorSwim\jarvis-trader\thinkorswim-scripts\`
**Primary reference**: `INTEGRATION_GUIDE.md` (506 lines, version 1.0, generated 2026-03-29)
**Total files**: 34 `.ts` files (21 unique scripts + 13 TOS-generated nested duplicates)

### Overview

The TOS scripts provide a **visual overlay** that mirrors the JARVIS engine signal framework. TOS generates visual alerts and chart annotations; JARVIS generates automated trade decisions. Both systems use identical indicator parameters so that what Matt sees on the TOS chart matches what the engine computes.

### Layer 1 -- Regime Map (3 scripts)

*What regime is the market in? (TRENDING_BULL, TRENDING_BEAR, COMPRESSION, RANGE_BOUND, EXHAUSTED)*

| Script File | What It Shows | JARVIS Signal | Key Parameters |
|---|---|---|---|
| `Saty_ATR_LevelsSTUDY.ts` | EMA Ribbon (8/21/34) on price chart. Green label = bullish, red = bearish, orange = mixed. ATR range consumed % vs full ATR | `ema_trend` (TRENDING_BULL/BEAR). ATR consumed >90% = EXHAUSTED | `fast_ema=8`, `pivot_ema=21`, `slow_ema=34`, `atr_length=14` |
| `Saty_Phase_OscillatorSTUDY.ts` | Phase oscillator -100 to +100. Magenta = compression. Fibonacci zone lines at +/-23.6, +/-61.8, +/-100 | `phase_val`, `phase_compression`. Magenta = COMPRESSION regime | EMA(21), ATR(14), BB(21, 2.0) -- all hardcoded |
| `shared_mtftrendbarSTUDY.ts` | CCI-based trend trail stop line (green = long, red = short). Up/down arrows on CCI zero-cross | Supplementary regime confirmation via CCI(50) | Configurable timeframe, default 5m |

**EMA Ribbon Rule** (hardcoded in Saty ATR Levels):
- Bullish: `price >= ema8 >= ema21 >= ema34`
- Bearish: `price <= ema8 <= ema21 <= ema34`
- Exact same logic as `ema_ribbon()` in `engine/backtest/indicators.py`

### Layer 2 -- Structure Map (6 scripts)

*Where is price relative to value? (BUYER_CONTROL, SELLER_CONTROL, NEUTRAL_STRUCTURE)*

| Script File | What It Shows | JARVIS Signal |
|---|---|---|
| `AA_CoreyTPOProfilev1STUDY.ts` | TPO time profile with POC (white), VAH/VAL (cyan), Fibonacci extensions from POC | POC = VPOC, VAH = `va_high`, VAL = `va_low`. Price above VAH + POC = BUYER_CONTROL |
| `AA_CoreyTscorev2STUDY.ts` | TPO score quantifying price vs POC/VAH/VAL as numeric score. Labels: "Buyers in Control", "Sellers in Control" | Direct readout of `layer2_structure()`. Positive = BUYER_CONTROL |
| `AA_CoreyIBv1STUDY.ts` | Initial Balance (first 60-min RTH range). IB High (red), IB Low (green), quadrants, extensions | `ib_high`/`ib_low`. IB High breakout = ENTRY_NOW trigger |
| `AA_CoreyRFv2STUDY.ts` | Rangefinder v2 -- dynamic volume profile resetting on range expansion. Control zone 38.2-61.8% | VP context between IB resets. Range extensions = imbalance targets |
| `AA_CoreySFv2STUDY.ts` | Singlefinder v2 -- identifies single prints (price areas visited only once). Bullish (pink), bearish (orange) | Gap-fill targets. Unfilled singles act as magnets |
| `AA_CoreyGapfinderv1STUDY.ts` | Marks open-to-close gaps. Gap Down (red), Gap Up (green). Lines extend until filled | Supplementary Layer 2 context |

### Layer 3 -- Directional Bias (3 scripts)

*What is the directional lean? (STRONG_BULL, LEAN_BULL, NEUTRAL, LEAN_BEAR, STRONG_BEAR)*

| Script File | What It Shows | JARVIS Signal | Alert Conditions |
|---|---|---|---|
| `NextSignalMomentumSTUDY.ts` | KAMA (Kaufman Adaptive MA, period=10) on price. Blue = above KAMA (long), Red = below (short). Also plots 7/20-bar linear regression | `kama_signal` = long/short. Matches `kama()` in `indicators.py` | `close` crosses above/below `MAA` plot |
| `Saty_Volume_StackSTUDY.ts` | Buy/sell volume separated by candle OHLC ratio. Winner stacked on top. Label shows buy%/sell% | `buy_pct`. >60% = buyer_dominant, <40% = seller_dominant | Visual monitoring only |
| `shared_OB_STYLE_CYCLE_TIMESHIFT_PAINT_BARSSTUDY.ts` | STC (Schaff Trend Cycle) oscillator 0-100. Green = rising, red = falling. Crossover arrows at OB/OS levels. Paints price bars | `stc_val`, `stc_cross_up`, `stc_cross_down`. Crossover arrows ARE the JARVIS entry signals | `RegularBuy` (green arrow up), `RegularSell` (red arrow down) |

**STC Parameters** (must match engine):

| Parameter | TOS Input | JARVIS Value |
|---|---|---|
| Fast EMA | `fastLength` | 23 |
| Slow EMA | `slowLength` | 50 |
| %K period | `KPeriod` | 10 |
| %D smoothing | `DPeriod` | 3 |
| Oversold (1h) | `over_sold` | 15 |
| Oversold (daily) | `over_sold` | 23 |
| Overbought | `over_bought` | 83 |

### Layer 4 -- Entry Timing (7 scripts)

*Is this bar an entry? (ENTRY_NOW, WAIT_FOR_PULLBACK, NO_TRADE, FADE_EXTREME)*

| Script File | What It Shows | JARVIS Entry Signal |
|---|---|---|
| `shared_OB_STYLE_CYCLE_TIMESHIFT_PAINT_BARSSTUDY.ts` | STC crossover arrows: RegularBuy (green up), RegularSell (red down) | `stc_cross_up` = ENTRY_NOW (long), `stc_cross_down` = ENTRY_NOW (short) |
| `AA_CoreyIBv1STUDY.ts` | IB High breakout: price closes above IB High with cloud confirmation | `above_ib_high` fresh breakout = ENTRY_NOW (unconditional) |
| `shared_shared_shared_shared_kelt_3.01STUDY.ts` | Keltner Channel single-factor (default iFactor=3.0, iLength=20, SMA) | 3.0x band = extreme level. `kelt_basis` in JARVIS |
| `shared_shared_OB_OMEGA_5mSTUDY.ts` | OB Omega -- dual Keltner (1.5x and 2.0x factors). Horizontal level lines with labels. Embedded MACD primer cloud | Outer (2.0x) breach = outer Keltner signal. Inner (1.5x) = inner band |
| `shared_shared_OB_OMEGA_15m7STUDY.ts` | OB Omega scaled for 15-min aggregation | Same signals, different timeframe |
| `shared_shared_OB_OMEGA_30m7STUDY.ts` | OB Omega scaled for 30-min aggregation | Same signals, different timeframe |
| `AA_CoreyRFv2STUDY.ts` | Range expansion arrows (up=green, down=red) on new range expansions | Arrow up + bull bias = ENTRY_NOW candidate |

### Layer 5 -- Position Sizing / ATR Stops & Targets (2 scripts)

| Script File | What It Shows | JARVIS Sizing Signal |
|---|---|---|
| `Saty_ATR_LevelsSTUDY.ts` | All ATR Fibonacci levels from prior close: 0.236x, 0.382x, 0.5x, 0.618x, 0.786x, 1.0x, extensions to 3.0x. Cyan trigger = +0.236 ATR (calls), orange = -0.236 ATR (puts) | `stop_level` = 0.70 ATR, `target_1` = 1.50 ATR (1h) / 2.00 ATR (daily), `target_2` = 2.618 ATR, `target_3` = 4.00 ATR |
| `shared_Saty_ATR_LevelsSTUDY.ts` | Duplicate for TOS sharing import | Same as above |

**ATR Level Mapping to Chart Lines**:
- Stop (0.70 ATR): between `lower_0618` (orange) and `lower_0786` (gray) lines
- T1 (1.50 ATR): `upper_1500` / `lower_1500` lines
- T2 (2.618 ATR): `upper_2618` / `lower_2618` lines (golden ratio extension)
- T3 (4.00 ATR): beyond default chart range -- calculate manually

### Supporting/Supplementary Scripts (6 files)

| Script File | Purpose |
|---|---|
| `GAPS_Chetan1STUDY.ts` | Alternative gap-finder (Chetan version) -- double confirmation alongside Corey's |
| `TRIN_ChetanSTUDY.ts` | TRIN (Arms Index) for market internals. High TRIN (>2.0) = extreme selling |
| `ThinkScript_study_20221014STUDY.ts` | Custom utility script (Oct 2022) |
| `ThinkScript_study_20221016STUDY.ts` | Custom utility script (Oct 2022) |
| `ThinkScript_study_20230523STUDY.ts` | Custom utility script (May 2023) |
| `AA_CoreyRFv1MobileSTUDY.ts` | Rangefinder v1 mobile variant (legacy -- use RFv2 instead) |

### Duplicate Files (13 -- ignore during import)

These are TOS-generated nested copies created during export/sharing. Import only the root-level originals listed in the layers above.

| Duplicate File | Use Instead |
|---|---|
| `shared_AA_CoreyRangefinderv1_01STUDY.ts` | `AA_CoreyRFv2STUDY.ts` |
| `shared_AA_CoreySinglefinderv2STUDY.ts` | `AA_CoreySFv2STUDY.ts` |
| `shared_AA_CoreyTPOScorev2STUDY.ts` | `AA_CoreyTscorev2STUDY.ts` |
| `shared_midcloudoteSTUDY.ts` | Sub-study -- do not add directly |
| `shared_Saty_ATR_LevelsSTUDY.ts` | `Saty_ATR_LevelsSTUDY.ts` |
| `shared_shared_midcloudoteSTUDY.ts` | Sub-study -- do not add directly |
| `shared_shared_OB_LBR_BARS_HH_LL17STUDY.ts` | Sub-study -- do not add directly |
| `shared_shared_shared_shared_shared_kelt_3.01STUDY.ts` | Deeper nested -- ignore |
| `shared_shared_shared_shared_shared_kmaster1STUDY.ts` | Sub-study dependency |
| `shared_shared_shared_shared_shared_Priceline11STUDY.ts` | Sub-study dependency |
| `shared_shared_shared_shared_shared_shared_kmaster1STUDY.ts` | Deeper nested -- ignore |
| `shared_shared_shared_shared_shared_shared_Priceline11STUDY.ts` | Deeper nested -- ignore |
| `shared_OB_STYLE_CYCLE_TIMESHIFT_PAINT_BARSSTUDY.ts` | This IS the main STC study -- USE this one |

### TOS-to-JARVIS Signal Mapping

TOS scripts are **visual confirmation** tools. JARVIS is the **decision engine**. The relationship:

1. **TOS generates visual alerts** (arrows, color changes, sound notifications) that Matt sees on his chart
2. **JARVIS generates trades** (pipeline decisions, order submissions) based on the same indicator calculations
3. Parameters are identical between TOS inputs and `engine/backtest/signals.py` constants
4. When JARVIS fires an STC cross signal, the corresponding green/red arrow appears on the TOS chart simultaneously

### TOS Workspace Setup

**Import order** (sub-studies first, then main studies):

1. `shared_shared_shared_shared_kelt_3.01STUDY.ts` -- Keltner core
2. `shared_shared_shared_shared_shared_kmaster1STUDY.ts` -- KMaster support
3. `shared_shared_shared_shared_shared_Priceline11STUDY.ts` -- Price line support
4. `Saty_ATR_LevelsSTUDY.ts` -- ATR levels + EMA ribbon (upper panel)
5. `Saty_Phase_OscillatorSTUDY.ts` -- Phase oscillator (lower panel)
6. `Saty_Volume_StackSTUDY.ts` -- Volume stack (lower panel)
7. `NextSignalMomentumSTUDY.ts` -- KAMA on price (upper panel)
8. `shared_OB_STYLE_CYCLE_TIMESHIFT_PAINT_BARSSTUDY.ts` -- STC (lower panel)
9. TPO/IB/RF/SF/Gap scripts (upper panel)
10. OB Omega Keltner scripts (upper panel)

**Save as**: "JARVIS 5-Layer 1H" and "JARVIS 5-Layer Daily" chart templates.

---

## 1.13 Dashboard Architecture

**Framework**: Next.js 15, TypeScript, Tailwind CSS
**Port**: 3010
**Design system**: Dark terminal aesthetic, monospace typography, navy/cyan accent palette
**Charts**: Recharts (equity curves, histograms, heatmaps)
**Data fetching**: SWR with 5-second default polling interval
**API connection**: `fetchEngine()` utility in `lib/api.ts` targeting `http://localhost:8010`
**Build verification**: `npm run build` (TypeScript must pass with 0 errors)
**Startup**: `cd dashboard && npm run dev`

### All 13 Pages

| Route | File | Purpose | Key Widgets/Components | Primary API Endpoints |
|-------|------|---------|------------------------|-----------------------|
| `/` | `app/page.tsx` | Main dashboard -- overview of all systems | KillSwitch, PositionsPanel, AgentFeed, SentimentPanel, PerformancePanel, WatchlistBar, PaperTradingPanel, TradeHistory, DailyPnlPanel, RegimeDisplay, MTFConfirmationWidget, SignalHistory, CircuitBreakerPanel, IBGatewayStatus, StrategyParamsPanel, SessionTodayWidget | `/health`, `/safety/status`, `/portfolio`, `/decisions/recent`, `/sentiment/recent`, `/watchlist`, `/macro/snapshot` |
| `/command-center` | `app/command-center/page.tsx` | Unified command center -- system health, safety status, portfolio overview, quick actions | Health status cards, safety layer widgets, portfolio summary, kill switch controls, connection health, pipeline status | `/health`, `/health/full`, `/safety/status`, `/safety/circuit-breakers`, `/portfolio`, `/ws/status` |
| `/backtest` | `app/backtest/page.tsx` | Backtest runner and results viewer -- equity curves, trade tables, parameter display | Recharts equity curve, trade table, backtest metrics cards | `/backtest/results`, `/backtest/run` |
| `/validation` | `app/validation/page.tsx` | Walk-forward validation results, WFE badges, regime analysis display | ValidationChecklist, WFE progress bars, regime breakdown tables | `/backtest/paper-status`, `/backtest/regime-status`, `/analytics/performance/compare` |
| `/performance` | `app/performance/page.tsx` | Detailed performance analytics -- rolling metrics, symbol breakdown, hourly analysis | PerformanceSummaryWidget, DrawdownChart, RollingPerformanceWidget, TradePnLHistogram, BestWorstTradesWidget | `/analytics/performance`, `/analytics/performance/rolling`, `/analytics/trades/by-symbol`, `/analytics/trades/by-hour` |
| `/stats` | `app/stats/page.tsx` | Statistical summary page | Performance summary cards, aggregate statistics | `/portfolio/stats/summary` |
| `/health` | `app/health/page.tsx` | System health monitoring -- all subsystem status, uptime, connectivity | Health status cards, subsystem checklist, API key validation, DB status | `/health/full`, `/system/preflight` |
| `/settings` | `app/settings/page.tsx` | Risk parameter configuration, strategy parameter tuning, notification settings | RiskSettingsWidget, EngineConfigCard, NotificationTestPanel | `/settings/risk`, `/strategy/params`, `/safety/config` |
| `/journal` | `app/journal/page.tsx` | Trade journal -- notes, tags, moods, lessons per trade | Journal entry cards, tag filters, mood selector | `/journal/*` endpoints |
| `/watchlist` | `app/watchlist/page.tsx` | Watchlist management and live price monitoring | WatchlistScanWidget, price cards, add/remove symbols | `/watchlist`, `/watchlist/scan`, `/prices/snapshot` |
| `/paper` | `app/paper/page.tsx` | Paper trading dashboard -- MGC signal status, trade logging, performance tracking | PaperTradingPanel, signal display, trade logger | `/paper/mgc-signal`, `/paper/mgc-performance`, `/portfolio/paper/positions` |
| `/scorecard` | `app/scorecard/page.tsx` | Daily/weekly scorecard -- win rate targets, P&L targets, discipline metrics | Scorecard widgets, target progress bars | `/portfolio/stats/summary`, `/portfolio/stats/weekly` |
| `/analysis` | `app/analysis/page.tsx` | Technical analysis viewer -- run analysis on symbols, view results | Analysis form, results display | `/analyze/technical`, `/analyze/bars/{symbol}` |

### Key Dashboard Components (90+ components in `dashboard/components/`)

**Core Trading Components:**
- `KillSwitch.tsx` -- Emergency kill switch toggle with confirmation dialog
- `PositionsPanel.tsx` / `OpenPositionsWidget.tsx` -- Current open positions with P&L
- `PaperTradingPanel.tsx` -- Paper trade entry form and status
- `OrderEntryPanel.tsx` -- Manual order entry interface
- `SignalHistory.tsx` / `SignalQueueWidget.tsx` -- Signal log and pending signals

**Performance & Analytics:**
- `PerformancePanel.tsx` / `PerformanceSummaryWidget.tsx` -- Aggregate performance metrics
- `DailyPnlPanel.tsx` / `DailyPnLChart.tsx` -- Daily P&L display and Recharts chart
- `DrawdownChart.tsx` -- Max drawdown visualization
- `SharpeRatioWidget.tsx` -- Sharpe ratio display
- `ProfitFactorWidget.tsx` -- Profit factor gauge
- `CalendarHeatmap.tsx` -- Trade calendar heatmap visualization
- `TradePnLHistogram.tsx` -- P&L distribution histogram
- `WeeklyPerformanceWidget.tsx` / `WeeklyPnLCard.tsx` -- Weekly stats

**Risk & Safety:**
- `CircuitBreakerPanel.tsx` / `CircuitBreakerWidget.tsx` -- Circuit breaker status display
- `RiskStatusWidget.tsx` / `RiskSettingsWidget.tsx` -- Risk metrics and settings
- `MaxDrawdownTrackerWidget.tsx` -- Drawdown tracking
- `WinStreakWidget.tsx` / `PnLStreakWidget.tsx` / `StreakBadge.tsx` -- Win/loss streak display

**Market & Regime:**
- `RegimeDisplay.tsx` / `MarketRegimeWidget.tsx` -- Current market regime classification
- `MTFConfirmationWidget.tsx` -- Multi-timeframe signal confirmation
- `VIXRegimeCard.tsx` -- VIX level and regime
- `SentimentPanel.tsx` -- Reddit/news sentiment display
- `WatchlistBar.tsx` / `WatchlistScanWidget.tsx` -- Watchlist display and scan results
- `MarketSessionIndicator.tsx` / `MarketSessionStatusCard.tsx` -- Market open/close status

**System & Infrastructure:**
- `IBGatewayStatus.tsx` / `IbGatewayDetailCard.tsx` -- IB Gateway connection status
- `SystemMetricsPanel.tsx` -- System-level metrics
- `EngineUptimeCard.tsx` / `EngineConfigCard.tsx` -- Engine uptime and configuration
- `ConnectionHealthCard.tsx` -- API connectivity health
- `DatabaseStatsCard.tsx` -- SQLite database statistics
- `WhatsAppStatusCard.tsx` -- WhatsApp notification status
- `PipelineStatusWidget.tsx` / `PipelineRunHistory.tsx` -- Pipeline execution status

**Agent & Decision:**
- `AgentFeed.tsx` -- Live agent decision feed
- `DecisionLogWidget.tsx` / `DecisionBreakdownCard.tsx` / `RecentDecisionsWidget.tsx` -- Decision history and breakdowns
- `StrategyParamsPanel.tsx` / `StrategyParamsCard.tsx` -- Strategy parameter display

**Planning & Readiness:**
- `ReadinessCheckWidget.tsx` / `PreFlightWidget.tsx` -- Pre-trading checklist
- `GoLivePlanCard.tsx` -- Live trading readiness plan
- `PhaseProgressWidget.tsx` -- Paper trading phase progress
- `TradingDaysCountdownCard.tsx` -- Countdown to live trading
- `MonthlyTargetCard.tsx` -- Monthly performance targets

### Badge System

The dashboard uses a consistent badge color system across all pages:

| Badge Type | Color | Tailwind Classes | Usage |
|------------|-------|-----------------|-------|
| Bull / Success | Green | `bg-green-500/20 text-green-400` | Profitable trades, healthy systems, bull signals |
| Bear / Danger | Red | `bg-red-500/20 text-red-400` | Losses, kill switch active, bear signals, errors |
| Warning | Amber | `bg-amber-500/20 text-amber-400` | Approaching limits, marginal WFE, caution states |
| Info | Cyan | `bg-cyan-500/20 text-cyan-400` | Neutral information, system status |
| Neutral | Gray | `bg-gray-500/20 text-gray-400` | Inactive, no data, hold decisions |

### Design System

- **Background**: `bg-gray-950` (near-black)
- **Cards**: `bg-gray-900` with `border-gray-800` borders
- **Text primary**: `text-gray-100`
- **Text secondary**: `text-gray-400`
- **Accent**: Cyan (`text-cyan-400`, `border-cyan-500`)
- **Typography**: Monospace for data values (`font-mono`), system sans-serif for labels
- **Icons**: Lucide React icon library throughout
- **UI Components**: shadcn/ui (Card, Badge, Button, Progress, Tabs)

---

## 1.14 Infrastructure

### Database Architecture

#### SQLite (Primary -- `data/jarvis_trader.db`)

The primary data store. Thread-safe via `threading.Lock`. WAL journal mode for read concurrency. Connection-per-call pattern (no shared connections). All timestamps stored as ISO-8601 UTC strings.

**Migration system**: Version-tracked via `schema_version` table. 5 migrations applied sequentially. Each migration is idempotent (uses `IF NOT EXISTS`).

**Tables (9 total across 5 migrations):**

| Table | Migration | Purpose | Key Columns |
|-------|-----------|---------|-------------|
| `schema_version` | Bootstrap | Tracks applied migration versions | `version` INTEGER, `applied_at` TEXT, `description` TEXT |
| `paper_trades` | v001 | Full lifecycle of every simulated trade | `trade_id` TEXT UNIQUE, `symbol`, `side` (buy/sell/buy_to_open/sell_to_open), `quantity` REAL, `entry_price` REAL, `exit_price` REAL, `entry_time` TEXT, `exit_time` TEXT, `pnl` REAL, `status` (open/closed/cancelled), `strategy_params` JSON, `notes` TEXT |
| `decisions` | v001 | Pipeline decision log with agent reasoning | `symbol`, `timestamp`, `action` (buy/sell/hold/exit_long/exit_short), `confidence` REAL 0.0-1.0, `regime`, `signal_data_json` TEXT, `reasoning` TEXT |
| `daily_pnl` | v001 | End-of-day P&L snapshots | `date` TEXT UNIQUE (YYYY-MM-DD), `starting_balance`, `ending_balance`, `realized_pnl`, `unrealized_pnl`, `total_trades`, `winning_trades`, `losing_trades`, `max_drawdown` |
| `positions` | v001 | Current open positions (live mirror) | `symbol` TEXT UNIQUE, `quantity`, `entry_price`, `entry_time`, `current_price`, `unrealized_pnl`, `stop_loss`, `take_profit` |
| `settings` | v001 | Key/value config store | `key` TEXT PRIMARY KEY, `value` TEXT, `updated_at` TEXT |
| `trade_journal` | v002 | Trade annotations with notes, tags, mood, lessons | `trade_id` TEXT (soft FK), `timestamp`, `note`, `tags` TEXT (comma-separated), `mood` (confident/uncertain/frustrated/neutral), `lesson` TEXT |
| `pipeline_runs` | v003 | History of every TradingPipeline execution | `run_id` TEXT UNIQUE (8-char UUID prefix), `symbol`, `webhook_action` (LONG/SHORT/CLOSE), `source` (tradingview/manual), `final_action`, `final_quantity`, `requires_human` BOOLEAN, `summary`, `status` (completed/error/skipped), `error_message`, `duration_ms`, `created_at` |
| `journal_notes` | v004 | Free-form trade observations not tied to specific trades | `trade_id` TEXT (optional), `note_type` (observation/lesson/alert), `title`, `body`, `tags` JSON array, `created_at`, `updated_at` |
| `alert_log` | v005 | History of every WhatsApp/notification sent | `alert_type` (trade_opened/trade_closed/morning_briefing/vix_alert/circuit_breaker/notification), `symbol` TEXT, `message`, `channel` (whatsapp), `status` (sent/failed/suppressed), `error` TEXT, `created_at` |

#### LLM Cost Database (`data/llm_costs.db`)

Separate SQLite file for LLM API cost tracking.

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `llm_calls` | Per-call LLM usage and cost | `timestamp` TEXT, `model` (e.g. "claude-opus-4-6"), `input_tokens` INT, `output_tokens` INT, `cost_usd` REAL, `latency_ms` INT, `agent_name` TEXT, `success` BOOLEAN |

Indexed on `timestamp`, `model`, and `agent_name` for fast per-day/per-model/per-agent queries.

#### PostgreSQL (Docker -- `jarvis_postgres`)

Defined in `infrastructure/docker-compose.yml` for production-grade order/audit storage. Not yet active in paper trading phase.

- **Image**: `postgres:16-alpine`
- **Port**: 5432
- **Credentials**: `jarvis`/`jarvis`
- **Database**: `jarvis_trader`
- **Init script**: `infrastructure/postgres/init.sql`
- **Volume**: `postgres_data` (persistent)

#### QuestDB (Docker -- `jarvis_questdb`)

Time-series database for high-frequency market data storage.

- **Image**: `questdb/questdb:8.2.3`
- **Ports**: 9000 (HTTP API + Web console), 9009 (InfluxDB line protocol), 8812 (PostgreSQL wire)
- **Volume**: `questdb_data` (persistent)

### Prometheus Metrics (10 custom metrics)

Defined in `engine/monitoring/metrics.py`. Uses the `prometheus_client` Python library.

| Metric Name | Type | Labels | Description |
|-------------|------|--------|-------------|
| `jarvis_pipeline_runs_total` | Counter | `symbol`, `decision` | Total number of trading pipeline runs |
| `jarvis_pipeline_duration_seconds` | Histogram | `symbol` | Duration of pipeline execution (buckets: 0.5, 1, 2, 5, 10, 30, 60s) |
| `jarvis_llm_calls_total` | Counter | `model`, `agent`, `success` | Total number of LLM API calls |
| `jarvis_llm_cost_usd` | Counter | `model` | Total USD cost of LLM API calls |
| `jarvis_orders_total` | Counter | `symbol`, `direction`, `status` | Total number of orders submitted |
| `jarvis_daily_pnl_usd` | Gauge | (none) | Current daily P&L in USD |
| `jarvis_equity_usd` | Gauge | (none) | Current account equity in USD |
| `jarvis_kill_switch_active` | Gauge | (none) | Kill switch status (0=off, 1=active) |
| `jarvis_safety_events_total` | Counter | `event_type` | Total number of safety layer events |
| `jarvis_consecutive_losses` | Gauge | (none) | Number of consecutive losing trades |

**Helper functions** for metric recording:
- `record_pipeline_run(symbol, decision)`
- `record_pipeline_duration(duration, symbol)`
- `record_llm_call(model, agent, success)`
- `record_llm_cost(model, cost_usd)`
- `record_order(symbol, direction, status)`
- `set_daily_pnl(pnl_usd)`
- `set_equity(equity_usd)`
- `set_kill_switch(active)`
- `record_safety_event(event_type)`
- `set_consecutive_losses(count)`

### Grafana Dashboards

Grafana runs on port 3030 (mapped from container port 3000 to avoid conflict with Next.js).

**Image**: `grafana/grafana:11.4.0`
**Provisioning**: `infrastructure/grafana/provisioning/` (auto-configures data sources and dashboards)
**Admin password**: Set via `GF_ADMIN_PASSWORD` env var (default: `jarvis_change_me`)

Three planned dashboards:

1. **Trading Performance**: P&L curve (`jarvis_daily_pnl_usd`), pipeline runs by symbol/decision, LLM cost tracking
2. **System Health**: Pipeline duration histogram, LLM call success rate, engine uptime via `/health`
3. **Risk Monitor**: Kill switch state (`jarvis_kill_switch_active`), consecutive losses gauge, equity tracking, safety events counter

### Docker Compose Services

Defined in `infrastructure/docker-compose.yml` (version 3.9):

| Service | Image | Container | Ports | Purpose |
|---------|-------|-----------|-------|---------|
| `questdb` | `questdb/questdb:8.2.3` | `jarvis_questdb` | 9000, 9009, 8812 | Time-series market data |
| `postgres` | `postgres:16-alpine` | `jarvis_postgres` | 5432 | Relational orders/audit |
| `redis` | `redis:7.4-alpine` | `jarvis_redis` | 6379 | Cache, signal bus, feature store |
| `prometheus` | `prom/prometheus:v2.51.0` | `jarvis_prometheus` | 9090 | Metrics collection |
| `grafana` | `grafana/grafana:11.4.0` | `jarvis_grafana` | 3030 | Monitoring dashboards |

**Volumes** (5 persistent): `questdb_data`, `postgres_data`, `redis_data`, `prometheus_data`, `grafana_data`

**Redis configuration**: `appendonly yes`, `maxmemory 512mb`, `maxmemory-policy allkeys-lru`

### Windows Startup (`start_jarvis.bat`)

Double-click startup script at project root. Launches all services in separate terminal windows.

**Startup sequence:**
1. Check for `engine/.env` existence (warn if missing)
2. Initialize SQLite database via `engine/init_db.py` (safe to run every startup)
3. Launch Engine on port 8010 (`uvicorn main:app --port 8010`)
4. Wait for engine health check (`/health` endpoint) -- up to 30 retries at 2-second intervals
5. Launch Dashboard on port 3010 (`npm run dev`)
6. Launch Health Monitor (`python health_monitor.py`)
7. Open `http://localhost:3010` in default browser

### Health Monitor (`engine/health_monitor.py`)

Standalone Python script (stdlib only -- zero third-party dependencies) that runs alongside the engine.

| Setting | Value |
|---------|-------|
| Health URL | `http://localhost:8010/health` |
| Polling interval | 60 seconds |
| Request timeout | 10 seconds |
| Alert cooldown | 300 seconds (5 minutes) |

**Behavior:**
- Polls `/health` every 60 seconds
- If HTTP 200: logs "OK -- Engine is healthy"
- If not 200 or timeout: logs "DOWN -- Engine not responding"
- On first DOWN detection: sends WhatsApp alert via Twilio with restart instructions
- Subsequent DOWN alerts: suppressed for 5-minute cooldown period
- On recovery (was down, now up): sends "JARVIS Engine RECOVERED" WhatsApp message

**WhatsApp delivery**: Direct Twilio REST API via `urllib` (no `requests` library needed). Uses Basic Auth with base64-encoded `ACCOUNT_SID:AUTH_TOKEN`. Configuration loaded from `engine/.env` with minimal parser.

### LLM Client (`engine/llm/cost_tracker.py`)

**Cost tracking**: Every LLM API call logged to `data/llm_costs.db` with:
- Timestamp (ISO-8601 UTC)
- Model name (e.g., `claude-opus-4-6`, `claude-sonnet-4-6`, `claude-haiku-4-5`)
- Input/output token counts
- Cost in USD
- Latency in milliseconds
- Agent name (which of the 10 agents made the call)
- Success/failure boolean

**Models used in the pipeline:**
- Claude Opus 4.6 -- Fund Manager, senior decision agents
- Claude Sonnet 4.6 -- Technical/News/Social analysts, debate orchestrator
- Claude Haiku 4.5 -- Lightweight classification, sentiment scoring

**Query endpoint**: `GET /llm/stats?days_back=N` returns per-model and per-agent cost breakdowns for any given day.

### Logging

Configured in `main.py` `setup_logging()` function, called first during lifespan startup.

| Component | Configuration |
|-----------|---------------|
| Log directory | `engine/logs/` (auto-created) |
| Main log file | `logs/jarvis.log` |
| File handler | `RotatingFileHandler`, 10MB max size, 5 backup files |
| File format | JSON structured via custom `JSONFormatter` |
| Console handler | Human-readable: `%(asctime)s [%(levelname)s] %(name)s: %(message)s` |
| Log level | Configurable via `LOG_LEVEL` environment variable (default: `INFO`) |
| Health monitor log | Separate file at `logs/health.log` (plain text format) |

**JSON log format:**
```json
{
  "timestamp": "2026-03-30T14:30:00.000Z",
  "level": "INFO",
  "module": "main",
  "funcName": "run_watchlist_analysis",
  "message": "Scheduled scan: ['MNQ', 'MGC', 'SPY']"
}
```

Exception stack traces are included in the `exception` field when present.

### Scheduler

APScheduler (`AsyncIOScheduler`) with Chicago timezone.

| Job | Schedule | Description |
|-----|----------|-------------|
| `watchlist_scan` | Mon-Fri, 9:00-15:30 CT, every 30 minutes | Full pipeline analysis on top 2 futures + top 3 equities from watchlists |
| `daily_mgc_signal` | Daily at 18:00 ET (23:00 UTC) | Fetch GC=F daily bar, run adaptive-regime signals, log pending entries |

Configuration: `max_instances=1`, `misfire_grace_time=300` (5 minutes).

### WebSocket Manager

Real-time event distribution to connected dashboard clients.

- **Module**: `engine/websocket/manager.py` + `engine/websocket/events.py`
- **Endpoint**: `ws://localhost:8010/ws/events`
- **Event types**: `order_fill`, `kill_switch`, `circuit_breaker`, `pipeline_complete`, `safety_event`, `price_update`, `ping`
- **Status endpoint**: `GET /ws/status` returns connected client count and uptime

### Global State (Lifespan-Managed)

All global state is initialized in `main.py`'s `lifespan()` async context manager and torn down on shutdown:

| Manager | Type | Purpose |
|---------|------|---------|
| `data_manager` | `MarketDataManager` | Market data connections (yfinance, Finnhub, IBKR) |
| `safety_layer` | `SafetyLayer` | Kill switch, circuit breakers, position limits |
| `technical_analyst` | `TechnicalAnalystAgent` | LLM-powered technical analysis |
| `trading_pipeline` | `TradingPipeline` | Full 5-stage pipeline with all 10 agents |
| `scheduler` | `AsyncIOScheduler` | Cron-based job scheduling |
| `paper_tracker` | `PortfolioTracker` | Paper trade position tracking and P&L |
| `db_manager` | `DatabaseManager` | SQLite connection factory |
| `pnl_monitor` | `PnLMonitor` | P&L monitoring feeding circuit breakers |
| `eod_scheduler` | `EODScheduler` | End-of-day tasks |
| `order_manager` | `IBOrderManager` | IB Gateway order bridge |
| `ws_manager` | `WebSocketManager` | WebSocket event broadcasting |
| `cost_tracker` | `CostTracker` | LLM cost tracking |
| `loss_tracker` | `ConsecutiveLossTracker` | Consecutive loss position sizing modulation |

### Alert Rate Limiting

WhatsApp alerts are rate-limited with a 2-hour cooldown per symbol to prevent flooding. Tracked in `_last_alert_time` dictionary (in-memory, resets on engine restart).

---

*End of Sections 1.11-1.14. Total endpoints: 82+. Total TOS scripts: 21 unique across 5 layers. Dashboard: 13 pages, 90+ components. Database: 10 tables across 2 SQLite files + PostgreSQL/QuestDB in Docker.*
# JARVIS TRADER -- Master Document (Part 4)
# Sections 1.15 through 1.20
# Version 3.0 | 2026-03-30

---

## 1.15 Options Trading System (FULL SPEC + BUILD PLAN)

> **STATUS: PLANNED -- NOT YET BUILT**
>
> This section is a complete specification for the options trading subsystem.
> No code exists yet. All files listed in "Infrastructure to Build" must be
> created before any options strategies can execute.

The options layer sits on top of the existing futures engine and adds five
distinct strategy types, each with precise entry/exit/management rules. Options
are used for income generation (covered calls, credit spreads), portfolio
hedging (protective puts), range-bound capture (iron condors), and event-driven
volatility (straddles/strangles).

---

### A. Covered Calls on Futures (MES / MNQ)

**Concept:** Own 1 micro futures contract in a current long position and sell
1 OTM call against it. The premium collected provides income and a small
downside buffer. The trade-off is capped upside above the strike price.

**Entry Conditions:**
- Already hold 1 micro futures contract (MES or MNQ) as a long position
- Sell 1 OTM call at **0.30 delta** (approximately 1 standard deviation OTM)
- Strike selection: current underlying price + (1.0 to 1.5 x ATR)
- Expiration: **7-14 DTE** (weeklies strongly preferred for faster theta decay)
- Regime requirement: RegimeClassifier must report **TRENDING** or **RANGING**
  - Do NOT sell calls in VOLATILE regime (gap risk too high, premium not worth it)
- IV Rank must be **> 30%** (only sell premium when it is expensive relative to history)

**Greeks Targets at Entry:**
| Greek   | Target              | Rationale                                    |
|---------|---------------------|----------------------------------------------|
| Delta   | -0.30 at entry      | ~70% probability of expiring OTM             |
| Theta   | > $0.50/day/contract | Minimum daily income to justify the position  |
| IV Rank | > 30%               | Sell expensive premium only                   |

**Delta Drift Management:**
- Allow call delta to drift from -0.30 toward -0.10 as time passes
- When delta reaches -0.10 (or premium hits 50% of max profit): **roll**
  - Close the current short call
  - Sell a new call further OTM (back to -0.30 delta)
  - Same or next expiration cycle

**Exit Rules (Priority Order):**
1. **Let expire worthless** -- primary goal. Keep 100% of premium collected.
2. **Roll at 0.10 delta** -- when 50% of max profit is captured, roll to next cycle
   further OTM to collect additional premium.
3. **Close if underlying hits T1 target** -- lock in the futures profit. Release
   the call obligation by buying back the short call. This is an active management
   decision: the futures gain exceeds the forfeited premium.
4. **Assignment risk** -- if the call goes ITM near expiration, accept assignment.
   The futures position is called away at the strike. Net P&L = (strike - futures entry)
   + premium collected. This is a profitable outcome by design.

**Stop-Loss:**
- There is no stop-loss on the call itself. Covered calls have defined risk:
  the maximum loss is forgone upside above the strike price.
- The underlying futures position retains its own stop-loss (from the STC strategy).
- Premium collected partially offsets potential futures losses if the underlying
  drops. The call expires worthless and the premium is retained.

**Risk Profile:**
- Maximum profit: premium received + (strike - futures entry) if called away
- Maximum loss: full downside on the futures position minus premium received
  (same directional risk as holding the futures contract unhedged)
- Breakeven: futures entry price minus premium received per point

**Example Trade (MES):**
```
MES long at 5,450.00
Sell 1 MES 5,480 Call (0.30 delta), 10 DTE
Premium received: 8.50 points = $42.50 ($5/point x 8.50)
Theta: $0.85/day

Scenario 1 -- Expire OTM: Keep $42.50. Continue holding MES long.
Scenario 2 -- Roll at 0.10 delta (day 6): Buy back for $2.00 ($10),
              sell new 5,500 Call for $6.00 ($30). Net new credit: $20.
Scenario 3 -- MES hits T1 (5,465): Close call for $3.00 ($15).
              Futures gain: 15 pts x $5 = $75. Net: $75 + $42.50 - $15 = $102.50.
```

---

### B. Credit Spreads (Vertical Put/Call Spreads)

**Concept:** Sell premium with defined risk using vertical spreads. Two flavors:

#### B1. Bull Put Spread (Bullish / Neutral Outlook)

**Structure:**
- Sell 1 put at **0.30 delta** (short strike)
- Buy 1 put **2-3 strikes lower** (long strike, protection wing)
- Net credit = premium received - premium paid for wing

**Example:**
```
MES at 5,450
Sell 5,430 Put (0.30 delta) for 12.00 points
Buy 5,420 Put (wing) for 8.00 points
Net credit: 4.00 points = $20.00
Spread width: 10 points = $50.00
Max risk: $50 - $20 = $30.00
Max profit: $20.00 (if both expire OTM)
Probability of profit: ~70% (short strike at 0.30 delta)
```

#### B2. Bear Call Spread (Bearish / Neutral Outlook)

**Structure:**
- Sell 1 call at **0.30 delta** (short strike)
- Buy 1 call **2-3 strikes higher** (long strike, protection wing)
- Same net credit structure, opposite directional bias

**Parameters for Both Spread Types:**
| Parameter         | MES Options    | MNQ Options     |
|-------------------|----------------|-----------------|
| Spread width      | $5-10 per side | $10-25 per side |
| DTE at entry      | 30-45 days     | 30-45 days      |
| Delta (short leg) | 0.30           | 0.30            |
| IV Rank minimum   | > 30%          | > 30%           |

**Management Rules:**
- **Profit target:** Close at **50% of max credit received**. Do not hold to
  expiration hoping for the last 50% -- risk/reward deteriorates.
- **Time-based close:** At **21 DTE**, close the spread regardless of P&L.
  Gamma risk accelerates after 21 DTE and small moves can wipe out gains.
- **Stop-loss:** If unrealized loss reaches **2x the premium received**, close
  the spread immediately. Discipline > hope.
- **Never roll losing spreads** -- close, assess, re-enter with fresh analysis.

**When to Use Which:**
- Bull put spread: regime = TRENDING UP or RANGING, signal = LEAN_BULL or HOLD
- Bear call spread: regime = TRENDING DOWN or RANGING, signal = LEAN_BEAR or HOLD
- Never enter either spread when regime = VOLATILE

---

### C. Iron Condors (Range-Bound Markets)

**Concept:** Combine a bull put spread and a bear call spread into a single
position. Profit from time decay while the underlying stays within a range.

**Structure:**
| Leg       | Delta  | Description                    |
|-----------|--------|--------------------------------|
| Long put  | -0.05  | Far OTM protection (wing)      |
| Short put | -0.16  | ~1 standard deviation OTM      |
| Short call| +0.16  | ~1 standard deviation OTM      |
| Long call | +0.05  | Far OTM protection (wing)      |

**Regime and Volatility Requirements (ALL must be true):**
1. RegimeClassifier reports **RANGING** -- TRENDING or VOLATILE regimes disqualify
2. VIX level must be **NORMAL (16-20) or ELEVATED (20-25)**
   - VIX < 16 (CALM): premium too thin, not worth the trade
   - VIX > 25 (HIGH/EXTREME): gap risk too high, spreads too wide
3. IV Rank > **30%** -- only sell premium when it is rich relative to recent history
4. No earnings announcements, FOMC, CPI, NFP, or GDP releases within the
   expiration window (check EconomicCalendar from `news_blackout.py`)

**Wing Width:** $5-10 per side (MES) or $10-25 per side (MNQ)

**DTE:** 30-45 days at entry

**P&L Profile:**
```
Max profit: total credit received (both spreads expire OTM)
Max loss: wider spread width - total credit received
          (capped by wings on both sides)
Breakeven: short put strike - total credit AND short call strike + total credit
```

**Management Rules:**
1. **Profit target:** Close entire condor at **50% of max credit**.
2. **Tested side adjustment:** If the short strike delta on either side reaches
   **0.30** (the underlying is moving toward it), roll that side out in time
   and further OTM. Roll means: close the threatened spread, re-sell at a new
   strike with the same or better credit.
3. **Hard stop (per side):** If max loss on either the put spread or call spread
   reaches **2x the credit received for that side**, close that side immediately.
   The untested side can remain if still within parameters.
4. **Time-based close:** At 21 DTE, close the entire condor regardless.

**Never Enter Iron Condors When:**
- VIX > 25 (HIGH or EXTREME) -- gap risk exceeds premium income
- Regime = VOLATILE -- the underlying will blow through one side
- Major economic events fall within the expiration window
- Less than 30 DTE (insufficient theta runway)

**Example Trade (MES):**
```
MES at 5,450, VIX at 18 (NORMAL), Regime = RANGING

Sell 5,380 Put (0.16 delta) / Buy 5,370 Put (0.05 delta)  -- Bull put wing
Sell 5,520 Call (0.16 delta) / Buy 5,530 Call (0.05 delta) -- Bear call wing

Put spread credit: 3.50 points = $17.50
Call spread credit: 3.00 points = $15.00
Total credit: 6.50 points = $32.50
Max loss per side: 10 points - 3.50 = 6.50 points = $32.50 (put side)
                   10 points - 3.00 = 7.00 points = $35.00 (call side)

Target: close at $16.25 (50% of $32.50)
Hard stop: close put side if loss exceeds $35.00 (2x $17.50)
           close call side if loss exceeds $30.00 (2x $15.00)
```

---

### D. Protective Puts (Portfolio Hedge)

**Concept:** Buy OTM puts as insurance against a sharp market decline. This is
a cost center, not a profit center. The goal is to cap portfolio drawdown during
elevated risk periods.

**Entry Triggers (BOTH must be true simultaneously):**
1. VIX enters **ELEVATED** regime (VIX > 20)
2. RegimeClassifier reports **VOLATILE**

When both conditions are met, buy protection. When either condition clears,
evaluate whether to close the hedge.

**Structure:**
- Buy 1 OTM put at **0.20 delta** on MES or MNQ (whichever has the larger
  position in the portfolio)
- Duration: **30-60 DTE** (long enough for protection, short enough to limit
  premium bleed)

**Cost Budget:**
- Maximum **0.5% of total portfolio value per month** on protective puts
- If the cost of a 0.20 delta put exceeds 0.5% of portfolio, either:
  - Move to a lower delta (cheaper, less protection)
  - Skip the hedge (accept the drawdown risk)
- Track cumulative hedging cost in `paper_tracker.py` as a separate line item

**Exit Rules:**
1. **VIX drops below 16 (CALM):** Close the put. The fear event has passed.
   Holding longer wastes premium via theta decay.
2. **Premium loss hits 80%:** Close and accept the cost. Re-evaluate conditions
   before buying new protection.
3. **Event materializes (underlying drops significantly):** The put gains value.
   Close when the put is ITM and the portfolio has been defended. Book the gain
   as an offset to portfolio losses.
4. **Expiration approaches (< 7 DTE):** Close or roll. Do not let puts expire
   worthless if conditions still warrant protection -- roll to next cycle.

**When NOT to Hedge:**
- VIX < 16 (CALM) -- hedging is cheap but unnecessary
- Regime = TRENDING UP -- buying puts during a strong uptrend is expensive and
  rarely pays off
- After a major decline has already occurred (buying puts at peak VIX is buying
  at the worst price)

---

### E. Straddles / Strangles (Pre-Event Volatility Plays)

**Concept:** Buy both a call and a put to profit from a large move in either
direction. Used exclusively around major scheduled economic events where the
move is expected to exceed the cost of both options.

#### E1. Straddle (Symmetric, Maximum Sensitivity)

**Structure:**
- Buy 1 ATM call + Buy 1 ATM put
- Same strike price (ATM), same expiration
- Entry: **1-2 trading days before the scheduled event**
- Higher cost, lower breakeven distance (small moves profit)

#### E2. Strangle (Wider, Cheaper, Requires Larger Move)

**Structure:**
- Buy 1 OTM call (0.25 delta) + Buy 1 OTM put (0.25 delta)
- Different strike prices (both OTM), same expiration
- Entry: **1-2 trading days before the scheduled event**
- Lower cost, wider breakeven (requires significant move to profit)

**Event Calendar (from `news_blackout.py`):**
| Event          | Frequency       | Time (ET)  | Impact Level | Typical Move |
|----------------|-----------------|------------|--------------|--------------|
| FOMC Decision  | 8x per year     | 14:00      | EXTREME (3)  | 30-80 MES pts|
| CPI Release    | Monthly (~12th) | 08:30      | HIGH (2)     | 20-50 MES pts|
| NFP Jobs       | 1st Friday/mo   | 08:30      | HIGH (2)     | 15-40 MES pts|
| GDP Advance    | Quarterly       | 08:30      | HIGH (2)     | 10-30 MES pts|
| PCE Deflator   | Monthly         | 08:30      | HIGH (2)     | 15-35 MES pts|

**Exit Rules (CRITICAL -- timing matters more than price):**
- Exit within the **first 30 minutes after the data release**
- The move happens fast; IV crush begins immediately after the number is known
- Holding past 30 minutes means IV collapse eats into intrinsic value
- Target: **1.5x total premium paid** (both legs combined)
- Maximum risk: **total premium paid** (both legs expire worthless -- worst case)

**Never Hold Through Full IV Crush:**
- The entire edge is in the initial move before IV reprices
- After 30 minutes, the options are repriced to post-event volatility
- A straddle that is breakeven on intrinsic value may still lose money due to
  the IV drop across both legs

**Position Sizing:**
- Maximum **1% of portfolio** on any single straddle/strangle
- Only trade EXTREME impact events (FOMC primarily) with straddles
- Use strangles for HIGH impact events (CPI, NFP) -- cheaper, similar payoff
  if the move is large enough

**Example (FOMC Straddle on MES):**
```
MES at 5,450, FOMC in 2 days
Buy 5,450 Call for 18.00 points = $90.00
Buy 5,450 Put for 17.00 points = $85.00
Total premium: 35.00 points = $175.00

Breakeven: 5,415 (down 35) or 5,485 (up 35)
Target: 52.50 points ($262.50 -- 1.5x premium)
Max loss: $175.00 (both expire worthless)

FOMC day: MES gaps to 5,510 (+60 pts)
Call value: ~62.00 points = $310.00
Put value: ~2.00 points = $10.00
Total: $320.00. Profit: $320 - $175 = $145.00 (83% return)
Exit immediately -- do not wait for more.
```

---

### Options Infrastructure to Build

All options modules will reside in `engine/options/`. No files exist yet.

#### Files to Create

| File                          | Purpose                                                    | Priority |
|-------------------------------|------------------------------------------------------------|----------|
| `engine/options/__init__.py`  | Package init, exports                                      | P0       |
| `engine/options/greeks_monitor.py` | Black-Scholes Greeks calculation, IV surface modeling  | P0       |
| `engine/options/chain_fetcher.py`  | IB Gateway options chain data via `ib_async`           | P0       |
| `engine/options/premium_calculator.py` | Premium pricing, probability of profit, expected value | P1  |
| `engine/options/strategy_executor.py` | Options order construction (spreads, condors, straddles) | P1 |
| `engine/options/position_manager.py` | Track positions, monitor Greeks drift, expiration alerts | P1 |
| `engine/options/iv_rank.py`   | IV Rank calculation (current IV vs. 52-week range)         | P1       |
| `engine/options/roll_manager.py` | Roll logic for covered calls and spreads               | P2       |
| `engine/options/event_scanner.py` | Scan upcoming events, suggest straddle/strangle trades | P2       |

#### API Endpoints to Add (in `engine/main.py` or new `engine/routers/options_router.py`)

| Method | Endpoint                      | Description                                       |
|--------|-------------------------------|---------------------------------------------------|
| GET    | `/options/chain/{symbol}`     | Fetch options chain with Greeks for a symbol       |
| GET    | `/options/positions`          | Current options positions with P&L and Greeks      |
| POST   | `/options/trade`              | Paper trade an options strategy (spread, condor)   |
| GET    | `/options/greeks`             | Portfolio-level Greeks summary (delta, gamma, theta, vega) |
| POST   | `/options/scan`               | Scan for opportunities (high IV rank, spread candidates) |
| GET    | `/options/iv-rank/{symbol}`   | Current IV Rank for a symbol                       |
| POST   | `/options/roll`               | Execute a roll (close current, open new position)  |
| GET    | `/options/events/upcoming`    | Upcoming economic events with straddle candidates  |

#### Dashboard Pages to Add

| Page                              | Components                                           |
|-----------------------------------|------------------------------------------------------|
| `dashboard/app/options/page.tsx`  | Options positions table, Greeks summary, P&L chart   |
| `dashboard/app/options/chain/page.tsx` | Options chain viewer with strike/expiry grid    |
| `dashboard/components/GreeksSummaryCard.tsx` | Portfolio delta, gamma, theta, vega display |
| `dashboard/components/IVRankGauge.tsx` | Visual gauge for IV Rank with threshold markers |
| `dashboard/components/OptionsPositionTable.tsx` | Active options positions with management buttons |

#### Dependencies Required

- `ib_async >= 0.9.86` -- already in `requirements.txt` (IB Gateway connection)
- `py_vollib` or `mibian` -- Black-Scholes pricing (to be added)
- No additional dashboard dependencies needed (existing Recharts + Tailwind sufficient)

---

## 1.16 Futures Strategies (Detailed Per-Instrument)

Each instrument has unique characteristics that determine strategy configuration,
risk parameters, and trading eligibility. This section is the canonical reference
for all instrument-specific decisions.

---

### MES (Micro E-mini S&P 500)

**Contract Specifications:**
| Spec              | Value                                           |
|-------------------|-------------------------------------------------|
| Exchange          | CME Globex                                      |
| Multiplier        | $5 per point                                    |
| Tick size         | 0.25 points ($1.25 per tick)                    |
| Typical margin    | ~$1,200 (varies with volatility)                |
| Session           | Near 24h; RTH 9:30-4:00 ET                     |
| Commission        | $2.50 per contract (round-trip estimate)        |
| ATR (daily)       | 15-30 points typical                            |

**Strategy Configuration:**
- STC_OS=15, STC_OB=83, Stop=0.50 ATR, T1=2.00 ATR, T2=3.236 ATR, T3=4.00 ATR
- `regime_filter=OFF` -- structure-based entries in EXHAUSTED and COMPRESSION regimes
  improve MES PF from 0.96 to 1.69 (v2.5 re-optimization)
- `adaptive_regime=OFF`

**Walk-Forward Results:**
- WFE = **0.09** (OVERFIT)
- OOS profitable: 1/6 windows (17%)
- Only 23 trades in test period -- insufficient for statistical significance
- **Verdict: DO NOT TRADE until signal redesign and extended data**

**Why MES Fails:**
- S&P 500 is highly efficient -- STC crossover signals lack edge
- Low trade count (23) provides no statistical confidence
- ATR targets (2.00 ATR) rarely hit intraday -- 36/51 daily trades exit at EOD
- Regime filter OFF somewhat helps but WFE remains deeply overfit

---

### MNQ (Micro E-mini Nasdaq 100)

**Contract Specifications:**
| Spec              | Value                                           |
|-------------------|-------------------------------------------------|
| Exchange          | CME Globex                                      |
| Multiplier        | $2 per point                                    |
| Tick size         | 0.25 points ($0.50 per tick)                    |
| Typical margin    | ~$2,500 (varies with volatility)                |
| Session           | Near 24h; RTH 9:30-4:00 ET                     |
| Commission        | $2.50 per contract                              |
| ATR (daily)       | 50-150 points typical                           |

**Volatility Profile:** HIGH -- Nasdaq moves 2-5x MES in percentage terms.
This higher volatility is precisely what gives STC more to work with.

**Strategy Configuration (APPROVED for paper trading):**
- STC_OS=15, STC_OB=92, Stop=0.70 ATR, T1=1.00 ATR, T2=1.80 ATR, T3=2.618 ATR
- `regime_filter=ON` (required for adaptive_regime to function)
- `adaptive_regime=ON` -- **CRITICAL**: lifts WFE from 0.24 to 0.57
- `volume_filter=OFF` -- **NEVER ENABLE**: degrades WFE from 0.57 to -0.23
- `mtf_filter=OFF` -- **NEVER ENABLE**: degrades WFE from 0.57 to 0.17

**Walk-Forward Results:**
- WFE = **0.57** (GOOD -- clears 0.50 threshold)
- OOS profitable: 4/6 windows (67%)
- Config: adaptive regime only -- no MTF, no volume filter
- Corrected from 0.48 on 2026-03-29T23:46 run

**Why Adaptive Regime Is Critical:**
- Nasdaq has distinct trending/ranging phases
- Trending regimes use tighter STC thresholds (enter earlier)
- Ranging regimes use wider thresholds (wait for stronger signals)
- The adaptive switching captures 138% more OOS performance vs static params

**OOS Stable Parameter Zone (Agent AC Finding):**
- OS=23, OB=88, stop=0.70 ATR, T1=2.00 ATR
- Identified as the most parameter-stable region across walk-forward windows
- Alternative to the primary OS=15/OB=92 if the primary set degrades during paper trading

**Paper Trading Config:**
- Capital: $25,000
- Risk/trade: 0.25% ($62.50 max risk per trade)
- Kill switch: -3% monthly OR 3 consecutive losses
- Max concurrent: 1 contract

---

### MCL (Micro Crude Oil)

**Contract Specifications:**
| Spec              | Value                                           |
|-------------------|-------------------------------------------------|
| Exchange          | CME Globex (NYMEX)                              |
| Multiplier        | $100 per point (1,000 barrels x $0.10 tick)     |
| Tick size         | $0.01/barrel ($10 per contract per tick)         |
| Typical margin    | ~$800 (varies with oil volatility)              |
| Session           | Near 24h (CME Globex extended hours)            |
| Commission        | $2.50 per contract                              |
| ATR (daily)       | $0.50-$2.00 typical                             |

**Mean-Reversion Tendency:** Crude oil oscillates within regimes far more than
equities. This mean-reverting behavior is well suited to STC crossover signals
that catch reversals within established ranges.

**Strategy Configuration (APPROVED for paper trading):**
- STC_OS=15, STC_OB=83, Stop=0.90 ATR, T1=1.50 ATR, T2=2.618 ATR, T3=4.00 ATR
- `regime_filter=ON` (oil is regime-sensitive)
- `adaptive_regime=OFF` -- **NEVER ENABLE**: adaptive WFE = -0.31, FAR WORSE
  than static 0.82
- `volume_filter=OFF`
- `mtf_filter=OFF`

**Walk-Forward Results:**
- WFE = **0.82** (EXCELLENT -- highest of all instruments)
- OOS profitable: 5/6 windows (83%)
- Config: static params only
- Confirmed on 2026-03-29T23:41 run

**Why Static Beats Adaptive for MCL:**
- Crude oil regime transitions are too abrupt for the EMA-spread-based RegimeClassifier
- The classifier flips TRENDING/RANGING mid-move in oil, causing false signal regime tags
- Static params with regime_filter=ON (which uses a simpler regime gate) works far better

**Paper Trading Config:**
- Capital: $25,000
- Risk/trade: 0.25% ($62.50 max risk per trade)
- Kill switch: -3% monthly OR 3 consecutive losses
- Max concurrent: 1 contract

---

### MGC (Micro Gold)

**Contract Specifications:**
| Spec              | Value                                           |
|-------------------|-------------------------------------------------|
| Exchange          | CME Globex (COMEX)                              |
| Multiplier        | $10 per point (10 troy ounces)                  |
| Tick size         | $0.10/oz ($1 per contract per tick)             |
| Typical margin    | ~$1,500 (varies)                                |
| Session           | Near 24h; RTH 8:20-1:30 CT                     |
| Commission        | $2.50 per contract                              |
| ATR (daily)       | $3-$15 typical                                  |

**Trend-Following Characteristics:** Gold makes extended trending moves (bull
runs, safe-haven flights) that can persist for months. This characteristic
initially made MGC appear to be the best STC candidate.

**Strategy Configuration (HALTED):**
- STC_OS=17, STC_OB=88, Stop=0.30 ATR, T1=1.50 ATR, T2=2.618 ATR, T3=4.00 ATR
- `regime_filter=OFF` -- regime_filter is **anti-predictive** for gold daily
  (regime=ON windows avg OOS -1.7%, regime=OFF avg OOS +5.9%)
- `adaptive_regime=OFF` -- identical WFE to static (0.27 both ways)
- Only viable on daily timeframe; hourly gold (MGC 1h PF=0.77) loses money

**Walk-Forward Results:**
- WFE = **0.14** (OVERFIT -- below 0.30 threshold)
- Extended history (2022-2026, 15 windows): only 6/15 (40%) OOS windows profitable
- Bear market data (2022-2023) exposes underlying parameter instability

**The Small-Sample Bias Story:**
- v2.2: MGC adaptive WFE = 0.88 (EXCELLENT) -- appeared ready for paper trading
- Only 3 walk-forward windows were used, all during the 2025 gold bull run
- Extended to 15 windows (2022-2026): WFE collapsed to 0.14
- This is a textbook case of small-sample overfitting -- the 2025 gold rally
  was an outlier regime that made the optimizer look like a genius
- **Lesson:** Always validate with 10+ walk-forward windows. 3 windows is
  insufficient for any statistical claim.

**Status:** HALTED. Requires fundamental signal redesign + extended 2022 history
before reconsideration. At minimum 24 months of new data before re-evaluation.

---

### M2K (Micro Russell 2000)

**Contract Specifications:**
| Spec              | Value                                           |
|-------------------|-------------------------------------------------|
| Multiplier        | $5 per point                                    |
| Commission        | $2.50 per contract                              |

**Status: PERMANENTLY REMOVED FROM TRADING UNIVERSE**

- 1h PF = 0.64 (consistently losing)
- 1d PF = 0.60 (consistently losing)
- Russell 2000 is unsuitable for STC strategy: high beta, mean-reverting at
  the index level, regime structure does not match STC's trend-following nature
- No walk-forward was even run -- in-sample results are negative
- **Do not reconsider M2K for the STC strategy. Period.**

---

### SPY (SPDR S&P 500 ETF)

**Status: BACKTESTING REFERENCE ONLY (Not a futures contract)**

- Used as a benchmark proxy in reporting
- WFE = -1.11 (DEEPLY OVERFIT, worst of all instruments)
- Re-optimized in v2.5: PF 3.00 to 3.79, but near-zero returns
- Negative Sharpe (-1.43) despite high PF -- a statistical warning sign
  (a few large wins mask many small losses)
- **Do not trade. Do not paper trade. Reference only.**

---

### Instrument Trading Status Summary

| Symbol | TF  | WFE    | Config                   | Status                        |
|--------|-----|--------|--------------------------|-------------------------------|
| MCL    | 1h  | 0.82   | Static, regime ON        | **APPROVED -- Paper trading** |
| MNQ    | 1h  | 0.57   | Adaptive regime only     | **APPROVED -- Paper trading** |
| MGC    | 1d  | 0.14   | Static, regime OFF       | HALTED -- Overfit             |
| MES    | 1h  | 0.09   | Static, regime OFF       | DO NOT TRADE                  |
| SPY    | 1h  | -1.11  | N/A                      | Reference only                |
| M2K    | any | N/A    | N/A                      | Permanently removed           |

---

## 1.17 Go-Live Validation Checklist (CANONICAL)

> **This is the ONE authoritative checklist.** All previous conflicting
> thresholds (WR 28%, WR 50%, WR 55%, MaxDD 8%, MaxDD 10%, MaxDD 15%,
> min trades 40 vs 60) are RESOLVED below. Do not reference older documents
> for threshold values.

---

### Tier 1: Paper Trading Qualification

**All items must be checked before paper trading can be declared successful.**
**Minimum period: 60 calendar days with 60+ trades.**

| #  | Criterion                                      | Threshold          | Status |
|----|-------------------------------------------------|--------------------|--------|
| 1  | Minimum trades executed                         | >= 60 trades       | [ ]    |
| 2  | Minimum calendar days                           | >= 60 days         | [ ]    |
| 3  | Forward walk-forward WFE (rolling, last 30 days)| >= 0.50            | [ ]    |
| 4  | Rolling win rate (paper, not backtested)         | >= 45%             | [ ]    |
| 5  | Profit factor (paper, not backtested)            | >= 1.5             | [ ]    |
| 6  | Maximum drawdown during paper period             | < 10%              | [ ]    |
| 7  | Zero EP-3 events (data feed failures) in last 2 weeks | 0 events    | [ ]    |
| 8  | WhatsApp alerts verified working                 | 5+ SIDs confirmed  | [ ]    |
| 9  | Kill switch tested                               | Activate + deactivate OK | [ ] |
| 10 | Engine uptime during paper period                | > 95%              | [ ]    |
| 11 | No -3% monthly draws during paper period         | 0 months at -3%    | [ ]    |
| 12 | IB paper port 4002 tested and connected          | Connected           | [ ]    |
| 13 | All endpoints returning valid responses           | ~95 endpoints OK   | [ ]    |

**Threshold Resolution Notes:**
- Win rate: 28% was an old estimate from early research, 55% was an aggressive
  target from the skill docs. **Resolved: 45% for paper qualification** (realistic
  for a trend-following strategy).
- Max drawdown: 8% was live gate, 15% was an old estimate. **Resolved: 10% for
  paper qualification** (strict enough to prove consistency, loose enough to allow
  learning).
- Min trades: 40 was from an early draft, 60 is current. **Resolved: 60 trades
  over 60 days** (approximately 1 trade/day average -- realistic for 2 instruments).

---

### Tier 2: Live Trading Gate

**Requires Tier 3 autonomy -- Matt must manually confirm EVERY item.**

| #  | Criterion                                      | Threshold          | Status |
|----|-------------------------------------------------|--------------------|--------|
| 1  | Paper qualification checklist (Tier 1)          | ALL items checked  | [ ]    |
| 2  | Forward WFE maintained                          | >= 0.50 for 3+ months | [ ] |
| 3  | Win rate in paper period                        | >= 50%             | [ ]    |
| 4  | Profit factor in paper period                   | >= 2.0             | [ ]    |
| 5  | Maximum paper drawdown                          | < 8%               | [ ]    |
| 6  | Sharpe ratio in paper period                    | >= 1.0             | [ ]    |
| 7  | SCHWAB_READY flag set manually by Matt          | True               | [ ]    |
| 8  | IB live account funded                          | >= $10,000         | [ ]    |
| 9  | Live port 4001 manually enabled                 | Enabled (blocked by default) | [ ] |
| 10 | Starting position size                          | 1 MES contract, 0.25% risk | [ ] |
| 11 | 30-day live trial before scaling                | Completed          | [ ]    |

**Live gate is stricter than paper gate on purpose.** Paper qualification proves
the system works mechanically. Live qualification proves it works financially.
The higher PF (2.0 vs 1.5), WR (50% vs 45%), and lower MaxDD (8% vs 10%)
thresholds reflect the reality that live trading introduces slippage variance,
emotional interference, and execution delays not present in paper.

---

### Tier 3: Scaling Authorization

**After 30-day live trial:**
| #  | Criterion                                      | Threshold          |
|----|-------------------------------------------------|--------------------|
| 1  | Live trial PF                                  | >= 1.5             |
| 2  | Live trial Sharpe                               | >= 0.8             |
| 3  | Live trial max drawdown                         | < 5%               |
| 4  | Matt's subjective comfort level                 | Explicit approval  |
| 5  | Scale step                                      | +1 contract per instrument per quarter |

---

### Circuit Breakers (Active at ALL Tiers)

| Breaker                | Trigger            | Action                          |
|------------------------|--------------------|---------------------------------|
| Daily loss limit       | -2% in one day     | Pause until next session        |
| Monthly kill switch    | -3% in one month   | Halt instrument, review required|
| Consecutive losses     | 3 in a row         | Manual review before next trade |
| Max portfolio drawdown | -10% from peak     | Kill switch ALL instruments     |
| WFE degradation        | Rolling WFE < 0.30 | Halt instrument, re-optimize    |

---

## 1.18 Session History & Decision Log

This section records the complete version timeline and every significant
strategic decision made during the project. It serves as an audit trail and
prevents re-litigating settled questions.

---

### Version Timeline

| Version | Date       | Key Change                                                    |
|---------|------------|---------------------------------------------------------------|
| v1.0    | Early 2026 | Initial strategy. In-sample results only. CONDITIONAL GO based on MGC. Numbers massively inflated by look-ahead bias + partial stop bugs. |
| v2.0    | 2026-03    | Full walk-forward validation for all 5 instruments. ALL 5 FAIL static WFE. Verdict: NO-GO. Signal redesign required. |
| v2.1    | 2026-03    | RegimeClassifier built (`regime.py`). MNQ WFE improved 0.24 to 0.34. Target > 0.40. |
| v2.2    | 2026-03    | MGC adaptive WFE = 0.88 (EXCELLENT). Later revealed as small-sample bias (3 windows). |
| v2.3    | 2026-03    | Combined filter testing. Volume filter destroys MNQ edge (0.34 to -0.23). SPY adaptive WFE improved -1.11 to -0.71 but still overfit. |
| v2.4    | 2026-03    | Extended MGC history (2022-2026, 15 windows). WFE = 0.27. Small-sample bias confirmed. CONDITIONAL-CAUTION. |
| v2.5    | 2026-03-29 | SPY/MES re-optimized. Per-instrument regime_filter flags added to INSTRUMENT_PARAMS (7-element tuples). MES PF 0.96 to 1.69 (regime OFF). |
| v2.6    | 2026-03-29 | **CRITICAL bug fix** -- optimizer kwarg bug discovered. Extra kwargs silently caused all walk-forward optimization calls to return None. ALL previous WFEs invalid. Corrected: MGC 0.27 to 0.14 (HALTED), MNQ static 0.34 to 0.24. |
| v2.7    | 2026-03-30 | Final corrections. MNQ adaptive WFE confirmed 0.57. MCL static WFE confirmed 0.82. MTF filter tested and REJECTED (0.57 to 0.17). Volume filter REJECTED (0.57 to -0.23). **Paper trading APPROVED for MCL 1h and MNQ 1h.** |

---

### Key Decisions Log

Each decision below is FINAL unless new walk-forward evidence contradicts it.

| # | Decision                                   | Verdict      | Evidence                                    | Date       |
|---|-------------------------------------------|--------------|---------------------------------------------|------------|
| 1 | Static STC params for all instruments      | REJECTED     | All 5 instruments OVERFIT (WFE < 0.30)      | 2026-03    |
| 2 | Adaptive regime for MNQ                    | **APPROVED** | WFE lifts 0.24 to 0.57 (+138%)              | 2026-03-30 |
| 3 | Adaptive regime for MCL                    | REJECTED     | WFE drops 0.82 to -0.31 -- adaptive HURTS   | 2026-03-30 |
| 4 | Adaptive regime for MGC                    | REJECTED     | WFE identical to static (0.14 both ways)     | 2026-03-29 |
| 5 | MTF filter for MNQ                         | REJECTED     | WFE drops 0.57 to 0.17 (-70%)               | 2026-03-30 |
| 6 | Volume filter for MNQ                      | REJECTED     | WFE drops 0.57 to -0.23 -- over-constrains  | 2026-03-30 |
| 7 | Volume filter for MCL                      | NOT TESTED   | MCL already at WFE 0.82 -- do not fix what works | 2026-03-30 |
| 8 | Trailing ATR stop                          | REJECTED     | Grid search confirms no improvement for any instrument | 2026-03-29 |
| 9 | MGC daily paper trading                    | **HALTED**   | WFE 0.14 post-bugfix (was 0.27, was 0.88 at 3 windows) | 2026-03-30 |
| 10| Paper risk: 0.25% (not 1.0%)              | **APPROVED** | Conservative for validation phase            | 2026-03-30 |
| 11| News/event blackout filter                 | KEEP (live)  | 81 events in calendar, ~1% signals blocked   | 2026-03-29 |
| 12| MCL static paper trading                   | **APPROVED** | WFE 0.82 EXCELLENT, 5/6 OOS profitable       | 2026-03-30 |
| 13| MNQ adaptive paper trading                 | **APPROVED** | WFE 0.57 GOOD, 4/6 OOS profitable            | 2026-03-30 |
| 14| M2K removed from universe                  | PERMANENT    | PF < 0.65 both timeframes, unsuitable for STC | 2026-03    |

---

### Bugs Found and Fixed (Chronological)

| # | Bug                                        | Impact                                         | Fix         |
|---|--------------------------------------------|-------------------------------------------------|-------------|
| 1 | Look-ahead bias in signal generation       | Signals used future candle data for entry decisions | backtester.py |
| 2 | Partial stop exits                         | Stop-loss exits credited partial bar P&L instead of exact stop price | backtester.py |
| 3 | T1 target unreachable at 1.50 ATR          | Almost never hit intraday -- changed to 1.00 ATR | signals.py |
| 4 | Duplicate trade counting                   | Same signal could fire on consecutive bars       | backtester.py |
| 5 | Equity curve calculation errors            | Compounding applied incorrectly                  | backtester.py |
| 6 | Win rate inflation                         | Partial exits counted as wins                    | backtester.py |
| 7 | Sharpe calculation wrong annualization     | Used incorrect factor for hourly bars            | backtester.py |
| 8 | Position sizing fractional shares          | Not properly rounded for futures contracts       | backtester.py |
| 9 | **Optimizer kwarg bug** (v2.6 CRITICAL)   | Extra kwargs (adaptive_regime, volume_filter, mtf_filter) silently caused TypeError in `_compute_signals()`, caught by bare except, returned None for ALL optimization calls. Every walk-forward run after these kwargs were added was invalid. | walk_forward.py `_run_with_params()` |

The optimizer kwarg bug (Bug #9) is the most consequential bug found. It
invalidated every walk-forward run between v2.1 and v2.5. The fix was to filter
kwargs to `signal_keys` in `_run_with_params()` before calling `_compute_signals()`.
This single change corrected MGC WFE from 0.27 to 0.14 (revealing overfit) and
MNQ from 0.34 to 0.24 (static) or 0.57 (adaptive, corrected).

---

### Phase Timeline

| Phase | Description                                       | Dates              | Status    |
|-------|---------------------------------------------------|--------------------|-----------|
| A     | Fix 8 critical backtesting bugs                   | Early Mar 2026     | COMPLETE  |
| B     | Corrected backtests: 12-matrix (6 symbols x 2 TF) | Mar 2026          | COMPLETE  |
| C     | Walk-forward validation: 5 instruments             | Mar 2026          | COMPLETE  |
| D     | Monte Carlo (10k sims) + sensitivity analysis      | Mar 2026          | COMPLETE  |
| E     | Research report: 1,245 lines                       | Mar 2026          | COMPLETE  |
| F     | Regime-adaptive STC: RegimeClassifier              | Mar 2026          | COMPLETE  |
| G     | Signal filter testing (volume, MTF, trailing stop) | Mar 2026          | COMPLETE  |
| H     | Paper trading approval: MCL + MNQ                  | 2026-03-30        | COMPLETE  |
| I     | Paper trading execution                            | Apr-May 2026      | ACTIVE    |
| J     | Live trading evaluation                            | Jun 2026+         | PENDING   |

---

## 1.19 Known Issues & Pending Work

---

### P0 -- Critical (Do Immediately)

**Security: API Keys in Git History**
- Anthropic API key (sk-ant-api03-...), Polygon.io key, Twilio SID/Auth Token,
  and Google OAuth client secrets are exposed in git history
- Full remediation guide: `SECURITY_REMEDIATION.md`
- Steps: Revoke all keys, run BFG Repo-Cleaner, force-push cleaned history,
  regenerate keys, populate `.env`
- Install pre-commit hook: `scripts/check-secrets.sh` linked to `.git/hooks/pre-commit`
- **This is the single highest-priority item in the entire project.**

---

### P1 -- High Priority (Before Paper Trading Ends)

**Infrastructure:**
- [ ] IB paper port 4002 integration tested end-to-end with live TWS/IB Gateway
  running. Currently only connection test exists (`/ib/connection-test`).
- [ ] SQLite persistence for paper trades verified under multi-day operation
  (current testing is single-session only).
- [ ] FRED API key configuration -- macro data currently falls back to cached
  values. Need live FRED data for regime classifier accuracy.
- [ ] Yahoo Finance rate limiting mitigation -- occasional 429 errors. Yahoo v8
  API bypass in `data_loader.py` exists as third fallback but needs monitoring.
- [ ] `EmailIntelligenceAgent.analyze_recent_emails` method may be missing in
  some code paths. Verify or remove references.

**Testing:**
- [ ] Zero integration tests for live IB Gateway connection (paper or live).
  Tests exist for HTTP endpoints but not the actual `ib_async` connection flow.
- [ ] Signal warmup tests require 300+ bars of data. 100-bar fixtures caused
  failures and were fixed, but edge cases may remain.
- [ ] No CI/CD pipeline -- all tests run manually via `pytest`. Consider GitHub
  Actions for automated testing.

**Dashboard:**
- [ ] Settings page (`dashboard/app/settings/page.tsx`) -- risk params and kill
  switch UI in progress but not finalized.
- [ ] Backtest comparison page (`dashboard/app/backtest/page.tsx`) -- paper vs
  backtest comparison partially built.
- [ ] Command center page (`dashboard/app/command-center/page.tsx`) -- Iron Man
  HUD concept. Not started.

---

### P2 -- Medium Priority (During Paper Trading)

**Data Limitations:**
- Historical data limited to Yahoo Finance free tier (max ~2 years hourly).
  This constrains walk-forward window count and prevents multi-cycle validation.
- No tick data available. All backtesting uses 1h bars, which masks intrabar
  price action (stop-outs that would have occurred on tick data are invisible).
- Weekend gaps in yfinance data require forward-fill handling. Currently handled
  but not robustly tested across DST transitions.

**Optimization Schedule:**
- Walk-forward re-optimization: scheduled quarterly. First re-optimization should
  run at the end of paper trading period (late May 2026).
- SPY 1h corrected walk-forward: not yet run. May clear 0.50 threshold but
  unverified. Low priority since SPY is not a futures instrument.
- Rolling WFE recalculation every 4 weeks with new data appended.

**Engine:**
- [ ] `engine/health_monitor.py` -- WhatsApp alert if engine goes down. Verify
  it correctly detects process crashes (not just API errors).
- [ ] EOD scheduler (`engine/schedulers/eod_scheduler.py`) -- verify daily
  snapshots execute correctly Mon-Fri at 3:05 PM CT.
- [ ] API authentication: no auth on any endpoint. Acceptable for `localhost`
  only deployment. If engine is ever exposed to a network, add JWT or API key auth.

---

### P3 -- Low Priority (Post Paper Trading)

**Options System:**
- [ ] Build all files in `engine/options/` per Section 1.15 specification.
- [ ] Add options API endpoints to engine.
- [ ] Add options dashboard pages.
- [ ] Integrate with IB Gateway for options chain data.

**Strategy Improvements:**
- [ ] MGC signal redesign with extended 2022 history (bear market data).
- [ ] MES signal redesign (new entry trigger beyond STC crossover).
- [ ] Multi-factor entry confirmation (beyond current regime + STC).
- [ ] Earnings calendar integration for equities proxy instruments.
- [ ] VIX regime overlay on all signals (currently only used for options spec).

**Infrastructure Upgrades:**
- [ ] Trade journal integration with OneNote via MCP.
- [ ] Real options flow data (Unusual Whales or similar).
- [ ] Cloud deployment consideration (currently local-only on Windows).
- [ ] PM2 ecosystem management for all services.

---

### Known Technical Debt

| Item                                  | Location                    | Severity |
|---------------------------------------|-----------------------------|---------:|
| Bare `except` in optimizer            | `walk_forward.py`           | Fixed v2.6 |
| No type hints in backtester core      | `backtester.py`             | Low      |
| Hardcoded event dates in blackout     | `news_blackout.py`          | Low (through 2026) |
| `conftest.py` asyncpg issue           | `engine/tests/conftest.py`  | Low (use `--noconftest`) |
| Dashboard uses `any` types in places  | Various `.tsx` files         | Low      |
| Paper config has `sic_params` typo    | `paper_config.py`           | Low (should be `stc_params`) |

---

## 1.20 File Reference

---

### Authoritative Files (Use These -- Not Older Versions)

These are the canonical, up-to-date files for each concern. When information
conflicts between files, the file listed here takes precedence.

| Concern                    | File                                          | Version / Status      |
|----------------------------|-----------------------------------------------|-----------------------|
| Strategy config (paper)    | `engine/backtest/paper_config.py`             | v2.7 AUTHORITATIVE    |
| Signal parameters          | `engine/backtest/signals.py` (INSTRUMENT_PARAMS) | AUTHORITATIVE      |
| Walk-forward results       | `engine/backtest/results/WF_*.json` (12 files)| FINAL                 |
| Executive briefing         | `engine/backtest/results/EXECUTIVE_BRIEFING.md`| v2.7 FINAL           |
| Paper trading approval     | `PAPER_TRADING_APPROVAL.md`                   | APPROVED 2026-03-30   |
| Strategy summary           | `SUMMARY.md`                                  | v2.7 FINAL            |
| Master document            | `JARVIS_TRADER_MASTER.md` (+ PART2, PART3, PART4) | v3.0 PRIMARY     |
| MCL paper setup            | `engine/paper/MCL_paper_setup.md`             | FINAL                 |
| MNQ paper setup            | `engine/paper/MNQ_paper_setup.md`             | FINAL                 |
| Research report            | `engine/docs/BACKTEST_RESEARCH_REPORT.md`     | 1,245 lines, FINAL   |
| Security remediation       | `SECURITY_REMEDIATION.md`                     | P0 ACTION REQUIRED    |
| Project log                | `jarvis-trader-skill-project-log.md`          | Session 5 current     |

---

### Engine Source Files

| Component                  | Path                                          | Description           |
|----------------------------|-----------------------------------------------|-----------------------|
| Signal generation          | `engine/backtest/signals.py`                  | STC signals + INSTRUMENT_PARAMS |
| Backtester core            | `engine/backtest/backtester.py`               | Trade simulation engine |
| Walk-forward validation    | `engine/backtest/walk_forward.py`             | Rolling 6m/3m WF      |
| Regime classifier          | `engine/backtest/regime.py`                   | EMA spread + BBWidth + ATR voting |
| MTF filter                 | `engine/backtest/mtf_filter.py`               | 4h/daily STC alignment gate |
| Indicators                 | `engine/backtest/indicators.py`               | Technical indicators (STC, ATR, volume_ratio) |
| Optimizer                  | `engine/backtest/optimizer.py`                | Parameter grid search |
| Monte Carlo                | `engine/backtest/monte_carlo.py`              | 10,000 sim Monte Carlo |
| Sensitivity analysis       | `engine/backtest/sensitivity.py`              | Parameter sensitivity |
| News blackout              | `engine/backtest/news_blackout.py`            | EconomicCalendar (81 events, 2024-2026) |
| Paper config               | `engine/backtest/paper_config.py`             | MCL/MNQ/MGC configs   |
| Paper tracker              | `engine/backtest/paper_tracker.py`            | Paper trade tracking  |
| Run backtest CLI           | `engine/backtest/run_backtest.py`             | CLI for single backtests |
| Run all backtests          | `engine/backtest/run_all_backtests.py`        | Full 12-matrix runner |
| Backtest unit tests        | `engine/backtest/test_backtester.py`          | 5/5 passing           |

---

### Engine Infrastructure Files

| Component                  | Path                                          | Description           |
|----------------------------|-----------------------------------------------|-----------------------|
| FastAPI main               | `engine/main.py`                              | ~95 endpoints, port 8010 |
| Database schema            | `engine/database/schema.py`                   | DatabaseManager, 6 tables |
| Database migrations        | `engine/database/migrations.py`               | Version-tracked migrations (001-005) |
| DB init script             | `engine/init_db.py`                           | CLI: `python init_db.py [--reset]` |
| IB Gateway manager         | `engine/execution/ib_gateway.py`              | Paper port 4002, live port 4001 blocked |
| IB Order manager           | `engine/execution/ib_order_manager.py`        | Order reconciliation  |
| Safety layer               | `engine/risk/safety_layer.py`                 | Circuit breakers, kill switch |
| P&L monitor                | `engine/risk/pnl_monitor.py`                  | 3-tier source (IB/SQLite/memory) |
| Position sizing            | `engine/utils/position_sizing.py`             | Fixed-fractional formula |
| Performance calculator     | `engine/analytics/performance.py`             | PF, Sharpe, win rate  |
| EOD scheduler              | `engine/schedulers/eod_scheduler.py`          | Mon-Fri 3:05 PM CT snapshots |
| WhatsApp notifications     | `engine/notifications/whatsapp.py`            | 4 formatters          |
| Journal router             | `engine/routers/journal_router.py`            | Trade journal CRUD    |
| Health monitor             | `engine/health_monitor.py`                    | WhatsApp alert if engine down |
| Trading pipeline           | `engine/agents/pipeline.py`                   | TradingPipeline.run_on_signal() |
| Trader agent               | `engine/agents/trader.py`                     | Position sizing integration |
| Portfolio tracker          | `engine/portfolio/tracker.py`                 | SQLite-backed PortfolioTracker |
| Config                     | `engine/config.py`                            | Env var validation at startup |

---

### Dashboard Files

| Component                  | Path                                          | Description           |
|----------------------------|-----------------------------------------------|-----------------------|
| Main dashboard             | `dashboard/app/page.tsx`                      | Landing page with summary widgets |
| Paper trading page         | `dashboard/app/paper/page.tsx`                | Paper trade monitoring |
| Performance page           | `dashboard/app/performance/page.tsx`          | Performance analytics  |
| Journal page               | `dashboard/app/journal/page.tsx`              | Trade journal view     |
| Watchlist page             | `dashboard/app/watchlist/page.tsx`            | Symbol scanning        |
| Scorecard page             | `dashboard/app/scorecard/page.tsx`            | Validation scorecard   |
| Health page                | `dashboard/app/health/page.tsx`               | 6-subsystem health grid |
| Validation page            | `dashboard/app/validation/page.tsx`           | Pre-live readiness     |
| Settings page              | `dashboard/app/settings/page.tsx`             | Risk params + kill switch |
| Backtest page              | `dashboard/app/backtest/page.tsx`             | Backtest vs live comparison |
| Stats page                 | `dashboard/app/stats/page.tsx`                | Rolling performance    |

**Dashboard component count:** 33+ components across 11 pages (Session 5 total).
All TypeScript: 0 errors.

---

### Scripts

| Script                         | Path                                       | Purpose                      |
|--------------------------------|--------------------------------------------|------------------------------|
| Smoke test                     | `engine/scripts/smoke_test.py`             | 48-endpoint smoke test       |
| Signal tester                  | `engine/scripts/test_signal.py`            | CLI signal tester            |
| Seed paper trades              | `engine/scripts/seed_paper_trades.py`      | 95 synthetic trades, 30 days |
| Pine Script generator          | `engine/scripts/pine_script_generator.py`  | TradingView Pine Script      |
| Generated Pine Script          | `engine/scripts/jarvis_trader_strategy.pine`| Pine Script v5 strategy     |
| TradingView setup guide        | `engine/scripts/TRADINGVIEW_SETUP.md`      | Webhook setup instructions   |
| Daily report                   | `engine/scripts/daily_report.py`           | EOD report generator         |
| Windows startup                | `start_jarvis.bat`                         | Double-click startup         |
| Phase 1-2 verification         | `engine/verify_phase1_2.py`                | Post-build verification      |
| Secret checker (pre-commit)    | `engine/scripts/check-secrets.sh`          | Git hook for secret detection|

---

### Walk-Forward Result Files (12 Completed Runs)

All files in `engine/backtest/results/`:

| File                                          | Description                                      | WFE    | Verdict         |
|-----------------------------------------------|--------------------------------------------------|--------|-----------------|
| `WF_MCL_1h_walk_forward.json`                 | MCL hourly, static params                        | 0.82   | **APPROVED**    |
| `WF_MNQ_1h_adaptive_walk_forward.json`        | MNQ hourly, adaptive regime                      | 0.57   | **APPROVED**    |
| `WF_MNQ_1h_adaptive_mtf_walk_forward.json`    | MNQ hourly, adaptive + MTF                       | 0.17   | REJECTED        |
| `WF_MNQ_1h_adaptive_volume_walk_forward.json` | MNQ hourly, adaptive + volume                    | -0.23  | REJECTED        |
| `WF_MCL_1h_adaptive_walk_forward.json`        | MCL hourly, adaptive regime                      | -0.31  | REJECTED        |
| `WF_MGC_1d_walk_forward.json`                 | MGC daily, static (15 windows)                   | 0.14   | HALTED          |
| `WF_MNQ_1h_walk_forward.json`                 | MNQ hourly, static params                        | 0.24   | OVERFIT         |
| `WF_MES_1h_walk_forward.json`                 | MES hourly, static params                        | 0.09   | OVERFIT         |
| `WF_MGC_1d_adaptive_walk_forward.json`        | MGC daily, adaptive regime                       | 0.14   | OVERFIT         |
| `WF_MGC_1d_adaptive_volume_walk_forward.json` | MGC daily, adaptive + volume                     | --     | OVERFIT         |
| `WF_SPY_1h_walk_forward.json`                 | SPY hourly, static params                        | -1.11  | DEEPLY OVERFIT  |
| `WF_SPY_1h_adaptive_walk_forward.json`        | SPY hourly, adaptive regime                      | -0.71  | OVERFIT         |

---

### Historical / Reference Files (Do Not Modify -- Audit Trail)

These files are kept for audit purposes. They document the research process
and should not be edited.

- `engine/backtest/results/WF_*.json` -- all 12 walk-forward run results
- `engine/backtest/results/optimizer_*.json` -- all optimization result files
- `engine/backtest/results/EXECUTIVE_BRIEFING.md` -- version history in document
- `jarvis-trader-skill-project-log.md` -- session-by-session development log
- `engine/CHANGELOG.md` -- version history (v1.0.0 through v1.5.0)
- `engine/docs/BACKTEST_RESEARCH_REPORT.md` -- 1,245-line research report

---

### Files to Be Created (Pending)

| File                                  | Section Reference | Priority |
|---------------------------------------|-------------------|----------|
| `engine/options/__init__.py`          | 1.15              | P3       |
| `engine/options/greeks_monitor.py`    | 1.15              | P3       |
| `engine/options/strategy_executor.py` | 1.15              | P3       |
| `engine/options/chain_fetcher.py`     | 1.15              | P3       |
| `engine/options/premium_calculator.py`| 1.15              | P3       |
| `engine/options/position_manager.py`  | 1.15              | P3       |
| `engine/options/iv_rank.py`           | 1.15              | P3       |
| `engine/options/roll_manager.py`      | 1.15              | P3       |
| `engine/options/event_scanner.py`     | 1.15              | P3       |
| `dashboard/app/command-center/page.tsx` | 1.19            | P2       |
| `dashboard/app/options/page.tsx`      | 1.15              | P3       |
| `dashboard/app/options/chain/page.tsx`| 1.15              | P3       |

---

### Quick Command Reference

```bash
# ── Engine ──────────────────────────────────────────────────────────────
cd C:\Users\mattm\ThinkorSwim\jarvis-trader\engine

# Start engine
.venv/Scripts/python -m uvicorn main:app --reload --port 8010

# Run single backtest
.venv/Scripts/python -m backtest.run_backtest --symbol MNQ --interval 1h

# Run optimizer
.venv/Scripts/python -m backtest.optimizer --symbol MNQ --interval 1h

# Run walk-forward
.venv/Scripts/python -m backtest.walk_forward --symbol MNQ --interval 1h

# Run walk-forward with adaptive regime
.venv/Scripts/python -m backtest.walk_forward --symbol MNQ --interval 1h --adaptive-regime

# Run Monte Carlo on a result file
.venv/Scripts/python -m backtest.monte_carlo --result backtest/results/some_result.json

# Run full 12-matrix
.venv/Scripts/python -m backtest.run_all_backtests

# Init database
.venv/Scripts/python init_db.py
.venv/Scripts/python init_db.py --reset  # destructive

# Run tests
.venv/Scripts/python -m pytest tests/ --noconftest -v

# Smoke test (48 endpoints)
.venv/Scripts/python scripts/smoke_test.py

# ── Dashboard ───────────────────────────────────────────────────────────
cd C:\Users\mattm\ThinkorSwim\jarvis-trader\dashboard
npm run dev          # port 3010
npm run build        # TypeScript check + production build

# ── Windows Startup ─────────────────────────────────────────────────────
# Double-click:
start_jarvis.bat     # Starts engine + dashboard + DB init
```

---

### Port Reference

| Service          | Port | Protocol | Notes                              |
|------------------|------|----------|------------------------------------|
| JARVIS Engine    | 8010 | HTTP     | FastAPI, ~95 endpoints             |
| Dashboard        | 3010 | HTTP     | Next.js 15, dev server             |
| IB Gateway Paper | 4002 | TCP      | TWS paper trading (when running)   |
| IB Gateway Live  | 4001 | TCP      | BLOCKED by default -- Tier 3 only  |

---

### Environment Variables Required

Defined in `engine/.env` (never committed). Template at `engine/.env.example`.

| Variable               | Required | Description                          |
|------------------------|----------|--------------------------------------|
| `ANTHROPIC_API_KEY`    | Yes      | Claude API for debate agents         |
| `TWILIO_ACCOUNT_SID`   | Yes      | WhatsApp alerts                      |
| `TWILIO_AUTH_TOKEN`     | Yes      | WhatsApp alerts                      |
| `TWILIO_WHATSAPP_FROM`  | Yes      | WhatsApp sender number              |
| `WHATSAPP_TO`          | Yes      | Matt's WhatsApp number               |
| `POLYGON_API_KEY`      | Optional | Market data (fallback to yfinance)   |
| `FRED_API_KEY`         | Optional | Macro data (fallback to cached)      |
| `FINNHUB_API_KEY`      | Optional | News data (free tier)                |

---

*End of JARVIS_TRADER_MASTER_PART4.md -- Sections 1.15 through 1.20*
*Version 3.0 | 2026-03-30 | Part 4 of 4*
