# JARVIS TRADER — API Command Catalog

All endpoints served by `engine/main.py` on port **8010**.
Auth: `X-API-Key` header required on all requests.
Dashboard calls all endpoints via `fetchEngine` / `postEngine` in `dashboard/lib/api.ts`.

---

## Health and System

| Method | Path | Purpose | Router |
|---|---|---|---|
| GET | `/health` | Basic liveness check — returns `{status: "ok"}` | `health_router.py` |
| GET | `/health/full` | Deep health: DB, LLM, market data, broker connectivity | `health_router.py` |
| GET | `/status` | System status: kill switch state, P&L, session info | `safety_router.py` |
| GET | `/system/preflight` | Pre-session checklist: all services ready? | `health_router.py` |
| GET | `/module/status` | Status of all registered market modules | `market_router.py` |
| GET | `/llm/stats` | LLM API cost tracking: spend per agent and session | `health_router.py` |

---

## Safety and Kill Switch

| Method | Path | Purpose | Router |
|---|---|---|---|
| POST | `/halt` | Trigger kill switch manually | `safety_router.py` |
| POST | `/resume` | Re-enable trading after halt (human only) | `safety_router.py` |
| GET | `/loss-tracker/status` | Consecutive loss tracker state, position sizing factor | `safety_router.py` |
| GET | `/pnl` | Current P&L vs daily limit (-2%) and drawdown (-10%) | `portfolio_router.py` |

---

## Pipeline and Decisions

| Method | Path | Purpose | Router |
|---|---|---|---|
| POST | `/run` | Trigger full 5-stage pipeline for a symbol | `pipeline_router.py` |
| GET | `/progress` | Current pipeline run progress and stage status | `pipeline_router.py` |
| GET | `/decisions/log` | Full decision log with all pipeline results | `decisions_router.py` |
| GET | `/decisions/recent` | Recent decisions (last N) with summary | `decisions_router.py` |

---

## Analysis and Signals

| Method | Path | Purpose | Router |
|---|---|---|---|
| POST | `/analyze/technical` | Run technical analysis for a symbol (STC, regime, ATR) | `analysis_router.py` |
| GET | `/analyze/bars/{symbol}` | OHLCV bar data for a symbol | `analysis_router.py` |
| POST | `/scan` | Scan all watchlist symbols and return ranked signals | `analysis_router.py` |
| GET | `/scheduler/manual-scan` | Trigger a manual scheduler scan cycle | `analysis_router.py` |
| GET | `/sentiment/recent` | Recent sentiment readings across all sources | `sentiment_router.py` |
| GET | `/sentiment/reddit` | Reddit sentiment for a symbol | `sentiment_router.py` |
| GET | `/macro/snapshot` | Current macro snapshot (VIX, yield curve, DXY, etc.) | `macro_router.py` |
| GET | `/macro/series/{series_id}` | Historical FRED macro series data | `macro_router.py` |

---

## Backtest and Validation

| Method | Path | Purpose | Router |
|---|---|---|---|
| POST | `/backtest/run` | Run backtest on a symbol with current signal params | `backtest_router.py` |
| GET | `/backtest/results` | Retrieve last backtest results | `backtest_router.py` |
| POST | `/backtest/walk-forward` | Walk-forward efficiency (WFE) analysis | `backtest_router.py` |
| GET | `/backtest/regime-analysis` | Regime performance breakdown | `backtest_router.py` |
| GET | `/backtest/regime-status` | Current detected regime for active instruments | `backtest_router.py` |
| GET | `/backtest/paper-status` | Paper trading run status and recent P&L | `paper_validation_router.py` |
| GET | `/analytics/performance/rolling` | Rolling performance metrics (Sharpe, win rate, etc.) | `analysis_router.py` |
| GET | `/validation/*` | Walk-forward validation endpoints | `validation_router.py` |

---

## Paper Trading

| Method | Path | Purpose | Router |
|---|---|---|---|
| GET | `/paper/runner-status` | Paper trading runner status and queue | `paper_validation_router.py` |
| POST | `/paper/mgc-signal` | Generate MGC signal (halted — monitoring only) | `paper_validation_router.py` |
| POST | `/paper/mgc-log-trade` | Log an MGC paper trade manually | `paper_validation_router.py` |

---

## Portfolio and Positions

| Method | Path | Purpose | Router |
|---|---|---|---|
| GET | `/positions` | All open positions with current P&L | `portfolio_router.py` |
| GET | `/portfolio` | Full portfolio state: positions, allocation, margin | `portfolio_router.py` |
| GET | `/targets` | Price targets and stop levels for open positions | `portfolio_router.py` |
| POST | `/position-sizing/calculate` | Calculate position size given risk params | `portfolio_router.py` |

---

## Market Data

| Method | Path | Purpose | Router |
|---|---|---|---|
| GET | `/markets` | Active markets list with status | `market_router.py` |
| GET | `/market/session` | Current market session (pre/regular/after) | `market_router.py` |
| GET | `/market/earnings` | Upcoming earnings for watched symbols | `market_router.py` |
| GET | `/prices/snapshot` | Latest price snapshot for all watchlist symbols | `prices_router.py` |

---

## Options

| Method | Path | Purpose | Router |
|---|---|---|---|
| GET | `/chain/{symbol}` | Full options chain for symbol | `options_router.py` |
| GET | `/greeks` | Greeks for current option positions | `options_router.py` |
| GET | `/iv-rank/{symbol}` | IV rank (0–100) for a symbol | `options_router.py` |

---

## Crypto

| Method | Path | Purpose | Router |
|---|---|---|---|
| GET | `/crypto/*` | Crypto market data endpoints (monitoring only) | `crypto_router.py` |

---

## Polymarket

| Method | Path | Purpose | Router |
|---|---|---|---|
| GET | `/polymarket/*` | Prediction market sentiment signal endpoints | `polymarket_router.py` |

---

## Strategies

| Method | Path | Purpose | Router |
|---|---|---|---|
| GET | `/strategy/params` | Current strategy parameters per instrument | `strategy_router.py` |
| PUT | `/strategy/params` | Update strategy parameters (Tier 3 for signal params) | `strategy_router.py` |
| GET | `/strategy/recommend` | Strategy parameter recommendations from tuner | `strategy_router.py` |
| GET | `/strategies/*` | Named strategy catalog and status | `strategies_router.py` |

---

## Settings

| Method | Path | Purpose | Router |
|---|---|---|---|
| GET | `/settings/risk` | Current risk configuration (limits, kill switch thresholds) | `settings_router.py` |
| PUT | `/settings/risk` | Update risk settings (requires Tier 3 for safety params) | `settings_router.py` |

---

## Trade Journal

| Method | Path | Purpose | Router |
|---|---|---|---|
| GET | `/trades` | All recorded trades with outcomes | `journal_router.py` |
| POST | `/record` | Record a new trade entry manually | `journal_router.py` |
| GET | `/journal` | Journal entries with notes | `journal_router.py` |
| PATCH | `/journal/{id}` | Update a journal entry | `journal_router.py` |
| DELETE | `/journal/{id}` | Delete a journal entry | `journal_router.py` |

---

## Performance and Reporting

| Method | Path | Purpose | Router |
|---|---|---|---|
| GET | `/summary` | Trading summary: total trades, win rate, net P&L | `reports_router.py` |
| GET | `/performance/7d` | 7-day rolling performance metrics | `reports_router.py` |
| GET | `/stats/streaks` | Win/loss streak statistics | `reports_router.py` |

---

## Watchlist

| Method | Path | Purpose | Router |
|---|---|---|---|
| GET | `/watchlist` | Current watchlist | `watchlist_router.py` |
| POST | `/watchlist` | Add symbol to watchlist | `watchlist_router.py` |
| DELETE | `/watchlist/{symbol}` | Remove symbol from watchlist | `watchlist_router.py` |
| GET | `/watchlist/scan` | Run scan on watchlist symbols | `watchlist_router.py` |

---

## Notifications

| Method | Path | Purpose | Router |
|---|---|---|---|
| POST | `/notifications/whatsapp/test` | Test WhatsApp alert delivery | `engine/main.py` |
| POST | `/notifications/telegram/test` | Test Telegram alert delivery | `engine/main.py` |
| GET | `/notifications/vix-alert-check` | Check if VIX alert threshold is triggered | `engine/main.py` |

---

## Webhooks

| Method | Path | Purpose | Router |
|---|---|---|---|
| POST | `/webhook/tradingview` | Receive TradingView alert webhooks | `webhook_router.py` |
| POST | `/webhook/tradingview/test` | Test webhook receipt | `webhook_router.py` |
| GET | `/webhook/dedup-stats` | Webhook deduplication statistics | `webhook_router.py` |

---

## ThinkScript

| Method | Path | Purpose | Router |
|---|---|---|---|
| POST | `/thinkscript/generate` | Generate ThinkorSwim ThinkScript from signal params | `thinkscript_router.py` |

---

## RL Module (Experimental)

| Method | Path | Purpose | Router |
|---|---|---|---|
| GET | `/rl/status` | RL module status | `analysis_router.py` |
| GET | `/rl/health` | RL module health check | `analysis_router.py` |
| GET | `/rl/models` | Available RL models | `analysis_router.py` |
| POST | `/rl/train` | Train a new RL model | `analysis_router.py` |
| POST | `/rl/train-walkforward` | RL walk-forward training run | `analysis_router.py` |
| GET | `/rl/evaluate` | Evaluate current RL model | `analysis_router.py` |

---

## WebSocket

| Protocol | Path | Purpose | Router |
|---|---|---|---|
| WS | `/ws/status` | Real-time status stream: P&L, kill switch, pipeline state | `websocket_router.py` |

---

## Dashboard Page → Engine Endpoint Mapping

| Dashboard Page | Primary Endpoints |
|---|---|
| Command Center | `/run`, `/progress`, `/status`, `/decisions/recent` |
| Portfolio | `/portfolio`, `/positions`, `/pnl`, `/targets` |
| Analysis | `/analyze/technical`, `/scan`, `/sentiment/recent` |
| Backtest | `/backtest/run`, `/backtest/results`, `/backtest/walk-forward` |
| Health | `/health/full`, `/system/preflight`, `/llm/stats` |
| Journal | `/trades`, `/record`, `/journal` |
| Options | `/chain/{symbol}`, `/greeks`, `/iv-rank/{symbol}` |
| Paper | `/paper/runner-status`, `/backtest/paper-status` |
| Performance | `/performance/7d`, `/stats/streaks`, `/analytics/performance/rolling` |
| Polymarket | `/polymarket/*` |
| Settings | `/settings/risk`, `/strategy/params` |
| Stats | `/summary`, `/stats/streaks` |
| Strategies | `/strategies/*`, `/strategy/recommend` |
| Validation | `/validation/*`, `/backtest/regime-analysis` |
| Watchlist | `/watchlist`, `/watchlist/scan` |
