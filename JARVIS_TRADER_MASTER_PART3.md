# JARVIS TRADER MASTER DOCUMENT -- Part 3

**Sections 1.11 through 1.14**
**Generated**: 2026-03-30
**Source of truth**: Live code inspection of `engine/main.py`, `ENDPOINT_REGISTRY.md`, `database/migrations.py`, `monitoring/metrics.py`, `thinkorswim-scripts/INTEGRATION_GUIDE.md`, and `dashboard/app/` directory.

---

## 1.11 API Surface (Live-Validated)

**Base URL**: `http://localhost:8010`
**Framework**: FastAPI 0.x with Pydantic v2 request/response models
**Authentication**: None (internal use only -- bind to `127.0.0.1`)
**API Docs**: `http://localhost:8010/docs` (Swagger UI auto-generated)
**Total Endpoints**: 82 REST + 1 WebSocket
**Status**: All 82 endpoints verified and wired (2026-03-29)

### Health & Diagnostics (3 endpoints)

| Method | Path | Description | Response Model |
|--------|------|-------------|----------------|
| GET | `/health` | Basic health check -- uptime, kill switch state, IBKR connection, paper mode flag | `HealthResponse` |
| GET | `/health/full` | Comprehensive check of all subsystems: API keys, database, IB Gateway, portfolio tracker, scheduler | `FullHealthResponse` |
| GET | `/system/preflight` | Pre-flight validation before accepting trading commands. Verifies API keys, DB, market hours, portfolio state | JSON: `check_count`, `pass_count`, `fail_count`, `warn_count`, detailed results |

### Safety & Risk Management (7 endpoints)

| Method | Path | Description | Response Model |
|--------|------|-------------|----------------|
| POST | `/safety/kill-switch/activate` | Immediately halt all trading. Sends WhatsApp alert + WebSocket broadcast | `KillSwitchToggleResponse` |
| POST | `/safety/kill-switch/deactivate` | Resume trading after kill switch event | `KillSwitchToggleResponse` |
| GET | `/safety/status` | Full safety layer state: kill switch, circuit breakers, daily P&L limits, position tracking | `SafetyStatusResponse` |
| GET | `/safety/circuit-breakers` | Per-breaker status: daily loss, max drawdown, margin utilization thresholds | `CircuitBreakerStatus` |
| GET | `/safety/config` | Read-only risk parameter configuration from `.env` at startup | JSON: `max_daily_loss_pct`, `max_drawdown_pct`, `max_position_size_pct` |
| POST | `/safety/reset-daily-pnl` | Reset in-memory daily P&L counter (testing/manual intervention) | JSON: `status`, `message` |
| GET | `/safety/loss-tracker` | Consecutive loss tracking state, position size multiplier, halt status | JSON: `global_consecutive_losses`, `symbol_losses`, `position_size_multiplier`, `is_halted`, `halt_until`, `config` |

### Strategy Configuration (4 endpoints)

| Method | Path | Description | Response Model |
|--------|------|-------------|----------------|
| GET | `/settings/risk` | Current risk/circuit breaker settings from database | JSON risk parameters |
| POST | `/settings/risk` | Update risk settings with range validation, persist to database | JSON: `updated`, `errors`, `count` |
| GET | `/strategy/params` | Current strategy parameters: EMA periods, ATR settings, filter flags | JSON: `ema_short`, `ema_long`, `ema_smoother`, `atr_length`, `atr_mult_stop`, `atr_mult_target`, filter flags |
| PUT | `/strategy/params` | Update strategy parameters (immediate effect on future backtests/live trading). Validates EMA ordering, ATR ranges, RSI thresholds | JSON: `status`, `old_params`, `new_params` |

### Analysis & Sentiment (5 endpoints)

| Method | Path | Description | Response Model |
|--------|------|-------------|----------------|
| POST | `/analyze/technical` | Run Technical Analyst agent on a symbol for signal generation | `TechnicalAnalysisResponse` |
| GET | `/analyze/bars/{symbol}` | OHLCV bars from market data manager (last 200 bars) | `BarsResponse` |
| GET | `/llm/stats` | LLM API usage and cost statistics -- per-model and per-agent breakdowns | JSON: `total_calls`, `total_cost_usd`, `success_rate`, `avg_latency_ms`, `per_model`, `per_agent` |
| GET | `/sentiment/reddit` | Trending tickers from Reddit via data manager | `RedditSentimentResponse` |
| GET | `/sentiment/news/{symbol}` | News sentiment for a symbol via Finnhub API | `NewsSentimentResponse` |

### Portfolio & Paper Trading (15 endpoints)

| Method | Path | Description | Response Model |
|--------|------|-------------|----------------|
| GET | `/portfolio` | Current portfolio state from broker API or paper tracker | `PortfolioResponse` |
| GET | `/portfolio/paper/positions` | All open paper-trade positions with entry prices, sizes, unrealized P&L | `PaperPositionsResponse` |
| POST | `/portfolio/paper/trade` | Log a completed paper trade to the tracker | `PaperTradeResponse` |
| GET | `/portfolio/paper/performance` | Performance metrics for all closed paper trades | `PaperPerformanceResponse` |
| GET | `/paper/pending-signals` | Pending entry signals from daily MGC scan | `PendingSignalsResponse` |
| GET | `/portfolio/history/trades` | Complete trade history from SQLite | `TradeHistoryResponse` |
| GET | `/portfolio/history/daily-pnl` | Daily P&L snapshots for last N days | `DailyPnLResponse` |
| GET | `/portfolio/history/decisions` | Historical agent decisions with reasoning and outcomes | `DecisionHistoryResponse` |
| GET | `/portfolio/stats/summary` | Aggregate performance: win rate, total P&L, profit factor | `StatsSummaryResponse` |
| GET | `/portfolio/stats/drawdown` | Max drawdown and equity curve data | `DrawdownResponse` |
| GET | `/portfolio/stats/streaks` | Current and maximum win/loss streaks | JSON: `current_streak`, `max_streak`, `streak_type` |
| GET | `/portfolio/stats/session-today` | Today's session stats (Chicago timezone) | JSON: session trades, P&L, commission |
| GET | `/portfolio/stats/commissions` | Estimated total commissions during paper trading | JSON: `total_commissions`, `per_trade_avg`, `per_symbol_breakdown` |
| GET | `/portfolio/stats/weekly` | 7-day rolling performance summary | JSON: `weekly_pnl`, `weekly_trades`, `win_rate`, `profit_factor` |
| POST | `/portfolio/import/trades` | Import trade records from CSV/JSON upload into trade history | JSON: `import_count`, `errors` |

### Paper Trading -- MGC (3 endpoints)

| Method | Path | Description | Response Model |
|--------|------|-------------|----------------|
| GET | `/paper/mgc-signal` | Generate today's MGC signal using walk-forward validated adaptive-regime strategy. Data: GC=F daily bars via yfinance. Scheduled daily at 18:00 ET | JSON: `signal`, `direction`, `entry_estimate`, `stop_level`, `target`, `regime` |
| POST | `/paper/mgc-log-trade` | Log a completed MGC paper trade and return updated cumulative metrics | JSON: `trade_id`, `cumulative_metrics` |
| GET | `/paper/mgc-performance` | Current MGC paper trading performance metrics | JSON: `trade_count`, `win_rate`, `profit_factor`, `total_pnl`, `monthly_summary`, `kill_threshold_breached` |

### Backtesting & Validation (8 endpoints)

| Method | Path | Description | Response Model |
|--------|------|-------------|----------------|
| GET | `/backtest/results` | List all saved backtest result JSON files | JSON: file list with metadata |
| POST | `/backtest/run` | Run a backtest for a symbol over a date range | JSON: trades, summary metrics, equity curve |
| POST | `/backtest/walk-forward` | Walk-forward validation with overlapping train/test windows. Returns WFE metric | JSON: windows array, summary metrics, WFE verdict |
| POST | `/backtest/regime-analysis` | Analyze backtest results broken down by market regime | JSON: `regime_metrics`, `overall_verdict`, `best`/`worst` regimes |
| GET | `/backtest/regime-status` | Current regime classification for tracked symbols (MNQ_1h, MGC_1d) | JSON: `current_regime`, `regime_breakdown_30d` per symbol |
| GET | `/backtest/paper-status` | WFE and paper-trading readiness for each symbol | JSON: `symbol`, `wfe`, `paper_start_date`, `trades_to_date`, `expected_duration` |
| POST | `/backtest/monte-carlo` | Run Monte Carlo simulation (N shuffled trade sequences with optional slippage) | JSON: `percentile_statistics`, `confidence_metrics`, `verdict` |
| POST | `/backtest/monte-carlo/chart` | Generate interactive HTML equity curve fan chart from Monte Carlo results | JSON: `chart_path`, `url` |

### Watchlist & Market Data (7 endpoints)

| Method | Path | Description | Response Model |
|--------|------|-------------|----------------|
| GET | `/watchlist` | Configured watchlists with live prices and daily changes | JSON: `futures_watchlist`, `options_watchlist` arrays |
| POST | `/watchlist` | Add a symbol to a watchlist (in-memory, not persisted) | JSON: `status`, `updated_watchlist` |
| DELETE | `/watchlist/{symbol}` | Remove a symbol from the watchlist | JSON: `status`, `updated_watchlist` |
| GET | `/prices/snapshot` | Current prices and daily change % for comma-separated symbols | JSON: price data per symbol |
| GET | `/market/earnings` | Upcoming earnings events near watched symbols | JSON: earnings calendar |
| GET | `/watchlist/scan` | Run MTF analysis on all watchlist symbols (honors kill switch) | JSON: per-symbol signals, consolidated recommendation |
| GET | `/macro/snapshot` | Macro indicators snapshot (Fed Funds, 10Y Treasury, VIX). 5-minute TTL cache | JSON: macro indicator values |

### Pipeline & Decision Making (6 endpoints)

| Method | Path | Description | Response Model |
|--------|------|-------------|----------------|
| POST | `/pipeline/run` | Full 5-stage AI pipeline: Technical -> News -> Social -> Debate -> Trade Decision | JSON: full decision chain, `final_action`, `final_quantity`, `confidence` |
| GET | `/pipeline/status` | Pipeline availability and last run info | JSON: `is_initialized`, `agent_count`, `last_run_timestamp`, `last_run_symbol` |
| GET | `/pipeline/history` | Historical pipeline run records from SQLite | JSON: runs array |
| GET | `/decisions/recent` | Most recent agent decisions from in-memory log | JSON: decisions array |
| POST | `/decisions/log` | Internal endpoint for agents to log decisions to in-memory feed | JSON: status |
| GET | `/signals/stats` | Webhook signal statistics including deduplication cache hits | JSON: `signal_count`, `unique_symbols`, `cache_hits` |

### Scheduler & Automation (2 endpoints)

| Method | Path | Description | Response Model |
|--------|------|-------------|----------------|
| GET | `/scheduler/status` | Scheduled job status and next run times | JSON: jobs array, running status, `next_run_timestamp` |
| POST | `/scheduler/scan-now` | Manually trigger full watchlist scan immediately (bypasses schedule) | JSON: `status`, `scan_started_at` |

### Notifications & Events (4 endpoints)

| Method | Path | Description | Response Model |
|--------|------|-------------|----------------|
| POST | `/notifications/whatsapp/test` | Test WhatsApp notification configuration | JSON: `status` ("sent" or "failed") |
| POST | `/notifications/vix-alert-check` | Check VIX and send WhatsApp alert if above key thresholds | JSON: `vix_value`, `alert_sent` |
| POST | `/thinkscript/generate` | Generate ThinkScript code from JARVIS analysis results | JSON: `thinkscript_code`, `file_path` |
| GET | `/macro/series/{series_id}` | Historical data for a FRED series (e.g. FEDFUNDS, GS10, UNRATE) | JSON: series data points |

### Analytics & Reporting (10 endpoints)

| Method | Path | Description | Response Model |
|--------|------|-------------|----------------|
| GET | `/analytics/performance` | Forward-test validation report comparing paper trading to backtest targets | JSON: `metrics`, `targets`, `deltas`, `verdict` |
| GET | `/analytics/performance/rolling` | Rolling performance metrics for last N days (7, 14, 30) | JSON: daily metrics array |
| GET | `/analytics/performance/compare` | Current forward-test metrics vs. backtest target benchmarks | JSON: current vs. target comparison |
| GET | `/analytics/mtf` | Multi-timeframe STC analysis for a single symbol (daily, hourly, 5m) | JSON: STC oscillator and trend bias per timeframe |
| GET | `/analytics/trades/by-day` | Day-of-week breakdown of paper trade performance | JSON: per-day stats |
| GET | `/analytics/trades/by-symbol` | Per-symbol breakdown of paper trade performance | JSON: symbol breakdown |
| GET | `/analytics/trades/by-hour` | Hour-of-day trade performance breakdown | JSON: hourly metrics (0-23) |
| GET | `/reports/performance` | Generate self-contained HTML performance report with charts | HTML content |
| GET | `/alerts/history` | Recent alert log entries (default limit 50) | JSON: alerts array |
| GET | `/alerts/stats` | Alert counts grouped by type and status | JSON: counts per type/status |

### WebSocket (2 endpoints)

| Type | Path | Description |
|------|------|-------------|
| WEBSOCKET | `/ws/events` | Real-time trading event stream. Broadcasts: `order_fill`, `kill_switch`, `circuit_breaker`, `pipeline_complete`, `safety_event`, `price_update`, `ping` |
| GET | `/ws/status` | WebSocket manager status: connected client count, connection uptime, `is_running` |

**WebSocket message format:**
```json
{
  "type": "event_type",
  "data": { ... },
  "timestamp": "ISO8601"
}
```

### Additional Routers (mounted separately)

| Router | Prefix | Source Module | Purpose |
|--------|--------|---------------|---------|
| `journal_router` | `/journal` | `routers/journal_router.py` | Trade journal CRUD endpoints for notes, tags, moods, lessons |
| `webhook_router` | `/webhook` | `routers/webhook_router.py` | TradingView webhook receiver for signal ingestion |

### Endpoint Summary by Category

| Category | Count |
|----------|-------|
| Health & Diagnostics | 3 |
| Safety & Risk | 7 |
| Strategy Config | 4 |
| Analysis & Sentiment | 5 |
| Portfolio & Paper Trading | 15 |
| Paper Trading (MGC) | 3 |
| Backtesting & Validation | 8 |
| Watchlist & Market Data | 7 |
| Pipeline & Decision Making | 6 |
| Scheduler & Automation | 2 |
| Notifications & Events | 4 |
| Analytics & Reporting | 10 |
| WebSocket | 2 |
| Journal Router (separate) | ~6 |
| Webhook Router (separate) | ~2 |
| **TOTAL** | **~84** |

---

## 1.12 ThinkOrSwim Script Library

**Source directory**: `C:\Users\mattm\ThinkorSwim\jarvis-trader\thinkorswim-scripts\`
**Primary reference**: `INTEGRATION_GUIDE.md` (506 lines, version 1.0, generated 2026-03-29)
**Total files**: 34 `.ts` files (21 unique scripts + 13 TOS-generated nested duplicates)

### Overview

The TOS scripts provide a **visual overlay** that mirrors the JARVIS engine signal framework. TOS generates visual alerts and chart annotations; JARVIS generates automated trade decisions. Both systems use identical indicator parameters so that what Matt sees on the TOS chart matches what the engine computes.

### Layer 1 -- Regime Map (3 scripts)

*What regime is the market in? (TRENDING_BULL, TRENDING_BEAR, COMPRESSION, RANGE_BOUND, EXHAUSTED)*

| Script File | What It Shows | JARVIS Signal | Key Parameters |
|---|---|---|---|
| `Saty_ATR_LevelsSTUDY.ts` | EMA Ribbon (8/21/34) on price chart. Green label = bullish, red = bearish, orange = mixed. ATR range consumed % vs full ATR | `ema_trend` (TRENDING_BULL/BEAR). ATR consumed >90% = EXHAUSTED | `fast_ema=8`, `pivot_ema=21`, `slow_ema=34`, `atr_length=14` |
| `Saty_Phase_OscillatorSTUDY.ts` | Phase oscillator -100 to +100. Magenta = compression. Fibonacci zone lines at +/-23.6, +/-61.8, +/-100 | `phase_val`, `phase_compression`. Magenta = COMPRESSION regime | EMA(21), ATR(14), BB(21, 2.0) -- all hardcoded |
| `shared_mtftrendbarSTUDY.ts` | CCI-based trend trail stop line (green = long, red = short). Up/down arrows on CCI zero-cross | Supplementary regime confirmation via CCI(50) | Configurable timeframe, default 5m |

**EMA Ribbon Rule** (hardcoded in Saty ATR Levels):
- Bullish: `price >= ema8 >= ema21 >= ema34`
- Bearish: `price <= ema8 <= ema21 <= ema34`
- Exact same logic as `ema_ribbon()` in `engine/backtest/indicators.py`

### Layer 2 -- Structure Map (6 scripts)

*Where is price relative to value? (BUYER_CONTROL, SELLER_CONTROL, NEUTRAL_STRUCTURE)*

| Script File | What It Shows | JARVIS Signal |
|---|---|---|
| `AA_CoreyTPOProfilev1STUDY.ts` | TPO time profile with POC (white), VAH/VAL (cyan), Fibonacci extensions from POC | POC = VPOC, VAH = `va_high`, VAL = `va_low`. Price above VAH + POC = BUYER_CONTROL |
| `AA_CoreyTscorev2STUDY.ts` | TPO score quantifying price vs POC/VAH/VAL as numeric score. Labels: "Buyers in Control", "Sellers in Control" | Direct readout of `layer2_structure()`. Positive = BUYER_CONTROL |
| `AA_CoreyIBv1STUDY.ts` | Initial Balance (first 60-min RTH range). IB High (red), IB Low (green), quadrants, extensions | `ib_high`/`ib_low`. IB High breakout = ENTRY_NOW trigger |
| `AA_CoreyRFv2STUDY.ts` | Rangefinder v2 -- dynamic volume profile resetting on range expansion. Control zone 38.2-61.8% | VP context between IB resets. Range extensions = imbalance targets |
| `AA_CoreySFv2STUDY.ts` | Singlefinder v2 -- identifies single prints (price areas visited only once). Bullish (pink), bearish (orange) | Gap-fill targets. Unfilled singles act as magnets |
| `AA_CoreyGapfinderv1STUDY.ts` | Marks open-to-close gaps. Gap Down (red), Gap Up (green). Lines extend until filled | Supplementary Layer 2 context |

### Layer 3 -- Directional Bias (3 scripts)

*What is the directional lean? (STRONG_BULL, LEAN_BULL, NEUTRAL, LEAN_BEAR, STRONG_BEAR)*

| Script File | What It Shows | JARVIS Signal | Alert Conditions |
|---|---|---|---|
| `NextSignalMomentumSTUDY.ts` | KAMA (Kaufman Adaptive MA, period=10) on price. Blue = above KAMA (long), Red = below (short). Also plots 7/20-bar linear regression | `kama_signal` = long/short. Matches `kama()` in `indicators.py` | `close` crosses above/below `MAA` plot |
| `Saty_Volume_StackSTUDY.ts` | Buy/sell volume separated by candle OHLC ratio. Winner stacked on top. Label shows buy%/sell% | `buy_pct`. >60% = buyer_dominant, <40% = seller_dominant | Visual monitoring only |
| `shared_OB_STYLE_CYCLE_TIMESHIFT_PAINT_BARSSTUDY.ts` | STC (Schaff Trend Cycle) oscillator 0-100. Green = rising, red = falling. Crossover arrows at OB/OS levels. Paints price bars | `stc_val`, `stc_cross_up`, `stc_cross_down`. Crossover arrows ARE the JARVIS entry signals | `RegularBuy` (green arrow up), `RegularSell` (red arrow down) |

**STC Parameters** (must match engine):

| Parameter | TOS Input | JARVIS Value |
|---|---|---|
| Fast EMA | `fastLength` | 23 |
| Slow EMA | `slowLength` | 50 |
| %K period | `KPeriod` | 10 |
| %D smoothing | `DPeriod` | 3 |
| Oversold (1h) | `over_sold` | 15 |
| Oversold (daily) | `over_sold` | 23 |
| Overbought | `over_bought` | 83 |

### Layer 4 -- Entry Timing (7 scripts)

*Is this bar an entry? (ENTRY_NOW, WAIT_FOR_PULLBACK, NO_TRADE, FADE_EXTREME)*

| Script File | What It Shows | JARVIS Entry Signal |
|---|---|---|
| `shared_OB_STYLE_CYCLE_TIMESHIFT_PAINT_BARSSTUDY.ts` | STC crossover arrows: RegularBuy (green up), RegularSell (red down) | `stc_cross_up` = ENTRY_NOW (long), `stc_cross_down` = ENTRY_NOW (short) |
| `AA_CoreyIBv1STUDY.ts` | IB High breakout: price closes above IB High with cloud confirmation | `above_ib_high` fresh breakout = ENTRY_NOW (unconditional) |
| `shared_shared_shared_shared_kelt_3.01STUDY.ts` | Keltner Channel single-factor (default iFactor=3.0, iLength=20, SMA) | 3.0x band = extreme level. `kelt_basis` in JARVIS |
| `shared_shared_OB_OMEGA_5mSTUDY.ts` | OB Omega -- dual Keltner (1.5x and 2.0x factors). Horizontal level lines with labels. Embedded MACD primer cloud | Outer (2.0x) breach = outer Keltner signal. Inner (1.5x) = inner band |
| `shared_shared_OB_OMEGA_15m7STUDY.ts` | OB Omega scaled for 15-min aggregation | Same signals, different timeframe |
| `shared_shared_OB_OMEGA_30m7STUDY.ts` | OB Omega scaled for 30-min aggregation | Same signals, different timeframe |
| `AA_CoreyRFv2STUDY.ts` | Range expansion arrows (up=green, down=red) on new range expansions | Arrow up + bull bias = ENTRY_NOW candidate |

### Layer 5 -- Position Sizing / ATR Stops & Targets (2 scripts)

| Script File | What It Shows | JARVIS Sizing Signal |
|---|---|---|
| `Saty_ATR_LevelsSTUDY.ts` | All ATR Fibonacci levels from prior close: 0.236x, 0.382x, 0.5x, 0.618x, 0.786x, 1.0x, extensions to 3.0x. Cyan trigger = +0.236 ATR (calls), orange = -0.236 ATR (puts) | `stop_level` = 0.70 ATR, `target_1` = 1.50 ATR (1h) / 2.00 ATR (daily), `target_2` = 2.618 ATR, `target_3` = 4.00 ATR |
| `shared_Saty_ATR_LevelsSTUDY.ts` | Duplicate for TOS sharing import | Same as above |

**ATR Level Mapping to Chart Lines**:
- Stop (0.70 ATR): between `lower_0618` (orange) and `lower_0786` (gray) lines
- T1 (1.50 ATR): `upper_1500` / `lower_1500` lines
- T2 (2.618 ATR): `upper_2618` / `lower_2618` lines (golden ratio extension)
- T3 (4.00 ATR): beyond default chart range -- calculate manually

### Supporting/Supplementary Scripts (6 files)

| Script File | Purpose |
|---|---|
| `GAPS_Chetan1STUDY.ts` | Alternative gap-finder (Chetan version) -- double confirmation alongside Corey's |
| `TRIN_ChetanSTUDY.ts` | TRIN (Arms Index) for market internals. High TRIN (>2.0) = extreme selling |
| `ThinkScript_study_20221014STUDY.ts` | Custom utility script (Oct 2022) |
| `ThinkScript_study_20221016STUDY.ts` | Custom utility script (Oct 2022) |
| `ThinkScript_study_20230523STUDY.ts` | Custom utility script (May 2023) |
| `AA_CoreyRFv1MobileSTUDY.ts` | Rangefinder v1 mobile variant (legacy -- use RFv2 instead) |

### Duplicate Files (13 -- ignore during import)

These are TOS-generated nested copies created during export/sharing. Import only the root-level originals listed in the layers above.

| Duplicate File | Use Instead |
|---|---|
| `shared_AA_CoreyRangefinderv1_01STUDY.ts` | `AA_CoreyRFv2STUDY.ts` |
| `shared_AA_CoreySinglefinderv2STUDY.ts` | `AA_CoreySFv2STUDY.ts` |
| `shared_AA_CoreyTPOScorev2STUDY.ts` | `AA_CoreyTscorev2STUDY.ts` |
| `shared_midcloudoteSTUDY.ts` | Sub-study -- do not add directly |
| `shared_Saty_ATR_LevelsSTUDY.ts` | `Saty_ATR_LevelsSTUDY.ts` |
| `shared_shared_midcloudoteSTUDY.ts` | Sub-study -- do not add directly |
| `shared_shared_OB_LBR_BARS_HH_LL17STUDY.ts` | Sub-study -- do not add directly |
| `shared_shared_shared_shared_shared_kelt_3.01STUDY.ts` | Deeper nested -- ignore |
| `shared_shared_shared_shared_shared_kmaster1STUDY.ts` | Sub-study dependency |
| `shared_shared_shared_shared_shared_Priceline11STUDY.ts` | Sub-study dependency |
| `shared_shared_shared_shared_shared_shared_kmaster1STUDY.ts` | Deeper nested -- ignore |
| `shared_shared_shared_shared_shared_shared_Priceline11STUDY.ts` | Deeper nested -- ignore |
| `shared_OB_STYLE_CYCLE_TIMESHIFT_PAINT_BARSSTUDY.ts` | This IS the main STC study -- USE this one |

### TOS-to-JARVIS Signal Mapping

TOS scripts are **visual confirmation** tools. JARVIS is the **decision engine**. The relationship:

1. **TOS generates visual alerts** (arrows, color changes, sound notifications) that Matt sees on his chart
2. **JARVIS generates trades** (pipeline decisions, order submissions) based on the same indicator calculations
3. Parameters are identical between TOS inputs and `engine/backtest/signals.py` constants
4. When JARVIS fires an STC cross signal, the corresponding green/red arrow appears on the TOS chart simultaneously

### TOS Workspace Setup

**Import order** (sub-studies first, then main studies):

1. `shared_shared_shared_shared_kelt_3.01STUDY.ts` -- Keltner core
2. `shared_shared_shared_shared_shared_kmaster1STUDY.ts` -- KMaster support
3. `shared_shared_shared_shared_shared_Priceline11STUDY.ts` -- Price line support
4. `Saty_ATR_LevelsSTUDY.ts` -- ATR levels + EMA ribbon (upper panel)
5. `Saty_Phase_OscillatorSTUDY.ts` -- Phase oscillator (lower panel)
6. `Saty_Volume_StackSTUDY.ts` -- Volume stack (lower panel)
7. `NextSignalMomentumSTUDY.ts` -- KAMA on price (upper panel)
8. `shared_OB_STYLE_CYCLE_TIMESHIFT_PAINT_BARSSTUDY.ts` -- STC (lower panel)
9. TPO/IB/RF/SF/Gap scripts (upper panel)
10. OB Omega Keltner scripts (upper panel)

**Save as**: "JARVIS 5-Layer 1H" and "JARVIS 5-Layer Daily" chart templates.

---

## 1.13 Dashboard Architecture

**Framework**: Next.js 15, TypeScript, Tailwind CSS
**Port**: 3010
**Design system**: Dark terminal aesthetic, monospace typography, navy/cyan accent palette
**Charts**: Recharts (equity curves, histograms, heatmaps)
**Data fetching**: SWR with 5-second default polling interval
**API connection**: `fetchEngine()` utility in `lib/api.ts` targeting `http://localhost:8010`
**Build verification**: `npm run build` (TypeScript must pass with 0 errors)
**Startup**: `cd dashboard && npm run dev`

### All 13 Pages

| Route | File | Purpose | Key Widgets/Components | Primary API Endpoints |
|-------|------|---------|------------------------|-----------------------|
| `/` | `app/page.tsx` | Main dashboard -- overview of all systems | KillSwitch, PositionsPanel, AgentFeed, SentimentPanel, PerformancePanel, WatchlistBar, PaperTradingPanel, TradeHistory, DailyPnlPanel, RegimeDisplay, MTFConfirmationWidget, SignalHistory, CircuitBreakerPanel, IBGatewayStatus, StrategyParamsPanel, SessionTodayWidget | `/health`, `/safety/status`, `/portfolio`, `/decisions/recent`, `/sentiment/recent`, `/watchlist`, `/macro/snapshot` |
| `/command-center` | `app/command-center/page.tsx` | Unified command center -- system health, safety status, portfolio overview, quick actions | Health status cards, safety layer widgets, portfolio summary, kill switch controls, connection health, pipeline status | `/health`, `/health/full`, `/safety/status`, `/safety/circuit-breakers`, `/portfolio`, `/ws/status` |
| `/backtest` | `app/backtest/page.tsx` | Backtest runner and results viewer -- equity curves, trade tables, parameter display | Recharts equity curve, trade table, backtest metrics cards | `/backtest/results`, `/backtest/run` |
| `/validation` | `app/validation/page.tsx` | Walk-forward validation results, WFE badges, regime analysis display | ValidationChecklist, WFE progress bars, regime breakdown tables | `/backtest/paper-status`, `/backtest/regime-status`, `/analytics/performance/compare` |
| `/performance` | `app/performance/page.tsx` | Detailed performance analytics -- rolling metrics, symbol breakdown, hourly analysis | PerformanceSummaryWidget, DrawdownChart, RollingPerformanceWidget, TradePnLHistogram, BestWorstTradesWidget | `/analytics/performance`, `/analytics/performance/rolling`, `/analytics/trades/by-symbol`, `/analytics/trades/by-hour` |
| `/stats` | `app/stats/page.tsx` | Statistical summary page | Performance summary cards, aggregate statistics | `/portfolio/stats/summary` |
| `/health` | `app/health/page.tsx` | System health monitoring -- all subsystem status, uptime, connectivity | Health status cards, subsystem checklist, API key validation, DB status | `/health/full`, `/system/preflight` |
| `/settings` | `app/settings/page.tsx` | Risk parameter configuration, strategy parameter tuning, notification settings | RiskSettingsWidget, EngineConfigCard, NotificationTestPanel | `/settings/risk`, `/strategy/params`, `/safety/config` |
| `/journal` | `app/journal/page.tsx` | Trade journal -- notes, tags, moods, lessons per trade | Journal entry cards, tag filters, mood selector | `/journal/*` endpoints |
| `/watchlist` | `app/watchlist/page.tsx` | Watchlist management and live price monitoring | WatchlistScanWidget, price cards, add/remove symbols | `/watchlist`, `/watchlist/scan`, `/prices/snapshot` |
| `/paper` | `app/paper/page.tsx` | Paper trading dashboard -- MGC signal status, trade logging, performance tracking | PaperTradingPanel, signal display, trade logger | `/paper/mgc-signal`, `/paper/mgc-performance`, `/portfolio/paper/positions` |
| `/scorecard` | `app/scorecard/page.tsx` | Daily/weekly scorecard -- win rate targets, P&L targets, discipline metrics | Scorecard widgets, target progress bars | `/portfolio/stats/summary`, `/portfolio/stats/weekly` |
| `/analysis` | `app/analysis/page.tsx` | Technical analysis viewer -- run analysis on symbols, view results | Analysis form, results display | `/analyze/technical`, `/analyze/bars/{symbol}` |

### Key Dashboard Components (90+ components in `dashboard/components/`)

**Core Trading Components:**
- `KillSwitch.tsx` -- Emergency kill switch toggle with confirmation dialog
- `PositionsPanel.tsx` / `OpenPositionsWidget.tsx` -- Current open positions with P&L
- `PaperTradingPanel.tsx` -- Paper trade entry form and status
- `OrderEntryPanel.tsx` -- Manual order entry interface
- `SignalHistory.tsx` / `SignalQueueWidget.tsx` -- Signal log and pending signals

**Performance & Analytics:**
- `PerformancePanel.tsx` / `PerformanceSummaryWidget.tsx` -- Aggregate performance metrics
- `DailyPnlPanel.tsx` / `DailyPnLChart.tsx` -- Daily P&L display and Recharts chart
- `DrawdownChart.tsx` -- Max drawdown visualization
- `SharpeRatioWidget.tsx` -- Sharpe ratio display
- `ProfitFactorWidget.tsx` -- Profit factor gauge
- `CalendarHeatmap.tsx` -- Trade calendar heatmap visualization
- `TradePnLHistogram.tsx` -- P&L distribution histogram
- `WeeklyPerformanceWidget.tsx` / `WeeklyPnLCard.tsx` -- Weekly stats

**Risk & Safety:**
- `CircuitBreakerPanel.tsx` / `CircuitBreakerWidget.tsx` -- Circuit breaker status display
- `RiskStatusWidget.tsx` / `RiskSettingsWidget.tsx` -- Risk metrics and settings
- `MaxDrawdownTrackerWidget.tsx` -- Drawdown tracking
- `WinStreakWidget.tsx` / `PnLStreakWidget.tsx` / `StreakBadge.tsx` -- Win/loss streak display

**Market & Regime:**
- `RegimeDisplay.tsx` / `MarketRegimeWidget.tsx` -- Current market regime classification
- `MTFConfirmationWidget.tsx` -- Multi-timeframe signal confirmation
- `VIXRegimeCard.tsx` -- VIX level and regime
- `SentimentPanel.tsx` -- Reddit/news sentiment display
- `WatchlistBar.tsx` / `WatchlistScanWidget.tsx` -- Watchlist display and scan results
- `MarketSessionIndicator.tsx` / `MarketSessionStatusCard.tsx` -- Market open/close status

**System & Infrastructure:**
- `IBGatewayStatus.tsx` / `IbGatewayDetailCard.tsx` -- IB Gateway connection status
- `SystemMetricsPanel.tsx` -- System-level metrics
- `EngineUptimeCard.tsx` / `EngineConfigCard.tsx` -- Engine uptime and configuration
- `ConnectionHealthCard.tsx` -- API connectivity health
- `DatabaseStatsCard.tsx` -- SQLite database statistics
- `WhatsAppStatusCard.tsx` -- WhatsApp notification status
- `PipelineStatusWidget.tsx` / `PipelineRunHistory.tsx` -- Pipeline execution status

**Agent & Decision:**
- `AgentFeed.tsx` -- Live agent decision feed
- `DecisionLogWidget.tsx` / `DecisionBreakdownCard.tsx` / `RecentDecisionsWidget.tsx` -- Decision history and breakdowns
- `StrategyParamsPanel.tsx` / `StrategyParamsCard.tsx` -- Strategy parameter display

**Planning & Readiness:**
- `ReadinessCheckWidget.tsx` / `PreFlightWidget.tsx` -- Pre-trading checklist
- `GoLivePlanCard.tsx` -- Live trading readiness plan
- `PhaseProgressWidget.tsx` -- Paper trading phase progress
- `TradingDaysCountdownCard.tsx` -- Countdown to live trading
- `MonthlyTargetCard.tsx` -- Monthly performance targets

### Badge System

The dashboard uses a consistent badge color system across all pages:

| Badge Type | Color | Tailwind Classes | Usage |
|------------|-------|-----------------|-------|
| Bull / Success | Green | `bg-green-500/20 text-green-400` | Profitable trades, healthy systems, bull signals |
| Bear / Danger | Red | `bg-red-500/20 text-red-400` | Losses, kill switch active, bear signals, errors |
| Warning | Amber | `bg-amber-500/20 text-amber-400` | Approaching limits, marginal WFE, caution states |
| Info | Cyan | `bg-cyan-500/20 text-cyan-400` | Neutral information, system status |
| Neutral | Gray | `bg-gray-500/20 text-gray-400` | Inactive, no data, hold decisions |

### Design System

- **Background**: `bg-gray-950` (near-black)
- **Cards**: `bg-gray-900` with `border-gray-800` borders
- **Text primary**: `text-gray-100`
- **Text secondary**: `text-gray-400`
- **Accent**: Cyan (`text-cyan-400`, `border-cyan-500`)
- **Typography**: Monospace for data values (`font-mono`), system sans-serif for labels
- **Icons**: Lucide React icon library throughout
- **UI Components**: shadcn/ui (Card, Badge, Button, Progress, Tabs)

---

## 1.14 Infrastructure

### Database Architecture

#### SQLite (Primary -- `data/jarvis_trader.db`)

The primary data store. Thread-safe via `threading.Lock`. WAL journal mode for read concurrency. Connection-per-call pattern (no shared connections). All timestamps stored as ISO-8601 UTC strings.

**Migration system**: Version-tracked via `schema_version` table. 5 migrations applied sequentially. Each migration is idempotent (uses `IF NOT EXISTS`).

**Tables (9 total across 5 migrations):**

| Table | Migration | Purpose | Key Columns |
|-------|-----------|---------|-------------|
| `schema_version` | Bootstrap | Tracks applied migration versions | `version` INTEGER, `applied_at` TEXT, `description` TEXT |
| `paper_trades` | v001 | Full lifecycle of every simulated trade | `trade_id` TEXT UNIQUE, `symbol`, `side` (buy/sell/buy_to_open/sell_to_open), `quantity` REAL, `entry_price` REAL, `exit_price` REAL, `entry_time` TEXT, `exit_time` TEXT, `pnl` REAL, `status` (open/closed/cancelled), `strategy_params` JSON, `notes` TEXT |
| `decisions` | v001 | Pipeline decision log with agent reasoning | `symbol`, `timestamp`, `action` (buy/sell/hold/exit_long/exit_short), `confidence` REAL 0.0-1.0, `regime`, `signal_data_json` TEXT, `reasoning` TEXT |
| `daily_pnl` | v001 | End-of-day P&L snapshots | `date` TEXT UNIQUE (YYYY-MM-DD), `starting_balance`, `ending_balance`, `realized_pnl`, `unrealized_pnl`, `total_trades`, `winning_trades`, `losing_trades`, `max_drawdown` |
| `positions` | v001 | Current open positions (live mirror) | `symbol` TEXT UNIQUE, `quantity`, `entry_price`, `entry_time`, `current_price`, `unrealized_pnl`, `stop_loss`, `take_profit` |
| `settings` | v001 | Key/value config store | `key` TEXT PRIMARY KEY, `value` TEXT, `updated_at` TEXT |
| `trade_journal` | v002 | Trade annotations with notes, tags, mood, lessons | `trade_id` TEXT (soft FK), `timestamp`, `note`, `tags` TEXT (comma-separated), `mood` (confident/uncertain/frustrated/neutral), `lesson` TEXT |
| `pipeline_runs` | v003 | History of every TradingPipeline execution | `run_id` TEXT UNIQUE (8-char UUID prefix), `symbol`, `webhook_action` (LONG/SHORT/CLOSE), `source` (tradingview/manual), `final_action`, `final_quantity`, `requires_human` BOOLEAN, `summary`, `status` (completed/error/skipped), `error_message`, `duration_ms`, `created_at` |
| `journal_notes` | v004 | Free-form trade observations not tied to specific trades | `trade_id` TEXT (optional), `note_type` (observation/lesson/alert), `title`, `body`, `tags` JSON array, `created_at`, `updated_at` |
| `alert_log` | v005 | History of every WhatsApp/notification sent | `alert_type` (trade_opened/trade_closed/morning_briefing/vix_alert/circuit_breaker/notification), `symbol` TEXT, `message`, `channel` (whatsapp), `status` (sent/failed/suppressed), `error` TEXT, `created_at` |

#### LLM Cost Database (`data/llm_costs.db`)

Separate SQLite file for LLM API cost tracking.

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `llm_calls` | Per-call LLM usage and cost | `timestamp` TEXT, `model` (e.g. "claude-opus-4-6"), `input_tokens` INT, `output_tokens` INT, `cost_usd` REAL, `latency_ms` INT, `agent_name` TEXT, `success` BOOLEAN |

Indexed on `timestamp`, `model`, and `agent_name` for fast per-day/per-model/per-agent queries.

#### PostgreSQL (Docker -- `jarvis_postgres`)

Defined in `infrastructure/docker-compose.yml` for production-grade order/audit storage. Not yet active in paper trading phase.

- **Image**: `postgres:16-alpine`
- **Port**: 5432
- **Credentials**: `jarvis`/`jarvis`
- **Database**: `jarvis_trader`
- **Init script**: `infrastructure/postgres/init.sql`
- **Volume**: `postgres_data` (persistent)

#### QuestDB (Docker -- `jarvis_questdb`)

Time-series database for high-frequency market data storage.

- **Image**: `questdb/questdb:8.2.3`
- **Ports**: 9000 (HTTP API + Web console), 9009 (InfluxDB line protocol), 8812 (PostgreSQL wire)
- **Volume**: `questdb_data` (persistent)

### Prometheus Metrics (10 custom metrics)

Defined in `engine/monitoring/metrics.py`. Uses the `prometheus_client` Python library.

| Metric Name | Type | Labels | Description |
|-------------|------|--------|-------------|
| `jarvis_pipeline_runs_total` | Counter | `symbol`, `decision` | Total number of trading pipeline runs |
| `jarvis_pipeline_duration_seconds` | Histogram | `symbol` | Duration of pipeline execution (buckets: 0.5, 1, 2, 5, 10, 30, 60s) |
| `jarvis_llm_calls_total` | Counter | `model`, `agent`, `success` | Total number of LLM API calls |
| `jarvis_llm_cost_usd` | Counter | `model` | Total USD cost of LLM API calls |
| `jarvis_orders_total` | Counter | `symbol`, `direction`, `status` | Total number of orders submitted |
| `jarvis_daily_pnl_usd` | Gauge | (none) | Current daily P&L in USD |
| `jarvis_equity_usd` | Gauge | (none) | Current account equity in USD |
| `jarvis_kill_switch_active` | Gauge | (none) | Kill switch status (0=off, 1=active) |
| `jarvis_safety_events_total` | Counter | `event_type` | Total number of safety layer events |
| `jarvis_consecutive_losses` | Gauge | (none) | Number of consecutive losing trades |

**Helper functions** for metric recording:
- `record_pipeline_run(symbol, decision)`
- `record_pipeline_duration(duration, symbol)`
- `record_llm_call(model, agent, success)`
- `record_llm_cost(model, cost_usd)`
- `record_order(symbol, direction, status)`
- `set_daily_pnl(pnl_usd)`
- `set_equity(equity_usd)`
- `set_kill_switch(active)`
- `record_safety_event(event_type)`
- `set_consecutive_losses(count)`

### Grafana Dashboards

Grafana runs on port 3030 (mapped from container port 3000 to avoid conflict with Next.js).

**Image**: `grafana/grafana:11.4.0`
**Provisioning**: `infrastructure/grafana/provisioning/` (auto-configures data sources and dashboards)
**Admin password**: Set via `GF_ADMIN_PASSWORD` env var (default: `jarvis_change_me`)

Three planned dashboards:

1. **Trading Performance**: P&L curve (`jarvis_daily_pnl_usd`), pipeline runs by symbol/decision, LLM cost tracking
2. **System Health**: Pipeline duration histogram, LLM call success rate, engine uptime via `/health`
3. **Risk Monitor**: Kill switch state (`jarvis_kill_switch_active`), consecutive losses gauge, equity tracking, safety events counter

### Docker Compose Services

Defined in `infrastructure/docker-compose.yml` (version 3.9):

| Service | Image | Container | Ports | Purpose |
|---------|-------|-----------|-------|---------|
| `questdb` | `questdb/questdb:8.2.3` | `jarvis_questdb` | 9000, 9009, 8812 | Time-series market data |
| `postgres` | `postgres:16-alpine` | `jarvis_postgres` | 5432 | Relational orders/audit |
| `redis` | `redis:7.4-alpine` | `jarvis_redis` | 6379 | Cache, signal bus, feature store |
| `prometheus` | `prom/prometheus:v2.51.0` | `jarvis_prometheus` | 9090 | Metrics collection |
| `grafana` | `grafana/grafana:11.4.0` | `jarvis_grafana` | 3030 | Monitoring dashboards |

**Volumes** (5 persistent): `questdb_data`, `postgres_data`, `redis_data`, `prometheus_data`, `grafana_data`

**Redis configuration**: `appendonly yes`, `maxmemory 512mb`, `maxmemory-policy allkeys-lru`

### Windows Startup (`start_jarvis.bat`)

Double-click startup script at project root. Launches all services in separate terminal windows.

**Startup sequence:**
1. Check for `engine/.env` existence (warn if missing)
2. Initialize SQLite database via `engine/init_db.py` (safe to run every startup)
3. Launch Engine on port 8010 (`uvicorn main:app --port 8010`)
4. Wait for engine health check (`/health` endpoint) -- up to 30 retries at 2-second intervals
5. Launch Dashboard on port 3010 (`npm run dev`)
6. Launch Health Monitor (`python health_monitor.py`)
7. Open `http://localhost:3010` in default browser

### Health Monitor (`engine/health_monitor.py`)

Standalone Python script (stdlib only -- zero third-party dependencies) that runs alongside the engine.

| Setting | Value |
|---------|-------|
| Health URL | `http://localhost:8010/health` |
| Polling interval | 60 seconds |
| Request timeout | 10 seconds |
| Alert cooldown | 300 seconds (5 minutes) |

**Behavior:**
- Polls `/health` every 60 seconds
- If HTTP 200: logs "OK -- Engine is healthy"
- If not 200 or timeout: logs "DOWN -- Engine not responding"
- On first DOWN detection: sends WhatsApp alert via Twilio with restart instructions
- Subsequent DOWN alerts: suppressed for 5-minute cooldown period
- On recovery (was down, now up): sends "JARVIS Engine RECOVERED" WhatsApp message

**WhatsApp delivery**: Direct Twilio REST API via `urllib` (no `requests` library needed). Uses Basic Auth with base64-encoded `ACCOUNT_SID:AUTH_TOKEN`. Configuration loaded from `engine/.env` with minimal parser.

### LLM Client (`engine/llm/cost_tracker.py`)

**Cost tracking**: Every LLM API call logged to `data/llm_costs.db` with:
- Timestamp (ISO-8601 UTC)
- Model name (e.g., `claude-opus-4-6`, `claude-sonnet-4-6`, `claude-haiku-4-5`)
- Input/output token counts
- Cost in USD
- Latency in milliseconds
- Agent name (which of the 10 agents made the call)
- Success/failure boolean

**Models used in the pipeline:**
- Claude Opus 4.6 -- Fund Manager, senior decision agents
- Claude Sonnet 4.6 -- Technical/News/Social analysts, debate orchestrator
- Claude Haiku 4.5 -- Lightweight classification, sentiment scoring

**Query endpoint**: `GET /llm/stats?days_back=N` returns per-model and per-agent cost breakdowns for any given day.

### Logging

Configured in `main.py` `setup_logging()` function, called first during lifespan startup.

| Component | Configuration |
|-----------|---------------|
| Log directory | `engine/logs/` (auto-created) |
| Main log file | `logs/jarvis.log` |
| File handler | `RotatingFileHandler`, 10MB max size, 5 backup files |
| File format | JSON structured via custom `JSONFormatter` |
| Console handler | Human-readable: `%(asctime)s [%(levelname)s] %(name)s: %(message)s` |
| Log level | Configurable via `LOG_LEVEL` environment variable (default: `INFO`) |
| Health monitor log | Separate file at `logs/health.log` (plain text format) |

**JSON log format:**
```json
{
  "timestamp": "2026-03-30T14:30:00.000Z",
  "level": "INFO",
  "module": "main",
  "funcName": "run_watchlist_analysis",
  "message": "Scheduled scan: ['MNQ', 'MGC', 'SPY']"
}
```

Exception stack traces are included in the `exception` field when present.

### Scheduler

APScheduler (`AsyncIOScheduler`) with Chicago timezone.

| Job | Schedule | Description |
|-----|----------|-------------|
| `watchlist_scan` | Mon-Fri, 9:00-15:30 CT, every 30 minutes | Full pipeline analysis on top 2 futures + top 3 equities from watchlists |
| `daily_mgc_signal` | Daily at 18:00 ET (23:00 UTC) | Fetch GC=F daily bar, run adaptive-regime signals, log pending entries |

Configuration: `max_instances=1`, `misfire_grace_time=300` (5 minutes).

### WebSocket Manager

Real-time event distribution to connected dashboard clients.

- **Module**: `engine/websocket/manager.py` + `engine/websocket/events.py`
- **Endpoint**: `ws://localhost:8010/ws/events`
- **Event types**: `order_fill`, `kill_switch`, `circuit_breaker`, `pipeline_complete`, `safety_event`, `price_update`, `ping`
- **Status endpoint**: `GET /ws/status` returns connected client count and uptime

### Global State (Lifespan-Managed)

All global state is initialized in `main.py`'s `lifespan()` async context manager and torn down on shutdown:

| Manager | Type | Purpose |
|---------|------|---------|
| `data_manager` | `MarketDataManager` | Market data connections (yfinance, Finnhub, IBKR) |
| `safety_layer` | `SafetyLayer` | Kill switch, circuit breakers, position limits |
| `technical_analyst` | `TechnicalAnalystAgent` | LLM-powered technical analysis |
| `trading_pipeline` | `TradingPipeline` | Full 5-stage pipeline with all 10 agents |
| `scheduler` | `AsyncIOScheduler` | Cron-based job scheduling |
| `paper_tracker` | `PortfolioTracker` | Paper trade position tracking and P&L |
| `db_manager` | `DatabaseManager` | SQLite connection factory |
| `pnl_monitor` | `PnLMonitor` | P&L monitoring feeding circuit breakers |
| `eod_scheduler` | `EODScheduler` | End-of-day tasks |
| `order_manager` | `IBOrderManager` | IB Gateway order bridge |
| `ws_manager` | `WebSocketManager` | WebSocket event broadcasting |
| `cost_tracker` | `CostTracker` | LLM cost tracking |
| `loss_tracker` | `ConsecutiveLossTracker` | Consecutive loss position sizing modulation |

### Alert Rate Limiting

WhatsApp alerts are rate-limited with a 2-hour cooldown per symbol to prevent flooding. Tracked in `_last_alert_time` dictionary (in-memory, resets on engine restart).

---

*End of Sections 1.11-1.14. Total endpoints: 82+. Total TOS scripts: 21 unique across 5 layers. Dashboard: 13 pages, 90+ components. Database: 10 tables across 2 SQLite files + PostgreSQL/QuestDB in Docker.*
