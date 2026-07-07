# JARVIS TRADER — Codebase Audit Report

**Date:** 2026-04-02
**Scope:** Full project — engine/, dashboard/, docs/, scripts/, config
**Purpose:** Identify structural weaknesses, dead code, duplication, doc bloat, and config conflicts before the 30-day paper validation run

---

## Executive Summary

The JARVIS TRADER codebase is feature-rich (80+ endpoints, 24 routers, 100+ dashboard widgets) but has accumulated significant technical debt during rapid development. The four highest-impact issues are: **duplicate endpoint routes** that will cause silent shadowing, **dead code modules** that inflate the attack surface without adding value, **documentation that outweighs the codebase** (75k LOC docs vs 64k LOC Python), and **config contradictions** between .env, config.py, and archived docs.

None of these are safety-critical — the hardcoded safety layer, kill switch, and risk parameters are clean. But they create drag on every future change and make onboarding (human or AI) unnecessarily difficult.

---

## 1. Duplicate / Overlapping Endpoints

**Severity: HIGH** — Silent route shadowing means one version wins and the other is dead code you think is live.

### 1.1 `/rl/train` — Two Definitions

- `engine/routers/strategies_router.py` — defines `POST /rl/train`
- `engine/routers/strategy_router.py` — also defines `POST /rl/train`

Both are mounted in `main.py`. FastAPI will register the first one encountered; the second is silently ignored. Whichever one you think you're calling, you might not be.

**Fix:** Consolidate into one router. `strategies_router.py` (plural) should own bulk/list operations; `strategy_router.py` (singular) should own single-strategy CRUD. Remove the duplicate.

### 1.2 `/validation/progress` vs `/paper/validation/progress`

- `engine/schedulers/validation_checker.py` — serves `/validation/progress`
- `engine/routers/paper_router.py` — serves `/paper/validation/progress`

Both return validation metrics but from different backends with different SQL. During the US-101 fix, only one was patched. The other may still have the broken column references.

**Fix:** Pick one canonical path (`/paper/validation/progress` is more RESTful). Have the other redirect or remove it entirely.

### 1.3 Paper Trading — 5 Separate Implementations

| File | Role |
|------|------|
| `engine/paper/paper_config.py` | Paper trading configuration |
| `engine/paper/paper_runner.py` | Paper trade execution loop |
| `engine/paper/paper_tracker.py` | Position/P&L tracking |
| `engine/execution/paper_trade_logger.py` | Trade logging to SQLite |
| `engine/schedulers/validation_tracker.py` | 30-day validation metrics |

These overlap significantly in trade logging, P&L calculation, and position tracking. `paper_tracker` and `paper_trade_logger` both write to SQLite with slightly different schemas.

**Fix:** Merge `paper_trade_logger` into `paper_tracker`. Make `validation_tracker` read-only (queries only, no writes). Single source of truth for paper trade state.

### 1.4 IB Connector Fragmentation — 4+ Files

| File | Methods |
|------|---------|
| `engine/execution/ib_gateway.py` | connect, place_order, get_positions, get_account_summary |
| `engine/execution/ibkr_executor.py` | execute_order, get_positions, get_open_orders |
| `engine/execution/ib_connector.py` | connect, subscribe_market_data, get_positions |
| `engine/data/ib_data_feed.py` | subscribe_bars, get_historical_data |

`get_positions` is defined in at least 3 files. `connect` logic exists in 2 files. Only `ib_gateway.py` has the port 4001 safety block.

**Fix:** Single `IBClient` class in `ib_gateway.py` that owns all IB communication. Other files become thin wrappers or are removed. The port 4001 safety block must be the single entry point — no bypass paths.

### 1.5 Two `GreeksMonitor` Classes

- `engine/analytics/greeks_monitor.py` — stub (empty methods, no logic)
- `engine/options/greeks_monitor.py` — real implementation with Black-Scholes

The stub in `analytics/` is imported by some dashboard endpoints. It returns empty data silently.

**Fix:** Delete the stub. Point all imports to `engine/options/greeks_monitor.py`.

---

## 2. Dead Code

**Severity: MEDIUM** — Dead code inflates cognitive load, creates false import chains, and increases the surface area for bugs.

### 2.1 Learning System — 4 Unused Modules

| Module | Lines | Imported Anywhere? |
|--------|-------|--------------------|
| `engine/learning/pattern_extractor.py` | ~180 | No |
| `engine/learning/session_memory.py` | ~150 | No |
| `engine/learning/strategy_tuner.py` | ~200 | No |
| `engine/learning/trade_classifier.py` | ~120 | No |

These are exported from `engine/learning/__init__.py` but never called by any router, scheduler, or pipeline stage. Total: ~650 lines of dead code.

**Fix:** Either wire them into the pipeline (post-trade analysis stage) or move to `engine/learning/_experimental/` with a note. Don't delete — they represent real design work that may be useful in Phase 2.

### 2.2 Execution Modules — 4/8 Unused

| Module | Status |
|--------|--------|
| `engine/execution/order_router.py` | Exported, never called |
| `engine/execution/paper_trade_logger.py` | Duplicates paper_tracker |
| `engine/execution/schwab_connector.py` | SCHWAB_READY=False, no callers |
| `engine/execution/ibkr_executor.py` | Overlaps ib_gateway.py |

**Fix:** `schwab_connector.py` stays (needed for Phase 3). The other three should be consolidated or removed.

### 2.3 Orchestrator Not Initialized

`engine/markets/orchestrator.py` defines `MultiMarketOrchestrator` and is imported by `markets_router.py`, but `main.py` never creates an instance. The router endpoints that depend on it will return errors or empty data.

**Fix:** Either initialize the orchestrator in `main.py` startup (with the futures module only, since MCL/MNQ are the approved instruments) or remove the router endpoints that depend on it.

### 2.4 Dashboard Widgets — Quantity Over Quality

100+ widget components in `dashboard/components/widgets/`. Many are thin wrappers around a single API call with identical patterns (fetch, loading spinner, error state, card). No shared abstraction.

**Fix:** Create a generic `<EngineWidget endpoint="/path" title="Name" />` component that handles the fetch/loading/error pattern. Convert the simplest widgets to use it. This could eliminate 30-40 files.

---

## 3. Documentation Bloat

**Severity: MEDIUM** — Docs that outweigh code create confusion about what's current.

### 3.1 By the Numbers

| Category | Lines of Code |
|----------|--------------|
| Python (engine/) | ~63,744 |
| TypeScript (dashboard/) | ~18,200 |
| Documentation (docs/) | ~75,677 |
| Session logs alone | ~25,000+ |

Documentation is **larger than the entire Python codebase**. Most of this is session logs and superseded reports.

### 3.2 Specific Problems

**Giant session logs:**
- `docs/session-logs/SESSION_LOG_2026-04-01_CONTINUATION.md` — 12,641 lines (single file)
- Multiple session logs over 3,000 lines each

These are historical records but they actively confuse AI agents that read them for context. An agent scanning `docs/` for current system state will find contradictory information across different session dates.

**Stale archived reports:**
- `docs/archive/` contains multiple "master reports" from different dates with conflicting information
- Port references: some docs say 7497 (old TWS), others say 4002 (correct IB Gateway paper)
- MES referenced as tradeable in archived docs (current status: DO NOT TRADE, WFE 0.09)

**Fix:**
1. Move all session logs to `docs/session-logs/archive/` — keep only the latest handoff
2. Add a `docs/archive/DEPRECATED.md` noting these are historical only
3. Create a single `docs/CURRENT_STATE.md` (under 200 lines) as the canonical reference
4. Delete or consolidate any doc over 3,000 lines — extract the actionable parts, archive the rest

---

## 4. Configuration Conflicts

**Severity: HIGH** — Config mismatches cause silent failures that look like bugs.

### 4.1 IBKR_CLIENT_ID Confusion

- `.env` has `IBKR_CLIENT_ID=2`, `IBKR_CLIENT_ID_DATA=1`, `IBKR_CLIENT_ID_TRADE=2`
- `config.py` only reads `IBKR_CLIENT_ID` (singular) — the `_DATA` and `_TRADE` variants are ignored
- Engine was running with client_id=10 from a previous session until manually corrected

**Fix:** Remove `IBKR_CLIENT_ID_DATA` and `IBKR_CLIENT_ID_TRADE` from `.env` (they do nothing). Document that `IBKR_CLIENT_ID` is the only field that matters.

### 4.2 FUTURES_WATCHLIST Format

- `.env`: `FUTURES_WATCHLIST=["MCL","MNQ"]` — JSON array as string
- `config.py`: `FUTURES_WATCHLIST: list[str] = Field(default=["MCL", "MNQ"])` — Python list

Pydantic v2 with `extra="ignore"` will parse the JSON string correctly, but this is fragile. A stray quote or bracket breaks startup silently (falls back to default).

**Fix:** Use comma-separated format in .env (`FUTURES_WATCHLIST=MCL,MNQ`) and add a Pydantic validator that splits on commas. More robust, more standard.

### 4.3 API_KEY Default Mismatch

- `config.py` default: `jarvis-dev-key-change-me`
- `.env`: `test-key`
- `dashboard/.env.local`: `test-key`

If .env fails to load (wrong path, permissions), the engine starts with `jarvis-dev-key-change-me` and the dashboard gets 401s on every request with no useful error message.

**Fix:** Make the config.py default match the dashboard default (`test-key`), or better yet, fail fast if API_KEY is not explicitly set in .env.

### 4.4 Port References in Docs

| Document | Port Referenced | Correct? |
|----------|----------------|----------|
| `docs/runbooks/PAPER_TRADING.md` | 7497 | NO — should be 4002 |
| `engine/execution/ib_gateway.py` | 4002 (paper), 4001 (blocked) | YES |
| `.env` | 4002 | YES |
| `docs/archive/` (various) | 7497, 4001, 4002 | Mixed |

**Fix:** Global find-replace 7497 → 4002 in all non-archived docs. Add a note in PAPER_TRADING.md that TWS port 7497 is not used — IB Gateway uses 4002.

---

## 5. Code Quality Violations

**Severity: LOW** — Not blocking, but accumulates drag.

### 5.1 Files Exceeding 400-Line Standard

The coding standard says 400 lines typical, 800 max. At least 27 files exceed 400 lines. Notable offenders:

| File | Lines | Notes |
|------|-------|-------|
| `engine/main.py` | 421 | Borderline — router imports could be extracted |
| `engine/agents/pipeline.py` | ~600 | Complex but justified — core pipeline logic |
| `engine/risk/safety_layer.py` | ~500 | Critical path — splitting adds risk |
| `engine/backtest/signals.py` | ~450 | Canonical signal logic — Tier 3 to change |
| Various router files | 400-600 | Could be split by sub-resource |

**Fix:** `safety_layer.py` and `signals.py` should stay monolithic (they're safety-critical and canonical). Router files over 500 lines should be split. `main.py` could extract the router registration into a `routers/__init__.py`.

### 5.2 Missing Error Handling

Several router endpoints lack try/except blocks. When the underlying service throws, the client gets a raw 500 with a Python traceback (information disclosure).

**Fix:** Add a FastAPI exception handler middleware that catches unhandled exceptions, logs the traceback, and returns a clean 500 JSON response.

---

## 6. Prioritized Remediation Plan

### Immediate (This Week)

1. **Deduplicate `/rl/train`** — Pick one router, delete the other (30 min)
2. **Fix port 7497 references** in non-archived docs (15 min)
3. **Remove IBKR_CLIENT_ID_DATA/TRADE** from .env with a comment (5 min)
4. **Delete GreeksMonitor stub** in analytics/, update imports (20 min)

### Short-Term (During Paper Validation)

5. **Consolidate paper trading modules** — merge paper_trade_logger into paper_tracker (2-4 hours)
6. **Initialize orchestrator** in main.py or remove dependent endpoints (1 hour)
7. **Archive session logs** — move to `docs/session-logs/archive/` (30 min)
8. **Create docs/CURRENT_STATE.md** as single source of truth (1 hour)
9. **Add global exception handler** middleware (1 hour)

### Phase 2 (Post-Validation)

10. **Consolidate IB connectors** into single IBClient class (4-8 hours)
11. **Wire learning system** into pipeline or move to experimental (2-4 hours)
12. **Create generic EngineWidget** component for dashboard (4-8 hours)
13. **Refactor oversized files** that exceed 800 lines (ongoing)

---

## 7. What's Clean

Not everything is debt. These areas are well-structured:

- **Safety layer** (`engine/risk/safety_layer.py`) — hardcoded, tested, no LLM involvement. Port 4001 is permanently blocked. Kill switch thresholds are non-negotiable constants.
- **Config model** (`engine/config.py`) — Pydantic v2 with proper Field defaults and descriptions. `extra="ignore"` handles .env flexibility well.
- **Dashboard API layer** (`dashboard/lib/api.ts`) — all engine calls go through `fetchEngine`/`postEngine`. No hardcoded URLs in components.
- **Test coverage for safety** — `test_safety_layer.py` is comprehensive and runs on every change.
- **Pipeline architecture** — the 5-stage design (analyze → debate → decide → risk → approve) is clean and each stage has clear responsibility.
- **Price cache** (new) — `engine/data/price_cache.py` is a model of simplicity: 140 lines, stdlib-only, proper TTL and locking.

---

*Generated by codebase audit — 2026-04-02. Review with Matt before executing remediation.*
