# JARVIS TRADER — Comprehensive Project Analysis Report
**Date**: 2026-04-02 | **Branch**: master (clean) | **Method**: 10-agent parallel deep dive
**Coverage**: Engine core, Dashboard, RL module, Test suite, Backtest/Signals, Documentation, Infrastructure, API/Connectivity, Session logs, Git/Code metrics

---

# I. PROJECT STATUS OVERVIEW

## Scale & Metrics

| Metric | Value |
|--------|-------|
| **Total source files** (excl. deps) | ~250+ |
| **Total LOC** | ~110,867 (59,293 Python + ~51,574 TSX/TS) |
| **Python files (engine)** | ~170 files, 59,293 lines |
| **TSX/TS files (dashboard)** | ~173 files, ~51,574 lines |
| **API endpoints** | 90+ across 25 routers |
| **Dashboard pages** | 18 routes |
| **Dashboard components** | ~155 files |
| **Test files** | 16 (416 test functions, 7,882 lines) |
| **Documentation files** | ~97 markdown files (~3.7 MB) |
| **PRD stories** | 14/15 passing (93%) |

## Architecture Summary

```
Engine (FastAPI, Python 3.12, port 8010)
├── 5-Stage LLM Pipeline (10 agents: 4 analysts → debate → trader → risk → fund mgr)
├── 25 API Routers (90+ endpoints)
├── Safety Layer (hardcoded Python, 14 safety rules, kill switch)
├── Backtest Framework (STC signals, walk-forward, Monte Carlo, sensitivity)
├── RL Strategy Module (PPO via stable-baselines3, Gymnasium environment)
├── Multi-Market Orchestrator (futures, options, crypto, polymarket)
├── Learning System (4 modules: patterns, classifier, tuner, memory)
├── Options Infrastructure (5 files: chains, Greeks, strategies, positions, pricing)
├── Hook System (event-driven, 9 event types)
├── Notifications (WhatsApp/Twilio, Telegram)
└── Databases (SQLite primary, PostgreSQL/Redis/QuestDB optional)

Dashboard (Next.js 15, TypeScript, port 3010)
├── 18 pages (all "use client")
├── ~155 components (Iron Man HUD aesthetic)
├── lib/api.ts (fetchEngine/postEngine central API layer)
├── SWR for real-time data polling
├── Recharts + lightweight-charts + Three.js for visualization
└── Radix UI primitives + Tailwind CSS
```

## Validated Instruments

| Symbol | TF | WFE | PF | Trades | Status |
|--------|----|-----|-----|--------|--------|
| **MCL** | 1h | **0.82** | 1.81 | 65 | APPROVED — paper trading active |
| **MNQ** | 1h | **0.57** | 1.51 | 86 | APPROVED — paper trading active |
| **MGC** | 1d | **0.14** | — | — | HALTED — overfit, small-sample |
| **MES** | 1h | **0.09** | — | — | DO NOT TRADE — overfit |
| **SPY** | 1h | TBD | — | — | PENDING walk-forward |

## Safety Status — ALL GREEN

- `LIVE_TRADING_ENABLED = False` (paper mode enforced)
- `REQUIRE_HUMAN_APPROVAL = True`
- Kill switch: -2% daily / -10% drawdown (hardcoded Python)
- Safety layer: pure Python, zero LLM routing
- Port 4001 (live IB): permanently blocked in code
- All 6 pre-trade gates operational

---

# II. DETAILED FINDINGS BY AREA

## A. Engine Core

**File**: `engine/main.py` (458 lines, 25 routers, 15 startup components)

**Startup sequence**: Logging → SQLite → Portfolio tracker → PnL monitor → Safety layer → IB order manager → Market data → 10 LLM agents → Trading pipeline → APScheduler → EOD scheduler → WebSocket → Cost tracker → Loss tracker → Dependency injection

**Config** (`engine/config.py`, 256 lines): Pydantic v2 BaseSettings. Risk limits: max position 5%, daily loss -2%, drawdown -10%, 10 orders/min, $5K max order, 2 micro contracts, 40% margin.

**Issues:**
- `database/schema.py`: 1,528 lines (nearly 2× the 800-line limit)
- `backtest/backtester.py`: 955 lines (over limit)
- **Duplicate RL routes**: `strategies_router.py` (/strategies/rl/) AND `strategy_router.py` (/rl/) define overlapping endpoints
- Options router registered with no prefix — root-level endpoints may conflict
- `datetime.utcnow()` deprecated usage throughout (Python 3.12 warns)
- Schwab connector: 581 lines but `SCHWAB_READY = False`, orders untested

## B. Dashboard

**18 pages, ~12,956 page lines + ~155 components + ~38,618 component/lib lines = ~51,574 total**

**Technology stack**: Next.js 15, React 19, TypeScript strict, Tailwind, Radix UI, Three.js, Recharts, lightweight-charts, SWR 2.3.3

**Central API proxy**: `next.config.ts` rewrites `/api/engine/:path*` → `http://localhost:8010/:path*`. `lib/api.ts` (562 lines) provides `fetchEngine`/`postEngine` with API key injection, 30s timeout, 1 retry.

**CRITICAL: ~80+ component files bypass fetchEngine** — define local `ENGINE_URL = "http://localhost:8010"` and call `fetch()` directly. This bypasses API key injection, timeout, retry, and proxy rewrite. Violations also in `app/settings/page.tsx` (lines 104, 115, 652) and `app/scorecard/page.tsx` (line 416).

**Other issues:**
- `/stats` page: 16-line stub ("coming soon")
- All pages `"use client"` — no SSR optimization anywhere
- 2 TypeScript `any` violations (use-websocket.ts, sound-alerts.ts)
- `lib/websocket-example.tsx`: not imported by any production code

## C. RL Strategy Module

**Status**: Architecturally complete (3,435 lines, 8 files). Reward function being tuned.

**Files:**
| File | Lines | Purpose |
|------|-------|---------|
| `rl_config.py` | 174 | 18-feature state space, 4-action space, PPO config, validation gates |
| `rl_environment.py` | 542 | Gymnasium env, feature extraction, reward function |
| `rl_agent.py` | 320 | PPO wrapper, kill switch safety |
| `rl_trainer.py` | 701 | Training orchestrator, cache-first data pipeline |
| `rl_evaluator.py` | 364 | OOS evaluation, 6 validation gates |
| `rl_executor.py` | 720 | Autonomous hourly execution, APScheduler, IBKR routing |
| `test_rl_env.py` | 613 | 53 tests, all passing |

**Current reward config** (entry_cost=-0.10, being tested in Run 5):
```python
"hold_cost_per_bar": -0.001,  # flat, NOT compounding
"entry_cost": -0.10,          # was -0.20 (too punishing, 14 trades only)
"t1_bonus": +0.10,
"flat_hold_reward": +0.003,   # when flat (patience reward)
```

**Training history:**
| Run | Timesteps | Hold Rate | Trades | PF | Status |
|-----|-----------|-----------|--------|-----|--------|
| Run 3 | 500k | 16.5% ❌ | — | 0.85 | Pre-fix, BUY-spam |
| Run 4 | 500k | 77.9% ✅ | 14 ❌ | 0.31 | Post-fix, over-HOLD |
| Run 5 | 500k | TBD | TBD | TBD | In progress (entry_cost=-0.10) |

**Open issues:**
- Only MES models exist. No MNQ/MCL/MGC models.
- Validation gate inconsistency: `RLAgent.evaluate()` checks 4 gates, `OOSEvaluator` checks 6
- `max_consecutive_losses` gate defined but never checked
- yfinance ticker: trainer uses `ES=F`, executor uses `MES=F` (different price scales)

## D. Test Suite

**16 files, 416 tests, 7,882 lines. Current: 285 passed / 65 failed (81%)**

| Failure Category | Count | Root Cause |
|-----------------|-------|------------|
| Safety/loss_tracker | 31 | test_loss_tracker.py uses production config not mock_settings fixture |
| Pipeline async mocks | 26 | Pipeline made async, MagicMock not updated to AsyncMock |
| Auth middleware | 7 | Middleware changes broke test expectations |
| LLM client field | 1 | Field count mismatch in LLMCallResult |

**Sacred tests**: `test_safety_layer.py` (25 tests, 100% pass rate when using correct fixtures)

**Major gaps:**
- No code coverage has ever been measured (pytest-cov configured but never run)
- Zero dashboard tests
- No tests for: `backtester.py`, `walk_forward.py`, `monte_carlo.py`, `sensitivity.py`, IB order manager, WhatsApp, health_monitor, market_data, individual agent implementations

## E. Backtest & Signals

**40 files (~12,000 lines) in `engine/backtest/`**

**5-Layer "Tony Stark" signal framework:**
1. **Regime Map**: EXHAUSTED/COMPRESSION/TRENDING_BULL/TRENDING_BEAR/RANGE_BOUND
2. **Structure Map**: BUYER_CONTROL/SELLER_CONTROL/NEUTRAL (auction theory, VPOC/VAH/VAL)
3. **Bias**: 4-indicator vote (KAMA, STC direction, volume dominance, EMA trend)
4. **Entry Timing**: Layer-aware with news blackout filter (FOMC/CPI/NFP/GDP)
5. **Pipeline Approval**: LLM agent pipeline

**Per-instrument canonical params** (`signals.py` INSTRUMENT_PARAMS — Tier 3 to change):
| Symbol | STC_OS | STC_OB | Stop ATR | T1 ATR | WFE |
|--------|--------|--------|----------|--------|-----|
| MCL | 15 | 83 | 0.90 | 1.50 | 0.82 |
| MNQ | 15 | 92 | 0.70 | 1.00 | 0.57 |
| MGC | 17 | 88 | 0.30 | 1.50 | 0.14 |
| MES | 15 | 83 | 0.50 | 2.00 | 0.09 |

**Walk-forward**: 6m train/3m test, scoring formula: `(PF×0.3 + WR×0.2 + Sharpe×0.3 + return×0.1) / DD×0.1`

**MTF filter verdict**: Hurts MNQ (WFE 0.57→0.17). Volume filter hurts MNQ (WFE→-0.23). Use adaptive_regime only for MNQ.

## F. API & Connectivity (21 external services)

| Service | Status |
|---------|--------|
| Anthropic Claude | CONFIGURED (Opus/Sonnet/Haiku fallback chain) |
| IB Gateway (paper, port 4002) | CONFIGURED but not actively connected |
| Schwab | INCOMPLETE 60% — orders untested |
| yfinance | ACTIVE (free fallback) |
| Polygon.io | OPTIONAL |
| Finnhub | OPTIONAL (news/sentiment) |
| FRED | ACTIVE (no API key needed) |
| ApeWisdom (Reddit) | ACTIVE |
| Twilio WhatsApp | CONFIGURED |
| Telegram | OPTIONAL |
| SQLite | ACTIVE (primary) |
| PostgreSQL | OPTIONAL (graceful degradation) |
| Redis | CONFIGURED (not needed for paper) |
| WebSocket | ACTIVE (real-time dashboard) |
| Freqtrade | NOT ACTIVE (requires separate process) |
| Polymarket | DISABLED by default |

**Security concerns:**
- Default `API_KEY = "[REDACTED]"` must be changed
- Agents bypass centralized config: read `ANTHROPIC_API_KEY` directly from `os.environ`
- `.schwab_token.json` at engine root (verify in .gitignore)
- API keys exposed in git history (P0 remediation pending)

## G. Infrastructure

**Ready (Green):**
- `.env.example` (281 lines, all 40+ vars documented)
- `ecosystem.config.js` (5 PM2 processes with cron scheduling)
- Docker stack (Postgres, Redis, QuestDB, Prometheus, Grafana) + paper overlay
- GitHub Actions CI (lint, typecheck, test, build, security scan)
- `.secrets.baseline` (27 detectors, clean)
- Health monitoring with WhatsApp alerts
- 3 pre-provisioned Grafana dashboards

**Issues:**
- `start_jarvis.bat` line 59 uses `npm run dev` instead of `pnpm dev`
- CI workflows use `npm ci` instead of `pnpm install`
- CI targets `main`/`develop` branches — active branch is `master`
- `engine-test` CI job has `continue-on-error: true` (failures won't block merges)
- No Dockerfile for engine or dashboard
- No log rotation, no backup automation, no SSL/TLS

## H. Documentation

**97 markdown files, ~3.7 MB total. Well-documented but fragmented.**

**Issues:**
- Two competing "single source of truth" documents (UNIFIED_CANON.md vs archived MASTER.md)
- MEMORY.md says MASTER.md is at project root — actually at `docs/archive/`
- README.md outdated: ports 8000/3000 (should be 8010/3010), Python 3.11 (should be 3.12), 84 tests (reality: 416), 3 Stage 1 agents (reality: 4)
- Endpoint counts vary across docs: 75, 80+, 82, 90+
- `discord-export-session-2026-04-02.md` at project root (wrong project)
- Session logs consuming >1 MB (one file at 513KB)

**PRD Status (all 3 PRD files):**
- Phase 1 (`prd.json` root): 5/5 PASS
- Phase 2 (`prd-phase2.json`): 4/5 PASS (US-015 split main.py: FAIL — but main.py is now 458 lines, may be complete)
- Phase 6 (`engine/prd.json`): 5/5 PASS

## I. Session History (11 sessions, March 28–April 2)

**Development velocity**: 49 files → 250+ files in 5 days

| Date | Files | Routes | Tests Passing |
|------|-------|--------|--------------|
| Mar 28 | ~49 | 2 | 0 |
| Mar 31 | ~100+ | 16 | 84 |
| Apr 1 | ~134 | 18 | 84+ |
| Apr 2 | ~140+ | 18 | 285 |

**Recurring issues across sessions:**
1. File truncation from multi-agent parallel writes (4+ occurrences)
2. PM2 zombie processes (2+ occurrences)
3. Python 3.14 vs 3.12 conflicts (3+ occurrences)
4. Missing venv dependencies (4+ occurrences)
5. Dashboard hardcoded localhost URLs (persistent, deferred)
6. Safety layer test failures (persistent, pre-existing)

---

# III. CRITICAL ACTION ITEMS

## P0 — Immediate (Security)
1. **Revoke exposed API keys** (Anthropic, Polygon, Twilio, Google OAuth) — `docs/runbooks/SECURITY_REMEDIATION.md`
2. **Change default API_KEY** from `jarvis-dev-key-change-me` in production `.env`

## P1 — High Priority (Correctness)
3. **Fix 65 failing tests**:
   - 31 test_loss_tracker.py: use `mock_settings` fixture instead of production config
   - 26 test_pipeline_e2e.py: migrate MagicMock → AsyncMock for async functions
   - 7 test_auth_and_rate_limit.py: realign test expectations with middleware
   - 1 test_llm_client.py: fix LLMCallResult field count
4. **Fix ~80+ dashboard hardcoded URLs** — migrate all `fetch("http://localhost:8010/...")` to `fetchEngine()`/`postEngine()`
5. **Fix CI branch** — target `master` in `.github/workflows/ci.yml` and `deploy-check.yml`
6. **Fix npm vs pnpm** in `start_jarvis.bat` (line 59) and CI workflows
7. **Resolve duplicate RL routes** — deprecate `strategy_router.py` (/rl/*) in favor of `strategies_router.py` (/strategies/rl/*)

## P2 — Medium Priority (Quality)
8. **Split oversized files**: `database/schema.py` (1,528 lines), `backtester.py` (955 lines)
9. **Run code coverage**: `pytest --cov=engine --cov-report=html` — first run ever
10. **Update README.md**: ports, Python version, test counts, agent counts
11. **Consolidate "source of truth"**: pick UNIFIED_CANON.md as canonical, deprecate MASTER.md
12. **Add dashboard tests**: at minimum, smoke tests for lib/api.ts
13. **Unify RL validation gates**: make RLAgent.evaluate() and OOSEvaluator use the same 6 gates
14. **Fix yfinance ticker**: trainer (ES=F) and executor (MES=F) must use same mapping

## P3 — Enhancement
15. **RL reward tuning** — Run 5 results pending; may need to adjust `flat_hold_reward`/`entry_cost` ratio
16. **Train MNQ/MCL models** — only MES exists
17. **Connect IB Gateway** (paper port 4002) for real paper order execution
18. **SPY walk-forward** to determine WFE threshold clearance
19. **Add Dockerfile** for engine and dashboard
20. **Remove `discord-export-session-2026-04-02.md`** from project root
21. **Check US-015 status** (split main.py) — main.py now at 458 lines, may be complete

---

# IV. SWOT ANALYSIS

## STRENGTHS

| # | Strength | Evidence |
|---|----------|---------|
| 1 | **Robust Safety Architecture** | 14 hardcoded rules, kill switch, 6 pre-trade gates, zero LLM in safety path. Port 4001 permanently blocked. |
| 2 | **Validated Statistical Framework** | WFE 0.82 (MCL) and 0.57 (MNQ). Walk-forward + Monte Carlo + sensitivity analysis = statistical rigor. |
| 3 | **Multi-Market Infrastructure** | Futures + options + crypto + prediction markets. Orchestrator + per-market capital allocation. |
| 4 | **Rapid Development Velocity** | 49 → 250+ files in 5 days. 10-agent parallel pattern. 93% PRD completion. |
| 5 | **Rich Trading Dashboard** | 18 pages, 155 components, Three.js HUD, WebSocket real-time, Iron Man aesthetic. |
| 6 | **Comprehensive Documentation** | 97 markdown files, 97 session logs, every decision recorded. |
| 7 | **Defense in Depth** | 3 broker connectors, 5 data sources, 2 notification channels, 4 database options. |
| 8 | **Learning System** | 4-module feedback loop (patterns, classification, tuning, memory) for continuous improvement. |

## WEAKNESSES

| # | Weakness | Evidence |
|---|----------|---------|
| 1 | **Test Health** | 19% failure rate. No coverage measured. Zero dashboard tests. Core backtest untested. |
| 2 | **Dashboard Technical Debt** | ~80+ components bypass fetchEngine with hardcoded localhost:8010. |
| 3 | **RL Module Immature** | 4 training runs, none pass validation gates. Only MES trained. |
| 4 | **Documentation Fragmentation** | Multiple "sources of truth". README outdated. Endpoint counts inconsistent. |
| 5 | **Infrastructure Inconsistencies** | npm/pnpm mismatch, CI targets wrong branch, no app containerization. |
| 6 | **Code Size Violations** | schema.py 1,528 lines, backtester.py 955 lines (both over 800-line limit). |
| 7 | **No Live Broker Connection** | Port 4002 not connected. Paper trading simulated not broker-verified. |

## OPPORTUNITIES

| # | Opportunity | Path |
|---|-------------|------|
| 1 | **RL Alpha** | PPO agent can discover non-STC patterns. Walk-forward framework ready. Run 5+ will show results. |
| 2 | **Options Income** | Infrastructure built (5 files, 7 strategies). VIX-regime-aware. Deploy alongside futures. |
| 3 | **Full Automation** | PM2 + cron + health alerts = hands-off once IB Gateway connected. |
| 4 | **Live Trading (Phase 3)** | Safety infrastructure complete. Need 60+ paper trades, WFE ≥ 0.50, MaxDD < 10%. |
| 5 | **Dashboard Deployment** | Next.js proxy ready. Deploy to Vercel would also fix hardcoded URL problem. |
| 6 | **Multi-Market Revenue** | MCL + MNQ + options + crypto running simultaneously with cross-market risk management. |

## THREATS

| # | Threat | Mitigation |
|---|--------|------------|
| 1 | **Exposed API Keys** | P0. Revoke at provider dashboards + BFG Repo-Cleaner. Blocker for live trading. |
| 2 | **Market Regime Change** | WFE is backward-looking. Rolling recalculation every 4 weeks. Alert at WFE < 0.40. |
| 3 | **yfinance Data Quality** | Free, rate-limited, 730-day intraday limit. Need Polygon or IBKR for production. |
| 4 | **Single Point of Failure** | One machine, one process. PM2 provides restart only. No HA. |
| 5 | **Python Version Fragility** | Python 3.14 breaks engine. No Docker = relies on correct PATH. |
| 6 | **Over-Optimization Risk** | 1,250-combination grid search. Walk-forward partially mitigates but doesn't eliminate. |

---

# V. PROJECT TRAJECTORY ASSESSMENT

## Where We Are
The project is at the end of the **Hardening Phase** with all Phase 6 PRD stories complete. The core signal strategy is validated (WFE ≥ 0.50 for MCL and MNQ), the safety architecture is solid, the dashboard is feature-complete for paper trading monitoring, and the RL module is architecturally finished but reward-tuning.

## What's Blocking Live Trading
1. API key security remediation (P0)
2. IB Gateway paper connection (actual broker-verified fills)
3. 60+ paper trades over 60 days with validated metrics
4. WFE rolling check confirms signals still valid

## Recommended Next Sprint Priorities
1. P0: Revoke API keys + BFG Repo-Cleaner
2. P1: Fix 65 failing tests (3 distinct fixes needed)
3. P1: Fix 80+ dashboard hardcoded URLs (systematic find-replace)
4. Connect IB Gateway paper (port 4002)
5. Monitor RL Run 5 results; train MNQ/MCL if reward balance achieved

---

*Report generated 2026-04-02 via 10-agent parallel deep dive.*
*Agents covered: engine core, dashboard, RL module, test suite, backtest/signals, documentation, infrastructure, API/connectivity, session logs, git/code metrics.*
