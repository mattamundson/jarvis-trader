# JARVIS TRADER

**AI-powered futures trading system with a 10-agent Claude pipeline and hardcoded safety layer**

> Version 0.1.0 | Status: Paper Trading Phase | All 10 Stories Complete ✓

---

## Table of Contents

1. [Validation Results — WFO Campaign](#validation-results--wfo-campaign)
2. [Quick Overview](#quick-overview)
3. [Architecture](#architecture)
4. [Tech Stack](#tech-stack)
5. [Quick Start](#quick-start)
6. [Project Structure](#project-structure)
7. [API Endpoints](#api-endpoints)
8. [Safety Layer](#safety-layer)
9. [Strategy](#strategy)
10. [Testing](#testing)
11. [Configuration](#configuration)
12. [Operational Scripts](#operational-scripts)
13. [Documentation Index](#documentation-index)
14. [Paper Trading](#paper-trading)

---

## Validation Results — WFO Campaign

This system uses a **gate v2** validation framework with seven independent statistical criteria. A strategy must pass walk-forward optimization (WFO) across 18 rolling 6-month/1-month train/test windows on real market data before any capital is risked. Failing any single gate is grounds for parking the strategy.

### Gate v2 Criteria (ALT path, $50K+ accounts)

| Metric | Threshold | What it tests |
|--------|-----------|---------------|
| `pf_ci_lower` | ≥ 1.10 | Lower 5% bound of bootstrapped OOS profit factor — robustness, not point estimate |
| `p_edge` | ≥ 0.95 | Fraction of OOS windows with PF > 1.0 — guards against single-window cherry-picks |
| `mc_95th_dd` | ≤ 7% | 95th-percentile Monte Carlo drawdown — bounds tail risk |
| `dsr` (deflated Sharpe) | ≥ 0.30 | Adjusts for multiple testing across grid combos |
| `wfo_consistency` | MODERATE/STRONG | ≥55% of windows profitable |
| `fixed_params_min_pf` | ≥ 1.20 | Worst combo on full dataset still profitable |
| `cost_survives_through` | ≥ realistic | Edge survives 4× expected commission + slippage |

### Live Validated Strategies (PASS gate v2)

| Symbol | Strategy | Champion Params | p_edge | DSR | MC DD | Consistency |
|--------|----------|-----------------|--------|-----|-------|-------------|
| **MES** (Micro S&P 500) | SMA Trend rank11 | fast=60, slow=200, ATR×2.0 | 0.75 | 1.0 | 0.81% | STRONG |
| **MGC** (Micro Gold) | SMA Trend rank4 | fast=50, slow=120, ATR×2.0 | 0.75 | 1.0 | 1.24% | STRONG |

Both pass via the ALT path (account size ≥$50K). Verdicts expire 30 days from creation and require IBKR data refresh + re-validation before extension.

### Strategies Evaluated and Parked (FAIL)

The campaign explored 7 distinct strategy/symbol combinations beyond the two PASSes. Each FAIL is documented with full verdict JSON in `engine/data/gate_v2_verdicts/`.

| Symbol | Family | Result | Root Cause |
|--------|--------|--------|------------|
| MNQ | SMA Trend ranks 1–2 | FAIL | Period scale mismatch — SMA crossovers too sparse in 2024–2025 bull regime; even short-period grid produced 0 OOS trades |
| MNQ | Breakout ranks 1–7 | FAIL | Non-stationarity confirmed (IS PF < 0.75 for windows 9–15); regime shift mid-2025 |
| MNQ | ORB rank 1 | FAIL | ATR/OR_range = 5–8× — stops blown by routine intraday volatility |
| MES | ORB rank 1 | FAIL | Despite favorable 2–3× ATR/OR ratio, p_edge = 0.18; ORB has no edge in current regime regardless of geometry |
| M2K | SMA Trend ranks 1–2 | FAIL | Rate-sensitivity whipsaws produce noise crossovers that don't correspond to genuine direction changes |
| MCL | Mean-Rev hyp A/B/C | FAIL | Crude is event-driven (OPEC, geopolitics), not technical-pattern-driven |
| MCL | SMA Trend hyp D/E | FAIL | Sparse signal frequency — daily crossovers <2/year insufficient for WFO |

**Why this matters for a public reader:** The two validated strategies are interesting, but the FAIL ledger is what demonstrates rigor. Most retail trading systems publish their wins. This system publishes every losing hypothesis with the metric values that killed it, because parameter tuning to rescue a fundamentally absent signal is the most common failure mode in quantitative trading.

### Engineering Patterns Worth Calling Out

- **Bootstrap CI on profit factor**, not point estimates — using the 5th-percentile lower bound of resampled PF means a strategy must be robust to which trades happened to land in the OOS window, not just lucky.
- **Inf-cap before percentile** — windows with zero losing trades produce `PF=inf`, which propagates NaN through `np.percentile` interpolation. Capping at 5.0 before the bootstrap is a small but load-bearing fix (`engine/backtest/run_mes_trend_rank11.py:380`).
- **Gate v2 ALT path for capital scale** — accounts ≥$50K can use looser drawdown/DSR thresholds because position-size diversification reduces tail-event impact. Smaller accounts must pass the stricter CORE gate. Single codebase, two thresholds, decided at runtime.
- **Routing layer separation** — `gate_v2_policy.is_ungate_eligible()` returns True if ANY non-stale PASS verdict exists for a symbol across all families. This decouples the question "does an edge exist for this symbol" from "which family generates the signal" — fixed in this campaign after a FAIL in one family was incorrectly blocking a PASS in another for the same symbol.

---

## Quick Overview

JARVIS TRADER is a fully autonomous futures trading system built on Claude Sonnet/Opus LLMs with a hardcoded safety layer that cannot be bypassed. The system uses a 10-agent pipeline to analyze market conditions, debate signals, execute trades, and enforce risk management in real time.

**Key Features:**
- **10 Claude Agents** across 5 pipeline stages (Analyst → Debate → Trader → Risk → Fund Manager)
- **Hardcoded Safety Layer** — 14 immutable risk rules cannot be overridden by LLM reasoning
- **Paper Trading Ready** — Full forward-test capability before live trading
- **82 REST Endpoints** — Complete API for monitoring, configuration, and control
- **Multi-Broker Support** — Interactive Brokers (IB Gateway), Charles Schwab, Alpaca
- **Real-Time Monitoring** — Prometheus metrics, Grafana dashboards, WebSocket events

---

## Architecture

### 5-Stage Pipeline with 10 Claude Agents

```
┌─────────────────────────────────────────────────────────────────┐
│                     MARKET DATA INPUT                            │
│  (Polygon, Finnhub, Alpaca | MES, MNQ futures | 5min bars)     │
└─────────────────────┬───────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  STAGE 1: ANALYST (3 agents)                        │ Sonnet 4.6 │
│  ┌─────────────────┬──────────────────┬──────────────────────┐  │
│  │ Technical Agent │ Fundamental Agent │ Sentiment Agent      │  │
│  │ (STC signals)   │ (macro analysis)  │ (market structure)   │  │
│  └─────────────────┴──────────────────┴──────────────────────┘  │
└─────────────────────┬───────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  STAGE 2: DEBATE (2 agents)                         │ Sonnet 4.6 │
│  ┌──────────────────────┬─────────────────────────────────────┐ │
│  │ Bull Case Agent      │ Bear Case Agent                     │ │
│  │ (Find longs)         │ (Find shorts)                       │ │
│  └──────────────────────┴─────────────────────────────────────┘ │
└─────────────────────┬───────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  STAGE 3: TRADER (2 agents)                         │ Opus 4.6   │
│  ┌──────────────────────┬─────────────────────────────────────┐ │
│  │ Long Entry Agent     │ Short Entry Agent                   │ │
│  │ (Size, stops, time)  │ (Size, stops, time)                 │ │
│  └──────────────────────┴─────────────────────────────────────┘ │
└─────────────────────┬───────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  STAGE 4: RISK MANAGER (1 agent)                    │ Opus 4.6   │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ Risk Veto Agent                                             │ │
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
│     IB Gateway (Paper/Live) | Schwab | Alpaca                   │
└─────────────────────────────────────────────────────────────────┘
```

### Agent Model Assignments

| Agent | Role | Model | Tier |
|-------|------|-------|------|
| Technical Analyst | STC signals, ATR stops/targets | Sonnet 4.6 | Mid |
| Fundamental Analyst | Macro economic signals | Sonnet 4.6 | Mid |
| Sentiment Analyst | Order flow, structure | Sonnet 4.6 | Mid |
| Bull Case Agent | Long entry thesis | Sonnet 4.6 | Mid |
| Bear Case Agent | Short entry thesis | Sonnet 4.6 | Mid |
| Long Entry Trader | Long order construction | Opus 4.6 | High |
| Short Entry Trader | Short order construction | Opus 4.6 | High |
| Risk Manager | Veto/approve orders | Opus 4.6 | High |
| Fund Manager | Final execution decision | Opus 4.6 | High |
| Position Monitor | Portfolio tracking (hardcoded) | N/A | Core |

---

## Tech Stack

### Engine

- **Language:** Python 3.11
- **Framework:** FastAPI 0.109+
- **LLM:** Anthropic Claude (Opus 4.6, Sonnet 4.6, Haiku 4.5)
- **Async Runtime:** asyncio + uvicorn
- **Code Quality:** Ruff (linter/formatter), mypy (type checking)

**Python Module Count:** 134 files | ~6,379 lines of code

### Dashboard

- **Framework:** Next.js 15 (React 19)
- **Language:** TypeScript 5
- **UI:** Tailwind CSS + shadcn/ui components
- **State Management:** React hooks + Context API
- **Real-Time:** WebSocket client for live updates

**TypeScript Module Count:** 156 files | ~7,437 lines of code

### Infrastructure

| Component | Purpose | Status |
|-----------|---------|--------|
| **PostgreSQL** | Order history, portfolio state, audit logs | Running |
| **Redis** | Caching, rate limiting, session store | Running |
| **QuestDB** | High-performance time-series (ohlcv bars) | Running |
| **Prometheus** | Metrics collection (orders/sec, P&L, drawdown) | Running |
| **Grafana** | Real-time dashboard and alerting | Running |
| **IB Gateway** | Interactive Brokers paper/live trading | Paper mode |
| **Twilio** | WhatsApp alerts (kill switch, errors) | Optional |

---

## Quick Start

### Prerequisites

- **macOS/Linux** (Windows requires WSL2)
- **Python 3.11+** with venv
- **Node.js 18+** with pnpm
- **Docker 24+** (for databases, optional if running locally)
- **API Keys:**
  - `ANTHROPIC_API_KEY` (Claude access)
  - `POLYGON_API_KEY` (market data)
  - `API_KEY` (FastAPI authentication)

### 1. Clone & Setup

```bash
cd /path/to/jarvis-trader
cp .env.example .env
nano .env  # Edit with real API keys
```

### 2. Start Infrastructure (Docker)

```bash
docker compose up -d
```

Waits for PostgreSQL, Redis, QuestDB, Prometheus, Grafana to be ready.

### 3. Start Engine

```bash
cd engine
python -m venv venv
source venv/bin/activate
pip install -r requirements-core.txt
python main.py
```

Engine runs on `http://localhost:8000`
Health check: `curl -H "X-API-Key: jarvis-dev-key" http://localhost:8000/health`

### 4. Start Dashboard

```bash
cd dashboard
pnpm install
pnpm dev
```

Dashboard runs on `http://localhost:3000`

### 5. Begin Paper Trading

```bash
./scripts/start_paper_trading.sh
```

See **[Paper Trading](#paper-trading)** section below.

---

## Project Structure

```
jarvis-trader/
├── engine/
│   ├── main.py                    # FastAPI app, route registration
│   ├── config.py                  # Configuration & env validation
│   ├── agents/                    # 10 Claude agents (pipeline stages)
│   │   ├── analyst.py             # Technical, Fundamental, Sentiment
│   │   ├── debater.py             # Bull/Bear case agents
│   │   ├── trader.py              # Long/Short entry agents
│   │   ├── risk_manager.py        # Risk veto logic
│   │   ├── fund_manager.py        # Final decision
│   │   └── pipeline.py            # 5-stage orchestration
│   ├── strategies/
│   │   ├── stc.py                 # Schaff Trend Cycle (STC)
│   │   ├── regime_filter.py       # 5-layer regime validation
│   │   └── signal_processor.py    # OHLCV → Signals
│   ├── risk/
│   │   ├── safety_layer.py        # 14 hardcoded kill switch rules
│   │   ├── loss_tracker.py        # Consecutive loss tracking
│   │   └── pnl_monitor.py         # P&L & drawdown monitoring
│   ├── execution/
│   │   ├── ib_gateway.py          # Interactive Brokers API
│   │   ├── schwab_connector.py    # Charles Schwab (OAuth)
│   │   └── alpaca_connector.py    # Alpaca Markets API
│   ├── database/
│   │   ├── models.py              # SQLAlchemy ORM
│   │   ├── postgres_manager.py    # PostgreSQL ops
│   │   └── migrations/            # Alembic schemas
│   ├── api/
│   │   ├── models.py              # Pydantic request/response
│   │   └── routes.py              # HTTP route handlers
│   ├── routers/                   # FastAPI APIRouter modules
│   ├── backtest/
│   │   ├── backtest_engine.py     # Historical simulation
│   │   ├── monte_carlo.py         # Monte Carlo scenarios
│   │   └── walk_forward.py        # Forward walk validation
│   ├── llm/
│   │   ├── client.py              # Anthropic API wrapper
│   │   └── token_counter.py       # Cost tracking
│   ├── notifications/
│   │   ├── whatsapp.py            # Twilio alerts
│   │   └── email.py               # SMTP
│   ├── websocket/
│   │   └── events.py              # Real-time streams
│   ├── monitoring/
│   │   ├── metrics.py             # Prometheus integration
│   │   └── health_monitor.py      # System health checks
│   ├── paper/
│   │   ├── paper_trading.py       # Paper trading logic
│   │   └── paper_portfolio.py     # Simulated execution
│   ├── cache/
│   │   └── redis_manager.py       # Redis operations
│   ├── tests/
│   │   ├── test_safety_layer.py   # 25 safety tests (100% pass)
│   │   ├── test_pipeline_e2e.py   # 27 pipeline tests (100% pass)
│   │   └── test_signals.py        # 32 signal tests (100% pass)
│   └── utils/
│       └── logging.py             # Structured JSON logging
│
├── dashboard/
│   ├── app/
│   │   ├── layout.tsx             # Root layout
│   │   ├── page.tsx               # Home page
│   │   ├── (auth)/                # Auth routes
│   │   ├── (trading)/             # Trading UI routes
│   │   └── api/                   # API integration
│   ├── components/
│   │   ├── TradingDashboard.tsx   # Main dashboard
│   │   ├── Chart.tsx              # TradingView charts
│   │   ├── PositionTable.tsx      # Active positions
│   │   ├── PnLMetrics.tsx         # Performance metrics
│   │   ├── OrderBook.tsx          # Live orders
│   │   └── SafetyStatus.tsx       # Kill switch, circuit breakers
│   ├── lib/
│   │   ├── api.ts                 # API client
│   │   └── utils.ts               # Helper functions
│   ├── package.json               # Dependencies (pnpm)
│   └── tsconfig.json              # TypeScript config
│
├── scripts/
│   ├── start_paper_trading.sh     # Launch paper trading
│   ├── stop_trading.sh            # Graceful shutdown
│   ├── health_check.sh            # System health
│   ├── daily_report.sh            # End-of-day P&L report
│   └── check-secrets.sh           # Pre-commit secret check
│
├── docs/
│   ├── ARCHITECTURE.md            # Design decisions
│   ├── API.md                     # OpenAPI documentation
│   └── DEPLOYMENT.md              # Production runbook
│
├── prd.json                       # All 10 user stories (100% complete)
├── TEST_RESULTS.md                # Test suite results (84/84 passing)
├── ENDPOINT_REGISTRY.md           # 82 endpoints documented
├── PAPER_TRADING_RUNBOOK.md       # Paper trading guide
├── SECURITY_REMEDIATION.md        # API key management
├── .env.example                   # Environment template
├── .gitignore                     # Git security
├── docker-compose.yml             # Infrastructure setup
└── pyproject.toml                 # Python project config
```

---

## API Endpoints

### Summary by Category

| Category | Count | Details |
|----------|-------|---------|
| Health & Diagnostics | 3 | `/health`, `/health/full`, `/system/preflight` |
| Safety & Risk | 9 | Kill switch, circuit breakers, loss tracker, config |
| Strategy | 6 | Parameters, signal generation, regime analysis |
| Pipeline & Decisions | 8 | Run pipeline, agent status, veto reasons |
| Portfolio | 7 | Positions, orders, P&L, cash |
| Backtesting | 5 | Monte Carlo, walk-forward, regime analysis |
| Watchlist & Data | 6 | Add/remove symbols, fetch bars, OHLCV |
| Notifications | 4 | WhatsApp test, email alerts, webhook config |
| Analytics & Reporting | 12 | Metrics, charts, daily/monthly reports |
| Execution | 8 | Submit order, cancel, modify, status |
| LLM & Tokens | 3 | Cost tracking, token usage, model config |
| WebSocket Events | 1 | Real-time connection `/ws/events` |

**Total: 82 REST endpoints + WebSocket**

See **[ENDPOINT_REGISTRY.md](ENDPOINT_REGISTRY.md)** for complete reference with request/response schemas.

### Example Calls

```bash
# Health check
curl -H "X-API-Key: jarvis-dev-key" http://localhost:8000/health

# Get safety status
curl -H "X-API-Key: jarvis-dev-key" http://localhost:8000/safety/status

# Activate kill switch
curl -X POST -H "X-API-Key: jarvis-dev-key" \
  "http://localhost:8000/safety/kill-switch/activate?reason=manual"

# Run full pipeline
curl -X POST -H "X-API-Key: jarvis-dev-key" -H "Content-Type: application/json" \
  -d '{"symbol": "MES", "timeframe": "5m"}' \
  http://localhost:8000/pipeline/run

# Get portfolio P&L
curl -H "X-API-Key: jarvis-dev-key" http://localhost:8000/portfolio/pnl
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
14. **Price Collar** — Reject orders > `5%` from NBBO (National Best Bid/Offer)

### Circuit Breaker Status

```bash
curl -H "X-API-Key: jarvis-dev-key" http://localhost:8000/safety/circuit-breakers
```

Response shows which rules are active/tripped and their current values.

### Position Sizing After Losses

After consecutive losses, position size automatically reduces:

- **0-2 losses:** 100% normal size
- **3-4 losses:** 50% normal size
- **5-6 losses:** 25% normal size
- **7+ losses:** TRADING HALTED for 24 hours

---

## Strategy

### Schaff Trend Cycle (STC) with ATR Stops & Targets

**STC Signal Generation:**

1. Compute fast EMA (fast period = 23)
2. Compute slow EMA (slow period = 50)
3. Calculate stochastic K and D on EMA difference
4. Apply smoothing (K period = 10)
5. Crossover detection:
   - **Bull Cross:** K crosses above D below 25 threshold
   - **Bear Cross:** K crosses below D above 75 threshold

**ATR Stop/Target Placement:**

```
Long Entry:
  Entry Price = STC crossover bar close
  Stop Loss = Entry - (2.0 × ATR)
  Target = Entry + (3.0 × ATR)

Short Entry:
  Entry Price = STC crossover bar close
  Stop Loss = Entry + (2.0 × ATR)
  Target = Entry - (3.0 × ATR)
```

### 5-Layer Regime Filter

Before any trade is approved, the system validates:

| Layer | Rule | Purpose |
|-------|------|---------|
| Layer 1 | Regime detection (uptrend, downtrend, range) | Avoid counter-trend trades |
| Layer 2 | Structure (higher high/low, lower high/low) | Confirm trend progression |
| Layer 3 | Bias (STRONG_BULL, LEAN_BULL, NEUTRAL, LEAN_BEAR, STRONG_BEAR) | Position bias alignment |
| Layer 4 | Entry confirmation (price action, volume) | Wait for clean setup |
| Layer 5 | Time-of-day filter (avoid last 30min of session) | Reduce slippage |

Only trades passing ALL 5 layers are forwarded to the trader agents.

---

## Testing

### Test Suite Coverage

| Module | Tests | Status | Pass Rate |
|--------|-------|--------|-----------|
| `test_safety_layer.py` | 25 | ✓ PASS | 100% |
| `test_pipeline_e2e.py` | 27 | ✓ PASS | 100% |
| `test_signals.py` | 32 | ✓ PASS | 100% |
| **Total** | **84** | **✓** | **100%** |

### Running Tests

```bash
# All tests
pytest engine/tests/ -v

# Specific module
pytest engine/tests/test_safety_layer.py -v

# With coverage
pytest engine/tests/ --cov=engine --cov-report=html

# Watch mode (requires pytest-watch)
ptw engine/tests/
```

### Test Infrastructure

- **Framework:** pytest with asyncio support
- **Fixtures:** Mock brokers, test data, configurations in `conftest.py`
- **Isolation:** Each test runs in a fresh event loop
- **Speed:** ~2 seconds for full suite

See **[TEST_RESULTS.md](TEST_RESULTS.md)** for detailed results and recent fixes.

---

## Configuration

### Environment Variables

All configuration via `.env` file. Copy `.env.example` and edit:

```bash
cp .env.example .env
nano .env
```

### Key Settings

| Variable | Type | Default | Purpose |
|----------|------|---------|---------|
| `API_KEY` | str | (required) | FastAPI X-API-Key header |
| `ANTHROPIC_API_KEY` | str | (required) | Claude API access |
| `POSTGRES_URL` | str | `postgresql://...` | Order history DB |
| `REDIS_URL` | str | `redis://localhost:6379` | Cache store |
| `POLYGON_API_KEY` | str | (optional) | Market data provider |
| `LIVE_TRADING_ENABLED` | bool | `False` | Enable real orders |
| `PAPER_TRADING` | bool | `True` | Simulate orders if enabled |
| `IBKR_HOST` | str | `127.0.0.1` | IB Gateway address |
| `IBKR_PORT` | int | `4002` | IB Gateway port (4002=paper) |
| `MAX_DAILY_LOSS_PCT` | float | `0.02` | Daily loss limit (-2%) |
| `MAX_DRAWDOWN_PCT` | float | `0.10` | Max drawdown (-10%) |
| `MAX_POSITION_SIZE_PCT` | float | `0.05` | Position cap (5%) |
| `LOG_LEVEL` | str | `INFO` | Logging verbosity |

See **[.env.example](.env.example)** for complete list with descriptions.

### Config Validation

On startup, `engine/config.py` validates:

- All required env vars are set and non-empty
- API keys have correct format
- Risk parameters are sensible
- Database URLs are reachable

Fails fast with clear error messages pointing to missing variables.

---

## Operational Scripts

### Portfolio & Verdict Tooling (Python — `engine/backtest/`)

These three tools are the operational interface to the gate v2 campaign. Run from `engine/` directory.

#### `show_verdict_history.py` — Portfolio dashboard

Single source of truth for what's currently validated, parked, or about to expire. Scans all gate v2 verdict files and prints a sorted summary table.

```bash
.venv/Scripts/python -m backtest.show_verdict_history
.venv/Scripts/python -m backtest.show_verdict_history --status PASS
.venv/Scripts/python -m backtest.show_verdict_history --expiring-soon
.venv/Scripts/python -m backtest.show_verdict_history --json   # for tooling
```

Returns exit code 1 if any PASS verdict is within 7 days of expiry — usable as a daily cron gate.

#### `live_readiness.py` — Phase 1 deployment gate

Single canonical check for all 7 mission-accomplished criteria. Returns exit code 0 only when every blocking check passes. Designed as the deployment-decision guard between "WFO campaign complete" and "live capital authorized."

```bash
.venv/Scripts/python -m backtest.live_readiness          # human-readable table
.venv/Scripts/python -m backtest.live_readiness --json   # for tooling
.venv/Scripts/python -m backtest.live_readiness --strict # advisory checks become blocking
```

Criteria checked: MES paper validation (30d/30 trades), second symbol validated, Phase 0 rotation complete, engine health stable, kill switch INACTIVE, all verdicts within 30-day TTL, `DO_NOT_TRADE_SYMBOLS` reflects verdict state.

#### `export_ibkr_history.py` — Verdict-refresh data prep

Fetches historical OHLCV bars from IB Gateway paper account (`127.0.0.1:4002`) and extends existing cache files. **Live port 4001 is permanently blocked** — paper port only.

```bash
# Refresh every PASS-verdict symbol in one command
.venv/Scripts/python -m backtest.export_ibkr_history --refresh-all-pass-verdicts

# Single symbol
.venv/Scripts/python -m backtest.export_ibkr_history --symbol MES --interval 1h

# Smoke-test without fetching
.venv/Scripts/python -m backtest.export_ibkr_history --refresh-all-pass-verdicts --dry-run
```

Required for verdict refresh because Polygon futures data is blocklisted; IBKR is the only valid source. Auto-detects gap from cache cutoff to current date.

#### `compare_verdicts.py` — Champion-param drift detection

Diffs an old verdict against a freshly-rerun verdict to answer the binary question after a refresh: did the champion hold or did the regime shift?

```bash
.venv/Scripts/python -m backtest.compare_verdicts \
    data/gate_v2_verdicts/archive/MES_trend_rank11.json \
    data/gate_v2_verdicts/MES_trend_rank11.json
```

Detects: verdict transitions (PASS↔FAIL, alt↔core), >10% champion-param drift, metric deltas, OOS sample-size changes, and symbol/family mismatch sanity-check failures.

Returns exit 0 if no drift (safe to commit refresh), 1 if review is needed.

#### Verdict refresh end-to-end workflow

Complete sequence when MES rank11 or MGC rank4 approach their 30-day TTL:

```bash
# 1. Bring up IB Gateway paper account (port 4002, API enabled, Read-Only OFF)

# 2. Refresh both PASS-verdict caches with fresh IBKR data
.venv/Scripts/python -m backtest.export_ibkr_history --refresh-all-pass-verdicts

# 3. Re-run each PASS verdict against the extended cache
.venv/Scripts/python -m backtest.run_mes_trend_rank11
.venv/Scripts/python -m backtest.run_mgc_trend_rank4

# 4. Diff the new verdict against the previous PASS to surface drift
.venv/Scripts/python -m backtest.compare_verdicts \
    data/gate_v2_verdicts/archive/MES_trend_rank11.json \
    data/gate_v2_verdicts/MES_trend_rank11.json

# 5. If drift is acceptable: commit the refreshed verdict
#    If champion params shifted significantly: design rank12 with new grid
git add data/gate_v2_verdicts/MES_trend_rank11.json
git commit -m "feat(backtest): refresh MES rank11 verdict — expiry extended"

# 6. Final readiness check
.venv/Scripts/python -m backtest.live_readiness
```

### Trading Stack Scripts (Bash — `scripts/`)

### `start_paper_trading.sh`

Launches the full paper trading stack:

```bash
./scripts/start_paper_trading.sh
```

**What it does:**
1. Validates all prerequisites (API keys, Docker, IB Gateway)
2. Starts engine + dashboard
3. Seeds initial portfolio state
4. Initializes data fetching
5. Begins monitoring loop

**Output:** Live dashboard at `http://localhost:3000`

### `stop_trading.sh`

Graceful shutdown:

```bash
./scripts/stop_trading.sh
```

**What it does:**
1. Closes all open positions
2. Saves portfolio state to database
3. Logs final P&L
4. Stops engine + dashboard cleanly

### `health_check.sh`

System diagnostics:

```bash
./scripts/health_check.sh
```

**Outputs:**
- Engine status (running/stopped, uptime)
- Database connectivity (PostgreSQL, Redis, QuestDB)
- IB Gateway connection
- API key validity
- Recent errors or warnings

### `daily_report.sh`

End-of-day P&L summary:

```bash
./scripts/daily_report.sh
```

**Generates:**
- Total P&L (realized + unrealized)
- Win rate and trade count
- Largest win/loss
- Sharpe ratio (if 30+ days of data)
- Consecutive losses
- Sends WhatsApp summary to Matt

### `check-secrets.sh`

Pre-commit security check:

```bash
./scripts/check-secrets.sh
```

**Prevents:**
- API keys from being committed
- `.env` file leaks
- Anthropic tokens in history

Runs automatically in git pre-commit hook.

---

## Documentation Index

### Core Documentation

| Document | Purpose |
|----------|---------|
| **[ENDPOINT_REGISTRY.md](ENDPOINT_REGISTRY.md)** | All 82 API endpoints with schemas |
| **[PAPER_TRADING_RUNBOOK.md](PAPER_TRADING_RUNBOOK.md)** | Step-by-step paper trading setup and operations |
| **[SECURITY_REMEDIATION.md](SECURITY_REMEDIATION.md)** | API key revocation and regeneration guide |
| **[TEST_RESULTS.md](TEST_RESULTS.md)** | Test suite status and coverage |
| **[CHANGELOG.md](CHANGELOG.md)** | Version history and updates |

### Module-Specific Docs

| Document | Coverage |
|----------|----------|
| **engine/IMPLEMENTATION_SUMMARY.md** | FastAPI routes, agent setup |
| **engine/LLM_CLIENT_INTEGRATION.md** | Anthropic client, cost tracking |
| **engine/CONSECUTIVE_LOSS_TRACKING.md** | Position sizing after losses |
| **engine/WALK_FORWARD_GUIDE.md** | Forward testing methodology |
| **engine/REDIS_IMPLEMENTATION_SUMMARY.md** | Caching strategy |
| **dashboard/IMPLEMENTATION_SUMMARY.txt** | Next.js components, charts |

### Quick References

- **[.env.example](.env.example)** — All environment variables
- **[prd.json](prd.json)** — All 10 user stories (acceptance criteria)
- **[JARVIS-TRADER-MASTER-REPORT.md](JARVIS-TRADER-MASTER-REPORT.md)** — Complete project status

---

## Paper Trading

### Current Phase

✓ **Phase 1: Development Complete** — All 10 stories delivered, tests passing, safety layer hardened
→ **Phase 2: Paper Trading** — 30-day forward test with IB Gateway
→ Phase 3: Live Trading (after successful paper test)

### Getting Started

```bash
# 1. Setup environment
cd /path/to/jarvis-trader
source .env

# 2. Start paper trading
./scripts/start_paper_trading.sh

# 3. Monitor in real-time
open http://localhost:3000

# 4. Check health
./scripts/health_check.sh

# 5. End of day
./scripts/daily_report.sh
```

### Success Criteria for 30-Day Test

- **Win Rate:** >= 50%
- **Sharpe Ratio:** >= 1.0
- **Max Consecutive Losses:** < 7
- **Max Drawdown:** < 10%
- **Slippage:** < 0.5% average
- **Execution Quality:** >= 95% fill rate

### Kill Switch Procedure

If any anomaly:

```bash
# Activate kill switch immediately
curl -X POST -H "X-API-Key: jarvis-dev-key" \
  "http://localhost:8000/safety/kill-switch/activate?reason=anomaly"

# Or use dashboard emergency button (big red button, top-right)
```

This closes all positions and suspends trading instantly.

### Transition to Live Trading

After 30 successful trading days:

1. Review 30-day backtest results in `/paper_trading_results.csv`
2. Get approval from risk committee (if any)
3. Update `.env`:
   ```bash
   LIVE_TRADING_ENABLED=true
   PAPER_TRADING=false
   IBKR_PORT=4001  # Switch from paper (4002) to live (4001)
   ```
4. Restart engine
5. Make first live trade manually to validate broker connection
6. Resume automated trading

See **[PAPER_TRADING_RUNBOOK.md](PAPER_TRADING_RUNBOOK.md)** for detailed instructions.

---

## Live Order Flow Feed

**Real-time ES micro-structure feed with self-monitoring and auto-recovery**

### Architecture

```
┌──────────────────────────────────────────────────────────────┐
│ Windows PC (ThinkorSwim)                                     │
│   └─ Tape Aggregation → flow_snapshot.json                  │
│        └─ Pusher Script (push_flow.py) every 5s             │
│             └─ HTTP POST → Vercel Dashboard                  │
└──────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────┐
│ Vercel Dashboard (/api/flow/ingest)                         │
│   ├─ Quality Validation Gates                               │
│   ├─ Vercel Blob Storage (flow/latest.json)                 │
│   └─ Health Check Endpoint (/api/flow/health)               │
└──────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────┐
│ Public Dashboard (/)                                         │
│   ├─ ● LIVE badge (data < 5s old)                           │
│   ├─ STALE (Xs) badge (data > 60s old)                      │
│   ├─ CVD + VWAP charts                                       │
│   ├─ Price gate visualization                                │
│   └─ Real-time 1m bars                                       │
└──────────────────────────────────────────────────────────────┘
```

### Monitoring Stack

| Layer | Tool | Purpose | Alert Channel |
|-------|------|---------|---------------|
| **External** | UptimeRobot | 5-min health check pings | Discord + Email |
| **Proactive** | Vercel Cron | 5-min data freshness checks | Discord |
| **Auto-Recovery** | Windows Watchdog | 5-min process + health checks, auto-restart | Logs |
| **Quality Gates** | Dashboard validation | Rejects unrealistic data at ingest | 400 response |

### Health Endpoint

```bash
curl https://jarvis-trader-dashboard.vercel.app/api/flow/health

# Response:
{
  "status": "live",          // "live" | "stale" | "offline"
  "age_seconds": 3,           // seconds since last update
  "last_update": "2026-10-27T03:15:42Z",
  "size_bytes": 2847
}
```

**Status thresholds:**
- **Live:** < 10 seconds
- **Stale:** 10-120 seconds
- **Offline:** > 120 seconds or blob unreachable

### Auto-Recovery (Watchdog)

**Script:** `scripts/tape/watchdog_flow_pusher.py`

Runs every 5 minutes via Windows Task Scheduler. Auto-restarts pusher if:
- Process (`pythonw.exe`) not running
- Data age > 120 seconds (via health endpoint check)

**Setup:**
```powershell
# PowerShell as Admin
$action = New-ScheduledTaskAction -Execute "python" `
  -Argument "C:\Users\mattm\ThinkorSwim\jarvis-trader\scripts\tape\watchdog_flow_pusher.py"
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
  -RepetitionInterval (New-TimeSpan -Minutes 5) `
  -RepetitionDuration ([TimeSpan]::MaxValue)
$settings = New-ScheduledTaskSettingsSet `
  -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries `
  -StartWhenAvailable
Register-ScheduledTask `
  -TaskName "JARVIS Flow Watchdog" `
  -Action $action `
  -Trigger $trigger `
  -Settings $settings
Start-ScheduledTask -TaskName "JARVIS Flow Watchdog"
```

### Data Quality Gates

Every ingest payload is validated before storage. Rejected if:

| Check | Threshold | Why |
|-------|-----------|-----|
| ES price range | 1000-10000 | Unrealistic price = data corruption |
| CVD magnitude | abs(CVD) < 10000 | Implausibly large cumulative delta |
| Price/VWAP divergence | abs(price - vwap) < 100 | Calculation error or stale VWAP |
| Bar integrity | volume >= 0, high >= low | Malformed OHLCV bars |
| Timestamp age | -60s to +300s | Clock skew or stale snapshot |
| Bars present | len(bars) > 0 | Missing aggregation data |

Validation failures return `400 Bad Request` with hint.

### Troubleshooting

See **[docs/runbooks/flow-feed-troubleshooting.md](docs/runbooks/flow-feed-troubleshooting.md)** for:
- Common issues (STALE DATA, FIXTURE DATA, 401/400 errors)
- Diagnosis commands
- Fix procedures
- Command reference
- Escalation path

**Quick checks:**
```bash
# Is pusher running?
tasklist | findstr pythonw

# Check health endpoint
curl https://jarvis-trader-dashboard.vercel.app/api/flow/health

# Watchdog status
Get-ScheduledTask -TaskName "JARVIS Flow Watchdog"

# Recent logs
cat $env:USERPROFILE\tape\logs\watchdog.log | tail -20
cat $env:USERPROFILE\tape\logs\push_flow.log | tail -50
```

### Success Metrics

After Phase 1-2 deployment (monitoring + auto-recovery):

| Metric | Target | How to Measure |
|--------|--------|----------------|
| Uptime | >99% | UptimeRobot dashboard |
| Data Freshness (P95) | <10s | Health endpoint `age_seconds` |
| Alert MTTD | <5 min | Discord timestamp - pusher crash time |
| Alert MTTR | <10 min | Watchdog auto-restart duration |
| Manual Interventions | 0/week | Count manual pusher restarts |

### Configuration

**Required env vars (Vercel):**
```bash
BLOB_READ_WRITE_TOKEN=<Vercel Blob token>
FLOW_INGEST_TOKEN=<same as pusher .env FLOW_INGEST_TOKEN>
CRON_SECRET=<openssl rand -base64 32>
DISCORD_WEBHOOK_FLOW_ALERTS=<Discord webhook URL>
```

**Pusher env vars (Windows `~/tape/.env`):**
```bash
FLOW_PUSH_URL=https://jarvis-trader-dashboard.vercel.app/api/flow/ingest
FLOW_INGEST_TOKEN=<same as Vercel FLOW_INGEST_TOKEN>
```

---

## Support

### Common Issues

**Engine won't start:**
```bash
# Check if API keys are set
grep -E "^(API_KEY|ANTHROPIC_API_KEY|POSTGRES_URL|REDIS_URL)" .env
# If empty, copy from .env.example and edit
```

**Dashboard shows "Cannot reach API":**
```bash
# Verify engine is running
curl -H "X-API-Key: jarvis-dev-key" http://localhost:8000/health
# If fails, restart engine
```

**Kill switch stuck "activated":**
```bash
# Requires manual deactivation
curl -X POST -H "X-API-Key: jarvis-dev-key" \
  http://localhost:8000/safety/kill-switch/deactivate
```

**Tests failing:**
```bash
# Ensure .env is in engine/ directory
cp .env engine/.env
# Re-run tests
pytest engine/tests/ -v
```

### Logs

```bash
# Engine logs (live)
tail -f logs/jarvis.log

# Docker logs
docker compose logs -f

# Dashboard console
open http://localhost:3000  # Then open browser DevTools
```

---

## Development

### Code Style

- **Formatter:** Ruff (`ruff format engine/`)
- **Linter:** Ruff (`ruff check engine/`)
- **Type Checking:** mypy (`mypy engine/`)
- **Pre-commit Hook:** Automatically checks secrets and formatting

### Contributing

1. Create feature branch from `main`
2. Write tests first (test-driven)
3. Implement feature
4. Ensure all tests pass: `pytest engine/tests/ -v`
5. Run linting: `ruff check engine/ && mypy engine/`
6. Commit with descriptive message
7. Push and open PR

---

## Project Stats

**Engine (Python)**
- 134 Python files
- ~6,379 lines of code
- 84 tests (100% passing)
- 92 FastAPI routes

**Dashboard (TypeScript)**
- 156 TypeScript files
- ~7,437 lines of code
- Real-time WebSocket updates
- Responsive mobile UI

**Infrastructure**
- PostgreSQL + Redis + QuestDB
- Prometheus metrics + Grafana dashboards
- Docker Compose orchestration
- Multi-broker abstraction

**Git History**
- 53 commits
- All 10 user stories completed
- Security hardening in place

---

## License

Proprietary — JARVIS TRADER v0.1.0
All rights reserved. Use only with explicit authorization.

---

**Ready to trade? Start with the [Quick Start](#quick-start) section above, then refer to [PAPER_TRADING_RUNBOOK.md](PAPER_TRADING_RUNBOOK.md).**
