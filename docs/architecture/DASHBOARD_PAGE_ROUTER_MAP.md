# Dashboard Page → Router → Component Map

> Maps every live dashboard route (`http://127.0.0.1:3010`) to the engine routers that
> feed it and the key components that render it. Generated 2026-06-26.
>
> Scope: 41 App Router pages, 73 engine routers, and the `dashboard/lib/api.ts` wrapper layer.

## How the wiring works

```
app/<route>/page.tsx
  -> widget components
    -> lib/api.ts (fetchEngine / postEngine)
      -> /api/engine rewrite (next.config.ts)
        -> FastAPI engine :8010 (73 routers, matched by URL prefix)

(a few pages bypass the engine: Master API :8030, quotes bridge :8020, AMO via /api/amo)
```

Every engine call routes through `fetchEngine` / `postEngine` in `dashboard/lib/api.ts`,
which prefixes `/api/engine` and is rewritten to the engine. Routers are matched by the
URL prefix declared in each `engine/routers/*.py` (a few prefixes are applied in
`engine/main.py`: `/journal`, `/portfolio`, `/options`, `/flags`).

## Page map (by domain)

Format: `route` — primary router(s) -> key components.

### Overview / command

- `/` (home) — the aggregator: `health`, `safety`, `portfolio`, `decisions`, `pipeline`,
  `analytics`, `discord`, `brokers`, `schwab`, `backtest`, `macro`, `watchlist`,
  `super-engine`, `institutional`, `events`. ~48 widgets: HonestPnlCard, KillSwitch,
  PendingApprovals, PositionsPanel, EngineHealthWidget, RollingWFEWidget, AgentFeed, etc.
  Note: HonestPnlCard pulls from the Master API, not the engine.
- `/command-center` — `health`, `safety`, `portfolio`, `decisions`, `scheduler`, `macro`,
  `backtest`, `journal_review`, `pipeline` (approvals). Components: ApprovalPanel,
  PortfolioCorrelationWidget, SignalFeedWidget, CandlestickChart.
- `/jarvis` — `health`, `analytics` (regime), `discord` (briefing/bookmarks),
  `jarvis` (ask), `reports` (quantstats), `attribution`, plus `/ws/pipeline`.
  Components: HeroStrip, BookmarkThemes/FeedPanel, QuantStatsPanel, AskJarvisPanel.
- `/today` — `health`, `portfolio` (session-today), `paper_validation` (eod),
  `analysis` (bars). Components: metric cards, MarketChart.

### Trades / portfolio / paper

- `/trades` — `paper_validation` (trades/closed), `execution_status` (fidelity).
- `/trades/journal` — `trades_router` (`/trades/journal`).
- `/trades/[id]/review` — `trades_router` (full-review), `analysis` (bars),
  `analytics` (excursion, entry-timing). Components: CandlestickChart, ExcursionPanel.
- `/trades/pending-approvals` — `approval_router` (`/pipeline/pending-approvals` + approve/reject).
- `/portfolio` — `portfolio_router` (summary / health / capital).
- `/paper` — `health`, `paper` (mgc-*), `safety`, `portfolio`, `paper_validation`,
  `settings`, `scanner`, `analytics`.
- `/parallel-paper` — `portfolio_router` (`/portfolio/paper/account/{A|B}/stats`).
- `/journal` — `portfolio_router` (session-today, history/trades).
- `/journal-review` — `journal_review_router` (stats / breakdown / analyze / formalize).

### Performance / stats / validation

- `/performance` — heavily `portfolio_router` (history/*, stats/*, paper/*) + `reports`
  (quantstats), `analytics` (trades/by-day), `journal` (regime-stats). ~22 widgets.
- `/stats` — `analytics` (performance, by-symbol, rolling) + `portfolio_router`
  (history/stats). 16 widgets.
- `/scorecard` — `portfolio_router` (stats/*), `analytics`, `backtest`, `validation`, `reports`.
- `/validation` — `analytics` (performance/compare), `backtest`, `portfolio_router` (stats),
  `paper_validation`, `experiments`, `pipeline`, `settings` (position-sizing), `wfe`.
- `/data-integrity` — `health_router` (`/system/data-integrity`) only.
- `/health` — `health_router` (full/pm2/ib), `alerts`, `portfolio`. Components:
  SystemLivenessCard, PreFlightWidget, DatabaseStatsCard.
- `/regime` — `regime_router` (`/regime/intraday`); falls back to sample data on error.

### Strategy / markets / scanning

- `/strategies` — `strategies_router` (rl/*), `discovery_router`.
- `/strategy-c` — `strategy_c_router` (`/v1/strategy_c/*`).
- `/strategy-c-command` — external: iframe to `strategy-c-command-center.html` ->
  quotes bridge `:8020` (not the engine).
- `/strategy-ledger` — `strategy_ledger_router` (ledger, gates).
- `/atr-trail` — `backtest_router` (`/backtest/atr-trail/trades`).
- `/hidden-pivots` — `hidden_pivots_router` (`/hidden-pivots/scan`).
- `/options` — `options_router` (module/status, scan, pnl).
- `/crypto` — `crypto_router` (status, freqtrade, positions, pnl).
- `/watchlist` — `watchlist_router`, `portfolio`, `paper`, `analytics`, `settings`, `notifications`.
- `/analysis` — `pipeline` (run), `jarvis` (analyze), `analysis` (bars/technical),
  `backtest`, `watchlist`.

### Intelligence / ops / settings

- `/kairos` — `kairos_router` (status / watchers / dream / tick / observations).
- `/discord` — `discord_router` (stats / intelligence / signals / briefing / ib-reports / commentary).
- `/learning` — `learning_router` (patterns / classify / suggestions / memory).
- `/settings` — `safety_router` (status / config / kill-switch / circuit-breakers),
  `settings` (risk), `notifications`, `health`, `alerts`.
- `/config` — `config_router` (overview, health-check).
- `/polymarket` — `polymarket_router` (status / markets / scan / pnl).
- `/trust-pane` — `health`, `brokers`, `attribution`, `trades`, `analytics`,
  `reports` (edge-ledger), plus external AMO via `/api/amo`.
- `/master`, `/master/trading`, `/master/finances` — external Master API :8030 (no engine calls).

## Reverse index — busiest routers

- `portfolio_router` (`/portfolio`) — by far the most-used; feeds `/`, `/performance`,
  `/stats`, `/scorecard`, `/validation`, `/paper`, `/journal`, `/trades`, `/parallel-paper`,
  `/command-center`, `/health`, `/watchlist`.
- `analytics_router` (`/analytics`) — `/stats`, `/performance`, `/validation`,
  `/trust-pane`, `/jarvis`, trade review.
- `safety_router` (`/safety`) — `/`, `/paper`, `/settings`, `/command-center`.
- `health_router` — `/`, `/today`, `/health`, `/command-center`, `/trust-pane`, `/settings`.
- `pipeline_router` + `approval_router` — `/`, `/analysis`, `/command-center`,
  `/trades/pending-approvals`, `/watchlist`.

## Notable findings

- Three pages bypass the engine entirely: `/master/*` -> Master API :8030,
  `/strategy-c-command` -> quotes bridge :8020, and `/trust-pane` (partly) + home
  `HonestPnlCard` -> AMO / Master. Confirm these are intentional separate surfaces.
- Likely UI-less routers (no dashboard page references found): `messaging_router`,
  `whatsapp_router`, `openclaw_router`, `webhook_router`, `tradingview_router`,
  `profiling_router`, `observability_router`, `cache_router`, `admin_router`.
  These are mostly backend / integration endpoints, expected to be UI-less.
- `/data-integrity` and `/regime` are the thinnest pages (single endpoint each);
  `/regime` silently falls back to sample data on error, which can mask an outage.
- Heavy fan-out pages (`/`, `/performance`, `/command-center`) issue 20-48 endpoint
  calls each — the main performance pressure points on the live dashboard.

## Engine router prefix reference

Effective prefix = `engine/main.py` include prefix + the router's internal prefix.

- admin_router -> `/admin`
- alerts_router -> (none) -> `/alerts/*`
- analysis_router -> (none) -> `/analyze/*`, `/llm/*`, `/sentiment/*`
- analytics_router -> `/analytics`
- approval_queue_router -> `/approvals`
- approval_router -> `/pipeline` (pending-approvals)
- attribution_router -> `/attribution`
- backtest_router -> (none) -> `/backtest/*`, `/paper/*`
- brokers_router -> `/brokers`
- cache_router -> `/cache`
- config_router -> `/config`
- crypto_router -> `/crypto`
- decisions_router -> (none) -> `/decisions/*`
- discord_router -> `/discord`
- discovery_router -> `/discovery`
- events_router -> `/events`
- execution_status_router -> `/execution`
- experiments_router -> `/experiments`
- flags_router -> `/flags`
- forward_test_router -> `/forward-test`
- health_router -> (none) -> `/health`, `/system/*`, `/ib/*`
- hidden_pivots_router -> `/hidden-pivots`
- ib_scanner_router -> `/ib-scanner`
- institutional_router -> `/institutional`
- instruments_router -> `/instruments`
- jarvis_router -> `/jarvis`
- journal_review_router -> `/journal/review`
- journal_router -> `/journal`
- kairos_router -> `/kairos`
- learning_router -> `/learning`
- macro_router -> (none) -> `/macro/*`
- market_router -> (none) -> `/market/*`
- messaging_router -> `/messaging`
- notifications_router -> (none) -> `/notifications/*`
- observability_router -> `/obs`
- openclaw_router -> `/openclaw`
- options_backtest_router -> `/backtest/options`
- options_router -> `/options`
- orders_router -> (none) -> `/orders/*`
- paper_validation_router -> `/paper/validation`
- phase3_readiness_router -> (none) -> `/system/phase3-readiness`, `/system/mes-sprint-gate`
- pipeline_board_router -> `/pipeline` (board)
- pipeline_router -> `/pipeline`
- pipeline_ws_router -> (none) -> `/ws/pipeline`
- polymarket_router -> `/polymarket`
- portfolio_router -> `/portfolio`
- prices_router -> (none) -> `/prices/*`
- proactive_validation_router -> `/validate`
- profiling_router -> `/pipeline/profiling`
- readiness_router -> `/readiness`
- regime_router -> `/regime`
- reports_router -> `/reports`
- safety_router -> `/safety`
- scanner_router -> `/scanner`
- scheduler_router -> `/scheduler`
- schwab_router -> `/schwab`
- sentiment_router -> (none) -> `/sentiment/*`
- settings_router -> (none) -> `/settings/*`, `/strategy/params`, `/position-sizing/*`
- strategies_router -> `/strategies`
- strategy_c_router -> `/v1/strategy_c`
- strategy_lab_router -> `/strategy-lab`
- strategy_ledger_router -> `/strategy`
- super_engine_router -> `/super-engine`
- thinkscript_router -> (none) -> `/thinkscript/*`
- trades_router -> `/trades`
- tradingview_router -> `/tv`
- validation_analytics_router -> `/analytics` (significance, sensitivity, monte-carlo)
- validation_router -> `/validation`
- watchlist_router -> (none) -> `/watchlist/*`
- webhook_router -> (none) -> `/webhook/*`, `/signals/stats`
- websocket_router -> (none) -> `/ws/*`
- wfe_router -> `/wfe`
- whatsapp_router -> `/webhook/whatsapp`
