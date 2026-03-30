# JARVIS TRADER

> AI-powered autonomous trading system for CME Micro Futures

**Status: MGC 1d ACTIVE (Paper Trading) | All 10 PRD User Stories Complete**

Built on a 5-stage LLM pipeline (Claude Opus), regime-adaptive STC signals, walk-forward validation, Monte Carlo simulation, and a full paper trading infrastructure with kill switch and WhatsApp alerts.

---

## Quick Start

### Engine (FastAPI, Python 3.12)

```bash
cd engine
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-core.txt
.venv\Scripts\python -m uvicorn main:app --reload --host 0.0.0.0 --port 8010
```

Or use the batch file:

```bash
start_jarvis.bat
```

- Health check: `http://localhost:8010/health`
- Full health: `http://localhost:8010/health/full`
- API docs: `http://localhost:8010/docs`

### Dashboard (Next.js 15)

```bash
cd dashboard
pnpm install
pnpm dev
```

- App: `http://localhost:3010`

### Verify Everything

```bash
curl http://localhost:8010/health/full
curl http://localhost:8010/paper/mgc-signal
curl http://localhost:3010
```

---

## Architecture

```
                    TradingView Alert
                          |
                    /webhook/tradingview
                          |
           Engine (FastAPI, port 8010)
           |
           +-- Stage 1: Data Collection (4 parallel agents)
           |     +-- Technical Analyst    (STC, ATR, regime classification)
           |     +-- News Analyst         (Finnhub headlines, sentiment scoring)
           |     +-- Social Analyst       (Reddit sentiment via API)
           |     +-- Fundamental Analyst  (macro data, sector context)
           |
           +-- Stage 2: Bull/Bear Debate
           |     +-- Bull Researcher      (builds long thesis)
           |     +-- Bear Researcher      (builds short thesis)
           |     +-- Debate Moderator     (synthesizes, scores conviction)
           |
           +-- Stage 3: Trade Decision
           |     +-- Trader Agent         (LONG / SHORT / HOLD + sizing)
           |
           +-- Stage 4: Risk Review
           |     +-- Risk Manager         (validates stops, position size, exposure)
           |
           +-- Stage 5: Fund Manager
           |     +-- Fund Manager         (final approval, portfolio-level context)
           |
           +-- Safety Layer
           |     +-- Kill switch (Tier 3 manual confirmation)
           |     +-- Circuit breakers (daily loss, max drawdown, max contracts)
           |     +-- Live port 4001 permanently blocked
           |
           +-- Execution
           |     +-- IB Gateway (paper: 4002 | live: 4001 LOCKED)
           |     +-- SQLite persistence (engine/data/jarvis_trader.db)
           |     +-- WhatsApp alerts via Twilio
           |
           +-- Scheduler
                 +-- APScheduler (EOD snapshot Mon-Fri 3:05 PM CT)
                 +-- Paper signal check (daily for MGC)

Dashboard (Next.js 15, port 3010)
  +-- /              Main dashboard (pipeline status, portfolio)
  +-- /paper         Paper trading monitor (MGC live signals)
  +-- /performance   P&L metrics and trade history
  +-- /validation    Paper trading validation vs backtest
  +-- /watchlist     Instrument monitor
  +-- /backtest      Backtest result browser
  +-- /analysis      Technical analysis view
  +-- /stats         Portfolio statistics
  +-- /journal       Trade notes
  +-- /health        System health monitor
  +-- /settings      Kill switch, risk params, IB connection
```

---

## Strategy Overview

**Signal**: Schaff Trend Cycle (STC) crossover with a 4-layer filter stack:

| Layer | Filter | Purpose |
|-------|--------|---------|
| 1 | Regime Map | EMA spread + BBWidth + ATR voting classifies trending/ranging/volatile |
| 2 | Structure | Price relative to key moving averages |
| 3 | Bias | Multi-timeframe trend alignment (4h for 1h entries) |
| 4 | Entry | STC oversold/overbought threshold crossover |

**Regime-Adaptive Parameters**: The `RegimeClassifier` dynamically adjusts STC thresholds based on detected market regime. This is the key innovation that took MGC walk-forward efficiency from 0.27 (overfit) to 0.88 (excellent).

**Position Sizing**: Fixed-fractional, 1% account risk per trade (0.25% during paper phase). Stops and targets are ATR-based.

**Execution**: CME Globex micro futures only (MGC, MNQ, MCL, MES, M2K). Commission model: $2.50/contract + 1 tick slippage.

---

## Performance Summary (as of 2026-03-29)

### Corrected In-Sample Results (Full Period)

| Rank | Symbol | TF | Trades | WR% | PF | Sharpe | Return | MaxDD | Status |
|------|--------|-----|--------|-----|------|--------|--------|-------|--------|
| 1 | MGC | 1d | 47 | 51.1 | 2.60 | 2.04 | +34.4% | 3.0% | **Paper Trading (adaptive)** |
| 2 | MNQ | 1h | 86 | 47.7 | 1.46 | 0.19 | +13.6% | 0.1% | Improving -- needs WFE > 0.40 |
| 3 | MCL | 1h | 65 | 60.0 | 1.83 | 0.15 | +0.2% | -- | DO NOT TRADE |
| 4 | SPY | 1h | 23 | 65.2 | 3.00 | -1.55 | +0.7% | 5.0% | DO NOT TRADE |
| 5 | MES | 1h | 21 | 42.9 | 0.96 | -0.12 | -4.0% | 0.1% | DO NOT TRADE |

*Test period: Jun 2024 -- Mar 2026 (1h) / Jan 2025 -- Mar 2026 (1d). Returns gross of commissions ($2.50/contract + 1 tick slippage).*

### Walk-Forward Efficiency (Critical Generalization Test)

| Symbol | TF | Static WFE | Adaptive WFE | OOS Profitable | Static Verdict | Adaptive Verdict |
|--------|-----|-----------|--------------|----------------|----------------|------------------|
| MGC | 1d | 0.27 | **0.88** | 2/3 (67%) | OVERFIT | **EXCELLENT -- Paper-trade ready** |
| MNQ | 1h | 0.24 | **0.34** | 3/6 (50%) | OVERFIT | ACCEPTABLE -- Needs WFE > 0.40 |
| MCL | 1h | -0.16 | **-0.31** | 2/6 (33%) | OVERFIT | FAIL -- Adaptive hurts MCL |
| MES | 1h | -0.17 | N/A | 1/6 (17%) | OVERFIT | Not tested (no edge) |
| SPY | 1h | -1.11 | N/A | 2/6 (33%) | OVERFIT | Not tested (random noise) |

**WFE thresholds**: > 0.70 = Excellent | 0.50-0.70 = Good | 0.30-0.50 = Marginal | < 0.30 = OVERFIT

### Monte Carlo Validation (MNQ 1h Adaptive, 10k Simulations)

| Metric | Value |
|--------|-------|
| Verdict | EXCELLENT |
| Probability profitable | 100.0% |
| Original return | +10.57% |
| Original max drawdown | 4.61% |
| Original Sharpe | 2.37 |
| Original PF | 1.44 |
| p5 max drawdown | 3.79% |
| p95 max drawdown | 9.18% |
| Median Sharpe | 2.41 |

---

## Paper Trading -- MGC 1d

**Active since 2026-03-29**

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Capital | $25,000 | Micro gold sizing |
| Risk/trade | 0.25% | Conservative start (quarter of standard 1%) |
| Stop | 0.30 ATR | Validated in walk-forward |
| T1 Target | 1.00 ATR | Intraday reachable |
| Adaptive Regime | ON | Key to WFE = 0.88 |
| Volume Filter | OFF | Daily volume data unreliable for MGC |
| Trailing Stop | OFF | No trailing config beats baseline |
| Kill threshold | 3 consecutive months > 50% below IS baseline (3.8% per 3-month window) |

**In-sample benchmark**: Avg IS return 7.6% per 3-month window. OOS avg return +6.7%, OOS avg Sharpe 0.89, OOS avg PF 2.55.

### Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/paper/mgc-signal` | GET | Current MGC signal (regime, STC, entry/exit levels) |
| `/paper/mgc-performance` | GET | Paper trading P&L, trade history, drawdown |
| `/paper/mgc-log-trade` | POST | Log an executed paper trade |
| `/paper/pending-signals` | GET | Signals awaiting execution |
| `/backtest/paper-status` | GET | Paper config, kill-switch state |

---

## Dashboard Pages

| Route | Page | Description |
|-------|------|-------------|
| `/` | Main Dashboard | Pipeline status, portfolio overview, recent decisions |
| `/paper` | Paper Trading | MGC live signal monitor, current regime, P&L tracker |
| `/performance` | Performance | P&L metrics, equity curve, trade history |
| `/validation` | Validation | Paper trading results vs backtest expectations |
| `/watchlist` | Watchlist | Multi-instrument monitor with price snapshots |
| `/backtest` | Backtest | Browse and compare all backtest result files |
| `/analysis` | Analysis | Technical analysis view (STC, regime, indicators) |
| `/stats` | Statistics | Portfolio-level stats, drawdown analysis |
| `/journal` | Journal | Manual trade notes and observations |
| `/health` | Health | System health, service status, connectivity |
| `/settings` | Settings | Kill switch toggle, risk parameters, IB connection |

---

## Engine API Endpoints

### Core

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Basic health check |
| `/health/full` | GET | Full system health (DB, scheduler, safety, IB) |
| `/pipeline/run` | POST | Execute full 5-stage AI pipeline for a symbol |
| `/pipeline/status` | GET | Current pipeline execution status |
| `/pipeline/history` | GET | Historical pipeline run results |
| `/scheduler/status` | GET | Scheduler state and next run times |
| `/scheduler/scan-now` | POST | Manually trigger a pipeline scan |

### Safety

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/safety/kill-switch/activate` | POST | Activate kill switch (halt all trading) |
| `/safety/kill-switch/deactivate` | POST | Deactivate kill switch |
| `/safety/status` | GET | Current safety layer state |
| `/safety/circuit-breakers` | GET | Circuit breaker thresholds and status |
| `/safety/config` | GET | Safety configuration |
| `/safety/reset-daily-pnl` | POST | Reset daily P&L counter |

### Portfolio and Trading

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/portfolio` | GET | Current portfolio state |
| `/portfolio/paper/positions` | GET | Open paper positions |
| `/portfolio/paper/trade` | POST | Execute a paper trade |
| `/portfolio/paper/performance` | GET | Paper trading performance metrics |
| `/portfolio/history/trades` | GET | Trade history |
| `/portfolio/history/daily-pnl` | GET | Daily P&L history |
| `/portfolio/history/decisions` | GET | Decision log |
| `/portfolio/stats/summary` | GET | Portfolio statistics |
| `/portfolio/stats/drawdown` | GET | Drawdown analysis |
| `/position-sizing/calculate` | GET | Calculate position size for given parameters |

### Analysis and Data

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/analyze/technical` | POST | Run technical analysis on a symbol |
| `/analyze/bars/{symbol}` | GET | OHLCV bar data |
| `/sentiment/reddit` | GET | Reddit sentiment scores |
| `/sentiment/news/{symbol}` | GET | News sentiment for a symbol |
| `/macro/snapshot` | GET | Macro economic snapshot |
| `/macro/series/{series_id}` | GET | Specific macro data series |
| `/prices/snapshot` | GET | Current price snapshot for watchlist |

### Backtest and Research

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/backtest/results` | GET | List all backtest result files |
| `/backtest/run` | POST | Run a backtest with specified parameters |
| `/backtest/regime-status` | GET | Current regime classification |
| `/backtest/monte-carlo` | POST | Run Monte Carlo simulation |
| `/backtest/monte-carlo/chart` | POST | Generate Monte Carlo visualization |

### Notifications

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/notifications/whatsapp/test` | POST | Send a test WhatsApp message via Twilio |
| `/thinkscript/generate` | POST | Generate ThinkScript code from strategy params |

---

## Development

### Running Backtests

```bash
cd engine

# Standard backtest
.venv\Scripts\python -m backtest.run_backtest --symbol SPY --start 2024-06-01 --end 2026-03-27 --interval 1h

# With adaptive regime
.venv\Scripts\python -m backtest.run_backtest --symbol MGC --start 2025-01-01 --end 2026-03-27 --interval 1d --adaptive

# Parameter optimization
.venv\Scripts\python -m backtest.optimizer --symbol SPY --start 2024-06-01 --end 2026-03-27 --interval 1h
```

Results are saved to `engine/backtest/results/` as JSON.

### Walk-Forward Validation

Walk-forward validation splits data into rolling train/test windows to measure out-of-sample generalization. WFE (Walk-Forward Efficiency) is the ratio of OOS performance to IS performance.

```bash
cd engine
.venv\Scripts\python -m backtest.walk_forward --symbol MGC --interval 1d --adaptive
```

### Monte Carlo Simulation

Shuffles trade ordering 10,000 times to build a distribution of possible outcomes and measure tail risk.

```bash
# Via API
curl -X POST http://localhost:8010/backtest/monte-carlo \
  -H "Content-Type: application/json" \
  -d '{"symbol": "MNQ", "interval": "1h", "n_simulations": 10000}'
```

### Testing

```bash
cd engine

# Integration tests
.venv\Scripts\python -m pytest tests/test_integration.py -v

# Simulate a paper trade
curl -X POST "http://localhost:8010/test/simulate-trade?symbol=MES&side=LONG&entry_price=5250&exit_price=5255"

# Simulate a batch (generates performance data)
curl -X POST "http://localhost:8010/test/simulate-batch?count=15&win_rate=0.6"

# Trigger EOD snapshot manually
curl -X POST "http://localhost:8010/test/eod-snapshot"

# Check performance metrics
curl http://localhost:8010/analytics/performance
```

### Building the Daily Cache

Yahoo Finance rate-limits futures data. Use the cache builder for 2025 daily bars:

```bash
cd engine
.venv\Scripts\python -m backtest.build_daily_cache_2025
```

This builds SPY daily from cached 1h data and proxies ES=F levels via SPY daily returns when Yahoo blocks ES=F directly.

---

## Research Findings

Eight phases of systematic research produced the following key findings:

### Phase A: Bug Fixes (Critical)

Eight bugs were identified and fixed in the backtesting engine before any results could be trusted:
- Stop-loss calculation error (was using wrong ATR period)
- Look-ahead bias in signal generation
- EOD exit logic not accounting for partial fills
- Commission model was applying per-share instead of per-contract
- Sharpe ratio calculation using wrong annualization factor
- Duplicate trade entries on bar boundaries
- Regime filter applied after entry instead of before
- ATR lookback mismatch between optimizer and backtester

**Impact**: Median profit factor dropped from inflated values to 0.96 after corrections.

### Phase B: 12-Matrix Scan

Six symbols (SPY, MES, MNQ, MCL, MGC, M2K) across two timeframes (1h, 1d) yielded 12 combinations. Only 5 of 12 (42%) were profitable after corrections.

### Phase C: Walk-Forward Validation

All 5 profitable combinations failed static walk-forward validation (WFE < 0.30). Key finding: **73-90% of in-sample edge evaporates on unseen data with static parameters.**

### Phase D: Monte Carlo + Sensitivity

Monte Carlo (10k simulations per instrument) confirmed the edge is real but thin. Parameter sensitivity analysis scored 94-95/100 across three instruments, indicating high sensitivity to parameter choices.

### Phase E: Research Report

A 1,245-line research report (`engine/docs/BACKTEST_RESEARCH_REPORT.md`) documents all findings with statistical rigor.

### Phase F: Regime-Adaptive STC

The `RegimeClassifier` (EMA spread + BBWidth + ATR voting) dynamically adjusts STC thresholds per regime. Results:
- MGC 1d: WFE 0.27 to **0.88** (+226%) -- EXCELLENT
- MNQ 1h: WFE 0.24 to **0.34** (+41%) -- needs more work

### Phase G: Signal Improvements

| Improvement | Impact |
|-------------|--------|
| Volume filter (20-SMA gate) | MNQ WR 47.7% to 60.0%, PF 1.46 to 2.36 |
| Multi-timeframe (4h alignment) | 20.6% counter-trend entries blocked |
| News/event blackout (81 events) | ~1% signals blocked (live safety net) |
| Trailing ATR stop | No configuration beats fixed baseline |

### Phase H: Paper Trading Infrastructure

Full paper trading system: PaperTracker, daily signal scheduler, live API endpoints, dashboard page, WhatsApp alerts, kill-switch integration.

---

## Optimal Parameters (Per Instrument)

| Param | MGC 1d | MNQ 1h | MCL 1h | SPY 1h |
|-------|--------|--------|--------|--------|
| STC_OS | 17 | 15 | 15 | 15 |
| STC_OB | 88 | 92 | 83 | 88 |
| Stop ATR | 0.30 | 0.70 | 0.90 | 0.30 |
| T1 ATR | 1.50 | 1.00 | 1.50 | 1.00 |
| T2 ATR | 2.618 | 1.80 | 2.618 | 1.80 |
| Regime Filter | ON | ON | ON | ON |

---

## File Structure

```
jarvis-trader/
+-- engine/                         FastAPI backend (Python 3.12)
|   +-- main.py                     API app, all route definitions (~2200 lines)
|   +-- .env                        Environment variables (not committed)
|   +-- requirements-core.txt       Python dependencies
|   +-- agents/                     LLM pipeline agents
|   |   +-- pipeline.py             5-stage orchestrator
|   |   +-- technical_analyst.py    STC + regime analysis
|   |   +-- news_analyst.py         Finnhub news sentiment (placeholder)
|   |   +-- social_analyst.py       Reddit sentiment
|   |   +-- fundamental_analyst.py  Macro/fundamental context
|   |   +-- bull_researcher.py      Bull thesis builder
|   |   +-- bear_researcher.py      Bear thesis builder
|   |   +-- debate.py               Debate moderator
|   |   +-- risk_manager.py         Risk validation
|   |   +-- fund_manager.py         Final approval
|   |   +-- rules/                  Agent rule definitions
|   |   +-- schemas.py              Pydantic models for agent I/O
|   +-- backtest/                   Backtesting and research engine
|   |   +-- backtester.py           Core backtest loop
|   |   +-- signals.py              Signal generation (STC crossover + filters)
|   |   +-- indicators.py           Technical indicator calculations
|   |   +-- regime.py               RegimeClassifier (EMA spread + BBWidth + ATR)
|   |   +-- mtf_filter.py           Multi-timeframe filter (4h alignment)
|   |   +-- optimizer.py            Parameter grid search
|   |   +-- walk_forward.py         Walk-forward validation (local module)
|   |   +-- monte_carlo.py          Monte Carlo simulation (10k sims)
|   |   +-- sensitivity.py          Parameter sensitivity analysis
|   |   +-- paper_config.py         Paper trading configuration
|   |   +-- paper_tracker.py        Paper trade tracking and P&L
|   |   +-- data_loader.py          Yahoo Finance data fetcher
|   |   +-- run_backtest.py         CLI backtest runner
|   |   +-- build_daily_cache_2025.py  Daily cache builder
|   |   +-- fetch_intraday.py       Intraday data fetcher
|   |   +-- cache/                  Cached OHLCV data (not committed)
|   |   +-- results/                Backtest JSON results (55+ files)
|   +-- data/                       Market data and database
|   |   +-- market_data.py          Data manager
|   +-- notifications/              Alert system
|   |   +-- whatsapp.py             Twilio WhatsApp integration
|   +-- docs/                       Research documentation
|   |   +-- BACKTEST_RESEARCH_REPORT.md  1,245-line research report
|   +-- strategies/                 Strategy definitions
|   +-- execution/                  Order execution (IB Gateway)
+-- dashboard/                      Next.js 15 frontend
|   +-- app/                        App router pages
|   |   +-- page.tsx                Main dashboard
|   |   +-- paper/page.tsx          Paper trading monitor
|   |   +-- performance/page.tsx    P&L and equity curves
|   |   +-- validation/page.tsx     Paper vs backtest comparison
|   |   +-- watchlist/page.tsx      Instrument watchlist
|   |   +-- backtest/page.tsx       Backtest result browser
|   |   +-- analysis/page.tsx       Technical analysis
|   |   +-- stats/page.tsx          Portfolio statistics
|   |   +-- journal/page.tsx        Trade journal
|   |   +-- health/page.tsx         System health
|   |   +-- settings/page.tsx       Configuration
+-- infrastructure/                 Docker Compose for data stores
|   +-- docker-compose.yml          Postgres, Redis, QuestDB, Grafana
+-- thinkorswim-scripts/            ThinkScript strategy exports
+-- SUMMARY.md                      Strategy research summary (v3.0)
+-- engine/prd.json                 Product requirements (10/10 complete)
+-- start_jarvis.bat                Quick-start batch file
```

---

## Safety

- **Kill switch**: Always Tier 3 (manual confirmation required before any trade execution)
- **Live port 4001**: Permanently blocked in code -- cannot be set via environment variable
- **Daily loss limit**: -2% account equity
- **Max drawdown**: -10% account equity triggers automatic kill switch
- **Max contracts**: 2 during paper phase
- **Paper kill threshold**: 3 consecutive months below 3.8% return (50% of IS baseline)

---

## Phases

| Phase | Timeline | Status |
|-------|----------|--------|
| Phase 1: Research + Backtest | Aug 2025 -- Mar 2026 | Complete (8 phases, 55+ result files) |
| Phase 2: Paper Trading | Mar 2026 -- May 2026 | **Active** (MGC 1d since 2026-03-29) |
| Phase 3: Live Trading | Jun 2026+ | Locked (requires Phase 2 validation pass) |

---

## PRD Status (All 10 User Stories Complete)

| ID | Title | Result |
|----|-------|--------|
| US-001 | SPY 1h backtest | 22 trades, PF 4.17, Sharpe 3.95, +1.55% |
| US-002 | MES 1h backtest | 61 trades, PF 5.27, Sharpe 4.16, +47.2% |
| US-003 | MNQ 1h backtest | 51 trades (adaptive), PF 1.44, Sharpe 2.37, +10.6% |
| US-004 | JSON output | Auto-saves to backtest/results/ |
| US-005 | SPY 1h optimization | STC_OS=15, STC_OB=83, stop=0.70, T1=1.50 ATR |
| US-006 | 2025 daily backtests | SPY + MES (proxy) daily completed |
| US-007 | Update signals.py | STC_OS=15, T1=1.50 ATR applied |
| US-008 | E2E pipeline test | All 10 agents ran, result: HOLD |
| US-009 | WhatsApp alert | Twilio sandbox verified, stale singleton fixed |
| US-010 | Summary report | SUMMARY.md v3.0 at project root |

---

## Environment Variables

See `.env.example` for all required variables. Key ones:

```env
# IB Gateway (paper account)
IB_HOST=127.0.0.1
IB_PORT=4002
IB_CLIENT_ID=1

# WhatsApp Notifications (Twilio)
TWILIO_ACCOUNT_SID=...
TWILIO_AUTH_TOKEN=...
WHATSAPP_FROM=whatsapp:+14155238886
WHATSAPP_TO=whatsapp:+1...

# Anthropic (for LLM pipeline)
ANTHROPIC_API_KEY=...

# TradingView webhook (optional security)
TRADINGVIEW_WEBHOOK_SECRET=

# Instrument defaults
DEFAULT_SYMBOL=MGC
```

Copy `engine/.env.example` to `engine/.env` and fill in values. Never commit `.env` files.

---

## Next Milestones

**MNQ 1h paper approval**: Requires WFE > 0.40 (currently 0.34 adaptive). Options under evaluation:
1. Combined walk-forward with adaptive regime + volume filter + MTF filter
2. Wider training windows (9-month IS instead of 6-month)
3. Additional signal confirmations to reduce parameter instability
4. Extend history back to 2022 to include bear market conditions

**MGC 1d monitoring**: Recalculate WFE monthly with latest 3 windows. Kill if 3 consecutive months fall below 3.8% return.

---

*Last updated: 2026-03-29. Source: 55+ result files in `engine/backtest/results/`, 11 walk-forward runs, 4 Monte Carlo simulations (10k each), 1,245-line research report, and all 10 PRD user stories validated.*
