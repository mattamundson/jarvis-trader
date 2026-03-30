# JARVIS TRADER — Master Reference Document
**Version:** 2.7 | **Date:** 2026-03-30 | **Status:** 2 instruments paper trading ACTIVE
**This is the ONE source of truth.** All other .md files are historical archives.
> For metrics, always cite this document. Canon policy: MEMORY.md v2.7 research authority.

---

## Table of Contents
1.1 System Overview & Architecture  
1.2 Strategy Framework (Tony Stark 5-Layer)  
1.3 Walk-Forward Validation Results (FINAL v2.7)  
1.4 Corrected Backtest Performance  
1.5 Paper Trading Configuration  
1.6 Risk Management & Safety Layer  
1.7 VIX Regime Reference (CANONICAL 6-Tier)  
1.8 Three-Tier Autonomy Model  
1.9 Standing Orders & Proactive Triggers  
1.10 Matt's Trading Context & Rules  
*(sections 1.11-1.20 in Part 2)*

---

## § 1.1 — System Overview & Architecture

### Identity
**JARVIS TRADER** — AI-powered autonomous trading system for futures and options, personal trading system for Matt Morrison. Not a commercial product.

### Technology Stack
| Component | Version | Port | Notes |
|-----------|---------|------|-------|
| Engine | FastAPI v0.1.0 | **8010** | Python 3.12, `uvicorn main:app --reload --port 8010` |
| Dashboard | Next.js 15 | **3010** | `npm run dev` (or 3000 if 3010 unavailable) |
| Primary DB | SQLite | — | `engine/data/jarvis_trader.db` |
| Paper trades | SQLite | — | `engine/data/jarvis_trader.db` (PortfolioTracker) |
| Options DB | SQLite | — | `engine/db/options_positions.db` (new v2.7) |
| Redis | 6379 | — | Caching, rate limiting |
| Postgres | 5432 | — | Extended analytics (Docker) |
| Grafana | 3001 | — | Prometheus metrics (Docker) |

### Agent Pipeline (5 Stages, 10 Agents)
```
Stage 1 — Analysts (parallel, model: Claude Sonnet)
  ├─ TechnicalAnalystAgent     — STC, ATR, regime, KAMA, indicators
  ├─ NewsAnalystAgent          — Finnhub headlines, event calendar
  ├─ SocialAnalystAgent        — ApeWisdom, StockTwits, Reddit
  └─ FundamentalistAgent       — FRED macro data, yield curve

Stage 2 — Debate (model: Claude Sonnet)
  ├─ BullResearcherAgent       — Synthesizes bullish case
  └─ BearResearcherAgent       — Synthesizes bearish case

Stage 3 — Trade Decision (model: Claude Haiku)
  └─ TraderAgent               — BUY/SELL/HOLD + qty + entry/stop/target

Stage 4 — Risk (model: Claude Haiku)
  └─ RiskManagerAgent          — Safety gate: checks all circuit breakers

Stage 5 — Final Decision (model: Claude Opus)
  └─ FundManagerAgent          — Final: EXECUTE / HOLD / REDUCE (confidence threshold ≥ 0.50)
```

### Architecture Diagram
```
Dashboard (Next.js 3010)
    │
    ▼
Engine API (FastAPI 8010)
    ├── /pipeline/run ──────► 5-Stage Agent Pipeline
    ├── /safety/* ──────────► SafetyLayer (Python — no LLM)
    ├── /backtest/* ────────► Backtester + WalkForward + MonteCarlo
    ├── /portfolio/* ───────► PortfolioTracker (SQLite)
    ├── /analyze/technical ─► TechnicalAnalystAgent
    ├── /options/* (v2.7) ──► Options Engine (new)
    └── /ws/events ─────────► WebSocket (realtime)
         │
         ▼
    Data Layer
    ├── yfinance (OHLCV)
    ├── Finnhub (news)
    ├── ApeWisdom/Reddit (social)
    ├── FRED (macro, requires API key)
    └── IB Gateway (execution — paper port 4002)
```

### Directory Structure
```
jarvis-trader/
├── engine/                     # FastAPI backend
│   ├── main.py                 # Server entry point, all route definitions
│   ├── agents/                 # 10 LLM agents
│   ├── api/                    # Pydantic models
│   ├── backtest/               # Strategy backtester, walk-forward, MC
│   │   ├── signals.py          # INSTRUMENT_PARAMS, 5-layer strategy
│   │   ├── walk_forward.py     # WFE calculation
│   │   ├── run_backtest.py     # CLI runner
│   │   ├── paper_config.py     # MCL + MNQ paper configs (v2.7)
│   │   ├── results/            # JSON results + EXECUTIVE_BRIEFING.md
│   │   └── SUMMARY.md          # Backtest summary table
│   ├── options/                # Options engine (new v2.7)
│   │   ├── greeks_monitor.py   # Black-Scholes Greeks, IV solver
│   │   ├── strategy_executor.py # Order builders for 7 strategies
│   │   ├── chain_fetcher.py    # yfinance options chain + greeks
│   │   ├── premium_calculator.py # Premium, POP, EV calculations
│   │   └── position_manager.py # SQLite-backed position tracking
│   ├── paper/                  # Paper trading setup docs
│   │   ├── MCL_paper_setup.md
│   │   └── MNQ_paper_setup.md
│   ├── risk/                   # Safety layer components
│   │   ├── safety_layer.py     # Hardcoded circuit breakers
│   │   ├── loss_tracker.py     # Consecutive loss counter
│   │   └── pnl_monitor.py      # P&L monitoring
│   ├── routers/                # Modular FastAPI routers
│   │   ├── journal_router.py
│   │   └── webhook_router.py
│   └── thinkorswim/            # TOS script generator
├── dashboard/                  # Next.js 15 frontend
│   ├── app/                    # App router pages (14 pages)
│   └── components/             # 132 React components
├── thinkorswim-scripts/        # 34 .ts ThinkScript files
│   └── INTEGRATION_GUIDE.md
├── docs/                       # Research and validation docs
│   ├── JARVIS_TRADER_UNIFIED_CANON.md
│   └── CANON_SOURCE_MAP.json
├── JARVIS_TRADER_MASTER.md     # THIS FILE — single source of truth
├── EXECUTIVE_BRIEFING.md       # Strategy results (v2.7)
├── PAPER_TRADING_APPROVAL.md   # Official approval doc
├── TRADING_DAILY_ROUTINE.md    # Daily operations playbook
└── README.md                   # Quick start

External plans: C:\Users\mattm\.claude\plans\humming-meandering-hummingbird.md
```

### Quick Start
```bash
# Engine
cd engine
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8010

# Dashboard
cd dashboard
npm install
npm run dev

# Healthcheck
curl http://localhost:8010/health

# Run backtest
cd engine
python backtest/run_backtest.py --symbol MCL --interval 1h
```

---

## § 1.2 — Strategy Framework (Tony Stark 5-Layer)

### Overview
The STC + ATR + Regime Filter strategy uses 5 layers that ALL must align before entry. No layer can be bypassed.

### Layer 1 — Regime Map
**Purpose:** Filter out choppy/consolidation environments  
**Indicator:** RegimeClassifier (EMA spread + BBWidth + ATR voting)  
**States:** TRENDING_UP | TRENDING_DOWN | RANGING | VOLATILE | UNKNOWN  
**TOS Scripts:** `Saty_ATR_LevelsSTUDY.ts`, `Saty_Phase_OscillatorSTUDY.ts`, `shared_mtftrendbarSTUDY.ts`  
**Entry rule:** Only enter in TRENDING_UP (long) or TRENDING_DOWN (short)  
**Per-instrument override:** MES 1h has `REGIME_FILTER=False` (7th tuple element in INSTRUMENT_PARAMS)

### Layer 2 — Structure Map  
**Purpose:** Identify key price levels, inside-bar structure  
**Indicators:** KAMA (adaptive MA), TPO Volume Profile, Initial Balance levels  
**TOS Scripts:** `AA_CoreyTPOProfilev1STUDY.ts`, `AA_CoreyIBv1STUDY.ts`, `AA_CoreyRFv2STUDY.ts`, `AA_CoreySFv2STUDY.ts`, `AA_CoreyGapfinderv1STUDY.ts`, `AA_CoreyTscorev2STUDY.ts`  
**Entry rule:** Price must be above/below KAMA for direction alignment

### Layer 3 — Directional Bias
**Purpose:** Confirm momentum direction  
**Indicators:** STC trend direction, CCI, Keltner Channels  
**TOS Scripts:** `NextSignalMomentumSTUDY.ts`, `Saty_Volume_StackSTUDY.ts`, `shared_OB_STYLE_CYCLE_TIMESHIFT_PAINT_BARSSTUDY.ts`  
**Entry rule:** STC trending in direction of trade

### Layer 4 — Entry Timing
**Purpose:** Precise entry trigger  
**Indicator:** STC threshold cross (not level check — must CROSS, not just be above/below)  
**Key rule:** `is_oversold: true` = STC just crossed ABOVE 15 (long trigger); `is_overbought: true` = STC just crossed BELOW 83 (short trigger)  
**TOS Scripts:** OB_OMEGA family (`shared_OB_OMEGA_5mSTUDY.ts`, etc.), Keltner channels  
**Entry calculation:**
- Entry price: current bar close
- Stop: Entry ± (STOP_ATR_MULT × ATR14)
- T1: Entry ± (T1_ATR_MULT × ATR14) — take 50% profit here
- T2: Entry ± (T2_ATR_MULT × ATR14)
- T3: Entry ± (T3_ATR_MULT × ATR14)

### Layer 5 — Position Sizing
**Purpose:** Fixed fractional sizing with safety caps  
**Formula:** `Contracts = floor(Account × Risk% / (Stop_pts × $/pt))`  
**Normal:** 1.0% risk per trade  
**Liberation Day (3+ consecutive losses):** 0.5% risk  
**Severe (5+ losses):** 0.25% risk  
**HALT (7+ losses):** No new positions for 24 hours  
**Hardcoded cap:** Maximum 2 contracts regardless of calculation  

### Per-Instrument Parameters (INSTRUMENT_PARAMS — authoritative)
| Symbol | STC_OS | STC_OB | Stop ATR | T1 ATR | T2 ATR | T3 ATR | Regime Filter |
|--------|--------|--------|----------|--------|--------|--------|---------------|
| **MCL** | 15 | 83 | 0.90 | 1.50 | 2.618 | 4.00 | **ON** |
| **MNQ** | 15 | 92 | 0.70 | 1.00 | 1.80 | 2.618 | **ON** |
| MGC | 17 | 88 | 0.30 | 1.50 | 2.618 | 4.00 | ON |
| SPY | 15 | 88 | 0.30 | 1.00 | 1.618 | 2.618 | ON |
| MES | 15 | 83 | 0.50 | 2.00 | 3.236 | 4.00 | **OFF** |

*Bold = active paper trading instruments as of 2026-03-30*

### Entry Checklist (ALL must pass)
- [ ] `is_oversold: true` (long) OR `is_overbought: true` (short) — STC threshold cross
- [ ] Regime = TRENDING_UP (long) or TRENDING_DOWN (short)
- [ ] `kill_switch_active: false`
- [ ] `live_trading_enabled: false` (paper mode confirmed)
- [ ] Daily P&L > -1.6% (approaching -2.0% halt)
- [ ] `drawdown_pct > -0.08` (approaching -10.0% limit)
- [ ] Margin used < 30% of available
- [ ] ATR stop defined (Entry ± STOP_ATR × ATR14)
- [ ] R:R ≥ 1:1.5 minimum (MCL = 1:1.67, MNQ = 1:1.43)
- [ ] No high-impact event within 30 minutes
- [ ] Pipeline `confidence ≥ 0.50`

### Exit Rules
| Exit Type | Condition | Action |
|-----------|-----------|--------|
| Stop Loss | Price hits Entry ± (STOP_ATR × ATR14) | Close 100% — HARD STOP, no exceptions |
| T1 Target | Price hits Entry ± (T1_ATR × ATR14) | Close 50%, move stop to breakeven |
| T2 Target | Price hits Entry ± (T2_ATR × ATR14) | Close 25% more (75% total) |
| T3 Target | Price hits Entry ± (T3_ATR × ATR14) | Close remaining 25% |
| Time exit | FOMC day: 12:45pm CT | Flatten ALL positions |
| End of day | 3:00pm CT RTH close | Evaluate overnight hold vs close |
| Overnight limit | After 3:00pm CT | Max 1 contract per instrument |

---

## § 1.3 — Walk-Forward Validation Results (FINAL v2.7)

### WFE Thresholds (Canonical)
| WFE Value | Grade | Action |
|-----------|-------|--------|
| > 0.70 | EXCELLENT | Paper trading approved, standard sizing |
| 0.50–0.70 | GOOD | Paper trading approved, conservative sizing (0.25%) |
| 0.30–0.50 | MARGINAL | Monitor only, no paper trading |
| < 0.30 | OVERFIT | HALT — strategy not generalizing |

**Formula:** WFE = 1 - (variance_OOS_return / variance_IS_return)  
Higher = better OOS consistency relative to IS performance.

### Complete WFE Results (All 12 Runs)
| Symbol | TF | Config | Windows | OOS Profitable | WFE | Grade | Status |
|--------|-----|--------|---------|----------------|-----|-------|--------|
| **MCL** | **1h** | **Static params** | **6** | **5/6 (83%)** | **0.82** | **EXCELLENT** | **✅ APPROVED** |
| **MNQ** | **1h** | **Adaptive regime** | **6** | **4/6 (67%)** | **0.57** | **GOOD** | **✅ APPROVED** |
| MNQ | 1h | Adaptive + MTF filter | 6 | — | 0.17 | FAIL | ❌ REJECTED (filter HURTS) |
| MNQ | 1h | Adaptive + Volume filter | 6 | — | -0.23 | FAIL | ❌ REJECTED (filter DESTROYS) |
| MCL | 1h | Adaptive regime | 6 | — | -0.31 | FAIL | ❌ REJECTED (adaptive HURTS MCL) |
| MGC | 1d | Extended (15 windows) | 15 | 6/15 (40%) | 0.14 | OVERFIT | 🛑 HALTED |
| MGC | 1d | Adaptive (3 windows, 2025 only) | 3 | 2/3 | 0.88 | — | ⚠️ SMALL SAMPLE BIAS |
| MES | 1h | Static params | 6 | 1/6 (17%) | 0.09 | OVERFIT | ❌ NOT CLEARED |
| SPY | 1h | Static params | 6 | 2/6 (33%) | -1.11 | OVERFIT | ❌ NOT CLEARED |
| SPY | 1h | Adaptive regime | 6 | — | -0.71 | OVERFIT | ❌ NOT CLEARED |

### Adaptive Regime Comparison
| Symbol | TF | Static WFE | Adaptive WFE | Delta | Verdict |
|--------|-----|-----------|--------------|-------|---------|
| MCL | 1h | **0.82** | -0.31 | -1.13 | Static WINS — adaptive HURTS |
| MNQ | 1h | 0.24 | **0.57** | +0.33 | Adaptive WINS — APPROVED |
| MGC | 1d | 0.27 | 0.88* | +0.61 | *Small sample bias (3 wins only) |
| SPY | 1h | -1.11 | -0.71 | +0.40 | Both fail — neither approved |

### Critical Bugs Found and Fixed (Chronological)
| Version | Bug | Impact | Fix |
|---------|-----|--------|-----|
| v2.1 | Optimizer kwargs (`adaptive_regime`, `volume_filter`, `mtf_filter`) silently passed to `_compute_signals()` | TypeError on every WF call → all None returns → inflated WFE scores | Removed extra kwargs from `walk_forward.py` call |
| v2.2 | MGC extended WFE re-ran 15 windows vs prior 3 | WFE 0.88→0.27 (was small-sample gold bull run bias) | Used full history 2022–2026 |
| v2.3 | Volume filter tested on MNQ combined with adaptive | WFE -0.80 degradation confirmed | Volume filter locked OFF for all 1h futures |
| v2.4 | MTF filter tested on MNQ | WFE -0.40 degradation | MTF filter locked OFF for MNQ |
| v2.5 | SPY/MES re-optimization with corrected params | PF improved but WFE still negative | INSTRUMENT_PARAMS updated |
| v2.6 | MCL static WFE confirmed 0.82, corrected from buggy run | Confirmed EXCELLENT | MCL approved |
| v2.7 | MNQ adaptive WFE confirmed 0.57 (up from 0.48) | Confirmed GOOD threshold exceeded | MNQ approved |

### Why Strategies Fail Walk-Forward
1. **Regime dependency** — STC crossover most effective in sustained trends; optimizer selects for in-sample regime
2. **Parameter instability** — Optimal STC_OB shifts dramatically window-to-window (e.g., MNQ W1=92, W2=83)
3. **Thin trade counts** — 6-86 trades per 6-month window = insufficient statistical power
4. **Single trigger** — STC crossover alone lacks multi-factor robustness

---

## § 1.4 — Corrected Backtest Performance

### Per-Instrument Optimized Results (Final v2.7)
| Rank | Symbol | TF | Trades | WR% | PF | Sharpe | Return | MaxDD | WFE | Status |
|------|--------|-----|--------|-----|------|--------|--------|-------|-----|--------|
| 1 | **MCL** | 1h | 65 | **60.0%** | 1.83 | 0.15 | +0.2% | — | **0.82** | ✅ APPROVED |
| 2 | **MNQ** | 1h | 86 | **47.7%** | 1.46 | 0.19 | +13.6% | 0.1% | **0.57** | ✅ APPROVED |
| 3 | MGC | 1d | 47 | 51.1% | 2.60 | 2.04 | +34.4% | 3.0% | 0.14 | 🛑 HALTED |
| 4 | MES | 1h | 23 | 34.8% | 1.69 | 0.09 | +0.1% | 0.1% | 0.09 | ❌ OVERFIT |
| 5 | SPY | 1h | 23 | 52.2% | 3.79 | -1.43 | +0.0% | 0.1% | -1.11 | ❌ OVERFIT |

*Test period: Jun 2024–Mar 2026 (1h) / Jan 2025–Mar 2026 (1d). Gross of commissions ($2.50/contract + 1 tick slippage).*

### Do Not Trade List
| Symbol | Reason | Required Before Re-evaluation |
|--------|--------|-------------------------------|
| MGC 1d | WFE=0.14 OVERFIT. 15-window extended history confirms instability | 24+ months new data + signal redesign |
| MES 1h | WFE=0.09 OVERFIT. Nasdaq/S&P correlation causes same param instability as MNQ but without adaptive improvement | New signal layer testing |
| SPY 1h | WFE=-1.11. Deeply overfit. Adaptive improves to -0.71 (still fails) | Not viable with current strategy |
| M2K 1h | Not tested. Russell 2000 micro — high beta, mean-reversion mismatch for STC trend-following | Full walk-forward required |

### Monte Carlo Results (10,000 simulations)
| Symbol | TF | Median Return | 5th %ile | 95th %ile | Ruin Prob | Verdict |
|--------|-----|---------------|----------|-----------|-----------|---------|
| MCL | 1h | ~+1.8% | — | — | Low | Stable |
| MNQ | 1h | ~+5.2% | — | — | Low | Acceptable |
| MGC | 1d | ~+8.1% | — | — | Medium | Volatility concern |
| MES | 1h | ~-2.1% | — | — | Medium | Not viable |

### Parameter Sensitivity Analysis
Stability scores indicate how sensitive performance is to parameter perturbation. Higher = more stable.
| Symbol | TF | STC_OB Stability | Stop ATR Stability | Overall Score |
|--------|-----|-----------------|-------------------|---------------|
| MCL | 1h | 0.78 | 0.82 | **High** |
| MNQ | 1h | 0.61 | 0.74 | **Moderate** |
| MGC | 1d | 0.44 | 0.51 | Low |
| MES | 1h | 0.31 | 0.29 | Very Low |

---

## § 1.5 — Paper Trading Configuration

### Active Instruments (as of 2026-03-30)

#### MCL 1h — ACTIVE (WFE=0.82 EXCELLENT)
| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Symbol | MCL (Micro Crude Oil) | CME Group, 1h bars |
| Capital | $25,000 | Initial simulated capital |
| Risk/trade | 0.25% = $62.50 | Conservative for paper validation |
| STC_OS | 15 | Long entry trigger |
| STC_OB | 83 | Short entry trigger |
| Stop | 0.90 × ATR14 | Validated optimal in walk-forward |
| T1 | 1.50 × ATR14 | 50% close, move stop to breakeven |
| T2 | 2.618 × ATR14 | Fibonacci extension |
| T3 | 4.00 × ATR14 | Final runner |
| regime_filter | **ON** | Blocks RANGING/VOLATILE entries |
| adaptive_regime | **OFF** | Adaptive WFE=-0.31 — NEVER ENABLE |
| volume_filter | OFF | Not tested for MCL |
| mtf_filter | OFF | Not tested for MCL |
| Max positions | 1 contract | Safety cap |
| Multiplier | $100/point (1,000 bbls × $0.10 tick) | $1.00 per tick |
| Kill switch | -3% monthly OR 3 consecutive losses | Triggers halt and review |
| Rolling WFE min | 0.40 | Recalculate monthly; halt if below |

Config file: `engine/backtest/paper_config.py` → `MCL_PAPER_CONFIG`  
Setup doc: `engine/paper/MCL_paper_setup.md`

#### MNQ 1h — ACTIVE (WFE=0.57 GOOD)
| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Symbol | MNQ (Micro Nasdaq) | CME Group, 1h bars |
| Capital | $25,000 | Initial simulated capital |
| Risk/trade | 0.25% = $62.50 | Conservative for paper validation |
| STC_OS | 15 | Long entry trigger |
| STC_OB | 92 | Short entry trigger (higher threshold filters Nasdaq noise) |
| Stop | 0.70 × ATR14 | Tighter stop for tech volatility |
| T1 | 1.00 × ATR14 | Take 50% quickly |
| T2 | 1.80 × ATR14 | Runner |
| T3 | 2.618 × ATR14 | Final |
| regime_filter | ON | Required for adaptive_regime |
| adaptive_regime | **ON** | CRITICAL — lifts WFE 0.24→0.57 |
| volume_filter | **OFF — NEVER ENABLE** | Hurts WFE 0.57→-0.23 |
| mtf_filter | **OFF — NEVER ENABLE** | Hurts WFE 0.57→0.17 |
| Max positions | 1 contract | Safety cap |
| Multiplier | $2/point (Micro Nasdaq) | $0.50 per tick |
| Kill switch | -3% monthly OR 3 consecutive losses | |
| Rolling WFE min | 0.30 | Lower threshold (GOOD grade) |

Config file: `engine/backtest/paper_config.py` → `MNQ_PAPER_CONFIG`  
Setup doc: `engine/paper/MNQ_paper_setup.md`

#### MGC 1d — HALTED
| Parameter | Value |
|-----------|-------|
| WFE | 0.14 (OVERFIT — below 0.30 threshold) |
| Status | `enabled: False` in `MGC_PAPER_CONFIG` |
| History | Previous WFE=0.88 was small-sample bias (3 windows, 2025 gold bull run only) |
| Re-evaluation | Requires 24+ months of new data + fundamental signal redesign |

### Re-Evaluation Schedule
| Frequency | Action |
|-----------|--------|
| Every 4 weeks | Recalculate rolling WFE with new data added |
| Quarterly | Full parameter re-optimization if WFE drops below 0.40 |
| Annually | Full strategy assessment, consider new signal layers |

### Paper Trading Kill Thresholds
| Threshold | MCL | MNQ | Effect |
|-----------|-----|-----|--------|
| Monthly loss | -3% | -3% | Automatic halt, manual review required |
| Daily loss | -2% | -2% | Pause until next session (SafetyLayer) |
| Consecutive losses | 3 | 3 | Manual review, optional sizing reduction |
| Rolling WFE minimum | 0.40 | 0.30 | Halt if recalculated WFE drops below |

---

## § 1.6 — Risk Management & Safety Layer

### Architecture Philosophy
The SafetyLayer is **pure Python** with hardcoded constants. No LLM can modify these limits. All circuit breakers operate independently of any AI component.

### Circuit Breakers (Hardcoded — Not API-Configurable)
| Limit | Value | Trigger Condition | Effect |
|-------|-------|------------------|--------|
| Daily loss | -2.0% | `daily_pnl / equity_peak ≤ -0.02` | Kill switch auto-activates |
| Max drawdown | -10.0% | `drawdown_pct ≤ -0.10` | Kill switch auto-activates |
| Order rate | >10/min | `orders_last_minute > 10` | Kill switch auto-activates |
| Max contracts | 2 | Any new position would exceed | New positions blocked |
| Margin limit | 40% | `margin_used / total_margin ≥ 0.40` | New positions blocked |

### Kill Switch States
| State | Description | Tier to Change |
|-------|-------------|----------------|
| OFF | Normal operation — new positions allowed | N/A |
| ACTIVE (auto) | Circuit breaker triggered — pipeline read-only | **Tier 3: human review + explicit confirm + POST /safety/kill-switch/deactivate** |
| ACTIVE (manual) | User activated via `POST /safety/kill-switch/activate` | Same — Tier 3 deactivation |

**Critical rule:** When `kill_switch_active: true`, JARVIS surfaces this FIRST on EVERY response until cleared.

### Consecutive Loss Tracker (Liberation Day Protocol)
| Consecutive Losses | Sizing | Status |
|-------------------|--------|--------|
| 0–2 | 1.0% risk | Normal |
| 3 | 0.5% risk | Liberation Day active |
| 5 | 0.25% risk | Severe — consider standing aside |
| 7+ | HALT 24h | No new positions for 24 hours |

**Origin:** "Liberation Day" = April 2025 crash event. Protocol named after the stress event that proved position sizing discipline critical.

### Emergency Protocols
**EP-1: Daily Loss Limit Breach (-2.0%)**
- Source: SafetyLayer Python, automatic
- Detection: `kill_switch_active: true` + `kill_switch_reason` in `/safety/status`
- Action: T-6 surfaces FIRST every response
- Deactivation (Tier 3): Review decisions → explicit confirm → `POST /safety/kill-switch/deactivate`

**EP-2: Max Drawdown Breach (-10.0%)**
- Source: SafetyLayer Python
- Action: T-6 + "Maximum drawdown limit breached — most severe halt"
- Deactivation (Tier 3): 3-step review: (1) last losing decisions, (2) regime during drawdown, (3) reduce to 1 contract until `drawdown_pct > -0.05`

**EP-3: Engine Unresponsive**
- `/health` returns `status != "online"` × 2
- Action: T-10 on every response. All data stale.
- Restart options:
  - Direct: `cd engine && uvicorn main:app --reload --port 8010`
  - PM2: `pm2 restart jarvis-trader`
  - Debug: `pm2 stop jarvis-trader && tail -100 engine/logs/app.log && pm2 start jarvis-trader`

**EP-4: Anomalous Order Rate (IB Gateway Phase 3+)**
- `orders_last_minute > 10`
- Investigation: Check `/decisions/recent?limit=50`, look for infinite pipeline loop or multiple scheduler instances

**EP-5: Market-Wide Circuit Breaker (NYSE Rule 80B)**
- S&P -7% → 15-min halt | S&P -13% → 15-min halt | S&P -20% → Day halt
- Rule: Above strategy kill switch — no orders regardless of kill switch state

**EP-6: Correlation Cascade**
- T-22 + 3+ correlated positions losing simultaneously
- JARVIS advisory only — NEVER closes positions autonomously
- Guidance: Pause new entries, no adding to losers, check regime shift

### IB Gateway Port Lock
| Mode | TWS Port | Gateway Port | Setting |
|------|---------|--------------|---------|
| Paper | 7497 | **4002** | `IBKR_PORT=4002` |
| Live | 7496 | **4001** | `IBKR_PORT=4001` |

**Rule:** Port 4001 is live — do NOT connect to 4001 until Phase 3 (June 2026+). All testing uses 4002.

---

## § 1.7 — VIX Regime Reference (CANONICAL 6-Tier)

*This is the canonical definition. All other VIX tier schemes (4-tier, 5-tier) in older files are superseded.*

| VIX Level | Regime | Position Sizing | Options Guidance | Trading Guidance |
|-----------|--------|-----------------|-----------------|-----------------|
| < 12 | VERY_LOW | Standard | Long spreads favored | Caution — mean reversion possible; trend entries may fail |
| 12–16 | LOW | Standard (1.0%) | All strategies viable | Favorable for trend-following |
| 16–20 | NORMAL | Standard (1.0%) | Iron condors viable; standard premium | Standard conditions; full sizing |
| 20–25 | ELEVATED | Reduced (0.5%) | Premium selling favorable (CSPs, condors) | Reduce size; tighten ATR stop mult |
| 25–30 | HIGH | 1 contract max | High risk — buy straddles | Consider standing aside |
| > 30 | EXTREME | Flat or minimum | Buy premium expensive; defined-risk only | Kill switch may auto-activate |

### VIX Alert Thresholds (Proactive Triggers)
| Level | Trigger | JARVIS Action |
|-------|---------|---------------|
| VIX > 20 | T-23 WARNING | Suggest reducing position sizes |
| VIX > 25 | T-23 HIGH | 1 contract max recommendation |
| VIX > 30 | T-23 CRITICAL | Suggest flat / stand aside |

### WhatsApp VIX Notifications
SO-4 includes VIX regime in every signal dispatch. Independent VIX alerts via `POST /notifications/vix-alert-check`.

---

## § 1.8 — Three-Tier Autonomy Model

| Tier | Type | Examples | Override |
|------|------|---------|---------|
| **Tier 1** | Fully autonomous | Health polling, market data cache, watchlist scans, pre-market brief, scheduler | None — runs automatically |
| **Tier 2** | Recommend-then-execute | Pipeline signals, WhatsApp alerts, paper trade logging (when SO-5 active) | Can ask JARVIS to pause |
| **Tier 3** | Human approval required | Kill switch activate/deactivate, live trading enable, capital changes, SO-5 activation, watchlist modifications | Always requires Matt's explicit confirm |

**Current SO-5 status:** INACTIVE (`require_human_approval: true` confirmed live). All trade logging is Tier 3.

**Conservative autonomy principle:** JARVIS researches freely and surfaces recommendations. Matt decides and confirms. JARVIS never acts on live/paper accounts without explicit instruction.

---

## § 1.9 — Standing Orders & Proactive Triggers

### Standing Orders (6)
| ID | Name | Tier | Trigger | Action |
|----|------|------|---------|--------|
| SO-1 | Health Monitor | 1 AUTO | Always active | `GET /health` every 60s — alert if status != "online" × 2 |
| SO-2 | Market Open Brief | 1 AUTO | Trading days, builds 6:00am | 7-step brief cached, delivered at 6:30am CT |
| SO-3 | Watchlist Scan | 1 AUTO | Mon–Fri per scheduler (~30min) | `POST /pipeline/run` on watchlist → fires T-7/T-20/T-21 |
| SO-4 | Signal Alert | 2 NOTIFY | Non-hold from SO-3 | Format + send WhatsApp via Twilio; 2hr cooldown/symbol |
| SO-5 | Paper Trade Auto-Log | 2 NOTIFY | `require_human_approval: false` | `POST /decisions/log` — **currently INACTIVE** |
| SO-6 | Daily P&L Watch | 1 AUTO | 6am–5pm CT | Polls safety/status + portfolio; T-8 at -1.6%, T-9 at -8.0% |

### Proactive Triggers (24)

**CRITICAL — Surface every response:**
| ID | Condition | Action |
|----|-----------|--------|
| T-6 | `kill_switch_active: true` | Surfaces FIRST before all content every interaction |
| T-10 | Engine `status != "online"` × 2 | Surfaces FIRST. Restart instructions every interaction |

**WARNING — Surface promptly:**
| ID | Condition | Action |
|----|-----------|--------|
| T-7 | `action != "hold"` from pipeline | Full signal + WhatsApp confirmation (SO-4) |
| T-8 | `daily_pnl / equity_peak ≤ -0.016` | Warning + 3 options (continue/reduce/halt) |
| T-9 | `drawdown_pct ≤ -0.08` | Warning + size reduction |
| T-12 | 3 consecutive losses | Liberation Day protocol (0.5% risk) |
| T-13 | FOMC day | Flatten reminder + time |
| T-20 | Regime changes between scans | Old→New regime + implications |
| T-21 | `is_oversold: true` or `is_overbought: true` | Primary entry signal + auto pipeline |
| T-22 | 2+ correlated instruments non-hold | Combined exposure warning |
| T-23 | VIX > 25 (WARNING) or > 30 (CRITICAL) | Size reduction / flatten suggestion |
| T-24 | Scheduler overdue > 45 min RTH | Check + offer manual scan |

**INFO — Auto-loads in context:**
| ID | Activates | Auto-Loaded |
|----|-----------|-------------|
| T-1 | 6:30am CT | Full 7-step pre-market brief |
| T-2 | 8:30am CT | RTH open alert + scheduler |
| T-3 | 3:45pm CT | Position decision prompt |
| T-4 | 4:05pm CT | EOD portfolio + decisions |
| T-5 | Monday 7:00am | Weekly review |
| T-11 | Twilio dispatch | Confirmation |
| T-14 | Symbol mentioned | `GET /prices/snapshot` + last 3 decisions |
| T-15 | "my position" mentioned | `GET /portfolio` |
| T-16 | "risk/drawdown/kill switch" | `GET /safety/status` + portfolio |
| T-17 | "backtest/track record" | MCL WFE=0.82, MNQ WFE=0.57 |
| T-18 | "regime/trending?" | `POST /analyze/technical` |
| T-19 | "options/delta/IV/0DTE" | VIX context + STC direction + options engine status |

### Automated Daily Timeline (All CT)
| Time | Event | Auto/Manual |
|------|-------|-------------|
| 6:00am | Engine health check begins (SO-1) | AUTO |
| 6:30am | Pre-Market Intelligence Brief (T-1) | AUTO |
| 7:00am | Economic calendar check | AUTO |
| 8:00am | Matt's prep window opens | MANUAL |
| 8:30am | RTH Open Alert (T-2) + SO-3 activates | AUTO |
| Every 30min | Watchlist scan (SO-3) | AUTO |
| 9:35am | Matt's morning window opens | — |
| 11:30am | Midday lull begins | — |
| 1:00pm | Matt's afternoon window opens | — |
| 3:00pm | RTH close final scan | AUTO |
| 3:30pm | Matt's afternoon window closes | — |
| 3:45pm | Market Close Warning (T-3) | AUTO |
| 4:05pm | EOD Summary (T-4) | AUTO |
| Monday 7:00am | Weekly Review (T-5) | AUTO |

---

## § 1.10 — Matt's Trading Context & Rules

### Trading Sessions (All Times Central)
| Session | CT Window | ET Window | Rule |
|---------|-----------|-----------|------|
| Pre-market active | 8:00–8:30am | 9:00–9:30am | Review brief, confirm plan |
| RTH Open — AVOID | 8:30–9:35am | 9:30–10:35am | High noise — NO ENTRIES |
| Morning Primary | **9:35–11:30am** | 10:35am–12:30pm | **Primary trading window** |
| Midday lull — AVOID | 11:30am–1:00pm | 12:30–2:00pm | Skip unless strong catalyst |
| Afternoon Secondary | **1:00–3:30pm** | 2:00–4:30pm | **Secondary trading window** |
| After-hours | 3:00–5:00pm | 4:00–6:00pm | Exits only — reduced liquidity |
| Futures close | 5:00pm | 6:00pm | Daily settlement |

### Personal Trading Rules (Permanent)
1. **Never trade the open** — 8:30–9:35am CT is noise; stop sweeps and false breakouts
2. **Respect the -2% daily halt** — When SafetyLayer fires, review and accept the halt
3. **Check WhatsApp before acting** — SO-4 alerts are the single source of signal truth
4. **Never hold MES overnight** — Micro S&P gap risk is disproportionate to reward
5. **FOMC rule** — Flatten ALL positions by 12:45pm CT on FOMC days
6. **Liberation Day discipline** — 3+ consecutive losses = 0.5% risk, no exceptions
7. **Confidence threshold** — Only act on pipeline signals with confidence ≥ 0.50
8. **No counter-trend entries** — Never fade a trending_up regime short

### Account Phases
| Phase | Status | Capital | Instruments | Automation |
|-------|--------|---------|-------------|-----------|
| Phase 1: Backtesting | ✅ COMPLETE | Simulated | MCL, MNQ, MES, MGC, SPY | WFE validation |
| **Phase 2: Paper Trading** | **⏳ ACTIVE** | **$25,000 simulated** | **MCL 1h, MNQ 1h** | SO-3/SO-4, Tier 3 trades |
| Phase 3: Live Micro | 📅 Jun 2026+ | $10,000 real | 1 MES contract | IB Gateway 4002 → 4001 |
| Phase 4: Full Deploy | 📅 Q3 2026+ | $25,000+ real | MCL + MNQ + MES | Full automation with SO-5 |

### Phase 2 → Phase 3 Graduation Checklist
All must pass before enabling `live_trading: true`:
- [ ] 60 consecutive trading days in paper mode
- [ ] Minimum 40 non-hold decisions logged
- [ ] Profit Factor > 3.0 (CANONICAL — not 1.5, not 5.27)
- [ ] Sharpe ≥ 1.0 (paper gate)
- [ ] Win Rate ≥ 45% (paper gate — NOT 28%, 50%, or 55%)
- [ ] Max drawdown < 10% (`drawdown_pct > -0.10` sustained)
- [ ] Live gate: PF ≥ 2.0, Sharpe ≥ 1.5, WR ≥ 50%, DD < 8%
- [ ] IB Gateway paper port tested (TWS=7497, Gateway=4002)
- [ ] WhatsApp alerts confirmed: ≥ 5 SO-4 dispatches with Twilio SIDs
- [ ] No EP-3 events in final 2 weeks
- [ ] Kill switch tested (activate + deactivate confirmed working)
- [ ] Liberation Day rule respected throughout

### Position Sizing Formula
```
Dollar risk = Account equity × Risk%
Contracts = floor(Dollar risk / (Stop_pts × $/pt))

Example — MCL (crude oil, $1/pt, ATR = 0.42):
  Account: $25,000 × 0.25% = $62.50 risk
  Stop: 0.90 × 0.42 = 0.378 pts × $100/pt = $37.80/contract
  $62.50 / $37.80 = 1.65 → 1 contract

Example — MNQ (Nasdaq micro, $2/pt, ATR = 155):
  Account: $25,000 × 0.25% = $62.50 risk
  Stop: 0.70 × 155 = 108.5 pts × $2/pt = $217/contract
  $62.50 / $217 = 0.29 → 0 contracts (below minimum)
  → Use minimum 1 contract or stand aside
```

### Instrument Contract Specifications
| Instrument | Full Name | Multiplier | Min Tick | Tick Value | Point Value | Sessions |
|------------|-----------|-----------|----------|------------|-------------|----------|
| MES | Micro E-mini S&P 500 | 5 | 0.25 pts | $1.25 | **$5.00** | Sun-Fri 5pm-4pm CT |
| MNQ | Micro E-mini Nasdaq | 2 | 0.25 pts | $0.50 | **$2.00** | Sun-Fri 5pm-4pm CT |
| MCL | Micro Crude Oil | 100 bbl | $0.01/bbl | $1.00 | **$100.00** | Sun-Fri 5pm-4pm CT |
| MGC | Micro Gold | 10 oz | $0.10/oz | $1.00 | **$10.00** | Sun-Fri 5pm-4pm CT |
| M2K | Micro Russell 2000 | 5 | 0.10 pts | $0.50 | **$5.00** | Not tested |

## § 1.11 — API Surface (Live-Validated)

### API Authority
- **Primary endpoint reference:** `TRADING_DAILY_ROUTINE.md` — 26 endpoints validated against live engine 2026-03-29
- **OpenAPI spec:** `http://localhost:8010/openapi.json` — runtime truth when docs drift
- **Engine version:** 0.1.0 | No authentication required (localhost only)
- **CANONICAL corrections:** 23 field name corrections documented below

### Complete Endpoint Registry (80+ endpoints)

**Engine State**
| Method | Endpoint | Response Fields | Notes |
|--------|----------|-----------------|-------|
| GET | `/health` | `status` ("online" NOT "ok"), `version`, `kill_switch_active`, `live_trading`, `paper_mode`, `ibkr_connected`, `schwab_connected`, `uptime_seconds` | ⚠️ status="online" — validated |
| GET | `/health/full` | Extended health with all subsystem status | |
| GET | `/system/preflight` | Pre-flight checklist for system start | |
| POST | `/safety/kill-switch/activate?reason=` | Activate kill switch (Tier 3 only) | |
| POST | `/safety/kill-switch/deactivate` | Deactivate (Tier 3 only) | |
| GET | `/safety/status` | `kill_switch_active`, `kill_switch_reason`, `live_trading_enabled`, `require_human_approval`, `daily_pnl` (dollars NOT %), `equity_peak`, `current_equity`, `drawdown_pct` (ratio e.g. -0.05 = -5%), `orders_last_minute` | ⚠️ daily_pnl is raw dollars |
| GET | `/safety/circuit-breakers` | Circuit breaker states | |
| GET | `/safety/config` | Safety configuration | |
| POST | `/safety/reset-daily-pnl` | Reset daily P&L | |
| GET | `/safety/loss-tracker` | Consecutive loss state | |

**Settings & Strategy**
| Method | Endpoint | Notes |
|--------|----------|-------|
| GET/POST | `/settings/risk` | Risk parameter settings |
| GET/PUT | `/strategy/params` | Strategy parameters (STC, ATR) |

**Market Data**
| Method | Endpoint | Response | Notes |
|--------|----------|----------|-------|
| GET | `/prices/snapshot` | `{SYMBOL: {symbol, last_price, prev_close, change_pct}}` | ⚠️ "last_price" NOT "price"; no volume field |
| GET | `/watchlist` | `[{symbol, name, type, last_price, change_pct}]` | type="futures" or "options" |
| GET | `/macro/snapshot` | `vix`, `vix_regime`, `ten_year_yield`, `dxy`, `fed_funds_target`, `macro_regime`, `macro_notes`, `upcoming_events[]` | Requires FRED_API_KEY → 422 without it |
| GET | `/macro/series/{series_id}` | FRED time series | ?periods=N |

**Analysis**
| Method | Endpoint | Request/Response | Notes |
|--------|----------|-----------------|-------|
| POST | `/analyze/technical` | Body: `{symbol, is_futures?, timeframe?}` → `signal`, `confidence`, `trend`, `regime`, `is_oversold`, `is_overbought`, `scores{}`, `levels{}` | ⚠️ Does NOT return atr/entry_price/stop directly |
| GET | `/analyze/bars/{symbol}` | ?timeframe=1h&days=5&futures=true | ⚠️ Use "timeframe" and "days" (NOT "interval" and "period") |
| POST | `/pipeline/run` | Body: `{symbol, is_futures?}` ONLY | ⚠️ No include_news/include_social/include_macro params |
| GET | `/pipeline/status` | `available`, `last_run{id, timestamp, symbol, action, confidence, summary}`, `decision_count` | |
| GET | `/pipeline/history` | Recent pipeline runs | |
| GET | `/analytics/performance` | Performance analytics | |
| GET | `/analytics/performance/rolling` | Rolling performance | |
| GET | `/analytics/performance/compare` | Backtest vs paper comparison | |
| GET | `/analytics/mtf` | Multi-timeframe analysis | |
| GET | `/signals/stats` | Signal statistics | |

**Sentiment & News**
| Method | Endpoint | Response | Notes |
|--------|----------|----------|-------|
| GET | `/sentiment/recent` | `[{symbol, score, post_count, source, timestamp}]` | score: -1.0 (bearish) to +1.0 (bullish). No sentiment_label field. |
| GET | `/sentiment/reddit` | Reddit sentiment | ?filter=string |
| GET | `/sentiment/news/{symbol}` | News sentiment | |

**Portfolio**
| Method | Endpoint | Response | Notes |
|--------|----------|----------|-------|
| GET | `/portfolio` | `total_equity`, `cash_balance`, `unrealized_pnl`, `realized_pnl`, `daily_pnl`, `margin_used`, `margin_available`, `positions[]` | ⚠️ Use this — NOT /portfolio/paper/positions |
| GET | `/portfolio/paper/positions` | Paper positions | May 404 in some versions |
| POST | `/portfolio/paper/trade` | Submit paper trade | |
| GET | `/portfolio/paper/performance` | Paper performance | May 404 in some versions |
| GET | `/paper/pending-signals` | Pending signals | |
| GET | `/portfolio/history/trades` | Trade history | |
| GET | `/portfolio/history/daily-pnl` | Daily P&L history | |
| GET | `/portfolio/history/decisions` | Decision history | |
| GET | `/portfolio/stats/summary` | Stats summary | |
| GET | `/portfolio/stats/drawdown` | Drawdown stats | |
| GET | `/portfolio/stats/streaks` | Trading streaks | |
| GET | `/portfolio/stats/session-today` | Today's session | |
| GET | `/portfolio/stats/commissions` | Commission stats | |
| GET | `/portfolio/stats/weekly` | Weekly stats | |

**Decisions & Logging**
| Method | Endpoint | Notes |
|--------|----------|-------|
| GET | `/decisions/recent?limit=N` | ⚠️ Only "limit" param. No "symbol" or "hours" params. action is lowercase: "buy", "sell", "hold" |
| POST | `/decisions/log` | Accepts any JSON (freeform) — only trade logging method in v1.1.0 |
| GET | `/decisions/recent` | Recent decisions | |

**Scheduler & Tools**
| Method | Endpoint | Notes |
|--------|----------|-------|
| GET | `/scheduler/status` | `running`, `jobs[{id, name, next_run}]`, `total_decisions_logged` — ⚠️ No enabled/last_scan_time/scan_interval_minutes |
| POST | `/scheduler/scan-now` | Trigger immediate scan |
| POST | `/thinkscript/generate` | Body: `{symbol, timeframe?, is_futures?}` → ThinkScript code |
| GET | `/macro/series/{series_id}` | FRED series |

**Backtest & Research**
| Method | Endpoint | Notes |
|--------|----------|-------|
| GET | `/backtest/results` | ⚠️ No GET endpoint for results — use POST /backtest/run |
| POST | `/backtest/run` | Body: `{symbol, start, end, interval, capital, risk_per_trade}` |
| POST | `/backtest/walk-forward` | Walk-forward validation run |
| POST | `/backtest/regime-analysis` | Regime analysis |
| GET | `/backtest/regime-status` | Current regime status |
| GET | `/backtest/paper-status` | Paper trading status |
| GET | `/paper/mgc-signal` | MGC paper signal (historical — instrument HALTED) |
| POST | `/paper/mgc-log-trade` | Log MGC paper trade (historical) |
| GET | `/paper/mgc-performance` | MGC paper performance (historical) |
| POST | `/backtest/monte-carlo` | Monte Carlo simulation |
| POST | `/backtest/monte-carlo/chart` | Monte Carlo chart |

**Notifications & Reports**
| Method | Endpoint | Notes |
|--------|----------|-------|
| POST | `/notifications/whatsapp/test` | Test Twilio WhatsApp |
| POST | `/notifications/vix-alert-check` | VIX alert check |
| GET | `/reports/performance` | Performance report |
| GET | `/alerts/history` | Alert history |
| GET | `/alerts/stats` | Alert statistics |
| GET | `/alerts/active` | Active alerts (may 404 → fallback to /health) |

**Options (New v2.7)**
| Method | Endpoint | Notes |
|--------|----------|-------|
| GET | `/options/chain/{symbol}` | Options chain with Greeks (new) |
| GET | `/options/positions` | Current options positions (new) |
| POST | `/options/trade` | Paper trade options strategy (new) |
| GET | `/options/greeks` | Portfolio-level Greeks summary (new) |
| POST | `/options/scan` | Scan for opportunities (new) |

**WebSocket**
| Type | Endpoint | Events |
|------|----------|--------|
| WS | `/ws/events` | Real-time pipeline events, signals, alerts |
| GET | `/ws/status` | WebSocket connection status |

**Analytics**
| Method | Endpoint | |
|--------|----------|-|
| GET | `/analytics/trades/by-day` | Trades grouped by day |
| GET | `/analytics/trades/by-symbol` | Trades by symbol |
| GET | `/analytics/trades/by-hour` | Trades by hour |
| GET | `/watchlist/scan` | Watchlist scan results |
| POST | `/watchlist` | Add to watchlist |
| DELETE | `/watchlist/{symbol}` | Remove from watchlist |
| GET | `/market/earnings` | Upcoming earnings |
| GET | `/llm/stats` | LLM cost tracking stats |

### Critical Field Name Corrections (23 validated)
1. `GET /health` → `status` = "online" NOT "ok" ❌
2. `GET /safety/status` → `daily_pnl` = raw dollars, NOT percentage ❌
3. `GET /prices/snapshot` → `last_price` NOT `price` ❌
4. `GET /prices/snapshot` → `change_pct` NOT `change` ❌
5. `GET /prices/snapshot` → No `volume` field ❌
6. `POST /pipeline/run` → No `include_news/social/macro` params ❌
7. `GET /decisions/recent` → No `symbol` or `hours` params ❌
8. `GET /decisions/recent` → `action` is lowercase "hold/buy/sell" ❌
9. `GET /analyze/bars` → `timeframe` NOT `interval`, `days` NOT `period` ❌
10. `POST /analyze/technical` → Does NOT return `atr`, `entry_price`, `stop_price` ❌
11. `GET /scheduler/status` → No `enabled`, `last_scan_time`, `scan_interval_minutes` ❌
12. `GET /portfolio` → Use this, not `/portfolio/paper/positions` ❌
13. `GET /sentiment/recent` → No `sentiment_label` field — derive from score ❌
14. `GET /backtest/results` → Does NOT exist; use `POST /backtest/run` ❌
15. `GET /thinkscript/list` → Does NOT exist ❌
16. `GET /thinkscript/{name}` → Does NOT exist ❌
17. `GET /alerts/active` → May 404; fallback to `/health` ❌
18. `GET /portfolio/paper/positions` → May 404; use `/portfolio` instead ❌
19. `GET /portfolio/paper/performance` → May 404; derive from `/portfolio` ❌
20. `GET /macro/snapshot` → Returns 422 without FRED_API_KEY ❌
21. `POST /decisions/log` → Accepts any JSON freeform (no strict schema) ✅
22. Sentiment score interpretation: derive label from score (< -0.2 = BEARISH, > 0.2 = BULLISH) ❌
23. `/paper/mgc-signal` endpoint — instrument HALTED but endpoint still exists ⚠️

---

## § 1.12 — ThinkOrSwim Script Library

### Inventory
- **34 total `.ts` files** in `thinkorswim-scripts/` directory
- **21 unique studies** (13 are TOS `shared_` export duplicates — redundant copies)
- **1 integration guide:** `thinkorswim-scripts/INTEGRATION_GUIDE.md`

### Canonical 21 Unique Studies × Strategy Layer

**Layer 1 — Regime Map (3 scripts)**
| Script | Function | Python Alignment |
|--------|----------|-----------------|
| `Saty_ATR_LevelsSTUDY.ts` | ATR-based support/resistance levels; consumed ATR range | `indicators.py: wilder_atr()`, `range_consumed_pct()` |
| `Saty_Phase_OscillatorSTUDY.ts` | Phase oscillator for regime classification | `indicators.py: phase_oscillator()` |
| `shared_mtftrendbarSTUDY.ts` | Multi-timeframe trend bar coloring | `indicators.py: ema_ribbon()`, RegimeClassifier |

**Layer 2 — Structure Map (6 scripts)**
| Script | Function | Python Alignment |
|--------|----------|-----------------|
| `AA_CoreyTPOProfilev1STUDY.ts` | TPO Volume Profile | `indicators.py` structure logic |
| `AA_CoreyIBv1STUDY.ts` | Initial Balance (first hour high/low) | `signals.py` IB levels |
| `AA_CoreyRFv2STUDY.ts` | Range finder v2 | `signals.py` structure map |
| `AA_CoreySFv2STUDY.ts` | Support/resistance finder v2 | `signals.py` structure map |
| `AA_CoreyGapfinderv1STUDY.ts` | Gap detection | GAPS_Chetan1STUDY.ts complementary |
| `AA_CoreyTscorev2STUDY.ts` | TPO Score — market structure quality | `signals.py` structure score |

**Layer 3 — Directional Bias (3 scripts)**
| Script | Function | Python Alignment |
|--------|----------|-----------------|
| `NextSignalMomentumSTUDY.ts` | Momentum signal for directional bias | `indicators.py: stc()`, `cci()` |
| `Saty_Volume_StackSTUDY.ts` | Volume stack (bull/bear pressure) | `indicators.py: volume_stack()` |
| `shared_OB_STYLE_CYCLE_TIMESHIFT_PAINT_BARSSTUDY.ts` | OBAR cycle + bar coloring | `indicators.py: phase_oscillator()` |

**Layer 4 — Entry Timing (4 scripts)**
| Script | Function | Python Alignment |
|--------|----------|-----------------|
| `shared_OB_OMEGA_5mSTUDY.ts` | OB Omega entry (5m) | `layer4_entry()`, Keltner |
| `shared_OB_OMEGA_30m7STUDY.ts` | OB Omega entry (30m) | Same |
| `shared_OB_OMEGA_15m7STUDY.ts` | OB Omega entry (15m) | Same |
| `shared_OB_LBR_BARS_HH_LL17STUDY.ts` | LBR bars (higher high / lower low) | `signals.py` entry confirmation |

**Layer 5 — Risk & Targets (1 script)**
| Script | Function | Python Alignment |
|--------|----------|-----------------|
| `Saty_ATR_LevelsSTUDY.ts` | ATR-based stop and target levels (also L1) | `signals.py` stop/target ATR multiples |

**Supporting Studies (4 scripts)**
| Script | Function | Layer |
|--------|----------|-------|
| `TRIN_ChetanSTUDY.ts` | TRIN (market breadth) | Market context |
| `GAPS_Chetan1STUDY.ts` | Gap finder | Gap risk |
| `AA_CoreyRFv1MobileSTUDY.ts` | Range finder mobile | Legacy |
| `ThinkScript_study_2022/2023STUDY.ts` | Dated legacy studies | Historical only |

### Parameter Parity (Critical)
STC and ATR inputs in TOS scripts MUST match `INSTRUMENT_PARAMS` in `engine/backtest/signals.py`:
- MCL: STC_OS=15, STC_OB=83, Stop=0.90 ATR, T1=1.50 ATR
- MNQ: STC_OS=15, STC_OB=92, Stop=0.70 ATR, T1=1.00 ATR
- Note: 1h uses STC_OS=15; daily uses STC_OS=23

### ThinkScript Generation
Generate any study on-demand:
```
POST http://localhost:8010/thinkscript/generate
{"symbol": "MCL", "timeframe": "1h", "is_futures": true}
```

### Generated Study Categories
**Signal Indicators:** `STC_Signal_Alert`, `STC_Color_Bars`, `ATR_StopLoss_Dynamic`, `JARVIS_Entry_Zone`, `Pipeline_Signal_Arrows`
**Regime Filters:** `ADX_Regime_Color`, `VIX_Regime_Overlay`, `EMA_Alignment_Signal`, `Volume_Regime_Filter`
**Risk Dashboard:** `DailyPnL_Meter`, `Drawdown_Gauge`, `Position_Size_Calc`, `ATR_Dollar_Risk`
**Session Reference:** `RTH_VWAP_Dynamic`, `Opening_Range_30min`, `Prior_Day_Levels`, `Daily_Pivots`
**Scan Tools:** `Regime_Scanner`, `STC_Oversold_Scan`, `STC_Overbought_Scan`

---

## § 1.13 — Dashboard Architecture

### Technology
- **Framework:** Next.js 15 (App Router) — confirmed version
- **Port:** 3010 (fallback to 3000)
- **Design system:** Dark terminal aesthetic — navy/cyan, monospace fonts
- **Components:** 132 React components in `dashboard/components/`

### Pages (14 routes)
| Route | Primary Purpose | Key Widgets |
|-------|----------------|-------------|
| `/` | **Home — overview** | KillSwitch, PositionsPanel, AgentFeed, SentimentPanel, PerformancePanel, WatchlistBar, PaperTradingPanel, TradeHistory, DailyPnlPanel, RegimeDisplay, MTFConfirmationWidget, SignalHistory, CircuitBreakerPanel, IBGatewayStatus, StrategyParamsPanel, SessionTodayWidget |
| `/analysis` | Pipeline runner | Inline all-stage expandable pipeline |
| `/paper` | Paper trading | OpenPositionsWidget, RiskStatusWidget, CircuitBreakerPanel, signals, regime, decisions |
| `/performance` | Performance analytics | AccountROIWidget, DailyPnLCalendarWidget, EquityCurveWidget, DrawdownChartWidget, WinRateBySymbolWidget, TradeHistory |
| `/scorecard` | Go-live readiness | LiveReadinessWidget, RollingPerformanceCard, PaperBalanceWidget, BacktestCompareWidget, DrawdownChartWidget, EquityCurveWidget |
| `/validation` | WFE validation | Pipeline history, sizing, reconciliation, export, go-live checklist |
| `/health` | System ops | PreFlightWidget, AgentPipelineStatusWidget, alerts, DatabaseStatsCard, EngineUptimeCard, IBGatewayStatus |
| `/settings` | Risk config | RiskSettingsWidget, WhatsAppStatusCard, PositionSizerWidget, RiskConfigDisplayWidget |
| `/watchlist` | Symbol scanning | WatchlistScanWidget, SymbolSignalWidget, VIXRegimeCard, MarketSessionWidget, SymbolPerformanceWidget |
| `/journal` | Trading journal | TodaySessionWidget, JournalStatsWidget, PipelineDecisionsWidget, TradeHistory |
| `/backtest` | Backtest research | BacktestCompareWidget, BacktestMetricsWidget, SignalAccuracyWidget |
| `/command-center` | **Iron Man HUD** | Full single-view command center (new v2.7) |
| `/stats` | Stats placeholder | Coming soon |

### UI Thresholds (v2.7 Canonical — update all hardcoded values)
| Widget | Old Value | Canonical v2.7 Value |
|--------|-----------|---------------------|
| LiveReadinessWidget — PF | ≥ 2.0 (paper target) | ≥ 1.5 (paper) / ≥ 2.0 (live gate) |
| LiveReadinessWidget — Sharpe | ≥ 1.5 | ≥ 1.0 (paper) / ≥ 1.5 (live gate) |
| LiveReadinessWidget — WR | ≥ 55% | ≥ 45% (paper) / ≥ 50% (live gate) |
| LiveReadinessWidget — Trades | ≥ 60 | ≥ 60 trades over 60+ days |
| LiveReadinessWidget — DD | ≤ 15% | ≤ 10% (paper) / ≤ 8% (live gate) |
| BacktestCompareWidget — MCL WFE | (none or old) | **0.82** |
| BacktestCompareWidget — MNQ WFE | (none or old) | **0.57** |
| MGC status indicator | ACTIVE | **HALTED** |
| MCL status indicator | DO NOT TRADE | **APPROVED** |

### Badge System
| Badge | Color | Meaning |
|-------|-------|---------|
| bull | Green | Bullish signal, positive trend |
| bear | Red | Bearish signal, negative trend |
| warn | Yellow/Orange | Warning state, approaching limit |
| info | Blue | Informational, neutral status |
| neutral | Gray | No signal, holding |

### Component Inventory (Key Components)
**Trading Core:** KillSwitch, CircuitBreakerPanel, SafetyLayer, OpenPositionsWidget, PositionSizerWidget, PositionsPanel
**Signals:** CurrentSignalWidget, RegimeDisplay, MarketRegimeWidget, MTFConfirmationWidget, SignalHistory, RecentSignalsWidget
**Performance:** EquityCurveWidget, DrawdownChartWidget, DailyPnLCalendarWidget, WinRateBySymbolWidget, AccountROIWidget, SharpeRatioWidget, ProfitFactorWidget
**Pipeline:** AgentFeed, AgentPipelineStatusWidget, PipelineStatusWidget, PipelineRunHistory, PipelineDecisionsWidget
**System:** IBGatewayStatus, DatabaseStatusWidget, EngineUptimeCard, PreFlightWidget, WhatsAppStatusCard
**Market:** MarketSessionWidget, VIXRegimeCard, WatchlistBar, WatchlistScanWidget, SymbolSignalWidget
**Options (new):** *(TODO: add options panel widget)*

---

## § 1.14 — Infrastructure

### Database Schema

**SQLite (primary — `engine/data/jarvis_trader.db`)**
| Table | Purpose | Key Fields |
|-------|---------|------------|
| `trades` | Paper trade log | id, symbol, action, entry_price, exit_price, qty, pnl, entry_time, exit_time |
| `decisions` | Pipeline decision log | id, timestamp, symbol, action, confidence, source, summary |
| `daily_pnl` | Daily P&L tracking | id, date, pnl, equity, drawdown_pct |
| `portfolio_snapshots` | Portfolio state history | id, timestamp, total_equity, positions_json |
| `alerts` | Alert history | id, timestamp, type, message, sent_to_whatsapp |
| `journal` | Trading journal entries | id, date, content, tags |

**SQLite (options — `engine/db/options_positions.db`) — new v2.7**
| Table | Purpose |
|-------|---------|
| `options_positions` | Active + closed options positions with Greeks |

**PostgreSQL (Docker — extended analytics)**
| Table | Purpose |
|-------|---------|
| `performance_metrics` | Extended performance analytics |
| `walk_forward_results` | WFE history |
| `monte_carlo_runs` | MC simulation results |
| `regime_history` | RegimeClassifier state history |
| `signal_accuracy` | Signal accuracy tracking |
| `backtest_runs` | Full backtest metadata |

### Prometheus Metrics (10 custom)
| Metric | Type | Description |
|--------|------|-------------|
| `jarvis_trades_total` | Counter | Total trades executed |
| `jarvis_pnl_dollars` | Gauge | Current paper P&L in dollars |
| `jarvis_drawdown_pct` | Gauge | Current drawdown percentage |
| `jarvis_kill_switch_active` | Gauge | 1 if active, 0 if off |
| `jarvis_pipeline_runs_total` | Counter | Total pipeline runs |
| `jarvis_signal_confidence_avg` | Gauge | Average signal confidence |
| `jarvis_engine_uptime_seconds` | Gauge | Engine uptime |
| `jarvis_whatsapp_alerts_total` | Counter | WhatsApp alerts sent |
| `jarvis_consecutive_losses` | Gauge | Current consecutive loss count |
| `jarvis_margin_used_pct` | Gauge | Margin utilization % |

### Docker Compose Services
| Service | Image | Port | Purpose |
|---------|-------|------|---------|
| questdb | questdb/questdb | 9000 | Time-series data |
| postgres | postgres:15 | 5432 | Analytics DB |
| redis | redis:7 | 6379 | Caching/rate limiting |
| grafana | grafana/grafana | 3001 | Metrics dashboard |

### Health Monitor
- Polls `GET /health` every 60 seconds (SO-1)
- Sends WhatsApp via `POST /notifications/whatsapp/test` when engine down
- Recovery detection: status returns to "online"
- Log location: `engine/logs/jarvis.log` (rotating, 10MB, 5 backups)

### LLM Client
- Provider: Anthropic (Claude models)
- Config: `ANTHROPIC_API_KEY` in environment
- Retry: Exponential backoff on rate limits
- Fallback: Haiku → Sonnet → Opus escalation
- Cost tracking: `GET /llm/stats` for session costs
- Model assignments: Stage 1-4 agents = Sonnet/Haiku; Fund Manager = Opus

### PM2 Process Management
```bash
pm2 start jarvis-trader    # Start engine
pm2 restart jarvis-trader  # Restart
pm2 stop jarvis-trader     # Stop
pm2 logs jarvis-trader     # View logs
pm2 list                   # Status
```

---

## § 1.15 — Options Trading System

### Current Status (v2.7)
Options engine is **BUILT** as of 2026-03-30. Code exists in `engine/options/`. API endpoints PENDING wire-up to `engine/main.py`.

Phase 2 paper trading: Options integration available for testing. Not yet automated in pipeline.

### Strategy Playbooks

#### A. Covered Calls on Futures (MES/MNQ)
| Parameter | Value |
|-----------|-------|
| Entry condition | Own 1 micro futures contract |
| Short strike | 0.30 delta OTM call, 1.0-1.5 ATR above price |
| Expiration | 7-14 DTE (weeklies preferred) |
| Exit — profit | Let expire worthless; keep premium |
| Exit — roll | Short delta reaches 0.10 → roll up |
| Exit — futures | Underlying hits T1 target → close call |
| Greeks target | Theta > $0.50/day; IV Rank > 30% |
| Risk | Capped upside above strike; full downside on futures |

#### B. Credit Spreads (Bull Put / Bear Call)
| Parameter | Bull Put Spread | Bear Call Spread |
|-----------|----------------|-----------------|
| Direction | Bullish/neutral | Bearish/neutral |
| Short leg | 0.30 delta put | 0.30 delta call |
| Long leg | 2-3 strikes lower | 2-3 strikes higher |
| Width | $5-10 (MES), $10-25 (MNQ) | Same |
| Max risk | Width - premium received | Same |
| DTE | 30-45 days | Same |
| Manage at | 21 DTE | Same |
| Target | 50% of max profit → close | Same |
| Stop | 2× premium received (loss = 1× premium) | Same |
| IV Rank | > 30% to sell premium | Same |

#### C. Iron Condors (Range-Bound Markets)
| Parameter | Value |
|-----------|-------|
| Structure | Bull put spread + Bear call spread |
| Short strikes | 0.16 delta each side (1 standard deviation) |
| Wing width | $5-10 |
| Entry regime | **RANGING only** (RegimeClassifier RANGING state) |
| VIX regime | NORMAL (16-20) or ELEVATED (20-25) ONLY |
| BLOCKED in | HIGH (>25) or EXTREME (>30) VIX — gap risk |
| Target | 50% of max profit → close |
| Adjustment | If short delta > 0.30 → roll tested side out and up/down |

#### D. Protective Puts (Portfolio Hedge)
| Parameter | Value |
|-----------|-------|
| Strike | 0.20 delta OTM put on MES/MNQ |
| Duration | 30-60 DTE |
| Entry trigger | VIX enters ELEVATED (>20) AND regime = VOLATILE |
| Budget | Max 0.5% portfolio value per month |
| Exit — bullish | VIX drops below 16 (LOW regime) |
| Exit — loss | 80% loss of premium |

#### E. Straddles/Strangles (Pre-Event)
| Parameter | Value |
|-----------|-------|
| Structure | 1 ATM call + 1 ATM put, same expiry (straddle) |
| Entry timing | 1-2 days before FOMC/CPI/NFP |
| Exit timing | First 30 minutes after release (IV crush momentum) |
| Max risk | Total premium paid |
| Target | 1.5× premium paid |
| Event calendar | Only events listed in `engine/news_blackout.py` |

### Options Engine Files (New v2.7)
| File | Contents |
|------|----------|
| `engine/options/greeks_monitor.py` | Black-Scholes Greeks (`calculate_greeks`), Newton-Raphson IV solver, `iv_rank()`, `iv_percentile()`, `PortfolioGreeks` dataclass, `GreeksMonitor` class with 0.30 delta breach alerts |
| `engine/options/strategy_executor.py` | `OptionsStrategy` enum (7 types), `OptionsOrder` + `OptionsLeg` dataclasses, 7 strategy builders, `validate_order()` with full regime rules |
| `engine/options/chain_fetcher.py` | `OptionsChain` + `OptionsContract` dataclasses, `fetch_chain_yfinance()`, `filter_by_delta()`, `find_strike_by_delta()`, `get_iv_rank()` |
| `engine/options/premium_calculator.py` | `black_scholes_price()`, `probability_of_profit()`, `expected_value()`, `get_credit_spread_metrics()`, PnL scenarios |
| `engine/options/position_manager.py` | `OptionsPosition` dataclass, `OptionsPositionManager` with SQLite persistence (WAL mode), `check_roll_candidates()`, `get_portfolio_greeks()` |

### Options API Endpoints (Pending Wire-Up)
| Method | Endpoint | Function |
|--------|----------|---------|
| GET | `/options/chain/{symbol}` | Fetch options chain with live Greeks |
| GET | `/options/positions` | Current options positions |
| POST | `/options/trade` | Paper trade an options strategy |
| GET | `/options/greeks` | Portfolio-level Greeks summary (delta, gamma, theta, vega) |
| POST | `/options/scan` | Scan for high IV rank opportunities |

### VIX as IV Proxy (Current Engine)
Until live options chain integration is complete, VIX serves as IV regime proxy:
| VIX | Regime | Options Guidance |
|-----|--------|-----------------|
| < 12 | VERY_LOW | Cheap options — long spreads favored |
| 12–16 | LOW | Standard IV — all strategies viable |
| 16–20 | NORMAL | Iron condors viable |
| 20–25 | ELEVATED | Premium selling favorable |
| 25–30 | HIGH | High risk — buy straddles; avoid condors |
| > 30 | EXTREME | Defined-risk only |

---

## § 1.16 — Futures Strategies (Detailed)

### MES — Micro E-mini S&P 500
| Parameter | Value |
|-----------|-------|
| Contract | /MES (CME) |
| Multiplier | $5.00 per point |
| Min tick | 0.25 pts = $1.25 |
| Margin (approx) | $1,600 paper / $640 retail |
| WFE | 0.09 — OVERFIT — NOT CLEARED |
| Status | Signal redesign required |
| ATR character | Moderate trend, high correlation with Nasdaq |
| Regime behavior | Responds to macro regime (Fed, rates) |
| STC notes | Over-optimized in current backtest period. MES/SPY too correlated to differentiate |
| Overnight | Do NOT hold overnight (Matt's rule) |
| Phase 3 target | 1 MES contract for live phase launch (June 2026+) |

### MNQ — Micro E-mini Nasdaq-100
| Parameter | Value |
|-----------|-------|
| Contract | /MNQ (CME) |
| Multiplier | $2.00 per point |
| Min tick | 0.25 pts = $0.50 |
| Margin (approx) | $2,200 paper / $880 retail |
| WFE | **0.57 — GOOD — APPROVED** |
| Status | ✅ Active paper trading |
| Config | Adaptive regime ON; MTF OFF; Volume OFF |
| ATR character | High volatility; large daily ranges ($300-800+) |
| Regime behavior | Tech-sector driven; responds to earnings, FOMC, CPI |
| STC notes | Adaptive regime critical — STC_OB=92 filters high-frequency noise |
| Key risk | Volume filter and MTF filter are CONFIRMED to degrade performance |

### MCL — Micro Crude Oil
| Parameter | Value |
|-----------|-------|
| Contract | /MCL (CME Globex) |
| Multiplier | $100 per point (1,000 barrels × $0.10 tick = $1 per tick) |
| Min tick | $0.01/bbl = $1.00 per contract |
| Margin (approx) | $900 paper / $360 retail |
| WFE | **0.82 — EXCELLENT — APPROVED** |
| Status | ✅ Active paper trading |
| Config | Static params; regime_filter ON; adaptive OFF |
| ATR character | Mean-reverting; $1-3 daily range typical |
| Regime behavior | Oil tends to regress to mean after spikes; STC crossover captures pullbacks |
| Key insight | Static params outperform adaptive — oil regime transitions too noisy for classifier |
| Geopolitical risk | Oil sensitive to OPEC decisions, Middle East events — check news before trading |

### MGC — Micro Gold
| Parameter | Value |
|-----------|-------|
| Contract | /MGC (CME) |
| Multiplier | $10 per point (10 oz × $1/oz) |
| Min tick | $0.10/oz = $1.00 per contract |
| Margin (approx) | $1,200 paper / $480 retail |
| WFE | 0.14 — OVERFIT — HALTED |
| Status | 🛑 Suspended indefinitely |
| History | WFE=0.88 was 3-window small-sample artifact (2025 gold bull run bias) |
| Re-evaluation | Requires new signal layer + 24 months data (include 2022 bear market) |
| ATR character | Trending instrument; gold follows macro/safe-haven flows |
| STC notes | STC works well in trending environments; FAILS in ranging. Gold spent 2022-2023 ranging. |

### M2K — Micro Russell 2000
| Parameter | Value |
|-----------|-------|
| Contract | /M2K (CME) |
| Multiplier | $5 per point |
| Status | NOT TESTED — not in current instrument list |
| STC assessment | High beta, mean-reversion mismatch for STC trend-following |
| Recommendation | Full walk-forward required before consideration |

---

## § 1.17 — Go-Live Validation Checklist (CANONICAL)

*All conflicting thresholds from earlier versions are superseded by these definitions.*

### Paper Trading Gate (Phase 2 → Phase 3)
| Metric | CANONICAL Threshold | Previously Conflicting Values |
|--------|---------------------|-------------------------------|
| Profit Factor | ≥ 1.5 | Was: 3.0, 5.27 |
| Sharpe Ratio | ≥ 1.0 | Was: 1.5, 4.16 |
| Win Rate | ≥ 45% | Was: 28%, 50%, 55% |
| Min trades | 60+ over 60+ days | Was: 40 |
| Max drawdown | < 10% | Was: 8%, 15% |
| Min days | 60 consecutive trading days | Was: 30 |

### Live Trading Gate (Phase 3 Minimum)
| Metric | Threshold |
|--------|-----------|
| Profit Factor | ≥ 2.0 |
| Sharpe Ratio | ≥ 1.5 |
| Win Rate | ≥ 50% |
| Max drawdown | < 8% |

### System Readiness Gate
- [ ] WhatsApp alerts: ≥ 5 successful SO-4 dispatches with Twilio SIDs logged
- [ ] IB Gateway paper port (4002) tested and connected
- [ ] Kill switch: manual activate AND deactivate tested successfully
- [ ] Engine stable: No EP-3 events in final 2 weeks
- [ ] Liberation Day rule respected throughout paper period
- [ ] No kill switch breach from sizing error (market-driven halts acceptable)
- [ ] SO-5 activation confirmed (sets require_human_approval: false) — Tier 3

### MaxDD Threshold Resolution
| Context | Threshold | Rationale |
|---------|-----------|-----------|
| SafetyLayer circuit breaker | -10.0% | Hardcoded in Python |
| Paper gate (warning) | -8.0% (T-9 fires) | Early warning before circuit breaker |
| Paper graduation requirement | < 10% | Must not have breached |
| Live gate | < 8% | Tighter for real capital |
| Liberation Day reference | -8.3% | April 2025 stress event (actual max DD) |

---

## § 1.18 — Session History & Decision Log

### Version History
| Version | Date | Key Change | Status |
|---------|------|-----------|--------|
| v1.0 | 2026-01 | Initial backtest (MES 1h): PF 5.27, Sharpe 4.16, WFE not yet calculated | Historical |
| v2.0 | 2026-02 | Walk-forward completed for all 5 instruments — all FAIL except MGC | Historical |
| v2.1 | 2026-02 | Adaptive regime implemented — MNQ WFE 0.24→0.34, MGC 0.27→0.88 | Historical |
| v2.2 | 2026-02 | MGC paper trading started (WFE=0.88 EXCELLENT at the time) | Historical |
| v2.3 | 2026-02 | Volume filter tested on MNQ — WFE -0.80 degradation, rejected | Historical |
| v2.4 | 2026-03 | Extended MGC history (15 windows) — WFE 0.88→0.27 (small sample bias exposed) | Historical |
| v2.5 | 2026-03 | SPY/MES re-optimized — better PF but WFE still negative | Historical |
| v2.6 | 2026-03-29 | CRITICAL: Optimizer kwarg bug found and fixed. MGC halted (0.27→0.14), MNQ improved (0.34→0.48) | Historical |
| **v2.7** | **2026-03-30** | **MCL confirmed WFE=0.82, MNQ confirmed WFE=0.57. Both approved. MTF filter rejected.** | **CURRENT** |

### Session Timeline (Compressed)
| Session | Focus | Outcome |
|---------|-------|---------|
| Session 1 | Engine setup, FastAPI + Next.js dashboard | Functional system built |
| Session 2 | Strategy backtesting — MES 1h optimizer | PF 5.27 (in-sample) |
| Session 3 | Walk-forward validation for all instruments | All failed except MGC |
| Session 4 | Adaptive regime, MCL/MNQ optimization | MGC approved (turned out to be overfit) |
| Session 5 | Dashboard build, API validation, bug fixes | 23 API corrections, v2.6 optimizer bug |
| **Session 6** | **MCL/MNQ final validation, options engine, master doc** | **v2.7 — MCL + MNQ approved** |

### Critical Decisions Made (Chronological)
| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-02 | Use STC + ATR as primary strategy | Grid search confirmed best IS performance |
| 2026-02 | RegimeClassifier for Layers 1-5 | Reduces false signals in choppy markets |
| 2026-03 | Reject volume filter for all 1h futures | WFE degradation confirmed empirically |
| 2026-03 | Reject MTF filter for MNQ | WFE 0.57→0.17 degradation confirmed |
| 2026-03-29 | Fix optimizer kwarg bug | Silenced TypeError causing all None WFE returns |
| 2026-03-30 | Approve MCL + MNQ for paper trading | WFE thresholds exceeded post-bugfix |
| 2026-03-30 | Build options engine (greeks_monitor, strategy_executor, etc.) | Phase 3 preparation |

---

## § 1.19 — Known Issues & Pending Work

### Open Issues
| Priority | Issue | Impact | Status |
|----------|-------|--------|--------|
| HIGH | FRED API key not configured | `/macro/snapshot` returns 422; VIX from manual proxy only | Pending |
| HIGH | Options endpoints not wired into main.py | 5 new `/options/*` routes exist as code but not registered | Pending |
| MEDIUM | Yahoo Finance rate limiting | `ES=F` data unavailable; MES 2025 uses SPY-return proxy | Known limitation |
| MEDIUM | IB paper port 4002 requires TWS running | IBKR not connected — `ibkr_connected: false` | Phase 3 gap |
| MEDIUM | `EmailIntelligenceAgent.analyze_recent_emails` missing | Referenced in pipeline but method not implemented | Pending |
| MEDIUM | API keys in git history | Security risk — requires git history rewrite | Planned remediation |
| LOW | Zero agent unit tests | Any refactoring could break agents silently | Sprint 7 item |
| LOW | No CI/CD pipeline | Manual deployments only | Sprint 7 item |
| LOW | `/alerts/active` returns 404 | Dashboard falls back gracefully | Minor |
| LOW | `api-reference.md` outdated | 14+ corrections needed vs live engine | Documented |
| INFO | SPY 1h walk-forward not re-run post-bugfix | WFE may improve; worth running | Backlog |
| INFO | MGC needs 24-month data before reconsideration | Extended history + bear market validation | Long-term |

### Pending Development
- [ ] Wire 5 options endpoints into `engine/main.py`
- [ ] Configure FRED_API_KEY (VIX + yield data)
- [ ] IB Gateway TWS setup for paper port 4002
- [ ] Dashboard `/command-center` page (Iron Man HUD)
- [ ] Rolling WFE recalculation job (4-week cadence)
- [ ] Options panel widget in dashboard
- [ ] Unit tests for agent pipeline (0% coverage currently)
- [ ] CI/CD setup (GitHub Actions)

---

## § 1.20 — File Reference

### Authoritative Files (Current)
| File | Path | Authority |
|------|------|-----------|
| **JARVIS_TRADER_MASTER.md** | `./JARVIS_TRADER_MASTER.md` | **ONE SOURCE OF TRUTH** |
| Executive Briefing | `engine/backtest/results/EXECUTIVE_BRIEFING.md` | Strategy results v2.7 |
| Paper Approval | `PAPER_TRADING_APPROVAL.md` | Paper trading status |
| Daily Routine | `TRADING_DAILY_ROUTINE.md` | API reference + daily schedule |
| Paper Config | `engine/backtest/paper_config.py` | MCL_PAPER_CONFIG, MNQ_PAPER_CONFIG |
| Signals | `engine/backtest/signals.py` | INSTRUMENT_PARAMS (canonical) |
| Walk-Forward | `engine/backtest/walk_forward.py` | WFE calculation |
| MCL Setup | `engine/paper/MCL_paper_setup.md` | MCL paper trading setup |
| MNQ Setup | `engine/paper/MNQ_paper_setup.md` | MNQ paper trading setup |
| MEMORY.md | `~/.claude/projects/.../memory/MEMORY.md` | Cross-session context |

### Historical Files (Keep — Do Not Delete)
| File | Notes |
|------|-------|
| `jarvis-trader-dashboard-session5-log.md` | Session 5 work log |
| `JARVIS_TRADER_SESSION_LOG_2026-03-30.md` | Session 6 work log |
| `Jarvis_Trader_Agent_Master_Claude_Code_Session.md` | Master session doc |
| `jarvis-trader-skill-project-log.md` | Skill project log |
| `docs/JARVIS_TRADER_UNIFIED_CANON.md` | Prior canonical doc (superseded by this file) |
| `docs/CANON_SOURCE_MAP.json` | Provenance map |
| `engine/backtest/results/SUMMARY.md` | Backtest summary table |
| All plan files in `~/.claude/plans/` | Historical plans |

### Do Not Use (Superseded)
| Old Reference | Replacement |
|--------------|-------------|
| VIX 4-tier or 5-tier scheme | § 1.7 canonical 6-tier |
| Win rate threshold 28% / 50% / 55% | § 1.17 canonical (45% paper, 50% live) |
| MGC "ACTIVE" status | MGC HALTED — § 1.5 |
| MCL "DO NOT TRADE" status | MCL APPROVED — § 1.5 |
| Next.js 14 references | Next.js 15 confirmed |
| MES backtest PF 5.27 as "current baseline" | Historical in-sample only — not walk-forward validated |
| MaxDD thresholds of 8% or 15% | § 1.17 canonical (-10% circuit, -8% live gate) |

---

## Appendix A — Pre-Market Brief Format (Canonical)

```
━━━ JARVIS TRADER — Pre-Market Brief | [DAY], [DATE] | 6:30am CT ━━━

SYSTEM: [ONLINE ✓ | OFFLINE ✗]
Kill Switch: [OFF ✓ | ACTIVE ⛔ — reason]
IBKR: [NOT CONNECTED (paper mode)] | Schwab: [NOT CONNECTED]
Engine uptime: [X hrs X min]

━━━ ACTIVE INSTRUMENTS (v2.7) ━━━
MCL 1h: WFE=0.82 ✅ APPROVED | Config: Static, regime_filter ON
MNQ 1h: WFE=0.57 ✅ APPROVED | Config: Adaptive regime, NO MTF, NO vol
MGC 1d: WFE=0.14 🛑 HALTED

━━━ MARKET SNAPSHOT (as of [TIME] CT) ━━━
| Symbol | Last Price | Prev Close | % Chg  |
|--------|------------|------------|--------|
| MES    | X,XXX.XX   | X,XXX.XX   | +/-X.X%|
| MNQ    | XX,XXX.XX  | XX,XXX.XX  | +/-X.X%|
| MCL    | XX.XX      | XX.XX      | +/-X.X%|

━━━ MACRO ━━━
VIX: X.X — [VERY_LOW/LOW/NORMAL/ELEVATED/HIGH/EXTREME] (6-tier canonical)
[FRED API key not configured — VIX from prices only]

━━━ PORTFOLIO ━━━
Equity: $X,XXX.XX | Daily P&L: $+/-X.XX ([+/-X.X%])
Drawdown: -X.X% (limit: -10.0%) | Consecutive losses: N

━━━ RISK STATUS ━━━
Daily P&L:  $+/-X.XX | Limit: -2.0%
Drawdown:   -X.X%    | Limit: -10.0%
Orders/min: N (halt at 11)
Liberation Day: [Active: N losses | Resolved]
[SAFE ✓ | WARNING ⚠ | HALTED ⛔]

━━━ PIPELINE ━━━
[Non-hold signals, or: "All HOLD"]
Scheduler: [RUNNING ✓ | STOPPED ✗] | Next: [TIME]

━━━ OPTIONS STATUS ━━━
Engine: BUILT (v2.7) | API: Pending wire-up
IV Proxy: VIX [X.X] — [NORMAL/ELEVATED/HIGH] regime
Positions: 0

Matt's prep window: 8:00–8:30am CT | No entries: 8:30–9:35am CT
Active: 9:35–11:30am + 1:00–3:30pm CT
```

---

## Appendix B — Conflict Resolution Table (Canonical)

| Topic | Prior Conflicting Values | CANONICAL v2.7 Resolution |
|-------|--------------------------|---------------------------|
| VIX regime tiers | 4-tier, 5-tier, 6-tier | **§ 1.7 — 6-tier** |
| Win rate threshold (paper) | 28%, 45%, 50%, 55% | **§ 1.17 — 45%** |
| Win rate threshold (live gate) | Various | **§ 1.17 — 50%** |
| Next.js version | 14, 15 | **Next.js 15 confirmed** |
| Min trade count | 40, 60 | **60 trades over 60+ days** |
| MaxDD paper circuit | 8%, 10%, 15% | **SafetyLayer: -10.0%** |
| MaxDD live gate | 8%, 10% | **§ 1.17 — 8%** |
| MES T1 ATR | 1.00, 1.50, 2.00 | **§ 1.2 — 2.00 (per INSTRUMENT_PARAMS)** |
| Win rate discrepancies | 36%, 47%, 60%, 67% | **MCL: 60%, MNQ: 47.7%, old 36% was IS estimate** |
| MGC paper status | ACTIVE, CAUTION, HALTED | **§ 1.5 — HALTED (WFE=0.14)** |
| MCL paper status | DO NOT TRADE, APPROVED | **§ 1.5 — APPROVED (WFE=0.82)** |
| Backtest baseline (MES IS) | PF 5.27, Sharpe 4.16 | **Historical in-sample only — not WFE validated** |
| Profit factor paper gate | 1.5, 2.0, 3.0 | **§ 1.17 — 1.5 (paper), 2.0 (live gate)** |
| Sharpe paper gate | 1.0, 1.5 | **§ 1.17 — 1.0 (paper), 1.5 (live gate)** |

---

## Appendix C — Data Sources

| Source | Data Provided | Config | Status |
|--------|--------------|--------|--------|
| yfinance | OHLCV bars (SPY, MES, MNQ, MCL) | No key needed | ⚠️ Rate limited — use cache |
| Finnhub | News headlines, earnings calendar | `FINNHUB_API_KEY` | Configured |
| ApeWisdom/Reddit | Social sentiment | No key | Working |
| StockTwits | Social sentiment | `STOCKTWITS_API_KEY` | Optional |
| FRED | VIX, yields, DXY, macro | `FRED_API_KEY` | ❌ NOT CONFIGURED |
| IB Gateway | Order execution (Phase 3+) | Paper: port 4002 | Not connected |
| Twilio | WhatsApp alerts | `TWILIO_*` | Configured |
| Anthropic | LLM pipeline | `ANTHROPIC_API_KEY` | Configured |

---

*JARVIS_TRADER_MASTER.md | Version 2.7 | 2026-03-30 | Single Source of Truth*
*Author: JARVIS (Claude) + Matt Morrison | All data validated against live engine*
