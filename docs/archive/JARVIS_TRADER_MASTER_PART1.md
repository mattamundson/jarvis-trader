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
