# API endpoint inventory (architecture)

**Purpose:** Orient engineers to where HTTP routes live. This file is **not** a substitute for the live OpenAPI schema.

## Canonical reference

With the engine running on port **8010**, use:

- **Swagger UI:** `http://localhost:8010/docs`
- **OpenAPI JSON:** `http://localhost:8010/openapi.json`

Regenerate or diff against production by fetching `openapi.json` after deploy.

## How routes are assembled

1. **`engine/main.py`** calls `app.include_router(...)` for modular routers (below).
2. **Additional handlers** are registered with `@app.get` / `@app.post` / … on the same `app`.
3. **Starlette** resolves the **first** route that matches method + path. If both a router and `main.py` register the same path and method, **whichever was registered first** wins. In the current file order, **included routers come first**, then WebSockets, then most `@app` routes—so router handlers typically take precedence over duplicate `@app` definitions when paths collide.

Always confirm behavior with `/openapi.json` or a quick `TestClient` call when in doubt.

## Routers mounted from `main.py`

| Order (approx.) | Router module | Prefix / notes |
|-----------------|---------------|----------------|
| 1 | `routers.health_router` | `GET /health`, `GET /health/full`, `GET /system/preflight`, `GET /system/backup-status` |
| 2 | `routers.phase3_readiness_router` | `GET /system/phase3-readiness` |
| 3 | `journal_router` | `/journal` |
| 4 | `flags_router` | `/flags` |
| 5 | `portfolio_router` | `/portfolio` |
| 6 | `market_router` | *(see module — paths like `/market/...`)* |
| 7 | `analytics_router` | `/analytics` |
| 8 | `safety_router` | `/safety` |
| 9 | `strategies_router` | `/strategies` |
| 10 | `validation_router` | `/validation` |
| 11 | `webhook_router` | *(see module)* |
| 12 | `discord_router` | `/discord` |
| 13 | `learning_router` | `/learning` |
| 14 | `kairos_router` | `/kairos` |
| 15 | `profiling_router` | `/pipeline/profiling` |
| 16 | `schwab_router` | `/schwab` |
| 17 | `instruments_router` | *(see module)* |
| 18 | `options_router` | *(see module)* |
| 19 | `v1_router` | `/v1` *(placeholder for future versioning)* |

WebSockets registered on `app` (not in table): `/ws/prices`, `/ws/events`.

## Legacy / monolith handlers still on `app` (`main.py`)

The following paths are registered directly on `FastAPI` in `main.py` (grep: `@app.get`, `@app.post`, etc.). Many overlap conceptually with router modules; treat OpenAPI as truth for which handler is active.

- **Safety:** kill switch, status, circuit breakers, config, position sizing, loss tracker, reset PnL
- **Settings / strategy:** `/settings/risk`, `/strategy/params`
- **Analysis / sentiment / portfolio / paper:** technical analysis, bars, LLM stats, Reddit/news sentiment, portfolio CRUD-style reads, paper endpoints, history, stats
- **Pipeline / analytics / watchlist:** pipeline run & status, analytics performance & trades breakdowns, watchlist CRUD, watchlist scan
- **Decisions / prices / market:** recent decisions, log decision, snapshot prices, earnings
- **Scheduler / notifications / thinkscript / macro**
- **Backtest / paper MGC / Monte Carlo**
- **WebSocket:** `WS /ws/events`, `GET /ws/status`
- **Reports / alerts / import**

For a **curated dashboard- and test-focused** table (with “tested?” columns), see `docs/reports/API_INVENTORY_2026-04-02.md`.

## Related docs

- `docs/architecture/ENDPOINT_ANALYSIS.md` — historical session notes; prefer this file + OpenAPI for structure.
- `ROUTE_VERIFICATION_GUIDE.md` — route verification workflow.
