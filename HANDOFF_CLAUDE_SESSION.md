# JARVIS TRADER — Claude Session Handoff
**Date**: 2026-04-05 (session ran 2026-04-04 → 2026-04-05)
**Branch**: master
**Engine**: Running on port 8010 (paper mode, IB disconnected)
**Dashboard**: Not verified this session
**Test Suite**: 1345 passed | 69 skipped | 5 FAILED

---

## 1. SESSION SUMMARY — WHAT WAS ACCOMPLISHED

This session executed the first half of **Sprint 25** from the approved 6-sprint engineering roadmap (Sprints 25–30). The primary goal is to harden JARVIS TRADER's engineering before defining any trading strategy. No trading plan work was started — that is explicitly deferred.

### Background: Approved Engineering Roadmap
Before this session, Matt approved a 6-sprint engineering roadmap. The core directive:
> "I dont want to start on the trade plan until everything is up and running perfectly, then we can dial in our trade plan and strategy."

This means: ALL work is engineering hardening. No trading parameters, no strategy rules, no WFE analysis until Sprint 30 gate passes. MES experiments, MCL params, WFE gates — all placeholders until Matt explicitly approves strategy work.

Full plan: `C:\Users\mattm\.claude\plans\vivid-brewing-sedgewick.md`

### Sprint 25 User Stories — Status

| Story | Title | Status | Commit |
|-------|-------|--------|--------|
| US-2501 | Rotate exposed API keys | BLOCKED (Matt must do manually) | — |
| US-2502 | Persist kill switch state to SQLite | DONE | ba5203e |
| US-2503 | Automated nightly DB backup | DONE | b0efec9 |
| US-2504 | PnL single source of truth (SQLite only) | DONE | ba5203e |
| US-2505 | Sprint 25 close-out | NOT STARTED | — |

### What Was Committed This Session (4 commits)

**Commit 366c198** — OpenClaw WhatsApp notification wiring:
- trading_hooks.py: 4 new WhatsApp hook functions (signal, trade close, drawdown, kill switch)
- safety_router.py: OpenClaw notify on API kill-switch activate
- openclaw_notifier.py: send_raw(), improved notify_target, regime change f-string fix
- market_data.py: Yahoo chart API fallback for delayed prices
- signal_scanner.py: America/Chicago timezone + Mon–Thu 4–5 PM CT maintenance break
- rl_executor.py: best-effort WhatsApp for RL BUY/SELL/CLOSE actions

**Commit f3c26ec** — Test coverage for kill-switch persistence:
- engine/init_db.py: print statement includes system_state
- engine/tests/test_safety_layer.py: TestKillSwitchPersistence class (5 new tests)

**Commit ba5203e** — US-2502 + US-2504 implementation:
- engine/database/_mixins_system_state.py: NEW get/set/delete system_state key-value mixin
- engine/database/manager.py: SystemStateMixin mixed in
- engine/database/migrations.py: migration_017 (system_state table)
- engine/main.py: passes db_manager.db_path to SafetyLayer
- engine/risk/safety_layer.py: _load_kill_switch_state() on startup, _persist_kill_switch_state()
- engine/routers/analytics_router.py: SQLite-first reads instead of ValidationTracker JSON
- engine/routers/portfolio_router.py: PF from SQLite closed_rows; daily PnL prefers DB
- engine/tests/test_system_state.py: NEW roundtrip + restart continuity tests

**Commit b0efec9** — US-2503 implementation:
- engine/backup/db_backup.py: run_nightly_backup() async wrapper, get_backup_status()
- engine/routers/health_router.py: GET /health/backup-status, POST /health/backup-now

### Additional Features Added (UNCOMMITTED — From Prior Context Windows)

22 modified tracked files represent a large body of work that was implemented across prior Claude context windows but never committed. This session ran out of context before committing them. The next session must clean this up. Key features in those uncommitted changes:

- **Futures confidence gate** in pipeline.py — downgrade BUY/SELL → HOLD if boosted confidence < per-instrument threshold
- **Brave Search integration** — news analyst can pull live web news; dormant until BRAVE_API_KEY set
- **AlertManager** (engine/risk/alert_manager.py) — push alerts at P&L thresholds via OpenClaw WhatsApp; deduplication within trading day
- **Alert thresholds** (engine/risk/alert_thresholds.py) — configurable thresholds for daily loss warnings, drawdown, consecutive losses, daily target
- **P&L snapshots** — migration_018 (pnl_snapshots table) + DB mixin for SafetyLayer intraday state persistence across restarts
- **Schwab Tier-2 wiring** — injects SchwabConnector into MarketDataManager in lifespan
- **STC threshold config fields** — STC_OVERSOLD=15.0, STC_OVERBOUGHT=83.0, STC_REQUIRED=True
- **Confidence config fields** — FUTURES_CONFIDENCE_BOOST=0.05, FUTURES_MIN_CONFIDENCE_TO_TRADE=0.55, EQUITY_MIN_CONFIDENCE_TO_TRADE=0.62
- **BRAVE_API_KEY field** added to TradingConfig
- **Scanner scans all configured futures** (not just top 2) — settings.FUTURES_WATCHLIST fully used
- **SQLite PRAGMA improvements** — cache_size=10000 pages, temp_store=MEMORY
- **/health/watchdog endpoint** — lightweight liveness ping (no auth, no heavy computation)
- **/health/apis endpoint** — checks Polygon, Finnhub, Brave, Anthropic, IBKR connectivity
- **/portfolio/pnl-snapshot endpoint** — returns today's P&L from pnl_snapshots SQLite table
- **/safety/alerts/history endpoint** — returns in-memory alert log from AlertManager
- **SchwabConnector.token_expires_in_days()** — warns when token < 2 days to expiry
- **engine/schedulers/market_scanner.py** — new scheduler module (purpose needs clarification)
- **watchdog_engine.ps1** — PowerShell watchdog auto-restarts engine if health check fails 3× in 60s
- **setup_watchdog_task.ps1** — registers watchdog as Windows Task Scheduler job

---

## 2. FILES CREATED OR MODIFIED

### COMMITTED Files (Sprint 25 — All Clean)
| File | Status | What Changed |
|------|--------|-------------|
| engine/database/_mixins_system_state.py | NEW | SystemStateMixin: get/set/delete system_state K/V |
| engine/tests/test_system_state.py | NEW | Roundtrip + kill-switch restart continuity tests |
| engine/database/migrations.py | MODIFIED | migration_017: system_state (key TEXT PK, value TEXT, updated_at TEXT) |
| engine/database/manager.py | MODIFIED | SystemStateMixin added to DatabaseManager inheritance chain |
| engine/main.py | MODIFIED | db_manager.db_path passed to SafetyLayer; EOF cleanup |
| engine/risk/safety_layer.py | MODIFIED | _resolve_db_path(), _load_kill_switch_state(), _persist_kill_switch_state() |
| engine/routers/analytics_router.py | MODIFIED | _get_all_trades() SQLite-first, not ValidationTracker JSON |
| engine/routers/portfolio_router.py | MODIFIED | PF from SQLite; get_daily_pnl prefers db_manager |
| engine/backup/db_backup.py | MODIFIED | run_nightly_backup(), get_backup_status() helpers |
| engine/routers/health_router.py | MODIFIED | GET /health/backup-status, POST /health/backup-now |
| engine/init_db.py | MODIFIED | Print includes system_state |
| engine/tests/test_safety_layer.py | MODIFIED | TestKillSwitchPersistence class (5 tests) |
| engine/data/market_data.py | MODIFIED | Yahoo chart API fallback |
| engine/hooks/trading_hooks.py | MODIFIED | whatsapp_signal, whatsapp_trade_closed, drawdown_alert; registered in register_default_hooks() |
| engine/notifications/openclaw_notifier.py | MODIFIED | send_raw(), notify_target custom message, regime change f-string fix |
| engine/routers/safety_router.py | MODIFIED | asyncio.create_task(_oc_ks) on kill switch activate |
| engine/scanner/signal_scanner.py | MODIFIED | America/Chicago timezone, Mon-Thu 4-5PM CT maintenance break |
| engine/strategies/rl_executor.py | MODIFIED | WhatsApp notify for RL BUY/SELL/CLOSE |

### UNCOMMITTED Modified Files (22 files — need commit or revert)
| File | Key Changes |
|------|------------|
| engine/agents/news_analyst.py | brave_client param; Brave Search news fetch; source-tagged headlines |
| engine/agents/pipeline.py | Futures confidence boost + min-confidence gate (87 lines added) |
| engine/agents/technical_analyst.py | Unknown — investigate (44 lines added) |
| engine/config.py | STC_OVERSOLD/OVERBOUGHT/REQUIRED; FUTURES_CONFIDENCE_BOOST=0.05; FUTURES_MIN_CONFIDENCE_TO_TRADE=0.55; EQUITY_MIN_CONFIDENCE_TO_TRADE=0.62; BRAVE_API_KEY |
| engine/data/market_data.py | Additional changes (108 lines modified) |
| engine/database/_mixins_pnl.py | upsert_pnl_snapshot() and get_pnl_snapshot() methods |
| engine/database/manager.py | PRAGMA cache_size=10000, temp_store=MEMORY |
| engine/database/migrations.py | migration_018: pnl_snapshots table |
| engine/execution/paper_trade_logger.py | Minor change (5 lines) |
| engine/execution/schwab_connector.py | token_expires_in_days() method + startup warning |
| engine/learning/data/session_memory.json | Data update |
| engine/main.py | Schwab Tier-2 wiring; Brave client init; scanner scans all futures; AlertManager init; signal module import fix |
| engine/risk/safety_layer.py | inject_alert_manager(); pnl_snapshot persistence in sync_from_broker(); major additions |
| engine/routers/health_router.py | GET /health/watchdog, GET /health/apis |
| engine/routers/pipeline_router.py | Unknown — investigate (31 lines added) |
| engine/routers/portfolio_router.py | GET /portfolio/pnl-snapshot endpoint |
| engine/routers/safety_router.py | _alert_manager global, inject_alert_manager(), /safety/alerts/history |
| engine/routers/validation_router.py | Unknown — investigate (19 lines added) |
| engine/scanner/signal_scanner.py | Additional changes beyond commit 366c198 |
| data/paper_trades.json | Data file updated |
| HANDOFF_CLAUDE_SESSION.md | This file |
| tradingview-mcp | Submodule updated |

### IMPORTANT New Untracked Files (need to commit)
| File | Purpose |
|------|---------|
| engine/data/brave_search.py | BraveSearchClient — async, rate-limited, structured results |
| engine/risk/alert_manager.py | AlertManager — threshold P&L push alerts, deduplication, history |
| engine/risk/alert_thresholds.py | ALERT_THRESHOLDS dict — -0.5%, -1%, -1.5% daily loss; 5%/10% drawdown; consecutive losses 2/3; daily target 50%/100% |
| engine/analytics/validation_metrics.py | New analytics module — purpose needs investigation |
| engine/schedulers/market_scanner.py | New scheduler — purpose needs investigation |
| watchdog_engine.ps1 | Engine auto-restart watchdog (polls /health/watchdog, restart after 3 failures) |
| setup_watchdog_task.ps1 | Windows Task Scheduler registration for watchdog |
| docs/reports/MASTER_PROJECT_AUDIT_2026-04-04.md | 10-agent comprehensive audit (B+ 87/100) |
| SCHWAB_SETUP.md | Schwab authentication guide |

### Junk Root Scripts (DO NOT COMMIT — delete these in Sprint 27)
add_events_widget.py, add_events_widget_v2.py, add_events_widget_v3.py,
add_notify_regime.py, check_openclaw_end.py, check_page.py, check_tracker_format.py,
commit_msg.txt, find_grid.py, find_methods.py, find_tracker_methods.py,
fix_imports.py, fix_line_endings.py, generate_handoff.ps1 (3 variants),
integrate_events.py, integrate_main.py, integrate_pipeline.py, integrate_pipeline_v2.py,
integrate_scanner.py, integrate_tracker.py, integrate_tracker_v2.py,
main_copy.py, modify_page.py, read_main.py, smart_handoff.ps1,
test_main_import.py, update_prd_progress.py, verify_components.py, verify_components_v2.py,
engine/patch_main.py, engine/progress.txt, engine/test_results.txt

---

## 3. CURRENT STATE

### Engine (port 8010)
```json
{
  "status": "ok",
  "version": "1.1.0",
  "live_trading": false,
  "kill_switch_active": false,
  "paper_mode": true,
  "database": "connected",
  "ibkr_connected": false,
  "schwab_connected": false,
  "uptime_seconds": ~700
}
```

**Engine IS running.** No restart needed unless you change Python files.

**IB Gateway is NOT connected.** To connect:
```
C:\Jts\ibgateway\1045\ibgateway.exe
Paper account: wolfof216 | API port: 4002 | Client ID: 10
```
This is NOT an emergency for Sprint 25/26 work, but required before Sprint 29 (30-day validation).

**Schwab is NOT connected** (SCHWAB_READY=False in .env — correct for paper phase).

**Kill switch**: inactive, state persisted to SQLite (system_state table, migration_017).

**Database**: engine/data/jarvis_trader.db (~492KB), 18 migrations applied, WAL mode.

### OpenClaw WhatsApp Gateway
Running in WSL Ubuntu as `openclaw-gateway.service`. Last confirmed healthy.
- WhatsApp phone: +16128771189
- 5 cron jobs active: morning brief (7AM CT weekdays), pre-market (8:30AM CT), EOD (4PM CT), weekly review (Fri 3:30PM CT), heartbeat (30min — silent unless critical)
- Kill switch → WhatsApp: VERIFIED working (tested with real activate/deactivate)
- Regime change alerts: ALREADY WIRED in scanner_router.py:149
- IB disconnect alerts: ALREADY WIRED in ib_monitor.py:81 (RTH only, 15min cooldown)

### Dashboard (port 3010)
NOT verified this session. Last known state: 26 routes, 0 TypeScript errors.
No changes were made to dashboard code in this session.

### Test Suite Status
```
1345 passed | 69 skipped | 5 FAILED | 980 warnings | 193s runtime
```

**5 NEW FAILURES (all caused by uncommitted changes):**

**Failures 1-4**: `test_config_validation.py` (3 tests) + `test_paper_trading_flow.py` (1 test)
- Root cause: New fields added to TradingConfig (STC_OVERSOLD, FUTURES_CONFIDENCE_BOOST, etc.) change the count or values that these tests validate
- Fix: Update test assertions to match new expected config field values/counts
- Risk level: LOW — config changes are intentional

**Failure 5**: `test_pipeline_run_human_gate.py::test_requires_human_inserts_pending_skips_paper`
- Root cause: pipeline_router.py was modified (31 lines added — unknown what) and now has `paper_mode_bypass` behavior that auto-logs trades even when `requires_human=True`
- Test expects `add_paper_trade` NOT to be called; it IS now being called once
- Risk level: MEDIUM-HIGH — this could be a real regression in the human approval gate
- Fix: Investigate what was changed in pipeline_router.py. If paper_mode_bypass is intentional, update the test. If not, revert the pipeline_router change.

**Before the uncommitted changes**, tests were: **1343 passed, 69 skipped, 0 failures**.

---

## 4. IN-PROGRESS WORK (STARTED, NOT FINISHED)

### 4.1 Uncommitted Change Set (LARGEST PRIORITY)
The 22 modified tracked files + ~8 important new untracked files represent ~2,000+ lines of changes that are functional but unverified and uncommitted. The next session's first task after engine health check is to sort through these:

1. Run `git diff HEAD -- engine/config.py` to understand all config changes
2. Run `git diff HEAD -- engine/agents/pipeline.py` to understand confidence gate
3. Run `git diff HEAD -- engine/risk/safety_layer.py` to understand AlertManager wiring
4. Run `git diff HEAD -- engine/routers/pipeline_router.py` to diagnose test failure 5
5. Check whether migration_018 (pnl_snapshots) is correctly structured

### 4.2 AlertManager Integration
Status: Partially wired.
- `engine/risk/alert_manager.py`: Fully implemented (AlertManager class, threshold checking, dedup, history)
- `engine/risk/alert_thresholds.py`: Thresholds defined
- `engine/main.py`: AlertManager init and inject added
- `engine/routers/safety_router.py`: inject_alert_manager() + /safety/alerts/history endpoint
- UNKNOWN: Whether SafetyLayer actually calls `alert_manager.check_and_alert()` in sync_from_broker() — needs verification
- UNKNOWN: Whether the /safety/alerts/history endpoint was tested

### 4.3 P&L Snapshots (migration_018)
Status: Schema added, DB mixin methods added, needs main.py wiring verification.
- migration_018 creates `pnl_snapshots (date TEXT PK, daily_pnl REAL, portfolio_equity REAL, peak_equity REAL, consecutive_losses INT, updated_at TEXT)`
- `_mixins_pnl.py` adds `upsert_pnl_snapshot()` and `get_pnl_snapshot()` methods
- UNKNOWN: Whether SafetyLayer.sync_from_broker() actually calls upsert_pnl_snapshot() yet
- UNKNOWN: Whether the pnl_snapshots migration has been applied to the live DB

### 4.4 US-2505 Sprint Close-Out
NOT started. Required steps:
1. Fix 5 failing tests
2. Commit all valid uncommitted work (8 groups — see Section 8)
3. Delete junk root scripts
4. Update prd.json marking all Sprint 25 stories passes:true
5. Write docs/reports/sprint25_summary.md
6. Run `pnpm run build` on dashboard to confirm 0 TS errors
7. Save YAML handoff to docs/session-logs/

---

## 5. BLOCKERS DISCOVERED

### BLOCKER 1: P0 — Exposed API Keys in Git History (US-2501)
**Matt must act.** These keys are exposed in git history and have NOT been rotated:
- **Anthropic API key** — currently working (engine is using it)
- **Polygon.io API key** — market data feeds
- **Twilio credentials** — WhatsApp/SMS notifications
- **Google OAuth client secret** — OAuth callback

**Steps for Matt:**
1. Go to console.anthropic.com → API keys → revoke old → create new
2. Go to polygon.io → account → API key → regenerate
3. Go to console.twilio.com → credentials → rotate
4. Go to console.cloud.google.com → OAuth → regenerate client secret
5. Update `engine/.env` with all new values
6. Restart engine: `.\restart_engine.ps1`
7. Run `bash scripts/hooks/check-secrets.sh`
8. Verify pipeline works: test a Polygon price fetch and one Anthropic LLM call

### BLOCKER 2: 5 Failing Tests
All tests were passing before uncommitted changes accumulated. Must fix before Sprint 25 close-out.
Priority: Fix failure #5 (pipeline_router human gate regression) first — it's a correctness issue, not just a test update.

### BLOCKER 3: API Key for curl Testing
`curl http://localhost:8010/safety/status` returns `{"detail": "Invalid or missing API key"}` with the default key `jarvis-dev-key-change-me`. The actual API_KEY in `engine/.env` is different. When testing with curl, source it:
```bash
API_KEY=$(grep "^API_KEY" engine/.env | cut -d= -f2 | tr -d '"')
curl -H "X-API-Key: $API_KEY" http://localhost:8010/safety/status
```

### BLOCKER 4: IB Gateway Not Connected
`ibkr_connected: false` in engine health. Not blocking Sprint 25-27, but required for Sprint 29 (30-day validation). Start IB Gateway manually when needed:
```
C:\Jts\ibgateway\1045\ibgateway.exe → Configure → API port: 4002 → paper account: wolfof216
```

### BLOCKER 5: main.py Bloat (Sprint 26 — Not Yet Urgent)
`engine/main.py` is 4,443+ lines (coding standard: 800 max). Sprint 26 will decompose it. Until then, it's a known issue. Do not add more code to main.py — add to routers instead.

---

## 6. KEY DECISIONS MADE

### Decision 1: Trading Plan Deferred Until Engineering is Solid
Matt's explicit instruction: "I dont want to start on the trade plan until everything is up and running perfectly, then we can dial in our trade plan and strategy."
- No trading strategy work until Sprint 30 Phase 3 gate passes
- All current WFE numbers, backtest params, MES experiments = unvalidated placeholders
- MCL WFE=0.82 and MNQ WFE=0.57 are APPROVED for paper trading, not for live capital decisions

### Decision 2: Kill Switch State Persists to SQLite (US-2502)
Problem: Engine restart reset kill switch to inactive even if manually triggered mid-session.
Solution: `system_state` table (migration_017, key/value). SafetyLayer reads on startup, writes on every activate/deactivate. DB failure is non-fatal — kill switch still works in-memory.
Verification: Test activates kill switch → restart engine → `/safety/status` shows `is_killed: true`. CONFIRMED.

### Decision 3: PnL Single Source of Truth = SQLite (US-2504 — B9 Bug Fix)
Problem: `analytics_router._get_all_trades()` read from `ValidationTracker` (stale JSON file), causing dashboard PnL to diverge from SQLite.
Solution: All PnL reads now go through `db_manager.get_closed_trades()` (SQLite). `portfolio_router.paper_phase_summary()` computes profit_factor from same SQLite rows. In-memory fallback only if DB unavailable.

### Decision 4: P&L Snapshot Architecture (Uncommitted)
Purpose: Intraday kill-switch state survives engine restart. Currently the -2% daily loss check starts from zero on each restart, which means a -1.9% loss session that restarts misses the accumulation.
Design: SafetyLayer calls `db_manager.upsert_pnl_snapshot()` on every `sync_from_broker()` call (every 60s). On startup, reads today's snapshot to restore `_daily_pnl`, `_portfolio_equity`, `_peak_equity`, `_consecutive_losses`.

### Decision 5: Futures Confidence Gate (Uncommitted)
Problem: LLM pipeline generates weak confidence for futures because no fundamentals/social analyst applies to them — only 2 of 4 Stage 1 analysts run (Technical + News).
Solution:
- `FUTURES_CONFIDENCE_BOOST = 0.05` additive (compensates for fewer inputs)
- `FUTURES_MIN_CONFIDENCE_TO_TRADE = 0.55` minimum gate (0.62 for equities)
- If technical analyst abstains (no_price_data), confidence forced to 0.0 → HOLD
These are config-driven and adjustable without code changes.

### Decision 6: AlertManager — Deduplication Within Trading Day
Design: Each alert threshold fires at most once per calendar day. `_fired_today` is a set, reset at midnight CT. This prevents WhatsApp spam if the same threshold is repeatedly crossed (e.g., P&L oscillating around -1%).

### Decision 7: Heartbeat Now Silent When Healthy
Prior behavior: OpenClaw heartbeat sent WhatsApp every 30 minutes regardless of state.
New behavior: Heartbeat fires ONLY if: engine down, kill switch active, consecutive_losses ≥ 3, IB disconnected during RTH, or daily P&L < -5%. Saves approximately 48 WhatsApp messages/day.

### Decision 8: Watchdog Architecture
`watchdog_engine.ps1` polls `GET /health/watchdog` (no auth, no DB) every 60 seconds. If it gets 3 consecutive failures, it calls `.\restart_engine.ps1`. This is a simple, effective way to handle engine crashes without requiring IB auto-reconnect code (Sprint 28 work).

---

## 7. TODO ITEMS — PLANNED BUT NOT STARTED

### Immediate (Next Session)
- [ ] Fix 5 failing tests
- [ ] Commit 22 modified files in 8 logical groups
- [ ] Delete 30+ junk root scripts
- [ ] Complete US-2505 sprint close-out

### Sprint 26 — main.py Decomposition (NEXT SPRINT)
- [ ] US-2601: Extract portfolio/trades direct routes from main.py to routers
- [ ] US-2602: Extract analytics/market direct routes from main.py to routers
- [ ] US-2603: Extract pipeline/safety/admin direct routes — `grep -c '@app\.' engine/main.py` → 0
- [ ] US-2604: Extract lifespan function + scheduler setup to `engine/lifespan_helpers.py`
  - TARGET: main.py < 800 lines
  - VERIFY: `GET /scheduler/jobs` still works after extraction
- [ ] US-2605: Sprint 26 close-out

### Sprint 27 — Dead Code + Test Fixes
- [ ] US-2701: Audit 15 unmounted routers (DEAD → `engine/routers/_archive/`, MOUNT, or KEEP)
- [ ] US-2702: Clean 37 root prototype scripts → `scripts/_archive/` or delete; zero .py files in root
- [ ] US-2703: Fix loss_tracker test failures (31 tests) — `yield` inside context manager fixture issue
- [ ] US-2704: Fix AsyncMock + auth failures (33 tests) — mock targets post-refactor
- [ ] US-2705: Sprint 27 close-out — target: 0 known test failures

### Sprint 28 — IB Reconnect + File Splits
- [ ] US-2801: IB Gateway auto-reconnect (backoff 1s→2s→4s→8s...60s, max 10 retries; kill switch if all fail; heartbeat 30s)
- [ ] US-2802: Split portfolio_router.py (1,204 → 3 files: portfolio, trades, pnl)
- [ ] US-2803: Split paper_validation_router.py (1,086 → 3 files)
- [ ] US-2804: Split analytics_router (848), backtest_router (829), strategies_router (815) — all under 800 lines
- [ ] US-2805: Sprint 28 close-out

### Sprint 29 — 30-Day Validation Start
- [ ] US-2901: Start 30-day validation period — reset counters, record start timestamp in system_state, scanner active for MCL/MNQ 60min intervals during market hours
- [ ] US-2902: Validation dashboard enhancement — days/30 progress, gate metrics (PF, Sharpe, WR, DD), green/red badges, auto-refresh 60s
- [ ] US-2903: Discord daily validation report — Day X/30, N trades, gate metrics
- [ ] US-2904: Kill switch + validation alerts — Discord/WhatsApp for: kill switch, IB disconnect >5min, no trades 24h, -1% daily warning
- [ ] US-2905: Sprint 29 close-out

### Sprint 30 — Phase 3 Gate
- [ ] US-3001: GET /phase3/readiness endpoint — all gate statuses (keys rotated, kill switch persists, IB reconnect, backup, tests passing, main.py <800, 30-day validation, safety tests green)
- [ ] US-3002: OrderRouter integration test (full pipeline → RiskManager → FundManager → OrderRouter paper flow)
- [ ] US-3003: Schwab connector smoke test (10+ unit tests: OAuth mock, order construction, error handling)
- [ ] US-3004: Learning system E2E verification (trade close → process_trade_outcome → trade_outcomes → pipeline injection)
- [ ] US-3005: Phase 3 gate status report and timeline projection

### After Sprint 30 — Trading Plan (Matt-Led)
- Define actual trading strategy with rules, risks, goals, capital allocation
- Approve/reject STC parameters (OS=15, OB=83), ATR stops (0.70x), regime filters
- Set validated position sizing for MCL and MNQ
- Design entry/exit rules and daily session policy
- CRITICAL: This work does NOT start until all Sprint 30 gates pass

---

## 8. FULL CURRENT TO-DO LIST (Priority Order)

### PRIORITY 0 (Do Before Any Code Work)
```
1. Verify engine is running: curl http://localhost:8010/health
2. Read this file completely
3. Read memory/MEMORY.md
4. Run: cd engine && .venv/Scripts/python -m pytest tests/ -v --tb=short 2>&1 | tail -20
   - Confirm still 5 failures, not more
```

### PRIORITY 1 (Fix Tests — Blocker for Sprint Close-Out)
```
5. Read engine/routers/pipeline_router.py git diff — understand paper_mode_bypass change
6. Decide: is paper_mode_bypass intentional behavior?
   - YES: update test_pipeline_run_human_gate.py assertion
   - NO: revert the pipeline_router change
7. Read engine/config.py git diff — understand all new fields
8. Update test_config_validation.py assertions to match new config fields
9. Run tests again — confirm 0 failures
```

### PRIORITY 2 (Commit Uncommitted Changes in Groups)
```
Group 1: Config + Pipeline Intelligence
  Files: engine/config.py, engine/agents/pipeline.py, engine/agents/technical_analyst.py
  Commit: "feat(engine): STC/confidence config, futures confidence gate, no_price_data abstention"

Group 2: Database Layer
  Files: engine/database/_mixins_pnl.py, engine/database/manager.py, engine/database/migrations.py
  Commit: "feat(engine): pnl_snapshots table (migration_018), PRAGMAs, upsert/get snapshot"

Group 3: SafetyLayer + AlertManager
  Files: engine/risk/safety_layer.py, engine/routers/safety_router.py
  New: engine/risk/alert_manager.py, engine/risk/alert_thresholds.py
  Commit: "feat(engine): AlertManager, P&L snapshot persistence in SafetyLayer"

Group 4: Brave Search / News
  Files: engine/agents/news_analyst.py
  New: engine/data/brave_search.py
  Commit: "feat(engine): Brave Search client, wire into NewsAnalystAgent (dormant until BRAVE_API_KEY)"

Group 5: New Endpoints
  Files: engine/routers/health_router.py, engine/routers/portfolio_router.py
  Commit: "feat(engine): /health/watchdog, /health/apis, /portfolio/pnl-snapshot endpoints"

Group 6: Schwab + Execution
  Files: engine/execution/schwab_connector.py, engine/execution/paper_trade_logger.py
  Commit: "feat(engine): SchwabConnector token expiry warning"

Group 7: Main.py Wiring
  Files: engine/main.py
  Commit: "feat(engine): Schwab Tier-2, Brave client, AlertManager, scanner full watchlist wiring"

Group 8: Infrastructure + Docs
  New: watchdog_engine.ps1, setup_watchdog_task.ps1, docs/reports/MASTER_PROJECT_AUDIT_2026-04-04.md, SCHWAB_SETUP.md
  Commit: "chore: engine watchdog script, audit report, Schwab setup guide"
```

### PRIORITY 3 (Clean Up Root Junk)
```
Delete all prototype scripts from root (see list in Section 2 "Junk Root Scripts")
git add .gitignore if needed to ignore generated files
```

### PRIORITY 4 (US-2505 Sprint Close-Out)
```
- Update engine/prd.json: all Sprint 25 stories passes:true
- Write docs/reports/sprint25_summary.md
- Run: cd dashboard && pnpm run build  (must pass 0 TS errors)
- Run: cd engine && .venv/Scripts/python -m pytest tests/ -v (must pass 0 failures)
- Save YAML handoff: docs/session-logs/handoff-2026-04-05.md
```

### PRIORITY 5 (Begin Sprint 26)
```
- Start main.py decomposition
- US-2601: Extract portfolio/trades routes to portfolio_router.py + trades_router.py
```

---

## 9. GIT STATE

### git status (captured 2026-04-05)
```
On branch master
Your branch is up to date with 'origin/master'.

Changes not staged for commit:
  modified:   HANDOFF_CLAUDE_SESSION.md
  modified:   data/paper_trades.json
  modified:   engine/agents/news_analyst.py
  modified:   engine/agents/pipeline.py
  modified:   engine/agents/technical_analyst.py
  modified:   engine/config.py
  modified:   engine/data/market_data.py
  modified:   engine/database/_mixins_pnl.py
  modified:   engine/database/manager.py
  modified:   engine/database/migrations.py
  modified:   engine/execution/paper_trade_logger.py
  modified:   engine/execution/schwab_connector.py
  modified:   engine/learning/data/session_memory.json
  modified:   engine/main.py
  modified:   engine/risk/safety_layer.py
  modified:   engine/routers/health_router.py
  modified:   engine/routers/pipeline_router.py
  modified:   engine/routers/portfolio_router.py
  modified:   engine/routers/safety_router.py
  modified:   engine/routers/validation_router.py
  modified:   engine/scanner/signal_scanner.py
  modified:   tradingview-mcp (new commits)

Untracked files (important):
  docs/reports/MASTER_PROJECT_AUDIT_2026-04-04.md
  engine/analytics/validation_metrics.py
  engine/data/brave_search.py
  engine/risk/alert_manager.py
  engine/risk/alert_thresholds.py
  engine/schedulers/market_scanner.py
  watchdog_engine.ps1
  setup_watchdog_task.ps1
  SCHWAB_SETUP.md
  [+ 30+ junk scripts at root]
```

### git log --oneline -20
```
366c198 feat(engine): OpenClaw alerts, yfinance price fallback, Globex hours
f3c26ec test: kill-switch SQLite persistence coverage; init_db lists system_state
ba5203e feat(engine): system_state table, kill-switch persistence, SQLite-first analytics
b0efec9 feat(engine): US-2503 — automated nightly DB backup with 30-day retention
5ef7e30 feat(engine): GET /discord/intelligence for dashboard widget
db6f75e feat: Discord IB fields in signals layer2, wire intelligence widget, gitignore DB WAL
51ec60b fix: restore tradingview-mcp submodule pin (submodule push not permitted)
812da09 chore: sync workspace — Discord widget, reports, session memory, submodule
a178e41 fix(engine): DailyPnLMixin.get_daily_pnl accepts days lookback
e4ad9eb fix(dashboard): route all daily PnL widgets through fetchDailyPnLHistory
40c960a "Update-prd-US-2501-passes-true"
0e464a8 US-2501-nightly-discord
125106c fix: add missing GET /portfolio/stats/weekly endpoint — 4 tests now pass
6cf6999 feat: Sprint 24 — confidence scoring, events ring buffer, IB health tests
7a22b33 feat: Sprint 23 wiring — IB health monitor, validation checkpoint, learning router
0c2cd54 fix(dashboard): use fetchDailyPnLHistory in trend and PnL chart widgets
5de7e0a revert: drop artifacts accidentally committed with ruff format
51a7ad1 style(engine): ruff format files flagged by CI format-check
bcb98d8 fix(engine): ruff B905/B904/I001 for CI lint
f0d7104 feat: US-2302 unrealized PnL tests + Sprint 23 docs close-out
```

### git diff --stat HEAD (uncommitted)
```
 HANDOFF_CLAUDE_SESSION.md                | 988 +++++++++++++++++++++++++------
 data/paper_trades.json                   | 272 ++++++++-
 engine/agents/news_analyst.py            |  30 +-
 engine/agents/pipeline.py               |  87 ++-
 engine/agents/technical_analyst.py      |  44 ++
 engine/config.py                         |  31 +
 engine/data/market_data.py              | 108 ++--
 engine/database/_mixins_pnl.py          |  49 ++
 engine/database/manager.py              |   2 +
 engine/database/migrations.py          |  26 +
 engine/execution/paper_trade_logger.py  |   5 +-
 engine/execution/schwab_connector.py    |  52 ++
 engine/learning/data/session_memory.json|   2 +-
 engine/main.py                           |  89 ++-
 engine/risk/safety_layer.py             | 212 +++++--
 engine/routers/health_router.py         | 114 ++++
 engine/routers/pipeline_router.py       |  31 +
 engine/routers/portfolio_router.py      |  62 ++
 engine/routers/safety_router.py         |  44 ++
 engine/routers/validation_router.py     |  19 +
 engine/scanner/signal_scanner.py        |  80 +++
 tradingview-mcp                          |   2 +-
 22 files changed, 2063 insertions(+), 286 deletions(-)
```

---

## 10. ARCHITECTURE REFERENCE

### Project Layout
```
C:\Users\mattm\ThinkorSwim\jarvis-trader\
  engine/            FastAPI, Python 3.12, port 8010
    main.py          4,443 lines — lifespan, 59 direct routes (NEEDS SPLITTING Sprint 26)
    config.py        TradingConfig — ALL risk parameters (Tier 3 to change)
    risk/
      safety_layer.py  Kill switch, hard limits (Tier 3 — never LLM-driven)
      alert_manager.py [NEW UNTRACKED] threshold P&L push alerts
    agents/
      pipeline.py    5-stage LLM orchestrator
    backup/
      db_backup.py   SQLite backup (30-day retention, nightly 01:00 ET)
    data/
      jarvis_trader.db  Primary SQLite DB (NOT engine/jarvis_trader.db — that's ghost)
    notifications/
      openclaw_notifier.py  WhatsApp alerts via OpenClaw
    hooks/
      trading_hooks.py  Event hooks for signals, trades, kill switch, drawdown
  dashboard/         Next.js 15, TypeScript, port 3010
  docs/
    reports/         Audit reports, sprint summaries
    strategy/        TRADING_RULES.md, EQUATIONS.md
    session-logs/    YAML handoffs
```

### Safety Invariants (ABSOLUTE — NEVER CHANGE)
```
LIVE_TRADING_ENABLED = False          # paper mode until Phase 3
REQUIRE_HUMAN_APPROVAL = True         # every trade requires review
Kill switch: -2% daily loss OR -10% drawdown (hardcoded in SafetyLayer)
SafetyLayer = pure hardcoded Python   # NEVER route safety decisions through LLM
IB port 4001 (live) = PERMANENTLY BLOCKED
engine/risk/safety_layer.py = Tier 3 file (explicit confirmation required to modify)
engine/config.py = Tier 3 file
engine/backtest/signals.py = Tier 3 file
```

### Validated Instruments (Current Paper Trading Status)
| Symbol | TF  | WFE  | Status |
|--------|-----|------|--------|
| MCL    | 1h  | 0.82 | APPROVED — paper active |
| MNQ    | 1h  | 0.57 | APPROVED — paper active |
| MGC    | 1d  | 0.14 | HALTED — overfit/small-sample |
| MES    | 1h  | 0.09 | DO NOT TRADE — overfit |
| SPY    | 1h  | 0.00 | REJECTED — WFE run 2026-04-02 |

### Key Commands
```bash
# Start/restart engine
cd engine && .venv/Scripts/python -m uvicorn main:app --port 8010
.\restart_engine.ps1              # Kill port 8010, restart
.\restart_engine_admin.ps1        # If taskkill fails (UAC required)

# Health check (no auth)
curl http://localhost:8010/health

# Tests
cd engine && .venv/Scripts/python -m pytest tests/ -v
cd engine && .venv/Scripts/python -m pytest tests/ -v --tb=short 2>&1 | tail -20

# Dashboard
cd dashboard && pnpm run build    # Must produce 0 TS errors
cd dashboard && pnpm dev          # Dev server on port 3010

# Secrets check
bash scripts/hooks/check-secrets.sh

# OpenClaw (WSL)
wsl -d Ubuntu -e bash -c "openclaw health 2>&1 | tail -3"
wsl -d Ubuntu -e bash -c "systemctl restart openclaw-gateway.service"
```

### Database Migrations Applied
```
001: Initial schema (paper_trades, positions, decisions, daily_pnl, settings, schema_version)
002-006: Various extensions
007: capital_allocation table
008: pending_trade_approvals table
009: pipeline_llm_costs table
010: paper_trades signal provenance columns
011: risk_pct_used column
012: trade_journal attribution columns
013: learning_events and trading_patterns tables
014: timeframe columns
015: pipeline confidence columns
016: wfe_snapshots + divergence_flag
017: system_state table (kill switch persistence) ← Sprint 25
018: pnl_snapshots table (intraday P&L persistence) ← UNCOMMITTED
```

### Sprint Dependency Chain
```
Sprint 25 (Security+Kill Switch) → Sprint 26 (main.py) → Sprint 27 (Cleanup+Tests)
  → Sprint 28 (IB+Splits) → Sprint 29 (30-Day Validation) → Sprint 30 (Phase 3 Gate)
  → Trading Plan (after Phase 3 gates pass)
```

Key blockers between sprints:
- US-2502 (system_state) blocks US-2901 (validation start) and US-2904 (alerts)
- US-2604 (main.py <800) blocks US-2701 (router audit) and US-2704 (test fixes)
- US-2801 (IB reconnect) blocks US-2901 (validation) and US-3002 (OrderRouter test)

---

*Generated: 2026-04-05 by Claude Sonnet 4.6*
*Previous handoff: HANDOFF_CLAUDE_SESSION.md (overwritten)*
*Session log template: docs/session-logs/HANDOFF_TEMPLATE.md*
