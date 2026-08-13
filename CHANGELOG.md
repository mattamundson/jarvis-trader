# JARVIS TRADER — Changelog

All notable changes to this project will be documented in this file.
Format: [version] — date — description

---

## [1.2.0] — 2026-03-29 — Session 3: Signal Pipeline Complete

### Added
- `TradingPipeline.run_on_signal()` — accepts TradingView webhook signal, runs full 5-stage pipeline
- `POST /pipeline/run-signal` — manual pipeline trigger endpoint (400 on invalid action, 503 if not ready)
- `GET /pipeline/history` — recent pipeline runs from SQLite (limit, symbol params)
- `GET /signals/recent` — unified chronological signal feed
- `GET /signals/stats` — signal statistics by action/symbol/status/success rate
- `GET /ib/connection-test` — ping IB Gateway port 4002 with latency measurement
- `POST /ib/connect` — connect to IB Gateway paper port
- `GET /portfolio/export/trades.csv` — paper trade history download
- `GET /portfolio/export/daily-pnl.csv` — daily P&L history download
- `POST /position-sizing/calculate` — fixed-fractional contract size calculator
- `pipeline_runs` SQLite table (migration_003) with indexes on symbol, status, created_at
- Dashboard `/health` page — 6-subsystem status grid with auto-refresh
- Dashboard Simulate Trade panel on `/validation` (Section E)
- Dashboard PipelineRunHistory component (Section F)
- Dashboard Position Sizing Calculator (Section G)
- `IBGatewayStatus.tsx` — latency badge, Connect button, 10s polling
- WhatsApp notification on pipeline run completion
- `.env.example` — complete environment variable template
- `start_jarvis.bat` — `.env` existence check with warning
- 5 webhook integration tests (4 pass, 1 skip on secret validation)

### Fixed
- `pipeline.py` `run_on_signal()` truncation — method was incomplete, now fully implemented
- Dead global `thinkscript_generator` removed from `main.py`

---

## [1.1.0] — 2026-03-29 — Session 2: Paper Trading Infrastructure

### Added
- `engine/database/schema.py` — DatabaseManager with 8 tables (paper_trades, decisions, daily_pnl, positions, settings, trade_journal, schema_version + migration system)
- `engine/database/migrations.py` — version-tracked migrations (001: initial, 002: trade journal)
- `engine/portfolio/tracker.py` — SQLite-backed PortfolioTracker (backward compatible)
- `engine/execution/ib_gateway.py` — IBGatewayManager, paper port 4002 only, port 4001 PERMANENTLY BLOCKED
- `engine/execution/ib_order_manager.py` — IBOrderManager with reconcile()
- `engine/risk/pnl_monitor.py` — PnLMonitor with 3-tier P&L source (IB → SQLite → memory)
- `engine/utils/position_sizing.py` — fixed-fractional formula (risk=1%, stop=0.70×ATR)
- `engine/analytics/performance.py` — PerformanceCalculator (PF, Sharpe, win rate)
- `engine/schedulers/eod_scheduler.py` — EOD snapshots Mon-Fri 3:05 PM CT
- `engine/routers/webhook_router.py` — TradingView webhook receiver
- `engine/routers/journal_router.py` — trade journal CRUD with tags
- `engine/analytics/greeks_monitor.py` — stub for options Greeks (future)
- `engine/analytics/mtf_confirmation.py` — stub for multi-timeframe confirmation (future)
- `engine/analytics/vix_overlay.py` — stub for VIX regime overlay (future)
- Dashboard: CircuitBreakerPanel, IBGatewayStatus, RegimeDisplay, SignalHistory
- Dashboard pages: /performance, /journal, /watchlist, /settings, /validation, /backtest
- 28 integration tests (all passing, zero deprecation warnings)
- New endpoints: /safety/circuit-breakers, /safety/config, /analytics/performance, /portfolio/history/*, /portfolio/stats/*

### Fixed
- All `datetime.utcnow()` → `datetime.now(timezone.utc)` across codebase

---

## [1.0.0] — 2026-03-29 — Session 1: Skill + Initial Engine

### Added
- 10-file Claude Code skill at `.claude/skills/jarvis-trader/`
- FastAPI engine (port 8010) with 5-stage 10-agent trading pipeline
- Next.js dashboard (port 3010)
- Strategy: STC OS=15 OB=83 + ATR Stop=0.70× + Regime Filter
- Backtest: MES 1h — PF 5.27, Sharpe 4.16, +47.2%
- WhatsApp alerts via Twilio
- In-memory paper trade tracker (replaced in v1.1.0)
- Instruments: MES (primary), MNQ, MCL
- Safety layer with kill switch

---

## Planned

### [2.0.0] — Phase 3: Live Trading (target: June 2026)
- Requirements: paper PF > 2.0, Sharpe > 1.5 over 60+ trading days
- Live IB account with MES/MNQ futures permissions
- SafetyLayer wired to IB Gateway port 4001
- Initial capital: ~$10,000, max 1 contract
- 3-month live monitoring

### Future Features
- Options Greeks monitoring (GreeksMonitor already stubbed)
- Multi-timeframe confirmation 1h+4h+daily (MTFConfirmationFilter already stubbed)
- VIX regime overlay (VIXOverlay already stubbed)
- Earnings calendar integration
- OneNote trade journal via MCP
