# API Endpoint Inventory — JARVIS TRADER
**Generated:** 2026-04-02
**Status:** 92 endpoints across 27 routers

## Summary
- **Total Endpoints:** 92
- **Total Routers:** 27 (analysis, backtest, crypto, decisions, discord, flags, health, kairos, learning, macro, market, options, paper_validation, pipeline_board, pipeline, polymarket, portfolio, prices, reports, safety, sentiment, settings, strategies, strategy, thinkscript, validation, watchlist, webhook, websocket)
- **Dashboard Calls:** 31 unique endpoints
- **Tested (test_integration.py, test_api_contract_minimal.py, etc.):** 45+
- **Dead (untested, no dashboard calls):** ~30

## Endpoints by Domain

### Portfolio (portfolio_router.py) — 9 endpoints
| Method | Path | Dashboard? | Tested? | Status |
|--------|------|-----------|---------|--------|
| GET | `/summary` | Yes | Yes | ACTIVE |
| GET | `/health` | No | Yes | ACTIVE |
| POST | `/halt` | No | Yes | ACTIVE |
| POST | `/resume` | No | Yes | ACTIVE |
| GET | `/stats/paper-phase-summary` | No | Yes | ACTIVE |
| GET | `/paper/positions` | Yes (as `/portfolio/stats`) | Yes | ACTIVE |
| GET | `/paper/performance` | Yes (as `/portfolio/stats`) | Yes | ACTIVE |
| POST | `/paper/trade` | No | Yes | DEPRECATED — use `/orders/place` |
| GET | `/history/trades` | No | Yes | ACTIVE |

### Backtest (backtest_router.py) — 12 endpoints
| Method | Path | Dashboard? | Tested? | Status |
|--------|------|-----------|---------|--------|
| GET | `/backtest/results` | Yes | Yes | ACTIVE |
| POST | `/backtest/run` | No | Yes | ACTIVE |
| POST | `/backtest/walk-forward` | No | Yes | ACTIVE |
| POST | `/backtest/regime-analysis` | No | Yes | ACTIVE |
| GET | `/backtest/regime-status` | No | Yes | ACTIVE |
| GET | `/backtest/paper-status` | No | Yes | ACTIVE |
| GET | `/paper/mgc-signal` | Yes | Yes | ACTIVE |
| POST | `/paper/mgc-log-trade` | Yes | Yes | ACTIVE |
| GET | `/paper/runner-status` | No | No | BETA |
| POST | `/backtest/compare-tos` | No | No | UNTESTED |
| GET | `/backtest/comparison-results` | No | No | UNTESTED |
| POST | `/backtest/validate-stc-math` | No | Yes | ACTIVE |

### Analysis (analysis_router.py) — 5 endpoints
| Method | Path | Dashboard? | Tested? | Status |
|--------|------|-----------|---------|--------|
| POST | `/analyze/technical` | No | Yes | ACTIVE |
| GET | `/analyze/bars/{symbol}` | No | Yes | ACTIVE |
| GET | `/llm/stats` | No | Yes | ACTIVE |
| GET | `/sentiment/reddit` | No | Yes | ACTIVE |
| GET | `/analytics/performance/rolling` | Yes | Yes | ACTIVE |

### Safety (safety_router.py) — 8 endpoints
| Method | Path | Dashboard? | Tested? | Status |
|--------|------|-----------|---------|--------|
| GET | `/safety/loss-tracker/status` | No | Yes | ACTIVE |
| GET | `/safety/position-sizing/calculate` | No | Yes | ACTIVE |
| GET | `/safety/status` | Yes | Yes | ACTIVE |
| GET | `/safety/circuit-breakers` | Yes | Yes | ACTIVE |
| POST | `/safety/kill-switch/activate` | No | No | UNTESTED |
| POST | `/safety/kill-switch/deactivate` | Yes | Yes | ACTIVE |
| POST | `/safety/kill-switch` | Yes | Yes | ACTIVE |
| POST | `/safety/reset-daily-pnl` | No | Yes | ACTIVE |

### Health (health_router.py) — 3 endpoints
| Method | Path | Dashboard? | Tested? | Status |
|--------|------|-----------|---------|--------|
| GET | `/health` | Yes | Yes | ACTIVE |
| GET | `/health/full` | No | Yes | ACTIVE |
| GET | `/system/preflight` | No | No | UNTESTED |

### Strategies/RL (strategies_router.py) — 11 endpoints
| Method | Path | Dashboard? | Tested? | Status |
|--------|------|-----------|---------|--------|
| POST | `/strategies/rl/train` | Yes | Yes | ACTIVE |
| POST | `/strategies/rl/stop` | No | Yes | ACTIVE |
| POST | `/strategies/rl/train-walkforward` | Yes | Yes | ACTIVE |
| GET | `/strategies/rl/status` | Yes | Yes | ACTIVE |
| GET | `/strategies/rl/models` | Yes | Yes | ACTIVE |
| GET | `/strategies/rl/results/{run_id}` | Yes | Yes | ACTIVE |
| POST | `/strategies/rl/evaluate` | Yes | No | UNTESTED |
| POST | `/strategies/rl/deploy` | Yes | No | UNTESTED |
| GET | `/strategies/rl/executor/status` | Yes | Yes | ACTIVE |
| POST | `/strategies/rl/executor/run-now` | No | No | UNTESTED |
| GET | `/strategies/rl/health` | Yes | Yes | ACTIVE |

### Learning (learning_router.py) — 5 endpoints
| Method | Path | Dashboard? | Tested? | Status |
|--------|------|-----------|---------|--------|
| GET | `/learning/patterns` | No | No | UNTESTED |
| GET | `/learning/classify` | No | No | UNTESTED |
| GET | `/learning/suggestions` | No | No | UNTESTED |
| GET | `/learning/memory` | No | No | UNTESTED |
| POST | `/learning/memory` | No | No | UNTESTED |

### Kairos (kairos_router.py) — 7 endpoints
| Method | Path | Dashboard? | Tested? | Status |
|--------|------|-----------|---------|--------|
| GET | `/kairos/status` | No | Yes | ACTIVE |
| GET | `/kairos/observations` | No | Yes | ACTIVE |
| GET | `/kairos/observations/{date_str}` | No | Yes | ACTIVE |
| GET | `/kairos/watchers` | No | Yes | ACTIVE |
| POST | `/kairos/tick` | Yes | Yes | ACTIVE |
| GET | `/kairos/dream/{date_str}` | No | No | UNTESTED |
| POST | `/kairos/dream` | No | No | UNTESTED |

### Pipeline (pipeline_router.py) — 5 endpoints
| Method | Path | Dashboard? | Tested? | Status |
|--------|------|-----------|---------|--------|
| POST | `/pipeline/notifications/telegram/test` | No | No | UNTESTED |
| GET | `/pipeline/scheduler/status` | No | No | UNTESTED |
| POST | `/pipeline/scheduler/manual-scan` | No | No | UNTESTED |
| POST | `/pipeline/notifications/whatsapp/test` | No | No | UNTESTED |
| POST | `/pipeline/run` | Yes | Yes | ACTIVE |

### Options (options_router.py) — 6 endpoints
| Method | Path | Dashboard? | Tested? | Status |
|--------|------|-----------|---------|--------|
| GET | `/chain/{symbol}` | No | No | UNTESTED |
| GET | `/greeks` | No | No | UNTESTED |
| GET | `/iv-rank/{symbol}` | No | No | UNTESTED |
| POST | `/strategy/recommend` | No | No | UNTESTED |
| GET | `/positions` | No | No | UNTESTED |
| GET | `/module/status` | No | No | UNTESTED |

### Paper Validation (paper_validation_router.py) — 4 endpoints
| Method | Path | Dashboard? | Tested? | Status |
|--------|------|-----------|---------|--------|
| GET | `/paper/validation/progress` | No | Yes | ACTIVE |
| GET | `/paper/validation/trades` | No | Yes | ACTIVE |
| POST | `/paper/validation/record` | No | Yes | ACTIVE |
| GET | `/paper/validation/status` | No | Yes | ACTIVE |

### Settings (settings_router.py) — 4 endpoints
| Method | Path | Dashboard? | Tested? | Status |
|--------|------|-----------|---------|--------|
| GET | `/settings/risk` | Yes | Yes | ACTIVE |
| POST | `/settings/risk` | Yes | Yes | ACTIVE |
| GET | `/strategy/params` | No | No | UNTESTED |
| PUT | `/strategy/params` | No | No | UNTESTED |

### Watchlist (watchlist_router.py) — 4 endpoints
| Method | Path | Dashboard? | Tested? | Status |
|--------|------|-----------|---------|--------|
| GET | `/watchlist` | Yes | No | UNTESTED |
| POST | `/watchlist` | No | No | UNTESTED |
| GET | `/watchlist/scan` | No | Yes | ACTIVE |
| DELETE | `/watchlist/{symbol}` | No | No | UNTESTED |

### Discord (discord_router.py) — 5 endpoints
| Method | Path | Dashboard? | Tested? | Status |
|--------|------|-----------|---------|--------|
| GET | `/discord/signals` | No | No | UNTESTED |
| GET | `/discord/ib-reports` | No | No | UNTESTED |
| GET | `/discord/corey-alerts` | No | No | UNTESTED |
| GET | `/discord/commentary` | No | No | UNTESTED |
| GET | `/discord/stats` | No | No | UNTESTED |

### Pipeline Board (pipeline_board_router.py) — 2 endpoints
| Method | Path | Dashboard? | Tested? | Status |
|--------|------|-----------|---------|--------|
| GET | `/pipeline/board` | No | No | UNTESTED |
| POST | `/pipeline/board/reset` | No | No | UNTESTED |

### Remaining Routers (1-3 endpoints each)
- **Crypto** (4): `/crypto/status`, `/crypto/positions`, `/crypto/pnl`, `/crypto/freqtrade/status` — UNTESTED
- **Decisions** (2): `/decisions/recent`, `/decisions/log` — UNTESTED
- **Flags** (2): `/flags/`, `/flags/{name}` — UNTESTED
- **Macro** (2): `/macro/snapshot`, `/macro/series/{series_id}` — UNTESTED
- **Market** (2): `/market/earnings`, `/market/session` — UNTESTED
- **Polymarket** (4): `/polymarket/status`, `/polymarket/markets`, `/polymarket/scan`, `/polymarket/pnl` — UNTESTED
- **Prices** (1): `/prices/snapshot` — No (dashboard uses embedded routing)
- **Reports** (1): `/reports/performance/7d` — UNTESTED
- **Sentiment** (1): `/sentiment/recent` — UNTESTED
- **Thinkscript** (1): `/thinkscript/generate` — UNTESTED
- **Validation** (3): `/validation/progress`, `/validation/readiness-check`, `/validation/targets` — UNTESTED
- **Webhook** (3): `/webhook/tradingview/test`, `/webhook/tradingview`, `/webhook/dedup-stats` — UNTESTED
- **WebSocket** (1): `/ws/status` — Yes, ACTIVE

## Dashboard Coverage
**31 endpoints called from dashboard (dashboard/lib/api.ts):**
- `/health` (health check)
- `/backtest/results` (backtest history)
- `/paper/mgc-signal` (MGC paper trading signal)
- `/paper/mgc-log-trade` (log MGC trades)
- `/safety/status` (circuit breaker monitoring)
- `/safety/circuit-breakers` (circuit breaker state)
- `/safety/kill-switch` (kill switch control)
- `/safety/kill-switch/deactivate` (deactivate kill switch)
- `/settings/risk` (risk settings CRUD)
- `/strategies/rl/*` (RL model training, status, deployment)
- `/kairos/tick` (Kairos time sync)
- `/pipeline/run` (pipeline orchestration)
- `/analytics/performance/rolling` (performance metrics)
- `/ws/status` (WebSocket health)
- `/orders/place` (order routing)
- `/paper/kill-switch`, `/paper/reset-pending-signals` (paper mode management)

## Dead Endpoints (Defined but Never Called)
**~30 endpoints unused by dashboard and tests:**
- **All Discord endpoints** (5) — integration stub
- **All Polymarket endpoints** (4) — pre-alpha
- **All Crypto endpoints** (4) — no Freqtrade integration
- **All Decisions endpoints** (2) — logging only, no reads
- **All Flags endpoints** (2) — feature flag infrastructure
- **Learning endpoints** (5) — experimental modules in `_experimental/`
- **Kairos dream endpoints** (2) — future-dated observations
- **Options endpoints** (6) — pre-alpha
- **Pipeline notification endpoints** (4) — integration stubs
- **Market, Macro, Sentiment routers** (5 total) — market research only
- **Thinkscript, Validation endpoints** (4) — archived/experimental

## Deprecated Endpoints
- `/portfolio/paper/trade` (POST) — replaced by `/orders/place` via safety layer

## Recommendations
1. **Archive endpoints:** Move Polymarket, Discord, all Crypto to `_experimental/` directory
2. **Delete or test Learning module:** If not in Phase 3 roadmap, migrate to experimental
3. **Test coverage gap:** 40+ endpoints untested; add contract tests via `/test/simulate-trade`
4. **Dashboard parity:** 3 endpoints called from dashboard lack proper tests (`/strategies/rl/evaluate`, `/strategies/rl/deploy`, `/strategies/rl/executor/run-now`)
