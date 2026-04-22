# JARVIS TRADER — Session Handoff Document
## 2026-04-02 | Paper Validation Boot + Hardening Sprint

> Pass this file into Claude Code to resume work with full context.
> All secrets redacted. Engine .env has live values.

---

## Current State (as of 2026-04-02 ~04:30 CT)

### Stack Status

| Component | Status | URL/Port | Notes |
|-----------|--------|----------|-------|
| Engine (uvicorn) | RUNNING | http://localhost:8010 | v1.1.0, no --reload |
| Dashboard (Next.js) | RUNNING | http://localhost:3010 | pnpm dev |
| IB Gateway | CONNECTED | localhost:4002 | Paper mode, user wolfof216 |
| PostgreSQL | RUNNING | localhost:5432 | Docker container jarvis_postgres |
| Redis | RUNNING | localhost:6379 | Docker container jarvis_redis |
| Prometheus | RUNNING | localhost:9090 | Docker container jarvis_prometheus |
| Grafana | RUNNING | localhost:3030 | Docker container jarvis_grafana |
| QuestDB | UNHEALTHY | localhost:9000 | Non-blocking, investigate later |

### IB Gateway Connection

| Field | Value |
|-------|-------|
| Host | 127.0.0.1 |
| Port | 4002 (paper only — 4001 permanently blocked) |
| Client ID (running) | 10 (loaded before .env update) |
| Client ID (.env) | 2 (takes effect on next engine restart) |
| Install path | C:\Jts\ibgateway\1045\ibgateway.exe |
| IB Gateway version | 1045 |
| Paper account username | wolfof216 |
| Server version | 178 |
| Market data farms | usfarm OK, secdefnj OK |

### Portfolio

| Field | Value |
|-------|-------|
| Starting balance | $10,000.00 |
| Current balance | $11,772.33 |
| Daily P&L | +$1,772.33 |
| Drawdown | -1.10% (limit: -10%) |
| Open positions | 0 |
| Paper trades in DB | 98 |
| DB schema version | 6 |

### Safety Layer

| Check | Status |
|-------|--------|
| Kill switch | OFF (tested: activate + deactivate both work) |
| Daily P&L limit | -2% — NOT breached |
| Drawdown limit | -10% — NOT breached |
| Order rate | 0/min (limit: 10) |
| Consecutive losses | 0 (halt at 7) |
| Position size multiplier | 1.0x |
| LIVE_TRADING_ENABLED | False |
| REQUIRE_HUMAN_APPROVAL | True |
| PAPER_TRADING | True |

---

## 30-Day Paper Validation

**Started:** 2026-04-02
**Target completion:** 2026-05-02
**Approved instruments:** MCL 1h, MNQ 1h ONLY
**Halted:** MGC 1d (WFE 0.14, overfit)
**DO NOT TRADE:** MES 1h (WFE 0.09)

### Validation Thresholds (from GET /validation/targets)

| Metric | Threshold |
|--------|-----------|
| Profit Factor | > 2.0 |
| Sharpe Ratio | > 1.5 |
| Win Rate | > 55% |
| Min Trades | 60 |
| Min Days | 30 |
| Max Drawdown | < 15% |

### Current Progress (Day 1)

**MCL:** 3 trades (2W/1L), WR 66.67%, PF 2.75 — needs 57 more trades, 29 more days
**MNQ:** 2 trades (1W/1L), WR 50%, PF 1.333 — needs 58 more trades, 29 more days, edge improvement needed

---

## Configuration

### engine/.env (secrets redacted)

```bash
# TRADING MODE
PAPER_TRADING=True
PAPER_TRADING_BROKER=IB_GATEWAY
LIVE_TRADING_ENABLED=False
REQUIRE_HUMAN_APPROVAL=True
INITIAL_CAPITAL=10000.0

# IB GATEWAY
IBKR_HOST=127.0.0.1
IBKR_PORT=4002
IBKR_CLIENT_ID=2              # <-- Updated this session (was missing, defaulted to 1)
IBKR_CLIENT_ID_DATA=1         # Ignored by config.py (extra="ignore")
IBKR_CLIENT_ID_TRADE=2        # Ignored by config.py (extra="ignore")
IBKR_PAPER_MODE=True
IB_ACCOUNT_ID=YOUR_IBKR_ACCOUNT_ID  # TODO: set to actual paper account ID

# SAFETY & RISK
MAX_DAILY_LOSS_PCT=0.02
MAX_DRAWDOWN_PCT=0.10
MAX_POSITION_SIZE_PCT=0.05
MAX_CONTRACTS_PER_INSTRUMENT=2
MAX_OVERNIGHT_CONTRACTS=1
MAX_SINGLE_ORDER_VALUE=5000.0
MAX_MARGIN_UTILIZATION=0.40
PRICE_COLLAR_PCT=0.05
MAX_ORDERS_PER_MINUTE=10
MAX_CORRELATED_EXPOSURE_PCT=0.20
CONSECUTIVE_LOSS_HALF_SIZE=3
CONSECUTIVE_LOSS_QUARTER_SIZE=5
CONSECUTIVE_LOSS_HALT=7
CONSECUTIVE_LOSS_HALT_HOURS=24

# INSTRUMENTS
FUTURES_WATCHLIST=["MCL","MNQ"]       # Must be JSON arrays (Pydantic v2)
OPTIONS_WATCHLIST=["SPY","QQQ","AAPL","TSLA"]

# MARKET DATA
POLYGON_API_KEY=<set in .env>         # Polygon.io — free tier, rate limited

# LLM
ANTHROPIC_API_KEY=<set in .env>       # Anthropic Claude API
LLM_PROVIDER=anthropic

# NOTIFICATIONS
TWILIO_ACCOUNT_SID=<set in .env>      # WhatsApp via Twilio
TWILIO_AUTH_TOKEN=<set in .env>
TWILIO_WHATSAPP_FROM=<set in .env>
WHATSAPP_TO=<set in .env>

# API SECURITY
API_KEY=test-key                       # Must match dashboard NEXT_PUBLIC_ENGINE_API_KEY
```

### dashboard/.env.local

```bash
NEXT_PUBLIC_ENGINE_API_KEY=test-key
NEXT_PUBLIC_ENGINE_URL=http://localhost:8010
```

### config.py Key Settings

- `TradingConfig` uses `SettingsConfigDict(extra="ignore")` — stale .env fields are silently ignored
- `IBKR_CLIENT_ID` is the only client ID field read (singular, not _DATA/_TRADE variants)
- `API_KEY` defaults to `"jarvis-dev-key-change-me"` but .env overrides to `"test-key"`

---

## What Was Done This Session

### Phase 1: Boot (completed)

1. **Launched Docker Desktop** and `docker compose up -d` in infrastructure/
2. **Launched IB Gateway** at C:\Jts\ibgateway\1045\ibgateway.exe — logged in as wolfof216 (paper)
3. **Fixed .env**: Added `IBKR_CLIENT_ID=2` (config.py only reads this field, not _DATA/_TRADE)
4. **Fixed .env**: Added `API_KEY=test-key` (was missing, engine used default)
5. **Started engine**: `cd engine && .venv\Scripts\python -m uvicorn main:app --port 8010` (no --reload)
6. **Started dashboard**: `cd dashboard && pnpm dev`
7. **Created boot script**: `scripts/boot_paper_trading.bat`

### Phase 2: P0 Verification (completed)

Verified every system against the P0 checklist:

| Endpoint | Method | Result |
|----------|--------|--------|
| /health | GET | 200 — status: ok, paper_mode: true, ibkr_connected: true |
| /health/full | GET | 200 — all subsystems healthy, phase: paper_trading |
| /safety/status | GET | 200 — kill switch off, all limits clear |
| /safety/kill-switch/activate | POST | 200 — activates correctly |
| /safety/kill-switch/deactivate | POST | 200 — deactivates correctly |
| /safety/circuit-breakers | GET | 200 — all_clear: true |
| /safety/loss-tracker/status | GET | 200 — 0 consecutive losses, multiplier 1.0 |
| /system/preflight | GET | 200 — all_pass: true (8/8 checks) |
| /portfolio | GET | 200 — balance $11,772.33, 0 positions |
| /watchlist | GET | 200 — MCL, MNQ (futures) + SPY, QQQ, AAPL, TSLA (options) |
| /paper/validation/status | GET | 200 — MCL + MNQ progress with pass/fail per metric |
| /validation/targets | GET | 200 — PF>2.0, Sharpe>1.5, WR>55%, 60 trades, 30 days |
| /pipeline/run | POST | 200 — started async (0 LLM calls — see US-102) |
| /decisions/recent | GET | 200 — empty (no pipeline decisions yet) |
| /llm/stats | GET | 200 — 0 calls |
| /prices/snapshot | GET | 200 — rate limited (Polygon free tier — see US-103) |

Full report saved: `docs/reports/P0_VERIFICATION_2026-04-02.md`

### Phase 3: Hardening Sprint — 5 Parallel Agents (completed)

Created PRD with 5 user stories at `prd.json` and deployed 5 agents:

#### US-101: Fix /validation/progress SQL Error — DONE
- **Root cause:** SQL query in `engine/schedulers/validation_checker.py` referenced nonexistent columns: `contracts`, `outcome`, `daily_pnl` (should be `realized_pnl`), and `created_at` (should be `entry_time`)
- **Fix:** Updated SQL queries to use correct column names and indices
- **File:** `engine/schedulers/validation_checker.py`
- **Tests:** 25 safety + 24 validation tests pass

#### US-102: Fix Pipeline LLM Execution — DONE
- **Root cause:** `/pipeline/run` endpoint was a non-functional stub that returned `{"status": "running"}` without actually invoking the trading pipeline
- **Fix:** Rewrote endpoint to accept `PipelineRunRequest` body (`symbol`, `is_futures`), call `_trading_pipeline.analyze_and_decide()` via `asyncio.create_task()`
- **File:** `engine/routers/pipeline_router.py`

#### US-103: Price Cache and Polygon Rate Limiting — DONE
- **What:** New `engine/data/price_cache.py` (140 lines) — in-memory cache with 60s TTL, asyncio.Lock for thread safety
- **Features:** `retry_with_backoff()` with exponential backoff (1s/2s/4s), 429 errors return expired cache
- **Also:** Added `FRED_API_KEY` to `config.py` and `.env.example`
- **Files:** New `engine/data/price_cache.py`, updated `engine/routers/prices_router.py`, `engine/main.py`, `engine/config.py`, `engine/.env.example`
- **Tests:** 8 new tests in `engine/tests/test_price_cache.py`

#### US-104: Dashboard Paper Trading Badge — DONE
- **What:** Added `PAPER MODE` badge to `dashboard/app/page.tsx` header (shows when `health?.paper_mode`)
- **Also:** Fixed truncated `dashboard/package.json` (was missing closing brace)
- **Files:** `dashboard/app/page.tsx`, `dashboard/package.json`

#### US-105: Scheduler Status Endpoint — DONE
- **What:** Added `GET /pipeline/scheduler/status` endpoint with Pydantic response models
- **Returns:** Scheduler running state, jobs list with next_run times, total decisions count
- **File:** `engine/routers/pipeline_router.py`

### IMPORTANT: Engine restart required

All 5 fixes are written to disk but the running engine has NOT been restarted. The engine was started without `--reload`, so code changes are not live yet.

**To activate all fixes:**
```bash
# Kill the engine (Ctrl+C in the JARVIS Engine terminal)
# Then restart:
cd C:\Users\mattm\ThinkorSwim\jarvis-trader\engine
.venv\Scripts\python -m uvicorn main:app --port 8010
```

This will also pick up `IBKR_CLIENT_ID=2` from the .env.

---

## Live API Surface (80+ endpoints)

### Health & System
```
GET  /health                          — Basic health (no auth required)
GET  /health/full                     — Detailed subsystem health
GET  /system/preflight                — Pre-trading checklist (8 checks)
```

### Safety & Risk
```
GET  /safety/status                   — Kill switch, P&L, drawdown, order rate
POST /safety/kill-switch/activate     — Activate kill switch (?reason=)
POST /safety/kill-switch/deactivate   — Deactivate kill switch
GET  /safety/circuit-breakers         — All circuit breaker states
GET  /safety/loss-tracker/status      — Consecutive loss tracking
GET  /safety/position-sizing/calculate — Calculate position size
POST /safety/reset-daily-pnl          — Reset daily P&L counter
```

### Portfolio & Trading
```
GET  /portfolio                       — Balance, positions, margin
GET  /portfolio/health                — Portfolio health metrics
GET  /portfolio/summary               — Summary view
GET  /portfolio/paper/positions       — Paper trading positions
GET  /portfolio/paper/performance     — Paper trading performance
POST /portfolio/paper/trade           — Submit paper trade
GET  /portfolio/history/trades        — Trade history
GET  /portfolio/stats/streaks         — Win/loss streaks
POST /portfolio/halt                  — Halt trading
POST /portfolio/resume                — Resume trading
GET  /positions                       — Current positions
```

### Pipeline & Decisions
```
POST /pipeline/run                    — Run 5-stage analysis pipeline {symbol, is_futures}
POST /pipeline/scheduler/manual-scan  — Trigger manual watchlist scan
GET  /pipeline/scheduler/status       — Scheduler running state + jobs (NEW — US-105)
GET  /decisions/recent?limit=N        — Recent pipeline decisions
POST /decisions/log                   — Log a decision
```

### Analysis
```
POST /analyze/technical               — Technical analysis {symbol, is_futures, timeframe}
GET  /analyze/bars/{symbol}           — OHLCV bars {timeframe, days, futures}
GET  /prices/snapshot                 — All watchlist prices (cached — US-103)
GET  /watchlist                       — Tracked symbols
GET  /watchlist/{symbol}              — Single symbol detail
POST /watchlist/scan                  — Scan watchlist
```

### Macro & Sentiment
```
GET  /macro/snapshot                  — VIX, yields, DXY, regime (needs FRED_API_KEY)
GET  /macro/series/{series_id}        — FRED time series
GET  /sentiment/recent                — Cached Reddit sentiment
GET  /sentiment/reddit                — Fresh Reddit sentiment
GET  /sentiment/news/{symbol}         — News sentiment
```

### Paper Validation
```
GET  /paper/validation/status         — MCL + MNQ validation progress with pass/fail
GET  /paper/validation/progress       — Single instrument progress (default MCL)
GET  /paper/validation/trades         — Validation trade list
POST /paper/validation/record         — Record validation data
GET  /paper/runner-status             — Paper runner health
GET  /validation/progress             — Alt validation progress (FIXED — US-101)
GET  /validation/targets              — Validation thresholds
```

### Backtest & Strategy
```
POST /backtest/run                    — Run backtest
GET  /backtest/results                — Backtest results
GET  /backtest/walk-forward           — Walk-forward validation
GET  /backtest/regime-analysis        — Regime analysis
GET  /backtest/regime-status          — Current regime
GET  /backtest/paper-status           — Paper status
GET  /strategy/params                 — Strategy parameters
GET  /strategy/recommend              — Strategy recommendations
```

### LLM & Monitoring
```
GET  /llm/stats                       — LLM cost tracking (calls, cost, latency)
GET  /market/session                  — Current market session
GET  /market/earnings                 — Upcoming earnings
GET  /module/status                   — Module health
```

### Journal
```
GET  /journal/entries                 — Trade journal entries
POST /journal/entries                 — Create journal entry
GET  /journal/entries/{id}            — Single entry
GET  /journal/notes                   — Journal notes
POST /journal/notes                   — Create note
GET  /journal/tags                    — All tags
```

### Notifications
```
POST /pipeline/notifications/whatsapp/test  — Test WhatsApp
POST /pipeline/notifications/telegram/test  — Test Telegram
GET  /notifications/vix-alert-check         — VIX alert check
```

### Reports & RL
```
GET  /reports/performance/7d          — 7-day performance report
GET  /rl/status                       — Reinforcement learning status
GET  /rl/health                       — RL health
GET  /rl/models                       — RL models
POST /rl/train                        — Train RL model
POST /rl/evaluate                     — Evaluate RL model
```

### WebSocket
```
GET  /ws/status                       — WebSocket status
```

### Webhook
```
POST /webhook/tradingview             — TradingView webhook
POST /webhook/tradingview/test        — Test TV webhook
GET  /webhook/dedup-stats             — Dedup statistics
```

---

## Architecture Quick Reference

### 5-Stage LLM Pipeline (engine/agents/pipeline.py)
1. **Parallel Analysis:** TechnicalAnalyst, NewsAnalyst, SocialAnalyst, FundamentalistAgent
2. **Debate:** BullResearcher, BearResearcher, DebateOrchestrator
3. **Decision:** TraderAgent
4. **Risk:** RiskManagerAgent (VETO power)
5. **Approval:** FundManagerAgent

### Key Files

| File | Purpose |
|------|---------|
| engine/main.py | FastAPI app, lifespan, router registration |
| engine/config.py | TradingConfig (Pydantic v2 settings) |
| engine/risk/safety_layer.py | Kill switch, hard limits — SACRED, never modify |
| engine/agents/pipeline.py | 5-stage LLM pipeline orchestrator |
| engine/execution/ib_gateway.py | IB Gateway connection manager |
| engine/execution/ib_gateway_connector.py | Paper trading order wrapper |
| engine/data/market_data.py | Market data aggregation |
| engine/data/price_cache.py | Price cache with TTL (NEW — US-103) |
| engine/schedulers/validation_checker.py | Validation progress calculator (FIXED — US-101) |
| engine/routers/pipeline_router.py | Pipeline + scheduler endpoints (FIXED — US-102, US-105) |
| engine/routers/prices_router.py | Price snapshot endpoint (UPDATED — US-103) |
| dashboard/lib/api.ts | fetchEngine/postEngine — ALL dashboard API calls |
| dashboard/app/page.tsx | Main dashboard page (UPDATED — US-104) |
| dashboard/.env.local | API key + engine URL |

### Safety Rules (NON-NEGOTIABLE)
- `LIVE_TRADING_ENABLED = False` — paper mode until Phase 3
- `REQUIRE_HUMAN_APPROVAL = True` — always
- Safety layer is hardcoded Python — NEVER use LLM for safety
- Kill switch: -2% daily loss, -10% drawdown
- Port 4001 PERMANENTLY BLOCKED
- `engine/risk/safety_layer.py` is sacred — never modify without Tier 3

---

## Startup Commands (Windows)

```bash
# 1. Docker Desktop (manual launch)
# 2. Docker services
cd C:\Users\mattm\ThinkorSwim\jarvis-trader\infrastructure
docker compose up -d

# 3. IB Gateway (manual launch + login as wolfof216, paper mode, port 4002)
C:\Jts\ibgateway\1045\ibgateway.exe

# 4. Engine (no --reload to avoid IB client ID conflicts)
cd C:\Users\mattm\ThinkorSwim\jarvis-trader\engine
.venv\Scripts\python -m uvicorn main:app --port 8010

# 5. Dashboard
cd C:\Users\mattm\ThinkorSwim\jarvis-trader\dashboard
pnpm dev

# Or use the boot script:
C:\Users\mattm\ThinkorSwim\jarvis-trader\scripts\boot_paper_trading.bat
```

### Test Commands

```bash
# Engine tests
cd engine && .venv\Scripts\python -m pytest tests/ -v

# Dashboard build check
cd dashboard && pnpm run build

# Secrets check
bash scripts/hooks/check-secrets.sh

# Quick API health check (PowerShell)
curl.exe -s http://localhost:8010/health | python -m json.tool
curl.exe -s -H "X-API-Key: test-key" http://localhost:8010/safety/status | python -m json.tool
```

---

## Known Issues & Next Steps

### Issues to Fix

| # | Issue | Priority | Details |
|---|-------|----------|---------|
| 1 | Client ID mismatch | LOW | Engine running with client_id=10, .env says 2. Fix: restart engine |
| 2 | QuestDB unhealthy | LOW | Docker container starts but health check fails. Non-blocking |
| 3 | IB_ACCOUNT_ID not set | LOW | .env has placeholder. Set to actual paper account ID |
| 4 | FRED_API_KEY missing | MEDIUM | VIX uses fallback (18.0). Get key at https://fred.stlouisfed.org/docs/api/api_key.html |
| 5 | Polygon rate limits | MEDIUM | Free tier limits. Price cache added (US-103) but needs engine restart |

### Next Steps (Priority Order)

1. **Restart engine** to activate all 5 fixes + client_id=2
2. **Verify all fixes work** after restart:
   - `curl -H "x-api-key: test-key" http://localhost:8010/validation/progress` (US-101)
   - `curl -X POST -H "x-api-key: test-key" -H "Content-Type: application/json" -d '{"symbol":"MCL","is_futures":true}' http://localhost:8010/pipeline/run` then check `/llm/stats` (US-102)
   - `curl -H "x-api-key: test-key" http://localhost:8010/prices/snapshot` twice (US-103 cache)
   - Open http://localhost:3010 — verify PAPER MODE badge (US-104)
   - `curl -H "x-api-key: test-key" http://localhost:8010/pipeline/scheduler/status` (US-105)
3. **Get FRED API key** and add to .env for live VIX data
4. **Set IB_ACCOUNT_ID** in .env to actual paper account ID
5. **Run tests**: `cd engine && .venv\Scripts\python -m pytest tests/ -v`
6. **Dashboard build**: `cd dashboard && pnpm run build`
7. **Monitor daily** per runbook at `docs/runbooks/DAILY_ROUTINE.md`

### PRD Status

All 5 user stories COMPLETE (code written, awaiting engine restart for verification):

| Story | Title | Status |
|-------|-------|--------|
| US-101 | Fix /validation/progress SQL error | DONE |
| US-102 | Fix pipeline LLM execution | DONE |
| US-103 | Price cache + Polygon rate limiting | DONE |
| US-104 | Dashboard paper trading badge | DONE |
| US-105 | Scheduler status endpoint | DONE |

PRD file: `prd.json`
Progress log: `scripts/ralph/progress.txt`

---

## Files Created/Modified This Session

### New Files
- `scripts/boot_paper_trading.bat` — One-click boot script
- `docs/reports/P0_VERIFICATION_2026-04-02.md` — P0 verification report
- `engine/data/price_cache.py` — In-memory price cache with TTL (US-103)
- `engine/tests/test_price_cache.py` — 8 cache tests (US-103)

### Modified Files
- `engine/.env` — Added IBKR_CLIENT_ID=2, API_KEY=test-key
- `engine/config.py` — Added FRED_API_KEY field (US-103)
- `engine/.env.example` — Added FRED_API_KEY docs (US-103)
- `engine/schedulers/validation_checker.py` — Fixed SQL queries (US-101)
- `engine/routers/pipeline_router.py` — Rewrote /pipeline/run, added /pipeline/scheduler/status (US-102, US-105)
- `engine/routers/prices_router.py` — Integrated price cache (US-103)
- `engine/main.py` — Injected price_cache dependency (US-103)
- `dashboard/app/page.tsx` — Added PAPER MODE badge (US-104)
- `dashboard/package.json` — Fixed truncated JSON (US-104)
- `prd.json` — Updated with paper validation hardening stories
- `scripts/ralph/progress.txt` — Updated with all session learnings

---

## Daily Monitoring Checklist (from runbook)

### Morning (before 8:30am CT)
```bash
curl -s http://localhost:8010/health                                    # Engine up?
curl -s -H "x-api-key: test-key" http://localhost:8010/safety/status   # Kill switch?
curl -s -H "x-api-key: test-key" http://localhost:8010/prices/snapshot # Prices flowing?
```

### During RTH (8:30am-3:00pm CT, every 30 min)
```bash
curl -s -H "x-api-key: test-key" http://localhost:8010/safety/circuit-breakers  # All clear?
curl -s -H "x-api-key: test-key" http://localhost:8010/decisions/recent?limit=5 # Decisions?
curl -s -H "x-api-key: test-key" http://localhost:8010/llm/stats               # LLM cost?
```

### Evening (after 3:00pm CT)
```bash
curl -s -H "x-api-key: test-key" http://localhost:8010/paper/validation/status  # Progress?
curl -s -H "x-api-key: test-key" http://localhost:8010/portfolio/paper/performance # P&L?
```

---

*Generated 2026-04-02 ~04:30 CT | Engine v1.1.0 | Day 1 of 30-day paper validation*
