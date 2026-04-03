# JARVIS TRADER — Master System Report

**Generated**: 2026-03-29
**Status**: Paper Trading Phase (April–May 2026 validation active)
**Sessions**: 5 (+ continuation)
**Total Components**: 60+ dashboard widgets
**Engine Endpoints**: ~95+
**Live Trading Gate**: June 2026 (contingent on validation)

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Architecture](#2-architecture)
3. [Engine — FastAPI Backend](#3-engine--fastapi-backend)
4. [Dashboard — Next.js Frontend](#4-dashboard--nextjs-frontend)
5. [Complete Component Registry](#5-complete-component-registry)
6. [Complete Endpoint Registry](#6-complete-endpoint-registry)
7. [Database Schema](#7-database-schema)
8. [Session-by-Session History](#8-session-by-session-history)
9. [Validation Targets](#9-validation-targets)
10. [Go-Live Plan](#10-go-live-plan)
11. [Files Created](#11-files-created)
12. [Known Issues & Pending Work](#12-known-issues--pending-work)

---

## 1. System Overview

JARVIS TRADER is a fully automated paper/live futures trading system built for Matt Morrison. It uses a 5-stage, 10-agent AI pipeline to generate trade signals from TradingView webhooks, evaluate risk, and route orders to Interactive Brokers (paper mode: port 4002).

**Key Instruments**: MES (Micro E-mini S&P 500), MGC (Micro Gold), MNQ, MCL
**Strategy**: STC (Schaff Trend Cycle) with adaptive OS/OB thresholds, ATR-based stops/targets, regime filter
**Best Backtest**: MES 1h — PF 5.27, Sharpe 4.16, Win Rate 67.3%, +47.2% total return
**Paper Trading Since**: ~March 2026
**Validation Target**: PF ≥ 2.0, Sharpe ≥ 1.5, Win Rate ≥ 55%, 60+ trades, 30+ trading days

---

## 2. Architecture

```
TradingView Webhook
       │
       ▼
FastAPI Engine (port 8010)
├── Webhook Router → pipeline.run_on_signal()
├── 5-Stage Trading Pipeline
│   ├── Stage 1: Regime Detection Agent
│   ├── Stage 2: Momentum Analysis Agent (STC)
│   ├── Stage 3: Entry Signal Agent
│   ├── Stage 4: Risk Management Agent (SafetyLayer)
│   └── Stage 5: Execution Agent → IB Gateway (port 4002)
├── SQLite Database (paper_trades, decisions, alerts, pipeline_runs)
├── PortfolioTracker (SQLite-backed)
├── PerformanceCalculator (PF, Sharpe, Win Rate, Drawdown)
├── EOD Scheduler (Mon-Fri 3:05 PM CT snapshots)
├── WhatsApp Notifications (Twilio)
└── 95+ REST API endpoints
       │
       ▼
Next.js Dashboard (port 3010)
├── 12 pages
├── 60+ React components
└── Tailwind CSS + custom theme (bull/bear/warn/neutral color system)
```

### Stack

| Layer | Technology |
|-------|-----------|
| Engine | Python 3.12, FastAPI, uvicorn |
| Database | SQLite (via aiosqlite) |
| Broker | ib_async 0.9.86 (IB Gateway paper port 4002) |
| Dashboard | Next.js 14, TypeScript, Tailwind CSS |
| Notifications | Twilio WhatsApp |
| Market Data | yfinance (for backtesting + signal generation) |
| Strategy | STC (custom), ATR-based risk, regime detection |

---

## 3. Engine — FastAPI Backend

### Location
`C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\`

### Key Files

| File | Purpose |
|------|---------|
| `main.py` | FastAPI app, all route registrations, lifespan |
| `agents/pipeline.py` | TradingPipeline — 5-stage orchestration |
| `agents/trader.py` | Execution agent with position sizing ceiling |
| `analytics/performance.py` | PerformanceCalculator (PF, Sharpe, WR, drawdown) |
| `database/schema.py` | DatabaseManager — 6 tables, 6+ bridge methods |
| `database/migrations.py` | Version-tracked migrations (001–005) |
| `execution/ib_gateway.py` | IBGatewayManager — paper-only (port 4002) |
| `execution/ib_order_manager.py` | IBOrderManager with reconcile() |
| `risk/safety_layer.py` | SafetyLayer — circuit breakers, kill switch |
| `risk/pnl_monitor.py` | PnLMonitor — 3-tier P&L source (IB→SQLite→memory) |
| `utils/position_sizing.py` | Fixed-fractional formula |
| `schedulers/eod_scheduler.py` | EOD snapshots Mon-Fri 3:05 PM CT |
| `notifications/whatsapp.py` | WhatsApp formatters (4+) |
| `portfolio/tracker.py` | SQLite-backed PortfolioTracker |
| `routers/journal_router.py` | Trade journal CRUD |
| `backtest/paper_tracker.py` | Paper trading tracker for backtesting |
| `init_db.py` | CLI database init (python init_db.py [--reset]) |
| `CHANGELOG.md` | v1.0.0 → v1.6.0 version history |

### Strategy Parameters (Confirmed)

```python
STC_OS = 15        # Oversold threshold (adaptive)
STC_OB = 83        # Overbought threshold (adaptive)
ATR_STOP = 0.70    # Stop distance multiplier
ATR_TARGET = 1.50  # Target distance multiplier
MULTIPLIER = 5     # MES $ per point
TICK = 1.25        # MES tick size

# Position sizing
risk_per_trade = account_value * 0.01
max_contracts = floor(risk_per_trade / (atr * 0.70 * multiplier))

# Theoretical R:R = 1.50 / 0.70 = 2.14:1
```

---

## 4. Dashboard — Next.js Frontend

### Location
`C:\Users\mattm\ThinkorSwim\jarvis-trader\dashboard\`

### Pages (12 total)

| Page | Route | Primary Purpose |
|------|-------|-----------------|
| Main Dashboard | `app/page.tsx` | Overview + paper phase summary |
| Paper Trading | `app/paper/page.tsx` | Live positions, signals, session P&L |
| Performance | `app/performance/page.tsx` | P&L charts, symbol breakdown, equity curve |
| Validation | `app/validation/page.tsx` | Go-live readiness checklist, Sharpe/PF targets |
| Journal | `app/journal/page.tsx` | Trade log, calendar, best/worst trades |
| Stats | `app/stats/page.tsx` | Trade count, hours, long/short, weekly |
| Backtest | `app/backtest/page.tsx` | Strategy reference, regime P&L, signal accuracy |
| Scorecard | `app/scorecard/page.tsx` | PnL streak, drawdown, R:R, profit factor |
| Watchlist | `app/watchlist/page.tsx` | Contract specs, win rate by symbol, ATR |
| Health | `app/health/page.tsx` | Engine status, IB connection, pipeline |
| Settings | `app/settings/page.tsx` | Risk params, WhatsApp, pipeline config |
| System Settings | (TBD) | — |

### UI Theme

```
bull  = green  (profitable, positive signals, targets met)
bear  = red    (losing, negative signals, danger)
warn  = yellow (caution, below-target, close to limits)
info  = blue   (informational, reference)
neutral = gray (no data, flat, inactive)
```

Badge variants **only**: `"bull" | "bear" | "warn" | "info" | "neutral"` — enforced across all 60+ components.

---

## 5. Complete Component Registry

### Sessions 1–4 Components (Pre-existing)

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
| 33 | `PaperPhaseSummaryWidget.tsx` | app/page | `/portfolio/stats/paper-phase-summary` |

### Session 5 Continuation Components (This Session)

| # | Component | Page | Data Source | Notes |
|---|-----------|------|-------------|-------|
| 34 | `ui/progress.tsx` | (shared) | — | New UI primitive, role=progressbar |
| 35 | `EngineConfigCard.tsx` | settings | `/health` + `/settings/risk` | Identity + strategy params display |
| 36 | `StcStrategyExplainerCard.tsx` | backtest | static | STC reference card, 4-signal grid |
| 37 | `SignalQueueWidget.tsx` | paper | `/paper/mgc-signal` | Full signal: action, STC, ATR, regime |
| 38 | `AlertHistoryWidget.tsx` | journal | `/alerts/history?limit=15` | Scrollable timeline, 24h summary |
| 39 | `TopSymbolsWidget.tsx` | performance | `/portfolio/history/trades` | Groups by symbol, WR + P&L |
| 40 | `PhaseProgressWidget.tsx` | validation | `/analytics/performance` | Phase 1/2/3 milestones with dates |
| 41 | `OpenPositionsWidget.tsx` | paper (first) | `/portfolio/paper/positions` | 15s refresh, safety-critical |
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
| 52 | `RiskRewardWidget.tsx` | scorecard | `/analytics/performance` | avg_win/avg_loss ratio, target ≥2.0 |
| 53 | `MarketSessionWidget.tsx` | health | client-side | CME Globex RTH/ETH/Weekend, CT time |
| 54 | `SignalAccuracyWidget.tsx` | backtest | `/portfolio/history/trades` | Signal direction → profitable outcome |
| 55 | `SessionSummaryWidget.tsx` | paper | `/portfolio/stats/session-today` | Rewritten: date, P&L, wins/losses, symbols |
| 56 | `TradeCalendarWidget.tsx` | journal | `/portfolio/history/trades` | Calendar heatmap, month nav, hover tooltips |
| 57 | `PipelineStatusWidget.tsx` | settings | `/pipeline/status` | 5-stage display, available + decision_count |
| 58 | `VolatilityWidget.tsx` | watchlist | `/paper/mgc-signal` | ATR stop/target/$, max contracts |
| 59 | `WeeklyPerformanceWidget.tsx` | stats | `/portfolio/history/trades` | 8-week bar chart + table, trend arrows |
| 60 | `DecisionLogWidget.tsx` | health | `/decisions/recent` + `/pipeline/status` | Live feed, signal badges, confidence % |
| 61 | `ProfitFactorWidget.tsx` | scorecard | `/analytics/performance` | Large PF, 0-3 gauge, target 2.0 |
| 62 | `EntryQualityWidget.tsx` | performance | `/portfolio/history/trades` | Target hit/stopped/scratch/partial breakdown |
| 63 | `BacktestMetricsWidget.tsx` | backtest | `/backtest/results` | Best result by PF, 2×2 metric grid |

### Failed (Rate Limited — Pending Re-run)

| Component | Target Page | Status |
|-----------|-------------|--------|
| `RecentTradesTableWidget.tsx` | performance | ❌ Rate limited |
| `CumulativeTradingDaysWidget.tsx` | scorecard | ❌ Rate limited |
| `LiveReadinessWidget.tsx` | validation | ❌ Rate limited |
| `PaperPhaseSummaryWidget.tsx` (main dashboard) | app/page.tsx | ⏳ Running |

---

## 6. Complete Endpoint Registry

### Health & System

| Method | Path | Response Key Fields |
|--------|------|---------------------|
| GET | `/health` | status, version, uptime_seconds, live_trading, kill_switch_active, paper_mode, database, ibkr_connected |
| GET | `/system/preflight` | 7-criteria pre-flight check |
| GET | `/ib/connection-test` | connected, latency_ms, host, port, client_id |
| POST | `/ib/connect` | Connect to IB Gateway paper port |
| GET | `/market/session` | session name, RTH/Extended/Weekend |

### Pipeline & Signals

| Method | Path | Response Key Fields |
|--------|------|---------------------|
| POST | `/webhook/tradingview` | Incoming TradingView alerts |
| POST | `/pipeline/run-signal` | Manual pipeline trigger |
| GET | `/pipeline/status` | available, last_run, decision_count |
| GET | `/pipeline/history` | Pipeline run history |
| GET | `/paper/mgc-signal` | signal, direction, regime, atr, stc_val, entry/stop/target |
| GET | `/signals/recent` | Unified signal feed |
| GET | `/signals/stats` | Signal aggregation by action/symbol |
| GET | `/decisions/recent?limit=N` | In-memory decision ring buffer |

### Portfolio & Trades

| Method | Path | Response Key Fields |
|--------|------|---------------------|
| GET | `/portfolio/paper/positions` | positions: [{trade_id, symbol, action, quantity, entry_price, pnl, is_open, stop_loss, take_profit}] |
| GET | `/portfolio/history/trades` | trades: [{id, symbol, side, quantity, entry_price, exit_price, realized_pnl, status, entry_time, exit_time, notes}] |
| GET | `/portfolio/history/daily-pnl` | Daily P&L history |
| GET | `/portfolio/history/decisions` | Decision history |
| GET | `/portfolio/stats/session-today` | date, session, closed_trades, open_trades, gross_pnl, wins, losses, win_rate, best_trade, worst_trade, avg_pnl, symbols_traded |
| GET | `/portfolio/stats/summary` | Summary stats |
| GET | `/portfolio/stats/drawdown` | Drawdown stats |
| GET | `/portfolio/stats/streaks` | win_streak, loss_streak, best_streak, worst_streak |
| GET | `/portfolio/stats/trading-days` | distinct trading day count vs 30-day target |
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
| GET | `/analytics/performance/compare` | vs backtest, degradation_factor, validation_thresholds |
| GET | `/analytics/mtf?symbol=MES` | Multi-timeframe STC analysis |
| GET | `/analytics/trades/by-day` | Trade breakdown by day-of-week |
| GET | `/analytics/trades/by-symbol` | Trade breakdown by symbol |
| GET | `/analytics/trades/by-hour` | Trade breakdown by hour |

### Risk & Safety

| Method | Path | Response Key Fields |
|--------|------|---------------------|
| GET | `/safety/circuit-breakers` | daily_pnl, daily_limit, drawdown_pct, kill_switch_active, all_clear, pnl_source |
| GET | `/settings/risk` | config: {daily_loss_limit, max_drawdown_pct, max_contracts, risk_per_trade_pct, atr_stop_multiplier, atr_target_multiplier} |
| GET | `/position-sizing/calculate` | Fixed-fractional calculator |
| GET | `/validation/readiness-check` | 8-criteria pre-live readiness |

### Alerts & Notifications

| Method | Path | Response Key Fields |
|--------|------|---------------------|
| GET | `/alerts/history` | alerts: [{id, alert_type, symbol, message, channel, status, error, created_at}] |
| GET | `/alerts/stats` | aggregation by type/channel/status |
| POST | `/notifications/morning-briefing` | Trigger WhatsApp morning brief |
| POST | `/notifications/whatsapp/test` | Test send |
| POST | `/notifications/vix-alert-check` | vix, regime (CALM/NORMAL/CAUTION/ELEVATED/EXTREME) |

### Backtest

| Method | Path | Description |
|--------|------|-------------|
| GET | `/backtest/results` | All saved backtest JSON files |
| POST | `/backtest/run` | Run backtest for symbol+date range |
| POST | `/backtest/walk-forward` | Walk-forward validation |
| GET | `/backtest/regime-status` | Current regime |
| GET | `/backtest/paper-status` | Paper trading status |
| POST | `/backtest/monte-carlo` | Monte Carlo simulation |
| POST | `/backtest/regime-analysis` | Regime-based analysis |

### Watchlist

| Method | Path | Description |
|--------|------|-------------|
| GET | `/watchlist/scan` | Scan symbols with current signals |

---

## 7. Database Schema

### Tables (5 + migrations)

```sql
-- paper_trades (core)
id, trade_id, symbol, side, quantity, entry_price, exit_price,
entry_time, exit_time, pnl, status, strategy_params (JSON), notes

-- pipeline_runs
run_id, symbol, webhook_action, final_action, summary, status,
error_message, created_at

-- alert_log (migration_005)
id, alert_type, symbol, message, channel, status, error, created_at

-- daily_snapshots
date, balance, pnl, trades, win_rate

-- performance_cache
(cached performance metrics)
```

### Key schema.py Bridge Methods
- `add_paper_trade()`, `get_trades()`, `update_trade()`
- `insert_pipeline_run()`, `get_pipeline_history()`
- `insert_alert_log()`, `get_alert_history()`
- `health_check()` — returns DB row counts for all tables

---

## 8. Session-by-Session History

### Session 1 — Skill Creation
- JARVIS TRADER skill (10 files, ~581KB)
- SKILL.md, api-reference.md, agent-registry.md, workflows.md, triggers.md, standing-orders.md, usage-guide.md, matt-context.md, strategy-reference.md, JARVIS-TRADER-COMPLETE-DOCUMENTATION.md

### Session 2 — SQLite + IB Gateway
- SQLite persistence layer (schema.py, migrations.py, tracker.py)
- IB Gateway integration (ib_gateway.py, ib_order_manager.py)
- SafetyLayer submit_paper_order() + circuit breakers
- Fixed-fractional position sizing
- PerformanceCalculator (PF, Sharpe, WR)
- EOD scheduler
- 28 integration tests

### Session 3 — Webhook → Pipeline Wiring
- `POST /pipeline/run-signal` endpoint
- `GET /pipeline/history` endpoint
- TradingView webhook → pipeline signal path fully wired
- Pine Script v5 strategy generated
- Dashboard: health page, validation simulate panel
- ~82 endpoints total

### Session 4 — Analytics + Dashboard Suite
- 22+ new dashboard components
- Alert log database table (migration_005)
- 13+ new endpoints including hourly/daily/symbol analytics
- smoke_test.py (48 endpoints), daily_report.py
- Nav audit (7 pages fixed)
- ~95+ endpoints total

### Session 5 — Dashboard Expansion (This Session)
- 30+ new dashboard components (see registry above)
- New endpoints discovered: `/portfolio/paper/positions`, `/decisions/recent`, `/pipeline/status`
- Fixed pre-existing TS error in validation/page.tsx (`CheckStatus` union missing `"WARN"`)
- Rate limit hit on final wave — 3 components pending

---

## 9. Validation Targets

### Paper Trading Criteria (June 2026 Gate)

| Metric | Target | Notes |
|--------|--------|-------|
| Profit Factor | ≥ 2.0 | Gross profit / gross loss |
| Sharpe Ratio | ≥ 1.5 | Risk-adjusted return |
| Win Rate | ≥ 55% | % of profitable trades |
| Total Trades | ≥ 60 | Minimum sample size |
| Trading Days | ≥ 30 | Distinct calendar days |
| Max Drawdown | ≤ 15% | Circuit breaker at 15% |

### Phase Timeline

| Phase | Target Date | Criteria |
|-------|-------------|---------|
| Phase 1 | March 2026 | ≥ 10 trading days |
| Phase 2 | April 2026 | ≥ 30 trades, WR ≥ 50%, PF ≥ 1.5 |
| Phase 3 | May 2026 | ≥ 60 trades, WR ≥ 55%, PF ≥ 2.0, Sharpe ≥ 1.5 |
| Live Gate | June 2026 | All 6 criteria met |

---

## 10. Go-Live Plan

1. **Paper Phase Complete** — All 6 criteria met (see above)
2. **IB Account** — Open live account with MES/MNQ futures permissions
3. **Capital** — ~$10,000 initial, 1 contract max
4. **Live Safety Layer** — Wire to IB Gateway port 4001 (currently blocked)
5. **Monitoring** — 3-month live monitoring period

---

## 11. Files Created (All Sessions)

### Engine (`engine/`)
```
main.py                          — FastAPI app (3,500+ lines)
agents/pipeline.py               — 5-stage trading pipeline
agents/trader.py                 — Execution with position sizing
analytics/performance.py         — PerformanceCalculator
database/schema.py               — DatabaseManager
database/migrations.py           — Version-tracked migrations
database/__init__.py             — Package exports
execution/ib_gateway.py          — IB paper gateway
execution/ib_order_manager.py    — Order reconciliation
risk/safety_layer.py             — Circuit breakers + kill switch
risk/pnl_monitor.py              — 3-tier P&L monitoring
utils/position_sizing.py         — Fixed-fractional formula
portfolio/tracker.py             — SQLite-backed tracker
schedulers/eod_scheduler.py      — EOD snapshots
notifications/whatsapp.py        — WhatsApp formatters
routers/journal_router.py        — Trade journal CRUD
tests/test_integration.py        — 28+ integration tests
init_db.py                       — DB init CLI
CHANGELOG.md                     — v1.0.0 → v1.6.0
.env.example                     — All required env vars
```

### Scripts (`scripts/`)
```
smoke_test.py                    — 48-endpoint smoke test
test_signal.py                   — CLI signal tester
seed_paper_trades.py             — Synthetic trade generator (95 trades, 30 days)
pine_script_generator.py         — TradingView Pine Script generator
jarvis_trader_strategy.pine      — Generated Pine Script v5
daily_report.py                  — EOD report generator
TRADINGVIEW_SETUP.md             — TradingView webhook setup guide
```

### Dashboard (`dashboard/`)
```
app/page.tsx                     — Main dashboard
app/paper/page.tsx               — Paper trading
app/performance/page.tsx         — Performance analytics
app/validation/page.tsx          — Validation & readiness
app/journal/page.tsx             — Trade journal
app/stats/page.tsx               — Statistics
app/backtest/page.tsx            — Backtest analysis
app/scorecard/page.tsx           — Validation scorecard
app/watchlist/page.tsx           — Watchlist
app/health/page.tsx              — System health
app/settings/page.tsx            — Settings
components/ui/progress.tsx       — Progress bar primitive
components/[60+ components]      — All widgets listed in registry
```

### Skill (`~/.claude/skills/jarvis-trader/`)
```
SKILL.md                               — 42KB core skill
api-reference.md                       — 57KB endpoint docs
agent-registry.md                      — 28KB agent catalog
workflows.md                           — 50KB workflows (10)
triggers.md                            — 31KB proactive triggers (24)
standing-orders.md                     — 28KB autonomy tiers
usage-guide.md                         — 13KB usage guide
matt-context.md                        — 7KB personal context
strategy-reference.md                  — 31KB strategy reference
JARVIS-TRADER-COMPLETE-DOCUMENTATION.md — 140KB merged reference
```

---

## 12. Known Issues & Pending Work

### Pending Components (Rate Limited)
- `RecentTradesTableWidget.tsx` → performance/page.tsx — paginated trade table with filters
- `CumulativeTradingDaysWidget.tsx` → scorecard/page.tsx — 30-day activity dots grid
- `LiveReadinessWidget.tsx` → validation/page.tsx — go/no-go checklist vs June 2026 target

### Engine Issues
- `EmailIntelligenceAgent.analyze_recent_emails` — method missing (affects morning briefing)
- Paradigm ERP API down since 2026-03-14 (affects GMS JARVIS, not JARVIS TRADER)

### Dashboard Notes
- `app/validation/page.tsx` — `CheckStatus` union now includes `"WARN"` (fixed 2026-03-29)
- Rate limit for subagents resets at 1am CT — remaining 3 components can be built next session

### IB Gateway
- Paper port (4002) integration complete but requires IB Trader Workstation running locally
- Live port (4001) permanently blocked in safety_layer.py — requires explicit unlock for live trading

### Future Roadmap
- Options Greeks monitoring (delta, theta, IV)
- Multi-timeframe confirmation (1h + 4h + daily stack)
- VIX regime overlay on all signals
- Earnings calendar integration
- OneNote trade journal via MCP
- Real options flow data (Unusual Whales or similar)
- SQLite → PostgreSQL migration for production
