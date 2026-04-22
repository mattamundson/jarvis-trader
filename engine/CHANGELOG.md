# JARVIS TRADER — Engine Changelog

All notable changes to the engine are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [1.5.0] - 2026-03-29

### Added (Session 4 Continuation — Dashboard Suite Completion)

**Dashboard Components (30+ new components total across all sessions)**

New components added in this continuation:
- `DrawdownChart` — Running drawdown SVG area chart (performance page)
- `EquityCurveWidget` — Cumulative P&L equity curve with trend coloring (scorecard page)
- `RollingPerformanceWidget` — 7d/14d/30d rolling PF/Sharpe/WinRate table (stats page)
- `TradePnLHistogram` — 7-bucket P&L distribution bar chart (journal page)
- `BestWorstTradesWidget` — Top 5 winners and losers side-by-side (stats page)
- `MarketRegimeWidget` — MTF analysis: alignment, confidence, per-timeframe STC (paper page)
- `AlertSummaryWidget` — Alert log with type/status/channel breakdown (health page)
- `PaperBalanceWidget` — Account balance, return %, 30-day progress bar (scorecard page)
- `StrategyParamsCard` — Static STC strategy parameter reference (backtest page)
- `OpenPositionsWidget` — Live open positions table with unrealized P&L (journal page)
- `TradingDaysCountdownCard` — Validation phase countdown + phase timeline (validation page)
- `CommissionTrackerWidget` — Total/gross/net P&L and commission breakdown (performance page)
- `TradingScheduleCard` — MES futures trading schedule reference (settings page)
- `RecentDecisionsWidget` — Last 10 AI pipeline decisions with reason/executed/P&L (paper page)
- `SignalAccuracyWidget` — LONG vs SHORT signal accuracy breakdown (backtest page)
- `PerformanceTrendWidget` — Linear regression trend analysis on 30-day P&L (watchlist page)
- `ConnectionHealthCard` — Engine/IB Gateway/mode/kill-switch status (health page)
- `PaperPhaseSummaryWidget` — Paper phase overview card (main dashboard)

**Testing**
- `TestSession4ContinuationEndpoints` class (8 tests) added to `test_integration.py`
- `smoke_test.py` updated to include `rolling?days=30` endpoint

### Changed
- All dashboard pages updated with cross-navigation links
- `app/stats/page.tsx` — PerformanceSummaryWidget at top, RollingPerformanceWidget, BestWorstTradesWidget added
- `app/performance/page.tsx` — WeeklyStatsWidget, CommissionTrackerWidget, DrawdownChart added
- `app/scorecard/page.tsx` — PaperBalanceWidget (first), EquityCurveWidget, CalendarHeatmap added
- `app/health/page.tsx` — ConnectionHealthCard (first), SystemMetricsPanel, AlertSummaryWidget added
- `app/backtest/page.tsx` — StrategyParamsCard (first), BacktestComparisonCard, SignalAccuracyWidget added
- `app/watchlist/page.tsx` — PerformanceTrendWidget, SymbolPerformanceWidget added
- `app/journal/page.tsx` — SessionSummaryWidget, OpenPositionsWidget, TradePnLHistogram added
- `app/paper/page.tsx` — RiskStatusWidget, RecentSignalsWidget, MarketRegimeWidget, RecentDecisionsWidget added
- `app/validation/page.tsx` — TradingDaysCountdownCard (first) added
- `app/settings/page.tsx` — TradingScheduleCard added

### Dashboard Summary
- Total components: 35+ across 10 pages
- TypeScript: 0 errors throughout
- All components follow consistent patterns: ENGINE_URL env var, Badge variants, useEffect/setInterval, graceful error states

---

## [1.4.0] — 2026-03-29

### Added — Session 4 Features

#### New Endpoints (11 new)
- `GET /alerts/history` — alert log with filtering (type, channel, symbol, limit, offset)
- `GET /alerts/stats` — alert log statistics grouped by type and channel
- `GET /system/preflight` — 8-point system readiness check
- `GET /analytics/mtf` — multi-timeframe STC analysis via MTFAnalyzer
- `GET /watchlist/scan` — multi-symbol MTF scan with market bias
- `GET /portfolio/stats/commissions` — commission estimator by symbol
- `GET /analytics/trades/by-day` — day-of-week performance breakdown
- `GET /analytics/trades/by-symbol` — per-symbol P&L breakdown
- `GET /analytics/trades/by-hour` — hour-of-day performance breakdown
- `POST /portfolio/import/trades` — bulk CSV trade import, max 1000 trades
- `GET /portfolio/stats/weekly` — 7-day rolling stats (total_trades, win_rate, period)
- `POST /notifications/whatsapp/test` — manual WhatsApp notification test

#### Database
- `migration_005`: `alert_log` table — columns: alert_type, message, channel, symbol, status, error, created_at
- WhatsApp `send_whatsapp_message()` events now logged to `alert_log` table

#### New Dashboard Components (11 new)
- `AlertHistoryLog.tsx` — alert notification history log
- `PreFlightWidget.tsx` — 8-point pre-flight system check panel
- `WatchlistScanWidget.tsx` — multi-symbol MTF scan results
- `DailyPnLChart.tsx` — daily P&L bar chart
- `WinStreakWidget.tsx` — current win/loss streak display
- `TradeAnalyticsWidget.tsx` — 3-tab analytics: by-symbol / by-day / by-hour
- `ExportDataWidget.tsx` — data export controls
- `CalendarHeatmap.tsx` — trade activity calendar heatmap
- `NotificationTestPanel.tsx` — manual notification test UI
- `RiskStatusWidget.tsx` — live risk/circuit-breaker status
- `WeeklyStatsWidget.tsx` — 7-day rolling statistics card
- `SessionSummaryWidget.tsx` — end-of-session summary card
- `BacktestComparisonCard.tsx` — forward vs backtest comparison card
- `SystemMetricsPanel.tsx` — CPU/memory/uptime metrics
- `SymbolPerformanceWidget.tsx` — per-symbol win rate and P&L

#### Testing
- `scripts/smoke_test.py` — expanded to 48 endpoints
- `tests/test_integration.py` — `TestSession4Endpoints` class: 9 integration tests
- `tests/test_integration.py` — `TestSession4ExtendedEndpoints` class: 8 integration tests

---

## [1.3.0] — 2026-03-29

### Added — Session 3 Features

#### New Endpoints (~20 new)
- `GET /market/session` — CT-aware session classifier (RTH/PRE_MARKET/AFTER_HOURS/OVERNIGHT/FUTURES_OPEN/WEEKEND)
- `GET /market/earnings` — upcoming earnings for SPY/QQQ/AAPL/MSFT/NVDA/AMZN/META/GOOGL
- `GET /analytics/regime` — 5-layer regime (VIX/MTF/STC/EMA/VOL) with alignment and trade_filter
- `GET /analytics/mtf` — multi-timeframe STC analysis via MTFAnalyzer
- `GET /analytics/performance/rolling` — rolling metrics for last N days (1-90)
- `POST /notifications/morning-briefing` — manual trigger for WhatsApp morning briefing
- `POST /notifications/vix-alert-check` — VIX threshold check → WhatsApp
- `GET /validation/readiness-check` — 8-criteria pre-live validation
- `GET /settings/risk` / `POST /settings/risk` — circuit breaker config CRUD with DB persistence
- `GET /reports/performance` — self-contained HTML performance report with Chart.js
- `GET /portfolio/stats/streaks` — win/loss streak tracker
- `GET /portfolio/stats/trading-days` — active trading day counter
- `GET /portfolio/stats/paper-phase-summary` — paper phase progress
- `GET /portfolio/stats/session-today` — today's trades and P&L (CT timezone)
- `GET /ib/reconcile` — IB Gateway vs SQLite position reconciliation
- `GET /webhook/dedup-stats` — dedup cache state
- `GET /alerts/history` / `GET /alerts/stats` — alert log CRUD
- `GET /system/preflight` — 8-point pre-flight system check
- `GET /watchlist/scan` — multi-symbol MTF scan with market bias

#### New Engine Files
- `engine/analytics/vix_overlay.py` — rewritten with yfinance live data, 15-min cache
- `engine/analytics/mtf_analyzer.py` — multi-timeframe STC using yfinance
- `engine/database/migrations.py` — migration_004 (journal_notes), migration_005 (alert_log)

#### New Scripts
- `scripts/smoke_test.py` — 42-endpoint smoke test (updated to ~60 endpoints)
- `scripts/test_signal.py` — CLI signal tester
- `scripts/seed_paper_trades.py` — synthetic trade generator (95 trades, 30 days)
- `scripts/pine_script_generator.py` — TradingView Pine Script v5 generator
- `scripts/jarvis_trader_strategy.pine` — generated strategy file
- `scripts/TRADINGVIEW_SETUP.md` — TradingView webhook setup guide

#### New Dashboard Components
- `MarketSessionIndicator.tsx` — session badge + countdown
- `PaperPhaseSummaryWidget.tsx` — paper phase progress bar
- `ReadinessCheckWidget.tsx` — pre-live checklist
- `MTFConfirmationWidget.tsx` — 1h/4h/1d STC bars
- `ReconciliationWidget.tsx` — IB vs SQLite position comparison
- `StreakBadge.tsx` — win/loss streak with flame icon
- `RollingPerformanceCard.tsx` — 7d/14d/30d rolling metrics
- `SessionTodayWidget.tsx` — today's session summary
- `AlertHistoryLog.tsx` — alert notification history
- `PreFlightWidget.tsx` — pre-flight system check widget

#### New Dashboard Pages
- `app/scorecard/page.tsx` — paper trading validation scorecard
- `app/health/page.tsx` — 6-subsystem health grid + pre-flight check

#### APScheduler Jobs (4 total)
- EOD snapshot — Mon-Fri 3:05 PM CT
- Morning briefing — Mon-Fri 8:25 AM CT
- VIX alert check — hourly 8-17 CT Mon-Fri
- EOD snapshot 2 — backup

### Changed
- `vix_overlay.py` — rewritten to use yfinance live data with graceful fallback
- `eod_scheduler.py` — added morning briefing and VIX alert jobs
- `whatsapp.py` — added `send_whatsapp_message()`, `format_morning_briefing()`, `format_trade_closed_alert()`, alert logging
- `webhook_router.py` — added 30-second dedup window
- `test_integration.py` — added TestWebhookDedup class (2 tests)

### Fixed
- `datetime.utcnow()` deprecated calls → `datetime.now(timezone.utc)`
- TypeScript: 0 errors (HistogramChart import removed, null→undefined, dead ternary removed, missing types added)

---

## [1.2.0] — 2026-03-28

### Added — Session 2 Features

#### New Endpoints
- `GET /portfolio/stats/streaks` — win/loss streak calculation from closed trades
- `GET /portfolio/history/trades` — paginated closed trade history
- `GET /portfolio/history/daily-pnl` — daily P&L history from SQLite
- `GET /portfolio/stats/summary` — aggregate metrics (total P&L, win rate, trade count)
- `GET /portfolio/stats/drawdown` — max drawdown from daily equity curve
- `GET /analytics/performance/rolling` — rolling N-day performance metrics
- `GET /analytics/performance/compare` — forward vs backtest comparison
- `GET /pipeline/history` — pipeline run log with symbol and outcome
- `GET /signals/stats` — webhook signal statistics + dedup cache size
- `GET /settings/risk` / `POST /settings/risk` — risk config read/write
- `GET /reports/performance` — Chart.js HTML performance report

#### New Engine Files
- `routers/webhook_router.py` — TradingView webhook ingestion with dedup
- `analytics/performance.py` — PerformanceCalculator (Sharpe, PF, drawdown, rolling)
- `routers/journal_router.py` — trade journal CRUD (entries + notes)
- `schedulers/eod_scheduler.py` — APScheduler EOD snapshot + weekly review

### Changed
- `main.py` — integrated webhook_router, journal_router, APScheduler
- `database/schema.py` — added trade_journal, journal_notes, alert_log tables

### Fixed
- Portfolio tracker thread-safety: added `_lock` to all SQLite writes
- Signal deduplication: 30-second window prevents duplicate webhook fires

---

## [1.1.0] — 2026-03-27

### Added — Session 1 Features

#### Core Infrastructure
- FastAPI server on port 8010 (`main.py`)
- SQLite database with schema (`database/schema.py`)
- Portfolio tracker (`portfolio/tracker.py`) — paper trade lifecycle
- Safety layer (`risk/safety_layer.py`) — kill switch + circuit breakers
- P&L monitor (`risk/pnl_monitor.py`) — daily loss limit enforcement
- IB Order Manager (`execution/ib_order_manager.py`) — IB Gateway integration
- WebSocket manager (`websocket/manager.py`) — real-time event broadcast

#### Endpoints
- `GET /health` / `GET /health/full` — health check
- `GET /safety/status` / `GET /safety/circuit-breakers` / `GET /safety/config`
- `POST /safety/kill-switch/activate` / `POST /safety/kill-switch/deactivate`
- `GET /portfolio` / `GET /portfolio/paper/positions` / `GET /portfolio/paper/performance`
- `POST /portfolio/paper/trade` — open/close paper trades
- `GET /paper/pending-signals` / `GET /paper/mgc-signal` / `GET /paper/mgc-performance`
- `GET /analytics/performance` — forward-test validation report
- `GET /signals/stats` — webhook signal count
- `GET /watchlist` / `POST /watchlist` / `DELETE /watchlist/{symbol}`
- `GET /prices/snapshot` — yfinance spot prices
- `GET /market/earnings` — upcoming earnings calendar
- `GET /backtest/results` / `GET /backtest/regime-status` / `GET /backtest/paper-status`
- `POST /backtest/run` / `POST /backtest/monte-carlo`
- `GET /macro/snapshot` / `GET /macro/series/{series_id}`
- `GET /sentiment/recent` / `GET /sentiment/reddit` / `GET /sentiment/news/{symbol}`
- `GET /analyze/bars/{symbol}` — OHLCV bar fetch
- `POST /analyze/technical` — technical analysis
- `GET /ws/status` — WebSocket connection count
- `GET /scheduler/status` / `POST /scheduler/scan-now`

#### Agents
- TechnicalAnalystAgent, NewsAnalystAgent, SocialAnalystAgent
- FundamentalistAgent, BullResearcherAgent, BearResearcherAgent
- DebateOrchestrator, TraderAgent, RiskManagerAgent, FundManagerAgent
- TradingPipeline — orchestrates full multi-agent decision loop

#### Backtesting
- `backtest/engine.py` — vectorized STC backtester
- `backtest/walk_forward.py` — walk-forward validation
- `backtest/monte_carlo.py` — Monte Carlo simulation
- Results: SPY 1h PF=5.27, Sharpe=4.16 (2024-06-01 to 2026-03-27)

### Fixed
- Port conflict: engine runs on 8010, GMS JARVIS on 8009
- CORS: dashboard origin `http://localhost:3000` whitelisted
