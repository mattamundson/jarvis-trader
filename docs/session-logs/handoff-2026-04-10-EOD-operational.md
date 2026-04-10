---
session_date: 2026-04-10
session_time: "13:00-15:00 CDT"
session_type: operational_hardening_eod
status: partial_success
commit: be6927d
next_session_priority: P0
---

# JARVIS TRADER — EOD Operational Hardening Session
**Date:** 2026-04-10 · **Duration:** 13:00–15:00 CDT · **Commit:** `be6927d`

## Goal
Matt requested: comprehensive audit of jarvis-trader workspace + everything operational for real paper trading by end of day. Four acceptance criteria:
1. Clean pipeline run on real data
2. First clean paper trade auto-executed
3. Full RTH session observed green
4. `docs/runbooks/daily_ops.md` all green

## What Actually Happened

Started as an audit. Discovered 4 contaminated paper trades had landed hourly against stale CSV cache prices (MES 3-contract shorts at $70.57 when real MES is ~$6388). The bleeding was active — a 4th contaminated trade landed at 18:26 UTC while I was diagnosing. Pivoted to operational hardening + emergency kill switch first, audit second.

## Stage Completion

| Stage | Description | Status | Evidence |
|---|---|---|---|
| 0 | Emergency kill switch — disable scanner | ✅ DONE | `/scanner/status` returns `active=false`; SignalScanner paused via `/scanner/pause` at 14:22 CDT; no new trades since #110 (18:26 UTC). Also added `WATCHLIST_SCAN_ENABLED=false` gate in config.py + main.py so kill switch survives restart. |
| 1 | Data layer recovery | ⚠️ PARTIAL | Polygon key already set (not 'test') — confirmed real key in `.env:162`. Polygon reachable (200 OK on smoke test). But engine's `/prices/snapshot` returns all sources as `csv_cache`, not live Polygon. IBKR Gateway still offline. Real data flowing NOT verified. Needs dedicated session. |
| 2 | DB split-brain fix | ✅ DONE | Root cause found: 4 discord modules walked `os.path.dirname()×3` from `engine/discord/` → workspace root → `data/jarvis_trader.db` instead of `engine/data/jarvis_trader.db`. Fixed `signal_context.py`, `ib_levels.py`, `commentary_processor.py`, `sentiment_provider.py` to anchor at `engine/` root (2-levels-up). Also added `@field_validator` in `config.py` that resolves `SQLITE_DB_PATH` to an absolute path anchored at engine/ regardless of caller cwd. Stray 104 MB workspace-root DB preserved as `data/jarvis_trader.db.orphaned-20260410-stage2`. Ghost 0-byte `engine/jarvis_trader.db` deleted. |
| 3 | Close contaminated positions | ✅ DONE | Trades #54 (MCL $84.20), #108, #109, #110 (all MES 3-contract $70.57) closed to $0 P&L via direct DB UPDATE with contamination notes. `paper_trades` table now has 0 open positions. |
| 4 | Safety cap + scanner guards | ✅ DONE | **Hard cap**: `MAX_CONTRACTS_PER_INSTRUMENT` now clamps ≥2 env overrides down to 2 via `@field_validator` in `config.py`. `.env` changed from 3 → 2. **Scanner guards**: Two inline guards in `main.py _analyze_and_alert()` — (1) already-open-position query on `paper_trades`, (2) price sanity check against hard-coded plausible range table. Tests: **7/7** hardcap + **13/13** scanner_guards all green. |
| 5 | Paper runner KeyError fix | ✅ DONE | Extracted `_adapt_trade_row_to_position()` in `engine/backtest/paper_runner.py` that translates SQLite column names (`stop_loss`, `entry_time`, `quantity`) to the legacy dict shape `manage_open_position()` expects (`stop`, `entry_date`, `contracts`, `targets`, `t{1,2,3}_hit` from `strategy_params` JSON). Tests: **10/10** adapter tests green. |
| 6 | Debate interface fix | ⚠️ INTERMITTENT | **Not modified.** Fresh instance probe of `BullResearcherAgent()._call_llm` shows bound method present. Live engine logs show 19 "no callable LLM interface" errors in current session **mixed with** working real scores (e.g. AAPL decision #2186 showed `"BULL_WINS (10 vs 7)"`). The bug is intermittent, not universal. Needs dedicated debugging — possibly ICWeightedEnsemble wrapping agents differently, stale Python module cache, or a race during lazy initialization. |
| 7 | Purge stale approvals | ✅ DONE | 36 → 0 pending approvals. 33 auto-rejected (>4h old with "market conditions changed" reason). 3 approvals linked to contaminated trades #108/#109/#110 also explicitly rejected with contamination note. |
| 8 | Four-criterion verification | ⚠️ PARTIAL | See "Acceptance Bar Status" below. |
| 9 | Memory + handoff + commit + push | 🔄 IN PROGRESS | This file. Commit `be6927d` already landed. Push pending. |

## Acceptance Bar Status (Matt's 4 Criteria)

| # | Criterion | Status | Notes |
|---|---|---|---|
| C1 | Clean pipeline run on real data | ⚠️ PARTIAL | Pipeline runs (manually fired via `POST /pipeline/run` MCL — decision #2187 logged as HOLD). Data source is still `csv_cache`, not live Polygon. Debate works intermittently. |
| C2 | First clean auto-trade | ⛔ DELIBERATELY BLOCKED | Scanner is paused. No auto-execution will happen until scanner is re-enabled. Decision was to keep blocked — the contamination guards need a real run-through before trusting auto-exec, and debate interface is still intermittent. |
| C3 | RTH session green | ✅ PARTIAL | Since Stage 0 (scanner pause ~14:22 CDT), zero new trades, zero safety violations, zero crashes, engine healthy. But "observed through 15:00 CT close" requires continuous watch — this session ends before close. |
| C4 | `daily_ops.md` all green | ❌ NOT VERIFIED | Not run. |

**Honest grade: 1 of 4 cleanly green (C3 proxy), 3 of 4 incomplete or blocked.** The "operational by EOD" goal was over-ambitious given the discovery of the contamination. The session's real value is the hardening + the commit `be6927d` that makes tomorrow's continuation safe.

## Files Changed (commit `be6927d`)

| File | Change | Purpose |
|---|---|---|
| `engine/config.py` | +44/-3 | Added `WATCHLIST_SCAN_ENABLED`, `@field_validator` for `SQLITE_DB_PATH` (absolute path), `@field_validator` for `MAX_CONTRACTS_PER_INSTRUMENT` (hard cap 2) |
| `engine/main.py` | +93/-10 | Gated `scheduler.add_job(watchlist_scan)` behind new flag; added scanner guards (already-open + price sanity) in `_analyze_and_alert()` |
| `engine/backtest/paper_runner.py` | +62/-10 | Extracted `_adapt_trade_row_to_position()` translator, called from `load_positions()` |
| `engine/discord/signal_context.py` | +6/-3 | Fixed DB path walk — anchor at engine/ not workspace-root |
| `engine/discord/ib_levels.py` | +5/-3 | Same fix |
| `engine/discord/commentary_processor.py` | +6/-3 | Same fix |
| `engine/discord/sentiment_provider.py` | +10/-8 | Same fix — replaced walk-parents-until-found with direct 2-level anchor |
| `engine/tests/test_safety_hardcap.py` | +89 (new) | 7 tests: hard cap clamping via instantiation + direct validator |
| `engine/tests/test_scanner_guards.py` | +184 (new) | 13 tests: both guards including regression for #108/#109/#110 |
| `engine/tests/test_paper_runner_adapter.py` | +146 (new) | 10 tests: field-name translation, JSON parsing, required key set |

## Files NOT in commit (local changes not pushed)

- `engine/.env` — gitignored. `MAX_CONTRACTS_PER_INSTRUMENT=2`, `WATCHLIST_SCAN_ENABLED=false`.
- `data/jarvis_trader.db` — WAS tracked, now deleted from working tree (renamed to `.orphaned-20260410-stage2`). Git reports as deletion — leave uncommitted for review. The orphaned file is preserved at `data/jarvis_trader.db.orphaned-20260410-stage2` for recovery.
- Various other modified/untracked files (backups, session logs, etc.) unrelated to this work — left alone.

## Runtime State (at session end)

- **Engine**: PID 21392, started 14:21:41 CDT, uptime ~40 min
- **Scheduler**: running, `watchlist_scan` job absent (kill switch active)
- **SignalScanner**: paused (`active=false`) via `/scanner/pause`
- **Paper trades**: 10 rows total, **0 open** (all contaminated positions closed to $0)
- **Pending approvals**: 0
- **IBKR Gateway**: offline (port 4002 not connected)
- **Polygon**: reachable but engine uses `csv_cache` source
- **Data waterfall**: degraded — all `/prices/snapshot` sources show `csv_cache`

## Critical TODOs for Next Session (P0 → P3)

### P0 — Must-do before re-enabling auto-execution
1. **Re-verify Polygon live data flow** — figure out why engine's `/prices/snapshot` shows `csv_cache` despite the key being set and Polygon being reachable. Check `engine/data/market_data.py` fallback chain. Test with `engine/.venv/Scripts/python -c "from engine.data.market_data import ..."`.
2. **Restart IBKR Gateway on port 4002** — needed for real-time futures data and as safety-layer equity source.
3. **Fix the debate interface intermittent bug** — `BullResearcherAgent` / `BearResearcherAgent` expose `_call_llm` at class level (verified by direct probe), but live engine shows 19 "no callable" errors mixed with working scores. Possible causes: (a) ICWeightedEnsemble wrapping agents and not forwarding attributes, (b) stale `__pycache__` from before `acb45ae` was committed, (c) a race in lazy initialization. Quick diagnosis: add a debug line in `_call_agent_llm` that does `print(type(agent).__mro__)` and `print(dir(agent))` before the probe.
4. **Re-enable scanner** only after #1-3 are green AND after running one manual `/pipeline/run` per instrument that produces a sane debate score and a sane price in `trade_decision.limit_price`.

### P1 — Strongly recommended
5. **Re-commit the stray DB deletion intentionally** — `data/jarvis_trader.db` was tracked by git; I deleted it (renamed). Review whether it should be untracked/gitignored, or if the deletion needs an explicit "remove stray DB" commit.
6. **Update `engine/database/manager.py` default** — line 79 still has `db_path: str = "data/jarvis_trader.db"` as a hardcoded default string. It should default to `None` and then read from `settings.SQLITE_DB_PATH`. Current behavior is masked because the engine sets an explicit path, but any other caller with cwd != engine/ will still get bit.
7. **Delete `main_copy.py`** at workspace root — it's an abandoned copy, nothing imports it, and it's confusing when grepping.

### P2 — Nice to have
8. Wire TradingView MCP into Stage 1 pipeline as a `TVIndicatorAnalystAgent` — biggest unused asset in the workspace (see prior handoff `docs/session-logs/handoff-2026-04-10-1150.md`).
9. Ingest ThinkorSwim strategy reports via `engine/backtest/tos_importer.py` — 36 scripts on disk unused.
10. Complete `US-1703` SQLite migration — 2 pre-existing test failures from JSON+SQLite dual-write.
11. Finish RL walk-forward validation gate — unlocks 46 skipped tests.

### P3 — Research
12. Rotate `ANTHROPIC_API_KEY` per `docs/setup-guides/DEV_API_KEY_ROTATION.md`.
13. Add per-minute rate limit on pipeline to cap LLM burst cost on news days.
14. `datetime.utcnow()` → timezone-aware refactor (1,007 deprecation warnings).

## Verification Runbook (re-run these in next session)

```bash
# Canonical DB + zero-open invariant
engine/.venv/Scripts/python.exe -c "import sqlite3; c=sqlite3.connect('engine/data/jarvis_trader.db'); print('open:', c.execute(\"SELECT COUNT(*) FROM paper_trades WHERE status='open'\").fetchone()[0])"

# Scanner still paused
curl -s http://localhost:8010/scanner/status -H "X-API-Key: $API_KEY" | python -m json.tool

# Watchlist scan job should NOT be in scheduler
curl -s http://localhost:8010/scheduler/status -H "X-API-Key: $API_KEY" | python -m json.tool | grep -i watchlist

# Confirm hard-cap + absolute DB path
cd engine && .venv/Scripts/python -c "from config import settings; print('MAX_C:', settings.MAX_CONTRACTS_PER_INSTRUMENT); print('DB:', settings.SQLITE_DB_PATH)"

# Run all new tests
cd engine && .venv/Scripts/python -m pytest tests/test_safety_hardcap.py tests/test_scanner_guards.py tests/test_paper_runner_adapter.py tests/test_safety_layer.py -v --timeout=60

# Check for debate interface errors in latest logs
tail -200 engine/logs/engine-error.log | grep -aE "no callable|rebuttal" | tail -20
```

## Ground Truth Snapshot (for next session context)

From earlier exploration phase (3 haiku Explore agents):

- **Repo scale**: 27,209 LOC engine Python, 51 routers, 22 agents, 96 test files, 1,606 test functions, `main.py` 4,811 lines, 25 dashboard pages
- **Test suite health pre-session**: 1,432 passed / 2 failed / 69 skipped (from `engine/test_output.txt`)
- **External assets inventory**:
  - **WIRED**: Hidden Pivots (826 LOC + 7 endpoints, called in Stage 1), Corey Auction Analyst (499 LOC, called at `pipeline.py:1232`), Discord bot signals (215,887 rows, read by TechnicalAnalystAgent)
  - **PARTIAL**: TradingView MCP (bridge exists, no Stage 1 agent calls `/tv/snapshot`), Discord `/intelligence` endpoint (exposed, not consumed)
  - **ORPHAN**: 36 ThinkorSwim scripts in `thinkorswim-scripts/` (referenced in docs, not ingested by pipeline)
- **Ports**: Engine 8010 ✓, Dashboard 3010, IBKR paper 4002 ✗ (offline), Redis 6379
- **Config flags**: LIVE_TRADING_ENABLED=False ✓, REQUIRE_HUMAN_APPROVAL=True ✓, PAPER_TRADING=True ✓, SCHWAB_READY=False

## Key Insights From This Session (for the next AI reader)

1. **Evidence > memory.** Prior handoffs said "DB has zero tables" (wrong), "MCL stop loss inverted" (wrong — it was $82.40 below $84.20), "only 1 paper trade" (wrong — there were 10). I almost acted on stale handoff narratives. Always re-query the DB before trusting prior-session claims.

2. **Split-brain DBs hide in plain sight.** The engine was writing to `engine/data/jarvis_trader.db` while Discord modules were writing to `data/jarvis_trader.db` (workspace root). Both files had identical row counts for some tables (215,887 discord_bot_signals in both), which masked the divergence. The 104 MB vs 128 MB size difference was the tell.

3. **"Scanner" is ambiguous.** There are THREE independent scanners in this engine: (a) `run_watchlist_analysis` cron in `main.py:484` gated by `ANTHROPIC_API_KEY`, (b) `SignalScanner` class at `scanner/signal_scanner.py:67` started via `signal_scanner.start()` at `main.py:1151`, (c) `intraday_scan_15m_job` at `main.py:980`. My first kill switch only disabled (a). I had to also `/scanner/pause` for (b). (c) doesn't create paper trades.

4. **pm2 process management is opaque.** The log JSON showed `process_id: 6` consistently even across engine restarts — that's the pm2 app ID, not a system PID. PID changed from 63196 → 21392 silently when the old engine was killed by something external. Without pm2 awareness, the log timeline is misleading.

5. **The contamination had a hidden pattern.** Trades #108, #109, #110 were IDENTICAL (MES SELL 3 @ $70.57, one hour apart). The scanner had neither a "same symbol, same direction, still open" guard nor a price sanity check. Both guards are now in place.

6. **Debate interface bug is intermittent.** Fresh imports probe cleanly. Live engine shows the failure mixed with success. This is NOT a simple missing-method bug — probably a wrapper or cache issue. Don't waste time on direct fixes until you can reproduce it deterministically.

## Git State (at session end)

- Branch: `master`
- HEAD: `be6927d fix(trader): EOD operational hardening — scanner kill switch, safety cap, adapters, guards`
- Ahead of origin/master: 4 commits (3 from earlier today + this one)
- Uncommitted: handoff file (this document), deletion of `data/jarvis_trader.db` (tracked file renamed to `.orphaned`), various unrelated M/?? files

---

*Handoff authored by JARVIS (Claude Opus 4.6) on 2026-04-10 at session close. Next session: start by reading this file, then Section "Critical TODOs" P0 items in order.*
