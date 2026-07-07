# JARVIS TRADER — Architecture

## High-Level Topology

```
┌──────────────────────────────────────────────────────────┐
│  DASHBOARD  (Next.js 15 / TypeScript — port 3010)        │
│  dashboard/app/**   ←→   dashboard/lib/api.ts            │
│  fetchEngine() / postEngine()  →  /api/engine/* rewrite  │
└────────────────────────┬─────────────────────────────────┘
                         │ HTTP + WebSocket
┌────────────────────────▼─────────────────────────────────┐
│  ENGINE  (FastAPI / Python 3.12 — port 8010)             │
│  engine/main.py  →  24 routers  →  80+ endpoints         │
│                                                           │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐  │
│  │ 5-Stage LLM  │   │  Safety      │   │  Learning    │  │
│  │  Pipeline    │   │  Layer       │   │  System      │  │
│  │ agents/      │   │ risk/        │   │ learning/    │  │
│  └──────────────┘   └──────────────┘   └──────────────┘  │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐  │
│  │  Markets     │   │  Backtest /  │   │  Execution   │  │
│  │ markets/     │   │  Signals     │   │ execution/   │  │
│  │              │   │ backtest/    │   │ (paper only) │  │
│  └──────────────┘   └──────────────┘   └──────────────┘  │
│                                                           │
│  data/  ·  database/  ·  portfolio/  ·  config.py        │
└────────────────────────┬─────────────────────────────────┘
                         │ API (paper mode)
┌────────────────────────▼─────────────────────────────────┐
│  IB GATEWAY  (port 4002 paper — port 4001 BLOCKED)       │
│  engine/execution/ib_order_manager.py                     │
└──────────────────────────────────────────────────────────┘
```

---

## Module Map

### `engine/main.py`
FastAPI application entry point. Wires all 24 routers via `app.include_router()`. Initializes all agents, injects dependencies, starts APScheduler, configures CORS, rate limiting, and API key middleware. 421 lines.

### `engine/config.py` — TradingConfig
Single source of truth for all risk parameters, API credentials (via environment), and feature flags. Loaded once at startup via `pydantic-settings`. Risk limits are:
- Max position: 5% portfolio
- Max contracts: 2 micro contracts
- Max overnight: 1 contract
- Max single order: $5,000
- Max margin utilization: 40%

### `engine/agents/` — 10 Agents

| Agent file | Role | Stage |
|---|---|---|
| `technical_analyst.py` | Price action, STC signal, regime | 1 (parallel) |
| `news_analyst.py` | News sentiment and event risk | 1 (parallel) |
| `social_analyst.py` | Reddit / social signal | 1 (parallel) |
| `fundamental_analyst.py` | Macro fundamentals, economic data | 1 (parallel) |
| `bull_researcher.py` | Constructs long thesis | 2 |
| `bear_researcher.py` | Constructs short thesis | 2 |
| `debate.py` (DebateOrchestrator) | Arbitrates bull/bear arguments | 2 |
| `trader.py` (TraderAgent) | Synthesizes → `TradeDecision` | 3 |
| `risk_manager.py` (RiskManagerAgent) | Full VETO power → `RiskDecision` | 4 |
| `fund_manager.py` (FundManagerAgent) | Portfolio-level approval → `FundDecision` | 5 |
| `pipeline.py` (TradingPipeline) | Orchestrates all stages | — |
| `schemas.py` | Pydantic models for all agent I/O | — |
| `thinkscript_generator.py` | Generates ThinkorSwim scripts | — |

**Pipeline contract**: Every agent has `.analyze(symbol)` (analysts) or `.argue(...)` / `.run_debate(...)` / `.make_decision(...)` methods. All return typed Pydantic objects. All are optional — missing agents degrade gracefully.

### `engine/risk/` — Safety and Risk

| File | Purpose |
|---|---|
| `safety_layer.py` | CANONICAL kill switch, order validation, hard limits — HARDCODED PYTHON |
| `pnl_monitor.py` | PnLMonitor — real-time P&L tracking against daily limits |
| `loss_tracker.py` | ConsecutiveLossTracker — streak-based position sizing reduction |
| `cross_market_risk.py` | Correlation risk across multiple open positions |

`SafetyLayer.validate_order(OrderRequest)` runs 6 sequential checks. Any failure = rejection. Order never reaches execution without passing all 6.

### `engine/backtest/signals.py` — CANONICAL Signal Source

Do not duplicate signal parameters anywhere else. `INSTRUMENT_PARAMS` dict holds per-instrument tuples: `(STC_OS, STC_OB, STOP_ATR, T1_ATR, T2_ATR, T3_ATR, REGIME_FILTER)`.

### `engine/markets/` — Multi-Market Framework

```
markets/
├── base.py          BaseMarketModule — interface all market modules implement
├── futures/         MCL, MNQ, MGC, MES futures modules
├── options/         Options chain, greeks, IV rank
├── crypto/          Crypto monitoring
└── polymarket/      Prediction market sentiment signal
```

Each market module is pluggable and registered with the orchestrator.

### `engine/learning/` — Learning System

| File | Responsibility |
|---|---|
| `pattern_extractor.py` | Mines trade outcomes for repeating patterns |
| `session_memory.py` | Holds working memory for the current trading session |
| `strategy_tuner.py` | Recommends parameter adjustments based on recent performance |
| `trade_classifier.py` | Tags trades by outcome type (momentum, reversal, range, etc.) |

### `engine/data/` — Market Data
`MarketDataManager` abstracts data sources. Primary: Polygon.io REST API. Fallback: yfinance. All callers use `MarketDataManager` — never call yfinance directly.

### `engine/execution/` — Order Execution
`IBOrderManager` manages IB Gateway connectivity. Paper mode uses port 4002. Live port 4001 is permanently blocked in code. All orders must pass `SafetyLayer.validate_order()` before reaching `IBOrderManager`.

### `engine/database/` — Persistence
`DatabaseManager` and `init_db` manage SQLite in paper mode. Repository pattern via `database/repository.py`. Schema defined in `database/schema.py`.

### `engine/portfolio/` — Portfolio Tracking
`PortfolioTracker` maintains position state, open P&L, and allocation percentages. Source of truth for portfolio-level decisions in FundManagerAgent.

### `engine/llm/` — LLM Client
Wraps the Anthropic API. `CostTracker` monitors and logs LLM API spend per agent and per session. Agents degrade gracefully when `ANTHROPIC_API_KEY` is absent.

### `engine/routers/` — 24 API Routers
Each router handles a functional area. Dependency injection is done via `inject_dependencies()` functions called in `main.py`. All routes are prefixed — see `COMMANDS.md` for the full endpoint catalog.

### `engine/middleware/`
- `APIKeyMiddleware` — validates `X-API-Key` header on all requests
- `rate_limit.py` — slowapi rate limiting

### `engine/websocket/` and `engine/hooks/`
WebSocket server for real-time dashboard updates. React hooks module (`engine/hooks/`) provides dashboard state and market data abstractions.

---

## Dashboard Architecture

### `dashboard/lib/api.ts`
The ONLY place dashboard → engine HTTP calls are made. All components import `fetchEngine<T>(path)` / `postEngine<T>(path, body)`. Never hardcode `localhost:8010` anywhere in component code.

### `dashboard/app/` — 16 Pages (Next.js App Router)

| Page | Route |
|---|---|
| Command Center | `/command-center` |
| Portfolio | `/portfolio` |
| Analysis | `/analysis` |
| Backtest | `/backtest` |
| Health | `/health` |
| Journal | `/journal` |
| Options | `/options` |
| Paper Trading | `/paper` |
| Performance | `/performance` |
| Polymarket | `/polymarket` |
| Scorecard | `/scorecard` |
| Settings | `/settings` |
| Stats | `/stats` |
| Strategies | `/strategies` |
| Validation | `/validation` |
| Watchlist | `/watchlist` |

### `dashboard/next.config.js`
Defines `/api/engine/*` → `http://localhost:8010/*` rewrite so components never need the engine URL directly.

---

## Request Flow — Trade Signal

```
APScheduler tick  (or /run endpoint)
    ↓
TradingPipeline.analyze_and_decide(symbol)
    ↓
Stage 1: asyncio.gather(technical, news, social, fundamental)
    ↓
Stage 2: BullResearcher + BearResearcher → DebateOrchestrator
    ↓
Stage 3: TraderAgent.make_decision(all_results) → TradeDecision
    ↓
Stage 4: RiskManagerAgent.validate(decision) → RiskDecision  [VETO]
    ↓
Stage 5: FundManagerAgent.approve(risk_decision) → FundDecision
    ↓
SafetyLayer.validate_order(OrderRequest)  [6 hard checks]
    ↓  (if approved AND human confirms)
IBOrderManager.submit_order()  [paper port 4002 only]
    ↓
database/repository.py  →  trade logged
learning/  →  outcome fed back
```

---

## Data Flow — Dashboard

```
Dashboard component (Server Component default)
    ↓ imports
dashboard/lib/api.ts → fetchEngine("/analysis/...")
    ↓ HTTP via Next.js rewrite
engine/routers/analysis_router.py → handler function
    ↓
engine/data/market_data.py  /  engine/database/repository.py
    ↓
JSON response → component renders
```

---

## Risky Surfaces

| Surface | Risk | Mitigation |
|---|---|---|
| `safety_layer.py` | Any change weakens hard limits | Tier 3 confirmation + test |
| `signals.py INSTRUMENT_PARAMS` | Bad params → bad signals → loss | Walk-forward validation required |
| `config.py` risk limits | Soft limits can be changed easily | Code review required |
| `LIVE_TRADING_ENABLED` flag | Flip = real money at risk | Hardcoded `False`; Phase 3 gate |
| IBOrderManager port config | Wrong port = live orders | Port 4001 blocked in code |
| Dashboard `fetchEngine` bypass | Hardcoded URLs break staging | Enforced by coding standard |
| `.env` file | Secrets exposure | `.gitignore` + `check-secrets.sh` |

---

## Test Architecture

```
engine/tests/
├── test_safety_layer.py       SACRED — must always pass, never skip
├── test_integration.py        28 tests — full pipeline integration
├── test_signals.py            Signal logic and parameter validation
├── test_pipeline_e2e.py       End-to-end pipeline with mocked LLM
├── test_paper_validation.py   Paper trading workflow
├── test_learning.py           Learning system modules
├── test_market_modules.py     Multi-market framework
├── test_orchestrator.py       Market orchestrator
├── test_rl_module.py          RL module (experimental)
├── test_rolling_wfe.py        Walk-forward evaluation
├── test_foundation.py         Core config and init
├── test_routes_wired.py       All 24 routers registered
├── test_auth_and_rate_limit.py API key + rate limit
├── test_api_contract_minimal.py Response shape contracts
├── test_loss_tracker.py       ConsecutiveLossTracker
├── test_integration_rl_endpoints.py  RL API integration
├── test_llm_client.py         LLM client + cost tracker
└── conftest.py                Shared fixtures
```
