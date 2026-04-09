# JARVIS TRADER

**AI-powered futures trading system with a 10-agent Claude pipeline and hardcoded safety layer**

> Version 0.2.0 | Status: Paper Trading Active | Python 3.12 | 467 Tests Passing

---

## Table of Contents

1. [Quick Overview](#quick-overview)
2. [Architecture](#architecture)
3. [Tech Stack](#tech-stack)
4. [Quick Start](#quick-start)
5. [IB Gateway Setup](#ib-gateway-setup)
6. [Project Structure](#project-structure)
7. [API Endpoints](#api-endpoints)
8. [Safety Layer](#safety-layer)
9. [Strategy](#strategy)
10. [Testing](#testing)
11. [Configuration](#configuration)
12. [Paper Trading Status](#paper-trading-status)
13. [Operational Scripts](#operational-scripts)
14. [Documentation Index](#documentation-index)

---

## Quick Overview

JARVIS TRADER is a fully autonomous futures trading system built on Claude Sonnet/Opus LLMs with a hardcoded safety layer that cannot be bypassed. The system uses a 10-agent pipeline to analyze market conditions, debate signals, execute trades, and enforce risk management in real time.

**Key Features:**
- **10 Claude Agents** across 5 pipeline stages (Analyst → Debate → Trader → Risk → Fund Manager)
- **Hardcoded Safety Layer** — 14 immutable risk rules cannot be overridden by LLM reasoning
- **Paper Trading Active** — MCL 1h (WFE=0.82) and MNQ 1h (WFE=0.57) running live on IB Gateway paper account
- **90+ REST Endpoints** across 25 routers — Complete API for monitoring, configuration, and control
- **Multi-Market Framework** — Futures, options, and crypto via pluggable module architecture
- **Learning System** — 4-module feedback loop (events, feedback, patterns, recommendations)
- **Real-Time Monitoring** — Prometheus metrics, Grafana dashboards, WebSocket events

---

## Architecture

### 5-Stage Pipeline with 10 Claude Agents

```
┌─────────────────────────────────────────────────────────────────┐
│                     MARKET DATA INPUT                            │
│  (Polygon, Finnhub, yfinance | MCL, MNQ futures | 1h bars)     │
└─────────────────────┬───────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  STAGE 1: ANALYST (4 agents)                        │ Sonnet 4.6 │
│  ┌──────────────┬───────────────┬────────────┬────────────────┐  │
│  │ Technical    │ Fundamental   │ Sentiment  │ Social         │  │
│  │ (STC signal) │ (macro/FRED)  │ (structure)│ (news flow)    │  │
│  └──────────────┴───────────────┴────────────┴────────────────┘  │
└─────────────────────┬───────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  STAGE 2: DEBATE (2 agents)                         │ Sonnet 4.6 │
│  ┌──────────────────────┬─────────────────────────────────────┐ │
│  │ Bull Case Agent      │ Bear Case Agent                     │ │
│  │ (Long thesis)        │ (Short thesis)                      │ │
│  └──────────────────────┴─────────────────────────────────────┘ │
└─────────────────────┬───────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  STAGE 3: TRADER (1 agent)                          │ Sonnet 4.6 │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ Trader Agent                                                │ │
│  │ (Entry decision, size, stops, targets)                     │ │
│  └────────────────────────────────────────────────────────────┘ │
└─────────────────────┬───────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  STAGE 4: RISK MANAGER (1 agent)                    │ Opus 4.6   │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ Risk Veto Agent — full VETO power                          │ │
│  │ Veto reason: position size, drawdown, margin, correlation  │ │
│  └────────────────────────────────────────────────────────────┘ │
└─────────────────────┬───────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  STAGE 5: FUND MANAGER (1 agent)                    │ Opus 4.6   │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ Fund Manager Final Decision                                 │ │
│  │ (Accept/Reject, final order sizing)                         │ │
│  └────────────────────────────────────────────────────────────┘ │
└─────────────────────┬───────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│            SAFETY LAYER (Hardcoded Python)                       │
│  14 Kill Switch Rules • Daily Loss Limit • Max Drawdown         │
│  Position Caps • Order Rate Throttle • Consecutive Loss Halt    │
└─────────────────────┬───────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                 BROKER EXECUTION                                 │
│     IB Gateway (Paper port 4002) | Schwab | Alpaca              │
└─────────────────────────────────────────────────────────────────┘
```

### Agent Model Assignments

| Agent | Role | Model | Tier |
|-------|------|-------|------|
| Technical Analyst | STC signals, ATR stops/targets | Sonnet 4.6 | Mid |
| Fundamental Analyst | Macro economic signals, FRED data | Sonnet 4.6 | Mid |
| Social Analyst | News flow, sentiment | Sonnet 4.6 | Mid |
| Sentiment Analyst | Order flow, market structure | Sonnet 4.6 | Mid |
| Bull Case Agent | Long entry thesis | Sonnet 4.6 | Mid |
| Bear Case Agent | Short entry thesis | Sonnet 4.6 | Mid |
| Trader Agent | Entry decision + order construction | Sonnet 4.6 | Mid |
| Risk Manager | Veto/approve orders (full veto power) | Opus 4.6 | High |
| Fund Manager | Final execution decision | Opus 4.6 | High |
| Position Monitor | Portfolio tracking (hardcoded) | N/A | Core |

### Multi-Market Framework

The `markets/orchestrator.py` manages multiple asset classes via pluggable modules:

- **Futures**: MCL (crude oil), MNQ (Nasdaq), MGC (gold), MES (S&P 500)
- **Options**: Greeks monitor, strategy executor, position manager
- **Crypto**: Pluggable module (disabled by default)

### Learning System

4-module feedback loop in `engine/learning/`:

- **Events** — Track all trading decisions and outcomes
- **Feedback** — Evaluate signal quality post-trade
- **Patterns** — Identify recurring market conditions
- **Recommendations** — Surface actionable tuning suggestions

---

## Tech Stack

### Engine

- **Language:** Python 3.12
- **Framework:** FastAPI 0.109+
- **LLM:** Anthropic Claude (Opus 4.6, Sonnet 4.6)
- **Async Runtime:** asyncio + uvicorn
- **Code Quality:** Ruff (linter/formatter)
- **Data Validation:** Pydantic v2

**Scale:** ~250+ source files | ~59,293 Python LOC | 90+ API endpoints across 25 routers

### Dashboard

- **Framework:** Next.js 15 (React 19)
- **Language:** TypeScript 5
- **UI:** Tailwind CSS + shadcn/ui components
- **State Management:** SWR for data fetching + React hooks
- **Real-Time:** WebSocket client for live updates
- **Build:** pnpm (system npm is broken — always use pnpm)

**Scale:** ~155 components | 18 dashboard pages | ~51,574 TSX/TS LOC

### Infrastructure

| Component | Purpose | Status |
|-----------|---------|--------|
| **PostgreSQL** | Order history, portfolio state, audit logs | Running (Docker) |
| **Redis** | Caching, rate limiting, session store | Running (Docker) |
| **QuestDB** | High-performance time-series (ohlcv bars) | Running (health check non-blocking) |
| **Prometheus** | Metrics collection (orders/sec, P&L, drawdown) | Running (Docker) |
| **Grafana** | Real-time dashboard and alerting | Running (Docker) |
| **IB Gateway** | Interactive Brokers paper/live trading | Paper mode (port 4002) |
| **Twilio** | WhatsApp alerts (kill switch, errors) | Configured |

---

## Quick Start

### Prerequisites

- **Windows 11** (native) or **macOS/Linux** (with shell adjustments)
- **Python 3.12** with venv at `engine/.venv/`
- **Node.js 18+** with **pnpm** (not npm — system npm is broken)
- **Docker 24+** for databases
- **Java 11+** for IB Gateway
- **API Keys:**
  - `ANTHROPIC_API_KEY` (Claude access)
  - `POLYGON_API_KEY` (market data)
  - `API_KEY` (FastAPI authentication — change from default)

### 1. Clone & Setup

```bash
cd jarvis-trader
cp engine/.env.example engine/.env
# Edit engine/.env with real API keys
```

### 2. Start Infrastructure (Docker)

```bash
docker compose -f infrastructure/docker-compose.yml up -d
```

Starts PostgreSQL, Redis, QuestDB, Prometheus, Grafana.

### 3. Start Engine

```bash
cd engine
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-core.txt
.venv/Scripts/python -m uvicorn main:app --port 8010
```

**Note:** Run WITHOUT `--reload` to avoid duplicate IB Gateway client connections.

Engine runs on `http://localhost:8010`
Health check: `curl -H "X-API-Key: your-api-key" http://localhost:8010/health`

### 4. Start Dashboard

```bash
cd dashboard
pnpm install
pnpm dev
```

Dashboard runs on `http://localhost:3010`

### 5. Windows One-Command Launch

```bat
start_jarvis.bat
```

Or use the PowerShell launch script with full safety verification:

```powershell
.\scripts\launch_paper_trading.ps1
```

---

## IB Gateway Setup

### Requirements

- IB Gateway installed at `C:\Jts\ibgateway\1045\ibgateway.exe` (version 1045+)
- Java 11+ required
- Paper trading account credentials

### Configuration

IB Gateway connects on **port 4002** (paper) — port 4001 (live) is permanently blocked in code.

```env
IBKR_HOST=127.0.0.1
IBKR_PORT=4002
IBKR_CLIENT_ID=10
```

### Launch IB Gateway

```powershell
Start-Process 'C:\Jts\ibgateway\1045\ibgateway.exe'
```

Then configure:
- **API Settings** → Enable ActiveX and Socket Clients
- **Socket Port**: 4002
- **Allow connections from localhost only**: checked

### Verify Connection

```bash
curl -H "X-API-Key: your-key" http://localhost:8010/health/full
```

Look for `ib_gateway.connected: true` in the response.

### Important: No --reload Flag

The engine **must not** use `--reload` when IB Gateway is active — the file watcher creates duplicate IB client connections. Use PM2 or plain uvicorn:

```bash
.venv/Scripts/python -m uvicorn main:app --port 8010
```

---

## Project Structure

```
jarvis-trader/
├── engine/
│   ├── main.py                    # FastAPI app, 421 lines, 25 routers
│   ├── config.py                  # TradingConfig — all risk parameters
│   ├── agents/                    # 10 Claude agents (5-stage pipeline)
│   │   ├── pipeline.py            # Orchestration entry point
│   │   ├── technical_analyst.py   # STC signals
│   │   ├── fundamental_analyst.py # Macro + FRED
│   │   ├── social_analyst.py      # News/sentiment
│   │   ├── bull_researcher.py     # Long thesis
│   │   ├── bear_researcher.py     # Short thesis
│   │   ├── trader.py              # Entry decision
│   │   ├── risk_manager.py        # Risk veto
│   │   ├── fund_manager.py        # Final decision
│   │   └── debate.py              # Bull/bear debate orchestration
│   ├── markets/
│   │   ├── orchestrator.py        # Multi-market coordinator
│   │   └── base.py                # MarketModule ABC
│   ├── learning/                  # 4-module learning system
│   ├── risk/
│   │   ├── safety_layer.py        # 14 hardcoded kill switch rules
│   │   └── pnl_monitor.py         # P&L & drawdown monitoring
│   ├── execution/
│   │   ├── ib_gateway.py          # IB Gateway connector
│   │   ├── ib_gateway_connector.py# Low-level IB API
│   │   └── schwab_connector.py    # Charles Schwab (OAuth)
│   ├── routers/                   # 25 FastAPI APIRouter modules
│   ├── backtest/
│   │   ├── backtester.py          # Historical simulation
│   │   ├── walk_forward.py        # 6m/3m walk-forward validation
│   │   ├── monte_carlo.py         # 10,000 simulation Monte Carlo
│   │   └── signals.py             # STC canonical params (Tier 3 to change)
│   ├── strategies/
│   │   ├── rl_agent.py            # RL trading agent (MES only, experimental)
│   │   ├── rl_environment.py      # Gym environment
│   │   └── rl_trainer.py          # Training loop
│   ├── options/                   # Greeks monitor, strategy executor
│   ├── portfolio/
│   │   └── tracker.py             # Paper portfolio tracker
│   ├── llm/
│   │   └── cost_tracker.py        # Anthropic API cost tracking
│   ├── notifications/
│   │   └── telegram.py            # Telegram alerts
│   ├── analytics/
│   │   ├── mtf_analyzer.py        # Multi-timeframe analysis
│   │   └── vix_overlay.py         # VIX regime overlay
│   └── tests/                     # 16 test files, 467 passing
│
├── dashboard/
│   ├── app/                       # Next.js App Router (18 pages)
│   │   ├── layout.tsx             # Root layout
│   │   ├── page.tsx               # Home / main dashboard
│   │   ├── command-center/        # Trading command center
│   │   ├── backtest/              # Backtest results
│   │   ├── scorecard/             # Performance scorecard
│   │   ├── settings/              # System settings
│   │   ├── stats/                 # Statistics
│   │   ├── options/               # Options chain viewer
│   │   ├── portfolio/             # Portfolio tracker
│   │   ├── strategies/            # Strategy management
│   │   ├── crypto/                # Crypto module
│   │   └── polymarket/            # Prediction markets
│   ├── components/                # ~155 components (dark terminal aesthetic)
│   ├── lib/
│   │   └── api.ts                 # fetchEngine/postEngine — ALL engine calls go here
│   └── hooks/                     # Custom React hooks
│
├── scripts/
│   ├── launch_paper_trading.ps1   # Full-safety paper trading launcher (PowerShell)
│   ├── stop_paper_trading.ps1     # Graceful shutdown
│   └── hooks/
│       └── check-secrets.sh       # Pre-commit secret scanner
│
├── infrastructure/
│   ├── docker-compose.yml         # Full stack (Postgres, Redis, QuestDB, Prometheus, Grafana)
│   └── docker-compose.paper.yml   # Paper trading variant
│
├── docs/                          # 97 markdown docs (~3.7 MB)
│   ├── architecture/              # System design, WebSocket, endpoint analysis
│   ├── runbooks/                  # Paper trading, IB connector, daily ops
│   ├── reports/                   # Verification reports, strategy analysis
│   ├── session-logs/              # Historical session logs + INDEX.md
│   └── plans/                     # Integrated roadmap
│
├── engine/prd.json                # Source of truth for PRD stories
├── engine/.env.example            # Environment template
├── start_jarvis.bat               # Windows quick-launch
├── LAUNCH_QUICK_START.md          # Paper trading launch guide
└── CLAUDE.md                      # AI agent instructions
```

---

## API Endpoints

### Summary by Category

| Category | Count | Details |
|----------|-------|---------|
| Health & Diagnostics | 4 | `/health`, `/health/full`, `/system/preflight`, `/api/v1/status` |
| Safety & Risk | 10 | Kill switch, circuit breakers, loss tracker, config, safety status |
| Strategy | 6 | Parameters, signal generation, regime analysis |
| Pipeline & Decisions | 8 | Run pipeline, agent status, veto reasons, decision log |
| Portfolio | 7 | Positions, orders, P&L, cash |
| Backtesting | 6 | Monte Carlo, walk-forward, optimizer, regime, comparison |
| Watchlist & Data | 6 | Add/remove symbols, fetch bars, OHLCV |
| Notifications | 4 | Telegram test, webhook config |
| Analytics & Reporting | 12 | Metrics, charts, daily/monthly reports |
| Execution | 8 | Submit order, cancel, modify, status |
| LLM & Tokens | 3 | Cost tracking, token usage, model config |
| Options | 8 | Greeks, chain, strategy execution |
| WebSocket Events | 1 | Real-time connection `/ws/events` |

**Total: 90+ REST endpoints + WebSocket**

### Example Calls

```bash
# Health check
curl -H "X-API-Key: your-api-key" http://localhost:8010/health

# Get safety status
curl -H "X-API-Key: your-api-key" http://localhost:8010/safety/status

# Activate kill switch
curl -X POST -H "X-API-Key: your-api-key" \
  "http://localhost:8010/safety/kill-switch/activate?reason=manual"

# Run full pipeline
curl -X POST -H "X-API-Key: your-api-key" -H "Content-Type: application/json" \
  -d '{"symbol": "MCL", "timeframe": "1h"}' \
  http://localhost:8010/pipeline/run

# Get portfolio P&L
curl -H "X-API-Key: your-api-key" http://localhost:8010/portfolio/pnl
```

---

## Safety Layer

The safety layer is **hardcoded in Python** and **cannot be overridden by LLM reasoning**. Every order passes through 14 immutable rules:

### 14 Hard Safety Rules

1. **Kill Switch** — Manual or automatic activation stops all trading immediately
2. **Live Trading Gate** — `LIVE_TRADING_ENABLED=False` blocks all real orders
3. **Human Approval** — All live orders require Matt's explicit approval
4. **Daily Loss Limit** — Halt at `-2%` cumulative daily loss
5. **Max Drawdown** — Emergency stop at `-10%` from equity peak
6. **Position Size Cap** — Max `5%` of portfolio per position
7. **Single Order Cap** — No order > `$5,000` value
8. **Order Rate Throttle** — Max `10` orders per minute
9. **Margin Utilization** — Never exceed `40%` available margin
10. **Correlated Exposure** — Max `20%` in correlated positions
11. **Futures Contract Limit** — Max `2` micro contracts per instrument
12. **Overnight Position Limit** — Max `1` contract held overnight
13. **Consecutive Loss Halt** — Auto-halt after `7` consecutive losses (24 hours)
14. **Price Collar** — Reject orders > `5%` from NBBO

### Circuit Breaker Status

```bash
curl -H "X-API-Key: your-api-key" http://localhost:8010/safety/circuit-breakers
```

### Position Sizing After Losses

After consecutive losses, position size automatically reduces:

- **0-2 losses:** 100% normal size
- **3-4 losses:** 50% normal size
- **5-6 losses:** 25% normal size
- **7+ losses:** TRADING HALTED for 24 hours

### Port 4001 Permanently Blocked

Port 4001 (IB Gateway live trading) is **permanently blocked** in code during the paper phase. This cannot be changed without explicit Tier 3 authorization.

---

## Strategy

### Schaff Trend Cycle (STC) with ATR Stops

The primary signal is the Schaff Trend Cycle oscillator with per-instrument parameters validated by walk-forward efficiency (WFE):

| Symbol | TF | STC OS | STC OB | ATR Stop | ATR T1 | WFE | Status |
|--------|----|--------|--------|----------|--------|-----|--------|
| MCL | 1h | 15 | 83 | 0.90x | 1.50x | **0.82** | APPROVED |
| MNQ | 1h | 15 | 92 | 0.70x | 1.00x | **0.57** | APPROVED |
| MGC | 1d | 17 | 88 | 0.30x | 1.50x | 0.14 | HALTED |
| MES | 1h | 15 | 83 | 0.50x | 2.00x | 0.09 | DO NOT TRADE |
| SPY | 1h | 15 | 88 | 0.30x | 1.00x | TBD | PENDING WF |

### Walk-Forward Efficiency (WFE)

WFE measures how well in-sample performance transfers out-of-sample:

- **WFE >= 0.50**: Approved for paper trading
- **WFE 0.20–0.49**: Under review
- **WFE < 0.20**: Halted — overfit or insufficient data

Recalculated every 4 weeks. Alert triggered if approved instrument drops below 0.40.

### 6-Tier VIX Regime Filter

| Tier | VIX Range | Label | Action |
|------|-----------|-------|--------|
| 1 | < 12 | VERY_LOW | Full size |
| 2 | 12–16 | LOW | Full size |
| 3 | 16–20 | NORMAL | Full size |
| 4 | 20–25 | ELEVATED | Half size |
| 5 | 25–35 | HIGH | Quarter size |
| 6 | > 35 | EXTREME | No new positions |

---

## Testing

### Test Suite Status (2026-04-02)

| Metric | Value |
|--------|-------|
| Total passing | **467** |
| Skipped | 28 (all legitimate) |
| Deterministic failures | **0** |
| Flaky tests | 1 (ordering-sensitive, passes in isolation) |
| Test files | 16 |

### Running Tests

```bash
# All tests (from engine/ directory)
cd engine && .venv/Scripts/python -m pytest tests/ -v

# Specific module
cd engine && .venv/Scripts/python -m pytest tests/test_safety_layer.py -v

# Safety tests (non-negotiable — must always pass)
cd engine && .venv/Scripts/python -m pytest tests/test_safety_layer.py -v

# Dashboard build check (TypeScript validation)
cd dashboard && pnpm run build
```

### Key Test Files

| File | Purpose |
|------|---------|
| `tests/test_safety_layer.py` | Safety invariants — must always pass |
| `tests/test_pipeline_e2e.py` | Full 5-stage pipeline |
| `tests/test_integration.py` | 28 integration tests |
| `tests/test_foundation.py` | Core utilities |
| `tests/test_learning.py` | Learning system |
| `tests/test_orchestrator.py` | Multi-market orchestrator |
| `tests/test_market_modules.py` | Market module integration |
| `tests/test_rl_module.py` | RL strategy (skipped if no model) |

---

## Configuration

### Environment Variables

All configuration via `engine/.env`. Copy from example:

```bash
cp engine/.env.example engine/.env
```

### Key Settings

| Variable | Type | Default | Purpose |
|----------|------|---------|---------|
| `API_KEY` | str | (required — change default) | FastAPI X-API-Key header |
| `ANTHROPIC_API_KEY` | str | (required) | Claude API access |
| `POSTGRES_URL` | str | `postgresql://...` | Order history DB |
| `REDIS_URL` | str | `redis://localhost:6379` | Cache store |
| `POLYGON_API_KEY` | str | (optional) | Market data provider |
| `LIVE_TRADING_ENABLED` | bool | `False` | Must stay False until Phase 3 |
| `PAPER_TRADING` | bool | `True` | Simulate orders |
| `IBKR_HOST` | str | `127.0.0.1` | IB Gateway address |
| `IBKR_PORT` | int | `4002` | IB Gateway port (4002=paper, 4001=BLOCKED) |
| `IBKR_CLIENT_ID` | int | `10` | IB client identifier |
| `MAX_DAILY_LOSS_PCT` | float | `0.02` | Daily loss limit (-2%) |
| `MAX_DRAWDOWN_PCT` | float | `0.10` | Max drawdown (-10%) |
| `MAX_POSITION_SIZE_PCT` | float | `0.05` | Position cap (5%) |
| `LOG_LEVEL` | str | `INFO` | Logging verbosity |
| `FUTURES_WATCHLIST` | json | `["MCL","MNQ"]` | Active instruments (JSON array) |

### Config Validation

On startup, `engine/config.py` validates all required env vars. Uses `extra="ignore"` in `SettingsConfigDict` to allow additional `.env` fields without error.

---

## Paper Trading Status

### Active Instruments (as of 2026-04-02)

| Symbol | Timeframe | WFE | Status | Notes |
|--------|-----------|-----|--------|-------|
| MCL | 1h | 0.82 | **ACTIVE** | Crude oil micro futures |
| MNQ | 1h | 0.57 | **ACTIVE** | Nasdaq micro futures |
| MGC | 1d | 0.14 | HALTED | Overfit, small-sample bias |
| MES | 1h | 0.09 | DO NOT TRADE | Overfit |

### IB Gateway Connection

- **Account**: wolfof216 (paper trading)
- **Port**: 4002
- **Client ID**: 10
- **Server Version**: 178
- **Status**: Connected and verified (2026-04-02)

### Phase Progress

- **Phase 1: Development** — Complete. All PRD stories delivered, safety layer hardened.
- **Phase 2: Paper Trading** — Active. MCL + MNQ running on IB Gateway paper account.
- **Phase 3: Live Trading** — Requires: 30-day paper test, win rate >= 50%, Sharpe >= 1.0, max DD < 8%.

### Success Criteria for Live Trading Transition

- **Win Rate:** >= 50% (paper gate: >= 45%)
- **Sharpe Ratio:** >= 1.0
- **Max Consecutive Losses:** < 7
- **Max Drawdown:** < 8%
- **Min Trade Count:** 60 trades over 60 days
- **Rolling WFE:** Stays above 0.40 on 4-week recalculation

---

## Operational Scripts

### Windows Launch

```bat
start_jarvis.bat          # Starts engine + dashboard
```

```powershell
.\scripts\launch_paper_trading.ps1           # Full safety verification + launch
.\scripts\launch_paper_trading.ps1 -SkipTests    # Skip tests (dev only)
.\scripts\launch_paper_trading.ps1 -SkipIBCheck  # Skip IB Gateway check
.\scripts\stop_paper_trading.ps1             # Graceful shutdown
```

### Engine Management (PM2)

```bash
pm2 start engine/ecosystem.config.js    # Start via PM2
pm2 logs jarvis-engine                  # Tail engine logs
pm2 restart jarvis-engine               # Restart
pm2 stop jarvis-engine                  # Stop
```

### Manual Commands

```bash
# Engine
cd engine && .venv/Scripts/python -m uvicorn main:app --port 8010

# Dashboard
cd dashboard && pnpm dev

# Tests
cd engine && .venv/Scripts/python -m pytest tests/ -v

# Linting
cd engine && .venv/Scripts/python -m ruff check .

# Dashboard build
cd dashboard && pnpm run build
```

---

## Documentation Index

### Core Documentation

| Document | Purpose |
|----------|---------|
| **[docs/strategic/README.md](docs/strategic/README.md)** | Strategic command center — executive brief, SWOT, risk register, execution spine, analysis protocol |
| **[LAUNCH_QUICK_START.md](LAUNCH_QUICK_START.md)** | Paper trading launch guide (PowerShell) |
| **[CLAUDE.md](CLAUDE.md)** | AI agent instructions and project overview |
| **[engine/CLAUDE.md](engine/CLAUDE.md)** | Engine-specific context |
| **[docs/session-logs/INDEX.md](docs/session-logs/INDEX.md)** | Complete session history |

### Runbooks

| Document | Coverage |
|----------|----------|
| **[docs/runbooks/P0_PAPER_IB_VERIFICATION.md](docs/runbooks/P0_PAPER_IB_VERIFICATION.md)** | IB Gateway + paper runner validation |
| **[docs/runbooks/IB_CONNECTOR_OVERVIEW.md](docs/runbooks/IB_CONNECTOR_OVERVIEW.md)** | IB connector architecture |
| **[docs/runbooks/DAILY_AUTOMATION.md](docs/runbooks/DAILY_AUTOMATION.md)** | Daily ops automation |
| **[docs/runbooks/ANTHROPIC_BILLING_AND_PIPELINE_SMOKE.md](docs/runbooks/ANTHROPIC_BILLING_AND_PIPELINE_SMOKE.md)** | LLM cost monitoring |
| **[docs/runbooks/SECURITY_OPERATOR_CHECKLIST.md](docs/runbooks/SECURITY_OPERATOR_CHECKLIST.md)** | Key rotation, kill-switch evidence, incident steps |
| **[docs/runbooks/PAPER_SOURCE_OF_TRUTH.md](docs/runbooks/PAPER_SOURCE_OF_TRUTH.md)** | Default paper ledger / dual-world rules |
| **[docs/runbooks/IB_RECONNECT_AND_HEALTH.md](docs/runbooks/IB_RECONNECT_AND_HEALTH.md)** | IB auto-reconnect limits + operator flow |
| **[docs/runbooks/HEALTH_API_CONTRACT.md](docs/runbooks/HEALTH_API_CONTRACT.md)** | `/health` and `/safety/*` JSON contract |
| **[docs/runbooks/SQLITE_BACKUP.md](docs/runbooks/SQLITE_BACKUP.md)** | Nightly DB backup, retention, on-demand endpoint |

### Architecture

| Document | Coverage |
|----------|----------|
| **[docs/architecture/WEBSOCKET.md](docs/architecture/WEBSOCKET.md)** | WebSocket event system |
| **[docs/architecture/CODEBASE_ANALYSIS_PASS_SUMMARY.md](docs/architecture/CODEBASE_ANALYSIS_PASS_SUMMARY.md)** | 10-agent codebase analysis |
| **[docs/reports/COMPREHENSIVE_PROJECT_ANALYSIS_2026-04-02.md](docs/reports/COMPREHENSIVE_PROJECT_ANALYSIS_2026-04-02.md)** | Full SWOT + 18 action items |

### Quick References

- **[engine/.env.example](engine/.env.example)** — All environment variables with descriptions
- **[engine/prd.json](engine/prd.json)** — PRD stories (source of truth)
- **[docs/plans/INTEGRATED_ROADMAP_2026-04.md](docs/plans/INTEGRATED_ROADMAP_2026-04.md)** — P0–P4 backlog

---

## Project Stats

**Engine (Python 3.12)**
- 250+ Python source files
- ~59,293 lines of code
- 467 tests passing (0 deterministic failures)
- 90+ FastAPI routes across 25 routers
- 5-day build velocity: 49 → 250+ files (March 28 → April 2, 2026)

**Dashboard (TypeScript / Next.js 15)**
- ~155 TypeScript components
- ~51,574 lines of code
- 18 dashboard pages
- Real-time WebSocket updates
- Dark terminal aesthetic

**Infrastructure**
- PostgreSQL + Redis + QuestDB
- Prometheus metrics + Grafana dashboards
- Docker Compose orchestration
- Multi-broker abstraction (IB Gateway, Schwab, Alpaca)

**Git History**
- Conventional commits (`feat:`, `fix:`, `refactor:`, `docs:`, `test:`)
- Full stack verified: engine + dashboard + IB Gateway + Docker (2026-04-02)

---

## Support

### Common Issues

**Engine won't start:**
```bash
# Verify API keys are set
type engine\.env | findstr ANTHROPIC_API_KEY

# Check venv
engine\.venv\Scripts\pip list | findstr fastapi

# Start manually with verbose output
cd engine && .venv/Scripts/python -m uvicorn main:app --port 8010
```

**Dashboard shows "Cannot reach API":**
```bash
# Verify engine is running
curl -H "X-API-Key: your-api-key" http://localhost:8010/health
```

**Kill switch stuck "activated":**
```bash
curl -X POST -H "X-API-Key: your-api-key" \
  http://localhost:8010/safety/kill-switch/deactivate
```

**Duplicate IB Gateway connection errors:**

Do not use `--reload` flag with uvicorn when IB Gateway is connected. Use plain uvicorn or PM2.

**QuestDB health check failing:**

This is non-blocking. QuestDB starts correctly but its HTTP health endpoint can fail intermittently. The engine handles this gracefully.

### Logs

```bash
# Engine logs (PM2)
pm2 logs jarvis-engine

# Docker infrastructure
docker compose -f infrastructure/docker-compose.yml logs -f

# Dashboard (dev mode terminal output)
cd dashboard && pnpm dev
```

---

## Security Notes

- **API keys have been exposed in git history** — rotate Anthropic, Polygon, Twilio, Google OAuth keys before live trading
- Change default `API_KEY` from `jarvis-dev-key-change-me` to a strong random key
- See `SECURITY_REMEDIATION.md` for rotation procedures
- Pre-commit hook (`scripts/hooks/check-secrets.sh`) prevents future leaks

---

## License

Proprietary — JARVIS TRADER v0.2.0
All rights reserved. Use only with explicit authorization.

---

**Paper trading active. Dashboard at http://localhost:3010 | Engine API at http://localhost:8010**
