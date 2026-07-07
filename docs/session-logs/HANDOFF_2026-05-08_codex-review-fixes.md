---
session: 2026-05-08 Codex PR review fix wave
branch: feat/tradingview-mcp-gamma-kraken
commits: fa7bcf7..05ffa33 (14 commits)
---

## Current state

- Branch is clean (git status empty). All commits pushed locally, not pushed to remote.
- 99 tests passing across key suites (safety_layer, signals, approvals, bracket chain, stop-loss invariants).
- Pre-existing IOCP timeout failures in `test_close_stale_positions.py` are unrelated to this session's changes.
- Engine is not running (no restart done this session — no config.py changes required restart).

## Key decisions made

| Decision | Reason |
|----------|--------|
| Per-symbol bracket sidecar `{"MES": {"count": N}}` instead of global `{"count": N}` | MES sprint gate must not be satisfied by MGC or MCL bracket fills; gate now reads `sc.get("MES", {}).get("count", 0)` |
| TP child gated on `LIVE_TRADING_ENABLED` (always False) | Paper connector fills LMT orders immediately → corrupted P&L; TP placement is only meaningful on live connector |
| STP failure triggers entry cancel + return `approved: False` | Orphaned entry with no stop is a hard safety violation; fail-safe over silent degradation |
| `submit_paper_order()` now receives `stop_price=stop_price` | Without it, `_check_trade_loss_gate` used None → bypassed MAX_TRADE_LOSS_USD entirely |
| StarkTPO directive conditional on `technical.get("stark_signal")` presence | TPO block previously hardcoded to "HOLD" because the key was never populated; gating prevents stale default from contaminating LLM prompt |
| `from risk.safety_layer import KillSwitchReason` (not `engine.risk...`) | Engine runs with `engine/` as cwd; `engine` is not an importable package |
| `MarketDataManager.get_bars()` (not `get_price_bars()`) | `get_price_bars` doesn't exist; sdk_pipeline was silently falling back every cycle |
| Futures orders route through `_safety_layer.submit_paper_order()` | Manual dashboard orders bypassed all risk checks entirely |
| `@model_validator(mode="after")` for LIMIT price validation | Pydantic v2 `@field_validator` not invoked when field is None and has a default |
| MGC added to `TREND_INSTRUMENTS` | MGC paper config has `strategy: "sma_trend"` but wasn't in the routing set → signal_error every cycle |

## In-progress work

None — all P1 and P2 items from the Codex review are addressed and committed.

## Blockers discovered

- 3 test failures noted in earlier agent run: "STP loss-limit threshold mismatch" and "activate_kill_switch() unexpected kwarg" — these were reported by an agent but did not reproduce when the main session ran the same test files. May be pre-existing flakiness or environment-specific. Not reproduced, not fixed, not verified.
- `test_close_stale_positions.py` has pre-existing IOCP timeout failures on Windows. Unrelated to this session.

## Files created or modified

### New files
- `engine/database/_mixins_trades.py` — `BrokerMetadataMixin.set_broker_metadata()` for persisting bracket order IDs after approval
- `engine/backtest/update_mgc_wfo_journal.py` — WFO journal updater for MGC
- `engine/data/mgc_wfo_journal.csv` — MGC WFO journal data
- `dashboard/components/EngineHealthWidget.tsx` — live /health subsystem indicator widget

### Modified (by area)
**Risk / safety:** `engine/risk/safety_layer.py` — bracket sidecar per-symbol, STP fail-safe, TP paper gate, stop_price passthrough, signed-qty fix  
**Orders:** `engine/routers/orders_router.py` — futures route through SafetyLayer, Schwab SELL fix, Pydantic v2 model_validator  
**Approval:** `engine/approval/service.py` — trade_decision key lookup, bracket order ID persistence, drain-loop for expired approvals  
**Agents:** `engine/agents/technical_analyst.py`, `engine/agents/trader.py` — StarkTPO wired + directive gated  
**Pipeline:** `engine/agents/pipeline.py` — `self._db` fix, regime prefetch try/except  
**SDK pipeline:** `engine/agents/sdk_pipeline.py` — `get_bars()` replaces nonexistent `get_price_bars()`  
**Signals:** `engine/backtest/signals.py` — MGC added to TREND_INSTRUMENTS  
**Messaging:** `engine/routers/messaging_router.py` — import path fix for KillSwitchReason  
**Learning:** `engine/learning/model_drawer.py` — lazy xgboost/joblib import; `engine/learning/promotion.py` — try/except for missing trade_outcomes table  
**Execution:** `engine/execution/ib_gateway_connector.py` — `get_open_orders()` method; `engine/execution/position_reconciler.py` — STP type normalization  
**Health/scripts:** `engine/scripts/health_watchdog.py`, `engine/scripts/daily_morning_briefing.py`, `engine/api/operations_dashboard.py` — IBKR key name updates  
**Data extraction:** `engine/notifications/morning_brief.py`, `engine/schedulers/eod_scheduler.py` — `last_price` key  
**Analytics:** `engine/analytics/paper_trade_pairing.py` — residual quantity tracking; `engine/scripts/daily_post_trade_report.py` — 14-day bar window, row["timestamp"]  
**Validation:** `engine/validation/shadow_mode.py` — `_parse_strategy_params()`, zero-metrics shape, DB injection  
**Dashboard:** `dashboard/components/Pm2StabilityWidget.tsx` — STP from notes JSON; `dashboard/lib/api.ts` — notes field  
**Routers:** `engine/routers/discord_router.py` — lazy import; `engine/routers/safety_router.py` — LimitOrder smoke test  
**Gate:** `engine/routers/phase3_readiness_router.py` — per-symbol bracket count read  
**Tests:** `engine/tests/test_bracket_sidecar_chain.py` — updated for per-symbol sidecar format

## TODO items

- Push branch to remote when ready (requires Amo authorization)
- Consider investigating the 3 unconfirmed test failures (STP threshold mismatch, kill_switch kwarg) — may be stale test artifacts
- IPv4/IPv6 dual-stack for health_router CDP socket check (P2 skip — edge case, low priority)
- Polymarket router module registration (skipped — feature not active per CLAUDE.md)

## Git state

```
Branch: feat/tradingview-mcp-gamma-kraken
Working tree: clean (0 modified, 0 untracked relevant files)

Recent commits:
05ffa33 test(bracket): update sidecar tests for per-symbol JSON format
ff8d57e refactor(backtest): consolidate tick_value lookup into contract_specs
110b37f chore(gitignore): exempt WFO journals from data/*.csv blanket ignore
b21c5f0 chore(style): fix ruff import-order and whitespace (3 files)
0ee385d fix(dashboard): read broker STP ID from correct metadata field in stability widget
3410829 fix(pipeline,discord): wrap regime prefetch in best-effort; defer discord_correlation import
28441e1 fix(approval): persist bracket order IDs to portfolio tracker after execution
082bb40 fix(health): update IBKR key names to match current /health response shape
3f22d38 [safety-review] fix(risk): track bracket count per symbol; gates now require MES-specific brackets
58638c0 fix(execution): reconciler get_open_orders fallback; normalize STP order_type case
77639d4 fix(data): read last_price key from MarketDataManager.get_current_price()
0512653 feat(agents): wire StarkTPO into TechnicalAnalystAgent; gate trader directive on key presence
7253b65 [safety-review] fix(risk): enforce stop loss gate for bracket entries; fail-safe on missing STP
090120b feat(orders): route futures through SafetyLayer; fix Schwab SELL bug
```

Total: 14 commits this session (+ ruff style cleanup commits). 68 files changed, ~1260 insertions.
```

## Suggested next action

Run `.\restart_engine.ps1` and verify `/health` returns `status=ok` with all subsystems healthy — the safety_layer, orders_router, and pipeline changes are significant enough that a live smoke test is warranted before pushing to remote.
