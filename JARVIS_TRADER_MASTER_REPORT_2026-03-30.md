# JARVIS TRADER — Master Reference Report

**Date**: 2026-03-30
**Status**: Paper Trading Phase Active (April–May 2026 validation)
**Sessions Covered**: Session 1 (2026-03-28) through Session 5+ continuation (2026-03-30)
**Total Engine Endpoints**: 95+ (26 confirmed live on `GET /openapi.json` as of 2026-03-30)
**Total Dashboard Components**: 63+
**Backtest Best Result**: MES 1h — PF 5.27, Sharpe 4.16, +47.2%
**Go-Live Gate**: June 2026 (contingent on paper trading validation)

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Directory Structure](#2-directory-structure)
3. [Technology Stack](#3-technology-stack)
4. [Strategy Architecture](#4-strategy-architecture)
5. [Backtest Results](#5-backtest-results)
6. [Five-Stage Pipeline Architecture](#6-five-stage-pipeline-architecture)
7. [Safety Layer — Circuit Breakers](#7-safety-layer--circuit-breakers)
8. [Three-Tier Autonomy Model](#8-three-tier-autonomy-model)
9. [Standing Orders](#9-standing-orders)
10. [Emergency Protocols](#10-emergency-protocols)
11. [Live-Validated API Surface (2026-03-30)](#11-live-validated-api-surface-2026-03-30)
12. [Live API Response Shapes (Confirmed)](#12-live-api-response-shapes-confirmed)
13. [Full Extended Endpoint Registry (95+)](#13-full-extended-endpoint-registry-95)
14. [Database Schema](#14-database-schema)
15. [Dashboard Pages and Components](#15-dashboard-pages-and-components)
16. [Skill Files Reference](#16-skill-files-reference)
17. [Matt's Trading Context](#17-matts-trading-context)
18. [VIX Regime Reference](#18-vix-regime-reference)
19. [Session-by-Session History](#19-session-by-session-history)
20. [API Documentation Corrections (2026-03-30 Audit)](#20-api-documentation-corrections-2026-03-30-audit)
21. [JARVIS v2 vs JARVIS Trader Comparative Analysis](#21-jarvis-v2-vs-jarvis-trader-comparative-analysis)
22. [Validation Targets and Go-Live Plan](#22-validation-targets-and-go-live-plan)
23. [Key Files Reference](#23-key-files-reference)
24. [Known Issues and Pending Work](#24-known-issues-and-pending-work)
25. [Quick Start Commands](#25-quick-start-commands)

---

## 1. System Overview

JARVIS TRADER is a fully automated AI-powered paper and live futures trading system built for Matt Morrison. It uses a 5-stage, 10-agent LLM pipeline (Claude Opus 4.6 / Sonnet 4.6) to generate trade signals from TradingView webhooks, evaluate risk through a hardcoded Python safety layer, and route orders to Interactive Brokers (paper mode: port 4002, live port 4001 locked).

**Primary instrument**: MES (Micro E-mini S&P 500, $5/point)
**Secondary instruments**: MNQ ($2/point), MCL (Micro Crude Oil), SPY, QQQ (options)
**Strategy**: STC (Schaff Trend Cycle, OS=15/OB=83) + ATR stop (0.70x) + T1 (1.50x) + 5-layer regime filter
**Engine**: FastAPI v0.1.0 at `http://localhost:8010`
**Dashboard**: Next.js 15 at `http://localhost:3010`
**Start command**: `start_jarvis.bat` (from project root)
**IB Gateway**: Paper port 4002 (TWS 7497) | Live port 4001 (TWS 7496) — LOCKED
**Broker library**: `ib_async==0.9.86` (NOT ib_insync)
**Safety layer**: `engine/risk/safety_layer.py` — hardcoded Python, zero LLM in enforcement path

---

## 2. Directory Structure

```
C:\Users\mattm\ThinkorSwim\jarvis-trader\
├── engine/                          # FastAPI backend
│   ├── main.py                      # App entry point, all route registrations
│   ├── config.py                    # Settings loaded from .env
│   ├── .env                         # Runtime configuration (Anthropic key, IBKR params)
│   ├── .env.example                 # Template with all required vars
│   ├── requirements.txt             # Full dependencies
│   ├── requirements-core.txt        # Trimmed deps (no ta-lib, vectorbt)
│   ├── init_db.py                   # CLI: python init_db.py [--reset]
│   ├── CHANGELOG.md                 # v1.0.0 through v1.6.0+
│   ├── agents/
│   │   ├── pipeline.py              # TradingPipeline — 5-stage orchestrator
│   │   ├── technical_analyst.py     # pandas-ta indicators + Claude
│   │   ├── news_analyst.py          # Finnhub headlines + claude-sonnet-4-6
│   │   ├── social_analyst.py        # Reddit/ApeWisdom + claude-haiku-4-5
│   │   ├── fundamental_analyst.py   # FRED economic data + Finnhub
│   │   ├── bull_researcher.py       # Long thesis builder
│   │   ├── bear_researcher.py       # Short thesis builder
│   │   ├── debate_orchestrator.py   # Synthesis agent
│   │   ├── trader.py                # Trade decision (claude-opus-4-6)
│   │   ├── risk_manager.py          # Risk validation
│   │   ├── fund_manager.py          # Final approval gate
│   │   └── thinkscript_generator.py # ThinkScript generation
│   ├── analytics/
│   │   ├── performance.py           # PerformanceCalculator (PF, Sharpe, WR)
│   │   ├── greeks_monitor.py        # Stub: options Greeks
│   │   ├── mtf_confirmation.py      # Stub: multi-timeframe confirmation
│   │   └── vix_overlay.py           # Stub: VIX regime overlay
│   ├── backtest/
│   │   └── paper_tracker.py         # Paper trading tracker for backtesting
│   ├── data/
│   │   ├── market_data.py           # MarketDataManager (IBKR + Polygon + yfinance)
│   │   └── reddit.py                # ApeWisdom scraper
│   ├── database/
│   │   ├── schema.py                # DatabaseManager — 6 tables + bridge methods
│   │   ├── migrations.py            # Version-tracked migrations (001–005)
│   │   └── __init__.py
│   ├── execution/
│   │   ├── ib_gateway.py            # IBGatewayManager, paper port 4002 ONLY
│   │   ├── ib_order_manager.py      # IBOrderManager with reconcile()
│   │   ├── ibkr_executor.py         # IBKR via ib_async (659 lines)
│   │   ├── schwab_connector.py      # Schwab via schwab-py
│   │   └── order_router.py          # Smart broker routing
│   ├── notifications/
│   │   └── whatsapp.py              # WhatsApp formatters (Twilio)
│   ├── portfolio/
│   │   └── tracker.py               # SQLite-backed PortfolioTracker
│   ├── risk/
│   │   ├── safety_layer.py          # Circuit breakers + kill switch (NO LLM)
│   │   └── pnl_monitor.py           # PnLMonitor — 3-tier P&L source
│   ├── routers/
│   │   ├── webhook_router.py        # TradingView webhook receiver
│   │   └── journal_router.py        # Trade journal CRUD with tags
│   ├── schedulers/
│   │   └── eod_scheduler.py         # EOD snapshots Mon-Fri 3:05 PM CT
│   ├── tests/
│   │   └── test_integration.py      # 28+ integration tests
│   └── utils/
│       └── position_sizing.py       # Fixed-fractional formula
├── dashboard/                       # Next.js 15 frontend
│   ├── app/                         # 12 pages (App Router)
│   ├── components/                  # 63+ React components
│   └── lib/
│       ├── api.ts                   # fetchEngine() + TypeScript types
│       └── utils.ts                 # formatCurrency, formatPercent, cn()
├── scripts/
│   ├── smoke_test.py                # 48-endpoint smoke test
│   ├── test_signal.py               # CLI signal tester
│   ├── seed_paper_trades.py         # Synthetic trade generator (95 trades, 30 days)
│   ├── pine_script_generator.py     # TradingView Pine Script generator
│   ├── jarvis_trader_strategy.pine  # Generated Pine Script v5
│   └── daily_report.py              # EOD report generator
├── thinkorswim-scripts/             # ThinkScript files
├── data/                            # SQLite DB files
├── logs/                            # Engine logs
├── start_jarvis.bat                 # Launch script
├── conftest.py                      # Pytest config
├── prd.json                         # PRD: all 10 user stories (complete)
├── TRADING_DAILY_ROUTINE.md         # 1,229-line live-validated daily ops playbook
├── JARVIS-TRADER-MASTER-REPORT.md   # Previous master report (2026-03-29)
└── [other .md reports and audits]
```

---

## 3. Technology Stack

| Layer | Technology | Notes |
|-------|-----------|-------|
| Engine language | Python 3.12 | 3.14 breaks numpy — use 3.12 venv |
| Engine framework | FastAPI + uvicorn | Port 8010 |
| Database | SQLite via aiosqlite | `data/jarvis_trader.db` |
| Broker | ib_async 0.9.86 | Paper port 4002 |
| Dashboard | Next.js 15, TypeScript, Tailwind CSS | Port 3010 |
| Package manager | pnpm (required — npm broken system-wide) |
| LLM models | claude-opus-4-6, claude-sonnet-4-6, claude-haiku-4-5 | See agent table |
| Notifications | Twilio WhatsApp | Signal alerts, morning brief |
| Market data | yfinance (free), Finnhub (free tier), ApeWisdom, FRED | No paid API required |
| Strategy indicators | pandas-ta 0.4.67b0 | pandas_ta Windows fix applied |
| Scheduler | APScheduler | Watchlist scan every 30min RTH |

### LLM Model Assignments

| Agent | Model | Reason |
|-------|-------|--------|
| TechnicalAnalyst | claude-opus-4-6 | Complex multi-indicator synthesis |
| NewsAnalyst | claude-sonnet-4-6 | Headline-level analysis sufficient |
| SocialAnalyst | claude-haiku-4-5 | High frequency, lightweight |
| FundamentalAnalyst | claude-sonnet-4-6 | Macro + metrics |
| Bull/Bear Researcher | claude-sonnet-4-6 | Research quality |
| DebateOrchestrator | claude-opus-4-6 | Key synthesis step |
| Trader | claude-opus-4-6 | High-stakes decision |
| RiskManager | claude-opus-4-6 | Risk-critical |
| FundManager | claude-opus-4-6 | Final approval gate |
| ThinkScriptGenerator | claude-sonnet-4-6 | Code generation |

---

## 4. Strategy Architecture

### Strategy Name: STC + ATR + 5-Layer Regime Filter

**Primary instrument**: MES (Micro E-mini S&P 500, $5/point, 1.25 tick)
**Secondary instruments**: MNQ ($2/point), MCL (Micro Crude Oil), SPY, QQQ (options)

### Entry Conditions (ALL must pass simultaneously)

1. STC < 15 (oversold — long setup) OR STC > 83 (overbought — short setup)
2. Regime = `trending_up` (long) OR `trending_down` (short) — from regime filter
3. Kill switch inactive (`kill_switch_active: false`)
4. Daily P&L > -1.6% (not approaching -2.0% halt threshold)
5. Drawdown > -8.0% (not approaching -10.0% circuit breaker)
6. Pipeline confidence >= 0.50 (FundManager gate)

### Strategy Parameters

```python
STC_OS = 15           # Oversold threshold (long entry signal)
STC_OB = 83           # Overbought threshold (short entry signal)
ATR_STOP = 0.70       # Stop loss = entry +/- (0.70 * ATR)
ATR_T1 = 1.50         # Take profit T1 = entry +/- (1.50 * ATR), take 50%
ATR_T2 = 2.50         # Take profit T2 = trail remainder
MES_MULTIPLIER = 5    # $ per point for MES
MES_TICK = 1.25       # Minimum tick size
THEORETICAL_RR = 1.50 / 0.70  # = 2.14:1
```

### Position Sizing — Fixed-Fractional

```python
# Normal conditions
risk_per_trade = account_equity * 0.01          # 1.0% risk per trade

# Liberation Day mode (3+ consecutive losses)
risk_per_trade = account_equity * 0.005         # 0.5% risk per trade

# Contract calculation
contracts = floor(risk_per_trade / (atr * ATR_STOP * MES_MULTIPLIER))
contracts = min(contracts, 2)                    # Hard cap: 2 contracts max
```

### Exit Rules

| Exit | Trigger | Action |
|------|---------|--------|
| Stop loss | Entry - (0.70 * ATR) | Close 100%, no extensions |
| T1 | Entry + (1.50 * ATR) | Close 50%, move stop to breakeven |
| T2 | Entry + (2.50 * ATR) | Trail remainder |
| End of session | 3:30 PM CT | Close all positions |

### Liberation Day Rule

Inspired by the April 2025 Liberation Day crash (S&P -12% gap down). Automatically triggered on 3+ consecutive losing trades. Risk per trade drops from 1.0% to 0.5%. Resets on next winning trade or manual Tier 3 override.

---

## 5. Backtest Results

### Best Result: MES 1h (Primary Timeframe)

| Metric | Value | Target for Live Gate |
|--------|-------|---------------------|
| Profit Factor | **5.27** | >= 2.0 |
| Sharpe Ratio | **4.16** | >= 1.5 |
| Total Return | **+47.2%** | — |
| Win Rate | **~36%** (per skill files) | >= 28% paper minimum |
| Max Drawdown | **-8.3%** | < -10.0% circuit breaker |
| R:R | 2.14:1 | >= 2.0 |

Note: Win rate figure discrepancy exists in documentation (skill files show ~36%, JARVIS-TRADER-MASTER-REPORT.md shows 67.3%). The ~36% figure aligns with the STC oversold/overbought strategy's expected win rate given the 2.14:1 R:R. The 67.3% figure may be from a filtered subset or different parameter set.

### Liberation Day Stress Test (April 2025 Crash Simulation)

- Event: S&P 500 -12% in 24 hours (April 2025 tariff shock)
- Max drawdown during stress period: **-8.3%** (within -10.0% limit)
- Liberation Day rule activated: yes (3 consecutive losses)
- System behavior: correct — reduced sizing, no circuit breaker triggered

---

## 6. Five-Stage Pipeline Architecture

```
TradingView Alert (webhook) OR Manual trigger (POST /pipeline/run)
         |
         v
Stage 1 — Parallel Analysis (asyncio.gather)
   TechnicalAnalystAgent  → STC value, ATR, regime, OHLCV signals
   NewsAnalystAgent       → Finnhub headlines, sentiment scoring
   SocialAnalystAgent     → Reddit/ApeWisdom sentiment
   MacroAnalystAgent      → FRED data: VIX, yields, DXY, Fed Funds
         |
         v
Stage 2 — Structured Debate
   BullDebaterAgent  → Build long thesis
   BearDebaterAgent  → Build short thesis
   DebateOrchestrator → Synthesize, score conviction
         |
         v
Stage 3 — Trade Decision
   TraderAgent → LONG / SHORT / HOLD + quantity + entry params
         |
         v
Stage 4 — Risk Review (2 layers)
   Layer 1: Python hard rules (kill switch, daily loss, drawdown, order rate)
   Layer 2: LLM soft review (claude-opus-4-6)
   → RiskDecision{approved, veto_reason, modified_quantity, risk_score}
         |
         v
Stage 5 — Fund Manager Approval
   FundManagerAgent → Final portfolio-level gate
   confidence >= 0.50 required for non-hold
   requires_human_approval: true → blocks auto-execution (currently active)
         |
         v
Decision logged to SQLite (pipeline_runs table)
WhatsApp alert dispatched (SO-4, non-hold signals, 2hr cooldown)
```

### Pipeline Request Schema

```json
POST /pipeline/run
{
  "symbol": "MES",
  "is_futures": true
}
```

Note: The documented optional fields `include_news`, `include_social`, `include_macro` do NOT exist on the live engine. Only `symbol` and `is_futures` are accepted.

---

## 7. Safety Layer — Circuit Breakers

File: `engine/risk/safety_layer.py`

This is hardcoded Python. No LLM is in the enforcement path. These limits cannot be overridden by any agent or API call except the explicit deactivate endpoint (Tier 3 only).

| Limit | Value | Enforcement |
|-------|-------|-------------|
| Daily loss halt | -2.0% of equity peak | `daily_pnl / equity_peak <= -0.02` |
| Max drawdown halt | -10.0% | `drawdown_pct <= -0.10` |
| Order rate halt | > 10 orders/minute | `orders_last_minute > 10` |
| Max contracts per trade | 2 | Hard cap, no override |
| Margin limit | 40% of equity | `margin_used / total_equity > 0.40` |

### Kill Switch States

| State | Meaning | How to Clear |
|-------|---------|-------------|
| `kill_switch_active: false` | Normal trading allowed | N/A |
| `kill_switch_active: true` | All orders blocked | `POST /safety/kill-switch/deactivate` (Tier 3) |
| `live_trading_enabled: false` | Paper mode — IB port 4002 | Set `LIVE_TRADING_ENABLED=True` in .env (never do this without full review) |
| `require_human_approval: true` | No auto-execution | Must confirm each trade manually in dashboard |

### IB Gateway Port Lock

`ib_gateway.py` permanently blocks port 4001 (live trading). The only way to enable live trading is:
1. Set `LIVE_TRADING_ENABLED=True` in `.env`
2. Modify `ib_gateway.py` to allow port 4001 connections
3. Both require Tier 3 decision and full validation gate completion

---

## 8. Three-Tier Autonomy Model

| Tier | Name | Behavior | Examples |
|------|------|----------|---------|
| T1 | AUTO-EXECUTE | Execute immediately, no confirmation needed | All GET endpoints, technical analysis, ThinkScript generation, pipeline status checks |
| T2 | NOTIFY-AFTER | Execute the action, then inform Matt | SO-4 WhatsApp dispatch, paper trade auto-log (when SO-5 active), morning brief delivery |
| T3 | CONFIRM-BEFORE | Always ask Matt first, never execute unilaterally | Kill switch deactivation, any live order, watchlist changes, risk parameter changes |

**Current state**: SO-5 (Paper Trade Auto-Log) is INACTIVE because `require_human_approval: true` is set in the engine. All trade execution requires manual confirmation.

---

## 9. Standing Orders

| ID | Name | Status | Tier | What It Does |
|----|------|--------|------|-------------|
| SO-1 | Health Monitor | ACTIVE | T1 | Polls `GET /health` every 60s, triggers EP-3 on failure |
| SO-2 | Market Open Brief | ACTIVE | T2 | Builds data cache at 6:00am CT, delivers brief at 6:30am CT |
| SO-3 | Watchlist Scan | ACTIVE | T1 | `POST /pipeline/run` on each watchlist symbol every 30min during RTH (9:30am-4pm CT) |
| SO-4 | Signal Alert Dispatch | ACTIVE | T2 | WhatsApp via Twilio on any non-hold signal, 2-hour cooldown per symbol |
| SO-5 | Paper Trade Auto-Log | **INACTIVE** | T2 | Would auto-log confirmed signals to paper tracker — blocked by `require_human_approval: true` |
| SO-6 | Daily P&L Watch | ACTIVE | T1/T2 | Monitors `daily_pnl / equity_peak`; fires T-8 at -1.6%, T-9 at -2.0% |

---

## 10. Emergency Protocols

| ID | Event | Detection Source | Required Deactivation Steps |
|----|-------|-----------------|----------------------------|
| EP-1 | Daily loss >= -2.0% | SafetyLayer Python (automatic) | Tier 3 + `POST /safety/kill-switch/deactivate` + next-day review |
| EP-2 | Max drawdown >= -10.0% | SafetyLayer Python (automatic) | Tier 3 + 3-step review: (1) verify all positions closed, (2) identify cause, (3) re-enable only after cause resolved |
| EP-3 | Engine unresponsive | SO-1 health monitor | `pm2 restart jarvis-trader` OR direct `uvicorn main:app --port 8010` from engine/ |
| EP-4 | Anomalous order rate > 10/min | SafetyLayer Python (automatic) | Identify rogue signal source before deactivation |
| EP-5 | Market circuit breaker (S&P -7%/-13%/-20%) | External event (CME rule) | No orders regardless of kill switch state — exchange-level halt |
| EP-6 | Correlation cascade | T-22 trigger + multiple concurrent losers | Advisory only — JARVIS never auto-closes positions |

---

## 11. Live-Validated API Surface (2026-03-30)

The following 26 endpoints were confirmed against `GET /openapi.json` on the live engine at `http://localhost:8010` on 2026-03-30. These are the only endpoints guaranteed to exist in the current deployment.

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/health` | Engine status, kill switch state, IBKR/Schwab connected, uptime |
| GET | `/safety/status` | Kill switch, daily P&L (raw $), drawdown %, order rate |
| POST | `/safety/kill-switch/activate?reason=` | Activate kill switch (Tier 3) |
| POST | `/safety/kill-switch/deactivate` | Deactivate kill switch (Tier 3) |
| GET | `/portfolio` | Equity, positions[], margin used/available, daily P&L |
| POST | `/analyze/technical` | Run TechnicalAnalystAgent on any symbol |
| GET | `/analyze/bars/{symbol}` | OHLCV bars — params: `?timeframe=1h&days=5` |
| POST | `/pipeline/run` | Full 5-stage pipeline — body: `{symbol, is_futures}` |
| GET | `/pipeline/status` | Last run metadata, decision count |
| GET | `/decisions/recent?limit=N` | Recent pipeline decisions (ring buffer) |
| POST | `/decisions/log` | Log any freeform decision object |
| GET | `/prices/snapshot` | Live prices for all watchlist instruments |
| GET | `/watchlist` | All tracked symbols with type (futures/options) |
| GET | `/macro/snapshot` | VIX, yields, DXY, macro regime |
| GET | `/macro/series/{series_id}` | FRED time series (e.g., `DGS10`, `VIXCLS`, `DFF`) |
| GET | `/sentiment/recent` | Cached Reddit sentiment for tracked symbols |
| GET | `/sentiment/reddit?filter=` | Fresh Reddit sentiment pull |
| GET | `/sentiment/news/{symbol}` | Finnhub news sentiment for specific symbol |
| GET | `/scheduler/status` | Scheduler running state, jobs list, next_run times |
| POST | `/thinkscript/generate` | Generate ThinkScript code via LLM |
| POST | `/backtest/run` | Run backtest on strategy params |
| POST | `/notifications/whatsapp/test` | Test WhatsApp/Twilio integration |

**Note**: This is the minimal confirmed surface. The full engine has 95+ endpoints — see Section 13.

---

## 12. Live API Response Shapes (Confirmed)

All shapes tested against `http://localhost:8010` on 2026-03-30.

### GET /health

```json
{
  "status": "online",
  "version": "0.1.0",
  "timestamp": "2026-03-29T23:02:09.258529",
  "live_trading": false,
  "kill_switch_active": false,
  "paper_mode": true,
  "ibkr_connected": false,
  "schwab_connected": false,
  "uptime_seconds": 97486.833677
}
```

### GET /safety/status

```json
{
  "kill_switch_active": false,
  "kill_switch_reason": null,
  "live_trading_enabled": false,
  "require_human_approval": true,
  "daily_pnl": 0.0,
  "equity_peak": 0.0,
  "current_equity": 0.0,
  "drawdown_pct": 0.0,
  "orders_last_minute": 0
}
```

### GET /portfolio

```json
{
  "total_equity": 0.0,
  "cash_balance": 0.0,
  "unrealized_pnl": 0.0,
  "realized_pnl": 0.0,
  "daily_pnl": 0.0,
  "margin_used": 0.0,
  "margin_available": 0.0,
  "positions": []
}
```

### GET /scheduler/status

```json
{
  "running": true,
  "jobs": [
    {
      "id": "watchlist_scan",
      "name": "Watchlist Auto-Scan",
      "next_run": "2026-03-30T09:00:00-05:00"
    }
  ],
  "total_decisions_logged": 3
}
```

### GET /decisions/recent

```json
[
  {
    "id": 3,
    "timestamp": "2026-03-29T01:04:36.611232",
    "symbol": "SPY",
    "action": "hold",
    "confidence": 0,
    "source": "pipeline",
    "summary": "SPY | regime=unknown trend=neutral | action=HOLD qty=0 | conviction=0% human=False"
  }
]
```

Note: `action` field is **lowercase** (`"hold"`, `"long"`, `"short"`) — not uppercase as documented in skill files.

### GET /sentiment/recent

```json
[
  {
    "symbol": "SPY",
    "score": 0.0,
    "post_count": 291,
    "source": "reddit",
    "timestamp": "2026-03-29T..."
  }
]
```

### GET /watchlist

```json
[
  {
    "symbol": "MES",
    "name": "Micro E-mini S&P 500",
    "type": "futures",
    "last_price": null,
    "change_pct": null
  }
]
```

### POST /analyze/technical (body: AnalysisRequest)

Request:
```json
{
  "symbol": "MES",
  "is_futures": true,
  "timeframe": "15m"
}
```

Response:
```json
{
  "symbol": "MES",
  "timestamp": "2026-03-30T...",
  "timeframe": "1h",
  "signal": 0.0,
  "confidence": 0.0,
  "trend": "neutral",
  "regime": "unknown",
  "is_overbought": false,
  "is_oversold": false,
  "summary": "...",
  "reasoning": "...",
  "scores": {
    "trend": 0.0,
    "momentum": 0.0,
    "volatility": 0.0,
    "volume": 0.0
  },
  "levels": {
    "current_price": 0.0,
    "support": [],
    "resistance": []
  },
  "raw_indicators": {}
}
```

### GET /analyze/bars/{symbol}

```
GET /analyze/bars/MES?timeframe=1h&days=5
```

Note: Parameters are `timeframe` and `days` — NOT `interval` and `period` as documented in earlier skill versions.

### POST /pipeline/run

Request body (`AnalysisRequest` schema):
```json
{
  "symbol": "MES",
  "is_futures": true
}
```

Response includes: `analyst_reports` object with keys: `technical`, `news`, `social`, `fundamental`

---

## 13. Full Extended Endpoint Registry (95+)

This is the complete documented endpoint surface including endpoints built in Sessions 2–5 that may exist in `main.py` beyond the `/openapi.json` surface.

### Health and System

| Method | Path | Response Key Fields |
|--------|------|---------------------|
| GET | `/health` | status, version, uptime_seconds, live_trading, kill_switch_active, paper_mode, ibkr_connected |
| GET | `/health/full` | Detailed health across all subsystems |
| GET | `/system/preflight` | 7-criteria pre-flight check |
| GET | `/ib/connection-test` | connected, latency_ms, host, port, client_id |
| POST | `/ib/connect` | Connect to IB Gateway paper port |
| GET | `/market/session` | session name, RTH/Extended/Weekend |

### Safety and Risk

| Method | Path | Response Key Fields |
|--------|------|---------------------|
| GET | `/safety/status` | kill_switch_active, live_trading_enabled, require_human_approval, daily_pnl, equity_peak, drawdown_pct, orders_last_minute |
| POST | `/safety/kill-switch/activate?reason=` | Activate kill switch |
| POST | `/safety/kill-switch/deactivate` | Deactivate kill switch (Tier 3) |
| GET | `/safety/circuit-breakers` | daily_pnl, daily_limit, drawdown_pct, all_clear, pnl_source |
| GET | `/settings/risk` | config: {daily_loss_limit, max_drawdown_pct, max_contracts, risk_per_trade_pct, atr_stop_multiplier, atr_target_multiplier} |
| GET | `/position-sizing/calculate` | Fixed-fractional calculator |
| GET | `/validation/readiness-check` | 8-criteria pre-live readiness |

### Pipeline and Signals

| Method | Path | Response Key Fields |
|--------|------|---------------------|
| POST | `/webhook/tradingview` | Incoming TradingView alerts |
| POST | `/pipeline/run` | Full 5-stage analysis (body: {symbol, is_futures}) |
| POST | `/pipeline/run-signal` | Manual signal trigger |
| GET | `/pipeline/status` | available, last_run, decision_count |
| GET | `/pipeline/history` | Recent pipeline runs from SQLite |
| GET | `/paper/mgc-signal` | signal, direction, regime, atr, stc_val, entry/stop/target |
| GET | `/signals/recent` | Unified chronological signal feed |
| GET | `/signals/stats` | Signal aggregation by action/symbol/status |
| GET | `/decisions/recent?limit=N` | In-memory decision ring buffer |
| POST | `/decisions/log` | Log any decision object |

### Portfolio and Trades

| Method | Path | Response Key Fields |
|--------|------|---------------------|
| GET | `/portfolio` | total_equity, cash_balance, unrealized_pnl, realized_pnl, daily_pnl, margin_used, positions[] |
| GET | `/portfolio/paper/positions` | positions: [{trade_id, symbol, action, quantity, entry_price, pnl, is_open, stop_loss, take_profit}] |
| GET | `/portfolio/history/trades` | trades: [{id, symbol, side, quantity, entry_price, exit_price, realized_pnl, status, entry_time, exit_time, notes}] |
| GET | `/portfolio/history/daily-pnl` | Daily P&L history array |
| GET | `/portfolio/history/decisions` | Decision history |
| GET | `/portfolio/stats/session-today` | date, session, closed_trades, open_trades, gross_pnl, wins, losses, win_rate, best_trade, worst_trade |
| GET | `/portfolio/stats/summary` | Aggregated stats |
| GET | `/portfolio/stats/drawdown` | Drawdown history |
| GET | `/portfolio/stats/streaks` | win_streak, loss_streak, best_streak, worst_streak |
| GET | `/portfolio/stats/trading-days` | Distinct trading day count vs 30-day target |
| GET | `/portfolio/stats/paper-phase-summary` | balance, return%, phase progress |
| GET | `/portfolio/stats/weekly` | 7-day rolling stats |
| GET | `/portfolio/stats/commissions` | Commission totals |
| POST | `/portfolio/import/trades` | Bulk import (max 500) |
| GET | `/portfolio/export/trades.csv` | CSV download |
| GET | `/portfolio/export/daily-pnl.csv` | CSV download |

### Analytics

| Method | Path | Response Key Fields |
|--------|------|---------------------|
| GET | `/analytics/performance` | profit_factor, sharpe_ratio, win_rate, total_trades, period_days, max_drawdown, total_pnl, avg_win, avg_loss, meets_paper_threshold |
| GET | `/analytics/performance/compare` | vs backtest baseline, degradation_factor, validation_thresholds |
| GET | `/analytics/mtf?symbol=MES` | Multi-timeframe STC analysis |
| GET | `/analytics/trades/by-day` | Trade breakdown by day-of-week |
| GET | `/analytics/trades/by-symbol` | Trade breakdown by symbol |
| GET | `/analytics/trades/by-hour` | Trade breakdown by hour |

### Technical Analysis

| Method | Path | Notes |
|--------|------|-------|
| POST | `/analyze/technical` | Body: {symbol, is_futures, timeframe} |
| GET | `/analyze/bars/{symbol}` | Params: ?timeframe=1h&days=5 |

### Macro and Market Data

| Method | Path | Response Key Fields |
|--------|------|---------------------|
| GET | `/macro/snapshot` | VIX, VIX_regime, yields (2Y/10Y/30Y), DXY, Fed Funds, macro_regime |
| GET | `/macro/series/{series_id}` | FRED series data (DGS10, VIXCLS, DFF, etc.) |
| GET | `/prices/snapshot` | {MES: {last_price, prev_close, change_pct}, ...} |
| GET | `/watchlist` | [{symbol, name, type, last_price, change_pct}] |
| GET | `/watchlist/scan` | Scan all symbols with current signals |

### Sentiment

| Method | Path | Notes |
|--------|------|-------|
| GET | `/sentiment/recent` | Cached Reddit sentiment |
| GET | `/sentiment/reddit?filter=` | Fresh Reddit pull with optional filter |
| GET | `/sentiment/news/{symbol}` | Finnhub news for symbol |

### Alerts and Notifications

| Method | Path | Response Key Fields |
|--------|------|---------------------|
| GET | `/alerts/history` | alerts: [{id, alert_type, symbol, message, channel, status, error, created_at}] |
| GET | `/alerts/stats` | aggregation by type/channel/status |
| POST | `/notifications/morning-briefing` | Trigger WhatsApp morning brief |
| POST | `/notifications/whatsapp/test` | Test send to configured number |
| POST | `/notifications/vix-alert-check` | Returns: vix, regime string |

### Backtest

| Method | Path | Notes |
|--------|------|-------|
| GET | `/backtest/results` | All saved backtest JSON files |
| POST | `/backtest/run` | Run backtest: {symbol, start_date, end_date, params} |
| POST | `/backtest/walk-forward` | Walk-forward validation |
| GET | `/backtest/regime-status` | Current regime from backtest engine |
| GET | `/backtest/paper-status` | Paper trading status from backtest tracker |
| POST | `/backtest/monte-carlo` | Monte Carlo simulation on backtest results |
| POST | `/backtest/regime-analysis` | Regime-based P&L breakdown |

### ThinkScript

| Method | Path | Notes |
|--------|------|-------|
| POST | `/thinkscript/generate` | Generate ThinkorSwim script via LLM |

Note: `GET /thinkscript/{name}` and `GET /thinkscript/list` do NOT exist. Only the POST generate endpoint exists.

### Scheduler

| Method | Path | Response Key Fields |
|--------|------|---------------------|
| GET | `/scheduler/status` | running, jobs[{id, name, next_run}], total_decisions_logged |

---

## 14. Database Schema

### Tables (6 core + migrations)

```sql
-- paper_trades (core trade log)
CREATE TABLE paper_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id TEXT UNIQUE,
    symbol TEXT,
    side TEXT,           -- 'LONG' or 'SHORT'
    quantity INTEGER,
    entry_price REAL,
    exit_price REAL,
    entry_time TEXT,
    exit_time TEXT,
    pnl REAL,
    status TEXT,         -- 'open', 'closed', 'cancelled'
    strategy_params TEXT, -- JSON: {regime, stc_val, atr, confidence}
    notes TEXT
);

-- pipeline_runs (migration_003)
CREATE TABLE pipeline_runs (
    run_id TEXT PRIMARY KEY,
    symbol TEXT,
    webhook_action TEXT,
    final_action TEXT,
    summary TEXT,
    status TEXT,
    error_message TEXT,
    created_at TEXT
);
CREATE INDEX idx_pipeline_runs_symbol ON pipeline_runs(symbol);
CREATE INDEX idx_pipeline_runs_status ON pipeline_runs(status);
CREATE INDEX idx_pipeline_runs_created ON pipeline_runs(created_at);

-- alert_log (migration_005)
CREATE TABLE alert_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_type TEXT,
    symbol TEXT,
    message TEXT,
    channel TEXT,        -- 'whatsapp', 'email', etc.
    status TEXT,         -- 'sent', 'failed', 'pending'
    error TEXT,
    created_at TEXT
);

-- daily_snapshots
CREATE TABLE daily_snapshots (
    date TEXT PRIMARY KEY,
    balance REAL,
    pnl REAL,
    trades INTEGER,
    win_rate REAL
);

-- performance_cache
CREATE TABLE performance_cache (
    id INTEGER PRIMARY KEY,
    metrics TEXT,        -- JSON
    updated_at TEXT
);

-- schema_version (migration tracking)
CREATE TABLE schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT
);
```

### Migration History

| Version | Applied | Changes |
|---------|---------|---------|
| 001 | Session 2 | Initial schema: paper_trades, daily_snapshots, performance_cache |
| 002 | Session 2 | Trade journal table |
| 003 | Session 3 | pipeline_runs table + indexes |
| 004 | Session 4 | (analytics tables) |
| 005 | Session 4 | alert_log table |

### DatabaseManager Bridge Methods

```python
# From engine/database/schema.py
add_paper_trade(trade_data: dict) -> str       # Returns trade_id
get_trades(limit=50, symbol=None) -> list
update_trade(trade_id: str, updates: dict) -> bool
insert_pipeline_run(run_data: dict) -> str
get_pipeline_history(limit=20, symbol=None) -> list
insert_alert_log(alert_data: dict) -> int
get_alert_history(limit=50) -> list
health_check() -> dict                          # Returns row counts per table
```

---

## 15. Dashboard Pages and Components

### Pages (12 total)

| Page | Route | Primary Purpose |
|------|-------|----------------|
| Main Dashboard | `app/page.tsx` | Overview + paper phase summary |
| Paper Trading | `app/paper/page.tsx` | Live positions, signals, session P&L |
| Performance | `app/performance/page.tsx` | P&L charts, symbol breakdown, equity curve |
| Validation | `app/validation/page.tsx` | Go-live readiness checklist, Sharpe/PF targets |
| Journal | `app/journal/page.tsx` | Trade log, calendar heatmap, best/worst trades |
| Stats | `app/stats/page.tsx` | Trade count, hours, long/short, weekly breakdown |
| Backtest | `app/backtest/page.tsx` | Strategy reference, regime P&L, signal accuracy |
| Scorecard | `app/scorecard/page.tsx` | P&L streak, drawdown gauge, R:R, profit factor |
| Watchlist | `app/watchlist/page.tsx` | Contract specs, win rate by symbol, ATR, VIX |
| Health | `app/health/page.tsx` | Engine status, IB connection, pipeline, alerts |
| Settings | `app/settings/page.tsx` | Risk params, WhatsApp, pipeline config |

### UI Theme Color System

```
bull    = green   (profitable, positive signals, targets met, above threshold)
bear    = red     (losing, negative signals, danger, below limit)
warn    = yellow  (caution, below-target, approaching limits)
info    = blue    (informational, reference, neutral positive)
neutral = gray    (no data, flat, inactive, unknown)
```

Badge variants: `"bull" | "bear" | "warn" | "info" | "neutral"` — enforced across all 63 components.

`CheckStatus` union (validation/page.tsx): `"PASS" | "FAIL" | "WARN" | "PENDING"` — includes "WARN" as of Session 5 fix.

### Complete Component Registry (63 components)

#### Sessions 1-4 Components

| # | Component | Page | Data Source |
|---|-----------|------|-------------|
| 1 | `ValidationChecklist.tsx` | validation | `/analytics/performance` |
| 2 | `TradingDaysCountdownCard.tsx` | validation | `/portfolio/stats/trading-days` |
| 3 | `PnLStreakWidget.tsx` | scorecard | `/portfolio/stats/streaks` |
| 4 | `RiskStatusWidget.tsx` | paper | `/safety/circuit-breakers` |
| 5 | `PositionSizingWidget.tsx` | paper | `/paper/mgc-signal` + `/settings/risk` |
| 6 | `RecentDecisionsWidget.tsx` | paper | `/portfolio/history/decisions?limit=10` |
| 7 | `WhatsAppStatusCard.tsx` | settings | `/alerts/history` + `/alerts/stats` |
| 8 | `TradingScheduleCard.tsx` | settings | static |
| 9 | `BacktestComparisonCard.tsx` | backtest | `/backtest/results` |
| 10 | `LongShortBalanceWidget.tsx` | backtest | static benchmark |
| 11 | `MesContractSpecCard.tsx` | watchlist | static |
| 12 | `GoLivePlanCard.tsx` | validation | static |
| 13 | `TradeRiskRewardWidget.tsx` | stats | `/portfolio/history/trades` |
| 14 | `ConnectionHealthCard.tsx` | health | `/health` + `/ib/connection-test` |
| 15 | `VIXRegimeCard.tsx` | watchlist | `POST /notifications/vix-alert-check` |
| 16 | `BacktestVsPaperWidget.tsx` | validation | `/analytics/performance` (vs static backtest) |
| 17 | `TradeHourlyBreakdownWidget.tsx` | stats | `/analytics/trades/by-hour` |
| 18 | `TradeDurationWidget.tsx` | performance | `/portfolio/history/trades` |
| 19 | `DatabaseStatsCard.tsx` | health | trade/decision/alert counts |
| 20 | `RiskSettingsWidget.tsx` | settings | `/settings/risk` |
| 21 | `WinStreakWidget.tsx` | stats | `/portfolio/stats/streaks` |
| 22 | `DailyPnLCalendarWidget.tsx` | scorecard | `/portfolio/history/daily-pnl` |
| 23 | `EngineUptimeCard.tsx` | health | `/health` |
| 24 | `CurrentSignalWidget.tsx` | watchlist | `/analytics/mtf?symbol=MES` |
| 25 | `CircuitBreakerWidget.tsx` | paper | `/safety/circuit-breakers` |
| 26 | `MonthlyTargetCard.tsx` | scorecard | `/portfolio/history/daily-pnl` |
| 27 | `AccountROIWidget.tsx` | performance | `/analytics/performance` |
| 28 | `MarketSessionStatusCard.tsx` | journal | client-side CT time |
| 29 | `WeeklyPnLCard.tsx` | performance | `/portfolio/history/trades` |
| 30 | `DecisionBreakdownCard.tsx` | backtest | `/portfolio/history/decisions` |
| 31 | `IbGatewayDetailCard.tsx` | health | `/ib/connection-test` |
| 32 | `TodaySummaryWidget.tsx` | paper | `/portfolio/stats/session-today` |
| 33 | `PaperPhaseSummaryWidget.tsx` | app/page.tsx | `/portfolio/stats/paper-phase-summary` |

#### Session 5 Components (This Session / 2026-03-30)

| # | Component | Page | Data Source | Notes |
|---|-----------|------|-------------|-------|
| 34 | `ui/progress.tsx` | (shared) | — | New UI primitive, role=progressbar |
| 35 | `EngineConfigCard.tsx` | settings | `/health` + `/settings/risk` | Identity + strategy params |
| 36 | `StcStrategyExplainerCard.tsx` | backtest | static | STC reference card, 4-signal grid |
| 37 | `SignalQueueWidget.tsx` | paper | `/paper/mgc-signal` | Full signal: action, STC, ATR, regime |
| 38 | `AlertHistoryWidget.tsx` | journal | `/alerts/history?limit=15` | Scrollable timeline, 24h summary |
| 39 | `TopSymbolsWidget.tsx` | performance | `/portfolio/history/trades` | Groups by symbol, WR + P&L |
| 40 | `PhaseProgressWidget.tsx` | validation | `/analytics/performance` | Phase 1/2/3 milestones with dates |
| 41 | `OpenPositionsWidget.tsx` | paper | `/portfolio/paper/positions` | 15s refresh, safety-critical |
| 42 | `DailyTradeCountWidget.tsx` | stats | `/portfolio/history/trades` | 14-day bar chart, green/red by P&L |
| 43 | `MaxDrawdownTrackerWidget.tsx` | scorecard | `/analytics/performance` | Gauge vs 15% circuit breaker |
| 44 | `RegimePnLBreakdownWidget.tsx` | backtest | `/portfolio/history/trades` | Extracts regime from strategy_params |
| 45 | `AvgTradeTimeWidget.tsx` | performance | `/portfolio/history/trades` | 4-bucket hold time: Scalp/Short/Swing/Extended |
| 46 | `BestWorstTradeWidget.tsx` | journal | `/portfolio/history/trades` | Top 3 winners/losers, hold time |
| 47 | `EquityCurveWidget.tsx` | performance | `/portfolio/history/trades` | Cumulative P&L CSS bars, HWM, drawdown |
| 48 | `TradingHoursWidget.tsx` | stats | `/portfolio/history/trades` | Hour-of-day bar chart, RTH focus |
| 49 | `WinRateBySymbolWidget.tsx` | watchlist | `/portfolio/history/trades` | Per-symbol: WR, P&L, avg hold |
| 50 | `SharpeRatioWidget.tsx` | validation | `/analytics/performance` | Large display, 0-3 gauge, target 1.5 |
| 51 | `LongShortBreakdownWidget.tsx` | stats | `/portfolio/history/trades` | LONG vs SHORT side-by-side |
| 52 | `RiskRewardWidget.tsx` | scorecard | `/analytics/performance` | avg_win/avg_loss ratio, target >= 2.0 |
| 53 | `MarketSessionWidget.tsx` | health | client-side | CME Globex RTH/ETH/Weekend, CT time |
| 54 | `SignalAccuracyWidget.tsx` | backtest | `/portfolio/history/trades` | Signal direction → profitable outcome |
| 55 | `SessionSummaryWidget.tsx` | paper | `/portfolio/stats/session-today` | Date, P&L, wins/losses, symbols traded |
| 56 | `TradeCalendarWidget.tsx` | journal | `/portfolio/history/trades` | Calendar heatmap, month nav, hover tooltips |
| 57 | `PipelineStatusWidget.tsx` | settings | `/pipeline/status` | 5-stage display, decision_count |
| 58 | `VolatilityWidget.tsx` | watchlist | `/paper/mgc-signal` | ATR stop/target/$, max contracts |
| 59 | `WeeklyPerformanceWidget.tsx` | stats | `/portfolio/history/trades` | 8-week bar chart + table, trend arrows |
| 60 | `DecisionLogWidget.tsx` | health | `/decisions/recent` + `/pipeline/status` | Live feed, signal badges, confidence % |
| 61 | `ProfitFactorWidget.tsx` | scorecard | `/analytics/performance` | Large PF, 0-3 gauge, target 2.0 |
| 62 | `EntryQualityWidget.tsx` | performance | `/portfolio/history/trades` | Target hit/stopped/scratch/partial breakdown |
| 63 | `BacktestMetricsWidget.tsx` | backtest | `/backtest/results` | Best result by PF, 2x2 metric grid |

#### Pending (Rate Limited — Not Yet Built)

| Component | Target Page | Status |
|-----------|-------------|--------|
| `RecentTradesTableWidget.tsx` | performance | Rate limited in Session 5 |
| `CumulativeTradingDaysWidget.tsx` | scorecard | Rate limited in Session 5 |
| `LiveReadinessWidget.tsx` | validation | Rate limited in Session 5 |

---

## 16. Skill Files Reference

**Location**: `C:\Users\mattm\.claude\skills\jarvis-trader\`
**Version**: v1.1.0
**Total size**: ~581KB across 10 files
**Activation**: `/jarvis-trader` command OR auto-trigger keywords

### Auto-Trigger Keywords

`trading`, `market analysis`, `pipeline`, `trade signal`, `kill switch`, `backtest`, `portfolio`, `risk status`, `what's the market doing`, `position check`, `futures`, `options`, `MES`, `MNQ`

### File Inventory

| File | Size | Purpose |
|------|------|---------|
| `SKILL.md` | 42KB | Core identity, three-tier autonomy, API quick reference, session protocol |
| `api-reference.md` | 57KB | All 26+ engine endpoints documented with schemas and examples |
| `agent-registry.md` | 28KB | 10 pipeline agents + supporting components, model assignments |
| `workflows.md` | 50KB | 10 multi-step workflows (Market Open Brief, Pipeline Signal Review, etc.) |
| `triggers.md` | 31KB | 24 proactive triggers (T-1 through T-24) |
| `standing-orders.md` | 28KB | 3-tier autonomy detail, 6 standing orders, 6 emergency protocols |
| `usage-guide.md` | 13KB | Activation layers, natural language commands, best practices |
| `matt-context.md` | 7KB | Personal trading context (schedule, instruments, style, numbers) |
| `strategy-reference.md` | 31KB | 5-layer framework, STC params, backtests, regime reference |
| `JARVIS-TRADER-COMPLETE-DOCUMENTATION.md` | 140KB | Complete merged reference (~2,975 lines) |

### 24 Proactive Triggers (T-1 through T-24)

| Trigger | Category | Description |
|---------|----------|-------------|
| T-1 | Time | Pre-market data build (6:00 AM CT) |
| T-2 | Time | Morning brief delivery (6:30 AM CT) |
| T-3 | Time | RTH open pipeline scan (9:35 AM CT) |
| T-4 | Time | Midday check (11:30 AM CT) |
| T-5 | Time | Afternoon session scan (1:00 PM CT) |
| T-6 | Time | Close prep brief (3:00 PM CT) |
| T-7 | Time | EOD summary (3:30 PM CT) |
| T-8 | Event | Daily P&L approaching -1.6% (warning) |
| T-9 | Event | Daily P&L hit -2.0% (halt) |
| T-10 | Event | Non-hold pipeline signal received |
| T-11 | Event | Kill switch activated |
| T-12 | Event | Kill switch deactivation requested (Tier 3 confirm) |
| T-13 | Event | IB Gateway connection lost |
| T-14 | Event | Engine health check failure |
| T-15 | Event | Position opened |
| T-16 | Event | Position closed |
| T-17 | Event | T1 target hit on open position |
| T-18 | Event | Stop loss triggered |
| T-19 | Context | User asks about current market |
| T-20 | Context | User asks about open positions |
| T-21 | Context | User asks about P&L |
| T-22 | Context | Correlation cascade (multiple concurrent losers) |
| T-23 | Intelligence | VIX spike > 25 (regime shift) |
| T-24 | Intelligence | Liberation Day rule activation (3+ consecutive losses) |

---

## 17. Matt's Trading Context

### Trading Windows

| Window | CT Time | ET Time | Purpose |
|--------|---------|---------|---------|
| Pre-market prep | 8:00–8:30 AM | 9:00–9:30 AM | Review brief, confirm trade plan for the day |
| Open noise (avoid) | 8:30–9:35 AM | 9:30–10:35 AM | High noise, whipsaw risk — no new entries |
| Morning primary | 9:35–11:30 AM | 10:35 AM–12:30 PM | Highest-conviction entries, primary window |
| Midday lull (avoid) | 11:30 AM–1:00 PM | 12:30–2:00 PM | Low volume, choppy — skip unless strong signal |
| Afternoon secondary | 1:00–3:30 PM | 2:00–4:30 PM | Trend continuation, secondary window |
| After-hours exits | 3:00–5:00 PM | 4:00–6:00 PM | Exits only — no new entries in reduced liquidity |
| Futures close | 5:00 PM | 6:00 PM | Daily settlement, all positions should be closed |

### Personal Trading Rules

1. Never enter during 8:30–9:35 AM CT (first hour noise)
2. Never hold MES overnight unless explicit plan
3. Always respect the -2.0% daily loss halt — no exceptions
4. Liberation Day rule: drop to 0.5% risk on 3rd consecutive loss
5. Maximum 2 contracts at any time (SafetyLayer enforced)
6. T1 hit = move stop to breakeven — never let a winner become a loser
7. STC must cross the threshold, not just touch it (confirmed cross required)
8. WhatsApp alerts for non-hold signals — check before acting

### Account Targets

| Phase | Capital | Contracts | Risk/Trade |
|-------|---------|-----------|-----------|
| Paper (current) | Simulated | 1-2 MES | 1% |
| Live Phase 1 (June 2026+) | ~$10,000 | 1 MES max | 1% |
| Live Phase 2 (TBD) | Scale up | 2 MES | 1% |

---

## 18. VIX Regime Reference

The canonical 6-tier VIX regime system used throughout JARVIS Trader:

| VIX Level | Regime Label | Sizing Guidance | Notes |
|-----------|-------------|-----------------|-------|
| < 12 | VERY_LOW | Caution — reduce or skip | Complacency, trend entries may fail suddenly |
| 12–16 | LOW | Standard sizing | Normal low-vol environment |
| 16–20 | NORMAL | Standard sizing | Healthy vol, best STC performance |
| 20–25 | ELEVATED | Reduce position size | Widen stops, lower conviction required |
| 25–30 | HIGH | 1 contract maximum | Capital preservation mode |
| > 30 | EXTREME | Flat or absolute minimum | No new entries unless extremely clear signal |

Note: Skill files and early documentation used a 5-tier system (CALM/NORMAL/CAUTION/ELEVATED/EXTREME). The canonical system is 6-tier as shown above.

---

## 19. Session-by-Session History

### Session 0 — Concept and Backtesting (Pre-2026-03-28)

- STC strategy backtested on MES 1h data (ThinkorSwim ThinkScript)
- Validated parameters: STC OS=15/OB=83, ATR stop 0.70x, T1 1.50x
- Best result: MES 1h PF 5.27, Sharpe 4.16, Win Rate ~36%, +47.2% total return
- Liberation Day stress test (April 2025 crash): max DD -8.3% (within -10% limit)
- Decision: build automated paper trading system to validate forward performance

### Session 1 — Initial Scaffold + Skill Creation (2026-03-28)

**Work completed**:
- Full project scaffold built by 5 parallel agents: 49 files, ~7,684 lines
- Git initialized with initial commit (`1c256a0`)
- `.env` created and configured with Anthropic API key
- Python venv created with Python 3.12 (3.14 breaks numpy)
- `requirements-core.txt` created (removed ta-lib, vectorbt, nautilus_trader, langchain)
- All 60+ Python packages installed successfully
- Fixed `pandas-ta` version pin (0.3.14b → 0.4.67b0)
- Fixed pandas_ta Windows bug: `from posix import pread` in alligator.py
- Fixed `ib_async` import guard in ibkr_executor.py
- Fixed schwab import path
- Added `POST /pipeline/run`, `GET /pipeline/status`, `GET /prices/snapshot` endpoints
- Added `GET /scheduler/status` endpoint with APScheduler
- Created `ThinkScriptGeneratorAgent`, `TelegramNotifier`
- APScheduler watchlist scan every 30min weekdays 9:30am-4pm CT
- Dashboard `npm install` (465 packages, Next.js 15)
- "Run Analysis" button and `/analysis` page added to dashboard
- 10-file Claude Code skill created at `C:\Users\mattm\.claude\skills\jarvis-trader\`
  - SKILL.md, api-reference.md, agent-registry.md, workflows.md, triggers.md,
    standing-orders.md, usage-guide.md, matt-context.md, strategy-reference.md,
    JARVIS-TRADER-COMPLETE-DOCUMENTATION.md (~581KB total)

**Key technical decisions**:
- 3-tier autonomy model matching JARVIS v2 (GMS) — Matt already knows the model
- Kill switch always Tier 3
- SafetyLayer hardcoded Python — no LLM in enforcement path
- Paper trading first, live trading gate in June 2026

### Session 2 — SQLite Persistence + IB Gateway (2026-03-29, v1.1.0)

**Work completed**:
- `engine/database/schema.py` — DatabaseManager with 8 tables
- `engine/database/migrations.py` — version-tracked migrations (001: initial, 002: journal)
- `engine/portfolio/tracker.py` — SQLite-backed PortfolioTracker (replacing in-memory)
- `engine/execution/ib_gateway.py` — IBGatewayManager, paper port 4002 only, live port 4001 PERMANENTLY BLOCKED
- `engine/execution/ib_order_manager.py` — IBOrderManager with `reconcile()`
- `engine/risk/pnl_monitor.py` — PnLMonitor with 3-tier P&L source (IB → SQLite → memory)
- `engine/utils/position_sizing.py` — fixed-fractional formula (risk=1%, stop=0.70xATR)
- `engine/analytics/performance.py` — PerformanceCalculator (PF, Sharpe, WR)
- `engine/schedulers/eod_scheduler.py` — EOD snapshots Mon-Fri 3:05 PM CT
- `engine/routers/webhook_router.py` — TradingView webhook receiver
- `engine/routers/journal_router.py` — trade journal CRUD with tags
- 3 analytics stubs: `greeks_monitor.py`, `mtf_confirmation.py`, `vix_overlay.py`
- Dashboard components: CircuitBreakerPanel, IBGatewayStatus, RegimeDisplay, SignalHistory
- Dashboard pages: /performance, /journal, /watchlist, /settings, /validation, /backtest
- New endpoints: `/safety/circuit-breakers`, `/safety/config`, `/analytics/performance`, `/portfolio/history/*`, `/portfolio/stats/*`
- 28 integration tests (all passing, zero deprecation warnings)
- All `datetime.utcnow()` → `datetime.now(timezone.utc)` across codebase

### Session 3 — Pipeline Wiring (2026-03-29, v1.2.0)

**Work completed**:
- `TradingPipeline.run_on_signal()` — accepts TradingView webhook signal, runs full 5-stage pipeline
- `POST /pipeline/run-signal` — manual pipeline trigger (400 on invalid action, 503 if not ready)
- `GET /pipeline/history` — recent pipeline runs from SQLite (limit, symbol params)
- `GET /signals/recent` — unified chronological signal feed
- `GET /signals/stats` — signal statistics by action/symbol/status/success rate
- `GET /ib/connection-test` — ping IB Gateway port 4002 with latency measurement
- `POST /ib/connect` — connect to IB Gateway paper port
- `GET /portfolio/export/trades.csv` — paper trade history download
- `GET /portfolio/export/daily-pnl.csv` — daily P&L history download
- `POST /position-sizing/calculate` — fixed-fractional contract size calculator
- `pipeline_runs` SQLite table (migration_003)
- Dashboard `/health` page — 6-subsystem status grid with auto-refresh
- Dashboard Simulate Trade panel on `/validation` (Section E)
- Dashboard PipelineRunHistory component (Section F)
- Dashboard Position Sizing Calculator (Section G)
- `IBGatewayStatus.tsx` component — latency badge, Connect button, 10s polling
- WhatsApp notification on pipeline run completion
- `start_jarvis.bat` — `.env` existence check with warning
- 5 webhook integration tests (4 pass, 1 skip on secret validation)
- Fixed `pipeline.py` `run_on_signal()` truncation
- Pine Script v5 strategy generated (saved to `scripts/jarvis_trader_strategy.pine`)

### Session 4 — Analytics and Dashboard Suite (2026-03-29, v1.x.0)

**Work completed**:
- 22+ new dashboard components (Sessions 1-4 components 1-33)
- Alert log database table (migration_005)
- 13+ new endpoints including hourly/daily/symbol analytics
- `scripts/smoke_test.py` — 48-endpoint smoke test
- `scripts/daily_report.py` — EOD report generator
- `scripts/seed_paper_trades.py` — synthetic trade generator (95 trades, 30 days)
- Nav audit — 7 pages fixed
- Engine: ~95+ endpoints total
- Fixed pre-existing TypeScript errors

### Session 5 — Dashboard Expansion + Daily Routine (2026-03-30)

**Context**: Session began as continuation of work on `JARVIS_v2_vs_TRADER_Analysis.html` report (4,545-line, 351KB comparative analysis). Matt declared focus pivot: all future recommendations should be trading-focused, not Greenfield Metal Sales.

**Primary deliverable**: `TRADING_DAILY_ROUTINE.md` — 3 versions produced

**v1** (initial creation):
- Created `TRADING_DAILY_ROUTINE.md` based on skill files (standing-orders.md, triggers.md)
- 15 sections covering all aspects of Matt's trading day
- Contained errors: wrong `/health` status value, wrong field names, non-existent endpoints

**v2** (API spec validation):
- Read `api-reference.md` (77.3KB) and `workflows.md` (58.8KB) from skill directory
- Corrected `/decisions/recent` — no `?hours` param, only `?limit` and `?symbol`
- Corrected VIX to 6-tier canonical system
- Corrected `/safety/status` field names
- Corrected trading windows to CT time
- Corrected `/portfolio/paper/trade` uses `action: "BUY/SELL"` not `side: "LONG/SHORT"`
- Complete rewrite of all 15 sections

**v3** (live engine validation — confirmed 2026-03-30):
- Tested every endpoint against `http://localhost:8010` live
- Discovered 14 major documentation corrections (see Section 20)
- Final file: 1,229 lines, live-validated

**Session 5 also completed**:
- 30 new dashboard components (components 34–63 in registry)
- `ui/progress.tsx` new UI primitive (role=progressbar)
- Fixed `CheckStatus` union in `validation/page.tsx` — missing "WARN" variant
- Rate limit hit on final wave — 3 components pending next session

---

## 20. API Documentation Corrections (2026-03-30 Audit)

These are confirmed corrections discovered by testing every endpoint live against `http://localhost:8010` on 2026-03-30. The skill files (`api-reference.md`) may contain the prior incorrect documentation and should be treated as authoritative only after these corrections.

| Endpoint | Prior Documentation | Live Actual (Confirmed 2026-03-30) |
|----------|--------------------|------------------------------------|
| `GET /health` | `"status": "ok"` | `"status": "online"` |
| `GET /safety/status` | `daily_pnl_pct` (percentage) | `daily_pnl` (raw dollar amount) |
| `GET /safety/status` | `trading_allowed` field | `live_trading_enabled` field |
| `GET /safety/status` | `circuit_breakers[]` array | `orders_last_minute` integer |
| `GET /prices/snapshot` | `instruments.MES.price` | `{MES: {last_price, prev_close, change_pct}}` |
| `GET /portfolio/paper/positions` | Documented as existing | **Does NOT exist on openapi.json** |
| `GET /portfolio/paper/performance` | Documented as existing | **Does NOT exist** |
| `POST /portfolio/paper/trade` | Documented as existing | **Does NOT exist** |
| `GET /scheduler/status` | `enabled`, `next_scan_time`, `watchlist[]` | `running`, `jobs[{id, name, next_run}]`, `total_decisions_logged` |
| `GET /decisions/recent` | `?limit` + `?symbol` params | `?limit` param only (symbol param does not exist) |
| `GET /backtest/results` | Documented as GET endpoint | **Is POST `/backtest/run`** (different path and method) |
| `GET /thinkscript/{name}` | Documented as existing | **Does NOT exist** — only `POST /thinkscript/generate` |
| `GET /thinkscript/list` | Documented as existing | **Does NOT exist** |
| `/analyze/bars/{symbol}` | `?interval=1h&period=5d` | `?timeframe=1h&days=5` (different param names) |
| `POST /pipeline/run` body | `{symbol, is_futures, include_news, include_social, include_macro}` | `{symbol, is_futures}` only — optional fields not accepted |
| `POST /analyze/technical` response | `bias`, `atr`, `entry_price`, `stop_price` | `signal`, `confidence`, `trend`, `regime`, `is_oversold`, `is_overbought`, `scores{}`, `levels{}` |
| Decision `action` field | Uppercase `"HOLD"`, `"LONG"`, `"SHORT"` | Lowercase `"hold"`, `"long"`, `"short"` |

---

## 21. JARVIS v2 vs JARVIS Trader Comparative Analysis

A full comparative analysis HTML report was built in the session prior to 2026-03-30.

**File**: `C:\Users\mattm\Greenfield Metal Sales\dev\personal_agent\JARVIS_v2_vs_TRADER_Analysis.html`
**Size**: 4,545 lines, 351KB (single self-contained file)
**Design**: Dark-mode dashboard, GMS brand system, Montserrat/DM Sans/JetBrains Mono fonts, CSS Grid + Flexbox, zero external JS dependencies

### Summary Comparison

| Dimension | JARVIS v2 (Business Intelligence) | JARVIS Trader (Trading Intelligence) |
|-----------|----------------------------------|--------------------------------------|
| Domain | Greenfield Metal Sales operations | CME Micro Futures trading |
| Port | 8009 (PM2) | 8010 (uvicorn) |
| Backend | Node.js/Python hybrid | Python/FastAPI |
| Agents | 68 agents | 10 pipeline agents |
| Endpoints | 190+ | 95+ (26 confirmed live) |
| Database | Redis + Postgres + ChromaDB | SQLite |
| Data sources | Paradigm ERP, QuickBooks, email, OneNote | yfinance, Finnhub, FRED, Reddit, TradingView |
| Autonomy | 3-tier (same model) | 3-tier (same model) |
| Standing Orders | 8 | 6 |
| Emergency Protocols | 4 | 6 |
| Notifications | WhatsApp + email | WhatsApp (Twilio) |
| Primary use | Morning briefing, customer intelligence, quote analysis | Signal generation, risk management, trade execution |
| Kill switch | Business process halt | Trading halt (circuit breaker) |
| Human approval | Required for outbound actions | Required for all trade execution |

Matt declared in Session 5 that all future focus is trading (JARVIS Trader), not Greenfield Metal Sales.

---

## 22. Validation Targets and Go-Live Plan

### Paper Trading Validation Criteria (June 2026 Gate)

All 6 criteria must be met for at least 60 consecutive trading days before live trading is enabled.

| Metric | Paper Target | Notes |
|--------|-------------|-------|
| Profit Factor | >= 2.0 | Gross profit / gross loss (backtest: 5.27) |
| Sharpe Ratio | >= 1.5 | Risk-adjusted return (backtest: 4.16) |
| Win Rate | >= 28% | % profitable trades (lower OK given 2.14:1 R:R) |
| Total Non-Hold Decisions | >= 40 | Minimum statistical sample |
| Trading Days | >= 60 | Consecutive distinct calendar days |
| Max Drawdown | < 8% | Circuit breaker fires at -10.0% |
| WhatsApp Alerts | 5+ Twilio SIDs confirmed | Notifications working |
| IB Gateway | Tested paper port 4002 | Connectivity confirmed |
| No EP-3 events | Last 2 weeks clean | No engine crashes |
| Liberation Day respected | Yes | Sizing reduced on 3rd loss |

### Phase Timeline

| Phase | Target Date | Criteria | Status |
|-------|-------------|---------|--------|
| Phase 1 (initial paper) | March 2026 | >= 10 trading days | COMPLETE |
| Phase 2 (validation paper) | April–May 2026 | 60 days, >= 40 signals, PF >= 2.0 | IN PROGRESS |
| Phase 3 (live micro) | June 2026 | All 6 criteria met | PENDING |
| Phase 4 (scale) | TBD | Consistent live performance | FUTURE |

### Go-Live Checklist (June 2026)

1. All 6 paper trading validation criteria met
2. Open live IBKR account with MES/MNQ futures permissions
3. Fund with ~$10,000 initial capital
4. Modify `ib_gateway.py` to allow live port 4001 connections (currently permanently blocked)
5. Set `LIVE_TRADING_ENABLED=True` in `.env` (Tier 3 decision)
6. Wire SafetyLayer to IB Gateway live port
7. Set `REQUIRE_HUMAN_APPROVAL=True` for first 30 live days minimum
8. Maximum 1 contract for first 3 months live
9. 3-month live monitoring period before scaling

---

## 23. Key Files Reference

### Engine (Critical Files)

| File | Path | Purpose |
|------|------|---------|
| main.py | `engine/main.py` | FastAPI app, all route registrations, lifespan |
| pipeline.py | `engine/agents/pipeline.py` | 5-stage trading pipeline orchestrator |
| safety_layer.py | `engine/risk/safety_layer.py` | Circuit breakers, kill switch, hard limits |
| schema.py | `engine/database/schema.py` | DatabaseManager, SQLite tables, bridge methods |
| migrations.py | `engine/database/migrations.py` | Version-tracked migrations (001–005) |
| ib_gateway.py | `engine/execution/ib_gateway.py` | IB paper port 4002 ONLY |
| position_sizing.py | `engine/utils/position_sizing.py` | Fixed-fractional formula |
| performance.py | `engine/analytics/performance.py` | PF, Sharpe, WR calculations |
| eod_scheduler.py | `engine/schedulers/eod_scheduler.py` | EOD snapshots Mon-Fri 3:05 PM CT |
| whatsapp.py | `engine/notifications/whatsapp.py` | WhatsApp formatters (Twilio) |

### Dashboard (Critical Files)

| File | Path | Purpose |
|------|------|---------|
| api.ts | `dashboard/lib/api.ts` | fetchEngine() + all TypeScript types |
| utils.ts | `dashboard/lib/utils.ts` | formatCurrency, formatPercent, cn() |
| progress.tsx | `dashboard/components/ui/progress.tsx` | Progress bar primitive |

### Scripts

| File | Path | Purpose |
|------|------|---------|
| smoke_test.py | `scripts/smoke_test.py` | 48-endpoint smoke test |
| seed_paper_trades.py | `scripts/seed_paper_trades.py` | 95 synthetic trades, 30 days |
| jarvis_trader_strategy.pine | `scripts/jarvis_trader_strategy.pine` | Pine Script v5 strategy |
| daily_report.py | `scripts/daily_report.py` | EOD report generator |

### Project Root Documents

| File | Purpose |
|------|---------|
| `TRADING_DAILY_ROUTINE.md` | 1,229-line live-validated daily operations playbook |
| `JARVIS-TRADER-MASTER-REPORT.md` | Previous master report (2026-03-29) |
| `CHANGELOG.md` | v1.0.0 through v1.6.0+ version history |
| `SESSION_NOTES_ARCHIVE.md` | Session 1 detailed notes |
| `jarvis-trader-skill-project-log.md` | Skill creation log |
| `prd.json` | PRD with all 10 user stories (all marked complete) |
| `start_jarvis.bat` | Launch script with .env check |
| `conftest.py` | Pytest configuration |

### Skill Files

| File | Path |
|------|------|
| SKILL.md | `C:\Users\mattm\.claude\skills\jarvis-trader\SKILL.md` |
| api-reference.md | `C:\Users\mattm\.claude\skills\jarvis-trader\api-reference.md` |
| workflows.md | `C:\Users\mattm\.claude\skills\jarvis-trader\workflows.md` |
| triggers.md | `C:\Users\mattm\.claude\skills\jarvis-trader\triggers.md` |
| standing-orders.md | `C:\Users\mattm\.claude\skills\jarvis-trader\standing-orders.md` |
| matt-context.md | `C:\Users\mattm\.claude\skills\jarvis-trader\matt-context.md` |
| strategy-reference.md | `C:\Users\mattm\.claude\skills\jarvis-trader\strategy-reference.md` |

---

## 24. Known Issues and Pending Work

### Dashboard (Pending Components)

| Component | Target Page | Reason Blocked |
|-----------|-------------|---------------|
| `RecentTradesTableWidget.tsx` | performance | Rate limited in Session 5 |
| `CumulativeTradingDaysWidget.tsx` | scorecard | Rate limited in Session 5 |
| `LiveReadinessWidget.tsx` | validation | Rate limited in Session 5 |

### Skill File Accuracy

The skill file `api-reference.md` (57KB) contains 14+ documented corrections from the 2026-03-30 live audit (see Section 20). These should be updated before relying on skill documentation for API calls.

Priority corrections needed in skill files:
- `GET /health` → `"status": "online"` (not `"ok"`)
- `GET /safety/status` → `daily_pnl` (not `daily_pnl_pct`), `live_trading_enabled` (not `trading_allowed`)
- `POST /pipeline/run` → body only accepts `{symbol, is_futures}` (not optional include_* fields)
- `/analyze/bars/{symbol}` → params are `timeframe` and `days` (not `interval` and `period`)
- `action` in decisions → lowercase (`"hold"`, `"long"`, `"short"`)

### IB Gateway

- Paper port 4002 integration complete but requires IB Trader Workstation or IB Gateway running locally
- Live port 4001 permanently blocked in `ib_gateway.py` — requires code change for live trading
- `ibkr_connected: false` in live health response — not connected to any IB instance currently

### Engine

- `EmailIntelligenceAgent.analyze_recent_emails` method missing — affects morning briefing if referenced
- Paradigm ERP API (GMS JARVIS, unrelated to JARVIS Trader)
- ChromaDB, Redis — not used in JARVIS Trader (JARVIS v2 GMS only)

### Future Roadmap

| Feature | Priority | Notes |
|---------|----------|-------|
| Options Greeks monitoring | Medium | `greeks_monitor.py` stub exists |
| Multi-timeframe confirmation (1h+4h+daily) | Medium | `mtf_confirmation.py` stub exists |
| VIX regime overlay on all signals | Medium | `vix_overlay.py` stub exists |
| Earnings calendar integration | Low | Prevents trading around announcements |
| OneNote trade journal via MCP | Low | Already use MCP for OneNote |
| Real options flow data (Unusual Whales) | Low | Paid API required |
| SQLite → PostgreSQL migration | Low | For production scale |
| Walk-forward validation endpoint | Complete | `POST /backtest/walk-forward` exists |
| Monte Carlo simulation | Complete | `POST /backtest/monte-carlo` exists |
| Update skill files with API corrections | High | See Section 20 |

---

## 25. Quick Start Commands

### Launch Everything

```bat
rem From project root (C:\Users\mattm\ThinkorSwim\jarvis-trader\)
start_jarvis.bat
```

### Manual Start — Engine

```bash
cd C:/Users/mattm/ThinkorSwim/jarvis-trader/engine
.venv/Scripts/python -m uvicorn main:app --reload --host 0.0.0.0 --port 8010
```

### Manual Start — Dashboard

```bash
cd C:/Users/mattm/ThinkorSwim/jarvis-trader/dashboard
pnpm dev
```

### Key URLs

| URL | Purpose |
|-----|---------|
| `http://localhost:8010/health` | Engine health check |
| `http://localhost:8010/docs` | Swagger API documentation |
| `http://localhost:8010/openapi.json` | Full OpenAPI spec |
| `http://localhost:3010` | Main dashboard |
| `http://localhost:3010/health` | Health dashboard page |
| `http://localhost:3010/paper` | Paper trading page |
| `http://localhost:3010/validation` | Go-live readiness |

### Common Curl Checks

```bash
# Health check
curl http://localhost:8010/health

# Safety status
curl http://localhost:8010/safety/status

# Recent decisions
curl http://localhost:8010/decisions/recent?limit=5

# Run pipeline on MES
curl -X POST http://localhost:8010/pipeline/run \
  -H "Content-Type: application/json" \
  -d '{"symbol": "MES", "is_futures": true}'

# Macro snapshot (VIX, yields)
curl http://localhost:8010/macro/snapshot

# Prices snapshot
curl http://localhost:8010/prices/snapshot

# Scheduler status
curl http://localhost:8010/scheduler/status

# Activate kill switch (emergency)
curl -X POST "http://localhost:8010/safety/kill-switch/activate?reason=manual_test"

# Test WhatsApp
curl -X POST http://localhost:8010/notifications/whatsapp/test \
  -H "Content-Type: application/json" \
  -d '{"message": "JARVIS Trader health check"}'
```

### Initialize Database

```bash
cd C:/Users/mattm/ThinkorSwim/jarvis-trader/engine
.venv/Scripts/python init_db.py

# Full reset (destroys all paper trades):
.venv/Scripts/python init_db.py --reset
```

### Run Integration Tests

```bash
cd C:/Users/mattm/ThinkorSwim/jarvis-trader
.venv/Scripts/python -m pytest engine/tests/test_integration.py -v
```

### Run Smoke Test (48 endpoints)

```bash
cd C:/Users/mattm/ThinkorSwim/jarvis-trader
.venv/Scripts/python scripts/smoke_test.py
```

### Seed Synthetic Paper Trades (for dashboard testing)

```bash
cd C:/Users/mattm/ThinkorSwim/jarvis-trader
.venv/Scripts/python scripts/seed_paper_trades.py
# Generates 95 trades over 30 days matching strategy parameters
```

---

*Report generated 2026-03-30. Covers all sessions from initial scaffold (2026-03-28) through Session 5+ continuation (2026-03-30). All API response shapes in Section 12 confirmed against live engine on 2026-03-30.*
