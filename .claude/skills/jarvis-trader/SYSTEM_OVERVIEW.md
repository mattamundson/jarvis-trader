# JARVIS TRADER — System Overview

## What This Project Is

JARVIS TRADER is an AI-powered futures and options trading system built for paper trading validation. It uses a 5-stage multi-agent LLM pipeline to generate trade signals, debate them, decide, validate risk, and seek final portfolio-level approval — all before a human reviews the recommendation.

The system is currently in **Phase 2: Hardening**. Live capital deployment is Phase 3 and is not yet enabled.

---

## Who Uses It

| Role | How They Interact |
|---|---|
| Matt (trader/owner) | Reviews trade recommendations; approves or rejects; monitors dashboard |
| Claude Code sessions | Develop, debug, refactor, and extend the system |
| Paper trading engine | Automated signal scanning and trade logging (no real money) |

---

## Two-Component Architecture

```
engine/          ← Python 3.12 / FastAPI — all trading logic, agents, risk
dashboard/       ← Next.js 15 / TypeScript — visualization and control UI
```

They communicate exclusively through HTTP. The dashboard calls the engine via `/api/engine/*` rewrites — never directly to `localhost:8010` in component code.

---

## Core Capabilities

**Trading Intelligence**
- 5-stage LLM pipeline: parallel analysis → debate → decision → risk veto → fund approval
- STC oscillator (OS=15) signal with per-instrument calibrated parameters
- 5-layer regime filter (trend, structure, bias, entry timing, volatility)
- ATR-based stop placement and multi-target exits

**Risk and Safety**
- Hardcoded Python safety layer — no LLM reasoning in the risk path
- Kill switches: -2% daily loss, -10% drawdown from peak
- Position limits: 2 micro contracts max, 5% portfolio max
- Human approval required for every trade

**Multi-Market Framework**
- Futures: MCL, MNQ (active), MGC (halted), MES (suspended)
- Options: chain data, greeks, IV rank
- Crypto: monitoring only
- Polymarket: sentiment signal

**Learning System** (`engine/learning/`)
- `pattern_extractor.py` — extracts patterns from trade outcomes
- `session_memory.py` — session-scoped working memory
- `strategy_tuner.py` — recommends parameter adjustments
- `trade_classifier.py` — classifies trades by outcome type

**Dashboard** (`dashboard/`)
- 16 pages: command center, portfolio, health, analysis, backtest, options, paper, strategies, etc.
- Real-time WebSocket status feed
- Regime visualization, walk-forward results, trade journal

---

## Phase Status

| Phase | Name | Status |
|---|---|---|
| Phase 1 | Architecture & signals | Complete |
| Phase 2 | Multi-market, hardening, paper trading | Active |
| Phase 3 | Live capital deployment | Not started — `LIVE_TRADING_ENABLED = False` |

---

## Out of Scope (Current Phase)

- Live order routing to any broker
- Schwab connector activation (`SCHWAB_READY = False`)
- IB Gateway live port 4001 (permanently blocked)
- Any change that sets `LIVE_TRADING_ENABLED = True` without explicit Tier 3 confirmation
- MGC and MES trading (MGC halted, MES suspended)

---

## Key Directories

```
engine/
├── agents/          10 agents — pipeline.py is the orchestrator
├── routers/         24 routers — 80+ API endpoints
├── risk/            safety_layer.py, pnl_monitor.py, loss_tracker.py
├── backtest/        signals.py (CANONICAL), indicators.py, walk-forward
├── markets/         futures/, options/, crypto/, polymarket/ modules
├── learning/        pattern_extractor, session_memory, strategy_tuner, trade_classifier
├── data/            market_data.py — MarketDataManager (Polygon → yfinance fallback)
├── execution/       ib_order_manager.py — paper mode only
├── portfolio/       tracker.py — PortfolioTracker
├── config.py        TradingConfig — ALL risk parameters
├── main.py          FastAPI app — 24 routers wired here
└── tests/           18 test files

dashboard/
├── app/             16 Next.js App Router pages
├── lib/
│   └── api.ts       fetchEngine / postEngine — ALL engine HTTP calls
├── components/      Shared UI components
└── hooks/           React hooks for market/state data
```

---

## Technology Stack

| Layer | Technology |
|---|---|
| Engine language | Python 3.12 |
| Engine framework | FastAPI + Pydantic v2 |
| LLM provider | Anthropic Claude (via `engine/llm/`) |
| Market data | Polygon.io → yfinance fallback |
| Database | SQLite (paper mode), PostgreSQL (optional multi-instance) |
| Cache | Optional Redis |
| Broker | IB Gateway (paper port 4002) — paper mode only |
| Dashboard | Next.js 15, TypeScript, Tailwind CSS, SWR, Recharts |
| Package manager | pnpm (Node), pip with `--break-system-packages` (Python) |
| Testing | pytest (engine), TypeScript build check (dashboard) |
| Linting | ruff (Python) |
| Task scheduling | APScheduler (inside engine) |
| Alerting | Twilio WhatsApp (optional), Telegram (optional) |
