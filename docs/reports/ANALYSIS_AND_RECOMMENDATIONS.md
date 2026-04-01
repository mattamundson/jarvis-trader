# JARVIS TRADER — Complete System Analysis & Recommendations

**Generated:** 2026-03-29
**Analyst:** Claude Opus 4.6
**Scope:** Full codebase audit — engine (12,000+ LOC), dashboard (14 components, 3 pages), infrastructure, TOS scripts (34 files), security, architecture

---

## Executive Summary

JARVIS TRADER is an impressive piece of work for its age. The 5-stage multi-agent pipeline is architecturally sound, the safety layer is best-in-class, and the backtest results (MES 1h: PF 5.27, Sharpe 4.16, +47.2%) validate a real edge. But the system has a critical security breach, significant gaps in testing and observability, and the dashboard is monitoring-grade — not yet trading-grade. Below is every finding, ranked by urgency, with specific remediation steps.

**Overall Scores:**

| Dimension | Score | Verdict |
|-----------|-------|---------|
| Architecture | 9/10 | Excellent pipeline design, clean separation of concerns |
| Safety Layer | 9.5/10 | Hardcoded Python guardrails — the right call |
| Agent Prompts | 9/10 | Professional, decisive, well-incentivized |
| Code Quality | 8/10 | Above industry standard for trading systems |
| Security | 3/10 | Live API keys committed to git — must fix NOW |
| Testing | 4/10 | Backtest coverage only, zero agent unit tests |
| Dashboard | 7.5/10 | Good monitoring UI, missing trading controls |
| Production Readiness | 6.5/10 (paper) / 4/10 (live) | Paper-ready, not live-ready |

---

## PRIORITY 1: CRITICAL SECURITY (Do This Today)

### 1.1 Live API Keys Committed to Git

**Files exposed in git history:**

| File | Keys Exposed |
|------|-------------|
| `engine/.env` | Anthropic API key, Polygon API key, Twilio SID + Auth Token, personal WhatsApp number |
| `client_secret_OPENCLAW_AMO_SZN_qeuke.apps.googleusercontent.com.json` | Google OAuth client_id, client_secret, project_id |

**Immediate actions:**

1. **Revoke every exposed key** — Anthropic Console, Polygon Dashboard, Twilio Console, Google Cloud Console. Do this before anything else.
2. **Scrub git history** — `.gitignore` prevents future commits but does NOT remove already-committed files:
   ```bash
   # Install BFG Repo-Cleaner (faster than filter-branch)
   # Then:
   bfg --delete-files "*.env" --delete-files "client_secret*.json"
   git reflog expire --expire=now --all
   git gc --prune=now --aggressive
   git push origin --force-all
   ```
3. **Regenerate all credentials** and populate a fresh `engine/.env` from `.env.example`.
4. **Externalize Grafana password** — `docker-compose.yml` has `GF_SECURITY_ADMIN_PASSWORD: jarvis123` hardcoded. Move to `.env`.

### 1.2 Kill Switch Has No Authentication

`POST /safety/kill-switch/activate` and `/deactivate` are open endpoints. Anyone on the network can toggle the kill switch.

**Fix:** Add API key middleware or JWT auth to all safety endpoints before paper trading begins. A simple `X-API-Key` header check in FastAPI middleware is sufficient for local use.

### 1.3 No Rate Limiting on Public Endpoints

All 26 endpoints are unprotected. If the dashboard is ever exposed beyond localhost, the entire pipeline can be spammed.

**Fix:** Add `slowapi` rate limiter to FastAPI, especially on `/pipeline/run` (expensive — triggers 8 LLM calls).

---

## PRIORITY 2: TESTING (Before Paper Trading)

### 2.1 Zero Agent Unit Tests

The backtest infrastructure has 5 test files (529 + 133 + 134 + 220 lines). The production agents — the code that will make real trading decisions — have **zero tests**.

**What to test:**

| Agent | Test Strategy |
|-------|--------------|
| TechnicalAnalyst | Mock LLM response, verify indicator data is correctly formatted in prompt, verify fallback to daily data works |
| RiskManager | Unit test every hard rule in SafetyLayer (kill switch, daily loss, drawdown, price collar, correlated exposure) |
| Pipeline | Integration test: feed known analyst outputs through debate → trader → risk → fund, verify decision chain |
| SafetyLayer | Fuzz test: throw edge cases (NaN prices, missing data, zero volume) and verify graceful rejection |

**Recommended framework:** `pytest` + `pytest-asyncio` + `respx` (for mocking httpx LLM calls).

### 2.2 No CI/CD Pipeline

No GitHub Actions, no pre-commit hooks, no automated quality gates.

**Minimum viable CI:**
```yaml
# .github/workflows/ci.yml
- Run pytest on engine/
- Run mypy type checks
- Run ruff lint
- Run npm run build on dashboard/
- Block merge if any fail
```

### 2.3 No End-to-End Smoke Test

The E2E test (US-008) was a one-time manual run. There's no repeatable test that verifies the full pipeline produces a valid decision from mock market data.

**Fix:** Create `engine/tests/test_pipeline_e2e.py` that:
1. Injects known OHLCV data (a bullish STC crossover scenario)
2. Mocks all LLM calls with deterministic responses
3. Asserts the pipeline produces a BUY decision with correct stop/target levels
4. Asserts SafetyLayer approves or rejects based on configured limits

---

## PRIORITY 3: ENGINE IMPROVEMENTS

### 3.1 LLM Client Has No Retry Logic

`SimpleLLMClient` in `main.py` is a thin wrapper with no retry, no exponential backoff, no token counting, no cost tracking.

**Fix:** Replace with a proper client that:
- Retries on 429/500/503 with exponential backoff (3 attempts, 1s/2s/4s)
- Counts input/output tokens per call
- Logs cumulative daily cost to SQLite
- Falls back from Opus → Sonnet → Haiku if primary model is unavailable

**Estimated daily LLM cost** (13 pipeline runs × 8 calls): ~$0.50–$1.00/day. Worth tracking.

### 3.2 No Persistent Trade Log

Trades exist only in memory per pipeline run. If the process restarts, all trade history is lost.

**Fix:** Wire the existing PostgreSQL schema (`infrastructure/postgres/init.sql` already defines `orders`, `agent_decisions`, `portfolio_snapshots` tables) to the engine. The schema is ready — the connection just isn't wired.

**Steps:**
1. Add `asyncpg` to requirements
2. Create `engine/database/connection.py` with connection pool
3. Insert into `orders` table after every trade decision
4. Insert into `agent_decisions` after every pipeline run
5. Snapshot portfolio to `portfolio_snapshots` every 30 minutes

### 3.3 Portfolio Endpoint Returns Mock Data

`GET /portfolio` (main.py ~line 404) returns approximate equity and margin. It doesn't pull from IBKR or any persistent store.

**Fix:** When IB Gateway is connected, pull real positions via `ib_async`. When disconnected, pull from the last `portfolio_snapshots` row in Postgres.

### 3.4 Schwab Connector Is 60% Complete

`schwab_connector.py` (512 lines) has OAuth flow partially implemented but isn't wired to the order router.

**Recommendation:** Either complete it or remove it. Dead code in a trading system is dangerous — someone might think it works and try to route orders through it.

### 3.5 No WebSocket Streaming

The dashboard polls via SWR (5s intervals). For a trading system, this introduces up to 5 seconds of latency on critical events (kill switch activation, order fills, circuit breaker trips).

**Fix:** Add a FastAPI WebSocket endpoint (`/ws/events`) that pushes:
- Order fills (immediate)
- Kill switch state changes (immediate)
- Circuit breaker warnings (immediate)
- Pipeline completion (when done)

Dashboard subscribes on mount, falls back to SWR polling if WS disconnects.

### 3.6 Inconsistent API Response Schemas

Some endpoints return custom dicts, others use dataclass `.to_dict()`. No versioning strategy.

**Fix:**
1. Define Pydantic response models for every endpoint
2. Add `/v1/` prefix to all routes
3. Use `response_model=` parameter in FastAPI route decorators for automatic validation

### 3.7 No Pydantic Validation on Agent Outputs

Analyst reports flow downstream without type checking. If an agent returns malformed JSON, the pipeline may silently produce garbage.

**Fix:** Add Pydantic validators on all inter-agent data contracts (AnalystReport, DebateResult, TradeDecision, RiskDecision, FundDecision). Reject and log any report that fails validation.

---

## PRIORITY 4: DASHBOARD IMPROVEMENTS

### 4.1 Missing Production Trading Features

The dashboard is a monitoring tool, not a trading control panel. For paper trading to be meaningful, it needs:

| Feature | Priority | Effort |
|---------|----------|--------|
| **Order entry panel** — manual override to place/cancel orders | High | 2–3 days |
| **Pending orders display** — show open orders with modify/cancel | High | 1–2 days |
| **Real-time toast notifications** — circuit breakers, fills, kill switch | High | 1 day |
| **Sound alerts** — audible notification on trade signals | Medium | 0.5 days |
| **Strategy parameter adjustment** — STC thresholds, ATR multipliers | Medium | 1–2 days |
| **Trade statistics dashboard** — win rate by hour, by day, by symbol | Medium | 2–3 days |
| **Account switching** — paper vs. live toggle with visual indicator | Low | 1 day |
| **Dark/light mode toggle** | Low | 0.5 days |
| **Keyboard shortcuts** — kill switch hotkey, quick analysis | Low | 1 day |

### 4.2 Performance Optimizations

Several components re-compute on every render:

| Component | Issue | Fix |
|-----------|-------|-----|
| `DailyPnlPanel` | `[...rows].reverse()` on every render | Wrap in `useMemo` |
| `AgentFeed` | `decisions.map()` without memoization | Wrap in `useMemo` |
| `Backtest page` | `backtestResults.map()` unmemoized | Wrap in `useMemo` |
| `Analysis page` | `JSON.stringify()` on every render | Cache expanded state differently |

### 4.3 Accessibility Gaps

| Issue | Severity | Fix |
|-------|----------|-----|
| Color-only P&L indicators (red/green) | High | Add icons or patterns alongside color |
| `div` with `onClick` instead of `<button>` | High | Replace with semantic HTML |
| Missing `aria-label` on status indicators | Medium | Add labels |
| Weak focus indicators (2px) | Medium | Increase to 3px with high-contrast ring |
| Small fonts (text-[10px]) on mobile | Low | Minimum 12px for touch targets |

### 4.4 KillSwitch Has No Error Feedback

The KillSwitch component catches POST errors with `console.error` but shows nothing to the user. If the kill switch fails to activate, the trader won't know.

**Fix:** Add error state with red toast/modal: "KILL SWITCH FAILED — Check engine connection."

### 4.5 PerformancePanel Always Receives Null

`page.tsx` passes `metrics={null}` and `equityCurve={[]}` to PerformancePanel. It's never populated.

**Fix:** Either wire it to real data from `/portfolio/history/equity-curve` or remove the component to avoid false confidence.

### 4.6 Type Safety Improvements

| Location | Issue | Fix |
|----------|-------|-----|
| `AgentFeed.tsx:217` | `stage as Record<string, unknown>` unsafe cast | Define `PipelineStage` interface |
| `page.tsx:83` | `lastResult: Record<string, unknown>` | Use `PipelineResult` from api.ts |
| Backtest page:217 | `result[key as keyof PipelineResult]` | Add proper type guards |

---

## PRIORITY 5: STRATEGY & BACKTEST ENHANCEMENTS

### 5.1 Optimizer Overfitting Risk

The optimizer reports 90% win rate and PF 26.20. The SUMMARY.md correctly flags this as an upper bound — good judgment. But there's no walk-forward validation on the optimized parameters.

**Recommendation:**
1. Split data into 3 periods: train (2024-06 to 2025-03), validate (2025-04 to 2025-09), test (2025-10 to 2026-03)
2. Optimize on train, select on validate, report on test
3. If the test period Sharpe drops >50% from train, the parameters are overfit

### 5.2 No Monte Carlo Analysis

The backtest runs one path through historical data. It doesn't test what happens if trade order changes, if fills are delayed, or if slippage varies.

**Fix:** Add `engine/backtest/monte_carlo.py`:
- Shuffle trade order (randomize entry sequence)
- Add random slippage (0–2 ticks per trade)
- Run 1,000 simulations
- Report 5th/25th/50th/75th/95th percentile outcomes
- If 5th percentile is still profitable, the edge is robust

### 5.3 No Regime-Specific Performance Breakdown

The backtest reports aggregate stats. It doesn't show how the strategy performs in each regime (trending, ranging, high-vol, low-vol).

**Fix:** Tag each trade with the regime filter state at entry time, then report performance per regime. This reveals whether the edge comes from one regime or is distributed.

### 5.4 Missing Walk-Forward Backtest

`run_backtest.py` runs a single in-sample test. A proper walk-forward test:
1. Train on 6 months, test on next 2 months
2. Roll forward: train on months 3–8, test on 9–10
3. Repeat until end of data
4. Concatenate all out-of-sample periods for true OOS performance

The infrastructure for this exists in `backtest/` but isn't wired to a single command.

### 5.5 Liberation Day Lesson Not Codified

The April 2025 stress test revealed that 9 consecutive stops during high-VIX regimes should trigger position sizing reduction. This wisdom is in SUMMARY.md but not in code.

**Fix:** Add a "consecutive loss counter" to the safety layer:
- After 3 consecutive stops: reduce position size to 50%
- After 5 consecutive stops: reduce to 25%
- After 7 consecutive stops: pause trading for 24 hours
- Reset counter on first winner

---

## PRIORITY 6: INFRASTRUCTURE & OPERATIONS

### 6.1 PostgreSQL Schema Ready But Not Connected

The `init.sql` schema is excellent (6 tables, proper indexes, JSONB for flexible data). But the engine doesn't connect to it — everything runs in-memory or SQLite.

**Fix:** This is the single highest-leverage infrastructure task. Wire Postgres and you get:
- Persistent trade history across restarts
- Proper audit trail for every agent decision
- Portfolio snapshots for equity curve reconstruction
- Safety event logging for post-incident review

### 6.2 No Metrics Export (Prometheus/Grafana)

Grafana is in docker-compose but has no data source configured. The engine doesn't export metrics.

**Fix:**
1. Add `prometheus-fastapi-instrumentator` to engine
2. Export: pipeline latency, LLM call count/cost, order count, P&L, safety events
3. Configure Grafana to scrape Prometheus
4. Create 3 dashboards: System Health, Trading Performance, LLM Cost

### 6.3 QuestDB Not Utilized

QuestDB is in docker-compose (ports 9000, 9009, 8812) but nothing writes to it.

**Intended use:** High-frequency tick data storage. If you're running 30-min pipeline cycles on futures, QuestDB is overkill. It becomes valuable when you move to sub-minute signal generation.

**Recommendation:** Keep it in docker-compose but mark as "Phase 2" — activate when latency requirements tighten.

### 6.4 Redis Not Utilized

Redis is configured but unused.

**Best use cases for JARVIS:**
- Signal cache (avoid re-running pipeline if regime hasn't changed)
- Rate limit tracking (per-symbol alert cooldown — currently in-memory)
- Feature store (pre-computed indicators for fast lookup)
- Pub/sub for WebSocket events (when you add WS streaming)

### 6.5 start_jarvis.bat Has No Error Handling

The batch file launches 4 processes but doesn't check if any fail. If the engine crashes on startup, the dashboard opens to a dead backend.

**Fix:** Add health check polling after engine launch:
```bat
:wait_engine
curl -s http://localhost:8010/health >nul 2>&1
if errorlevel 1 (
    timeout /t 2 >nul
    goto wait_engine
)
echo Engine is UP
```

### 6.6 No Log Rotation

The health monitor writes to `engine/logs/health.log` continuously. Over weeks, this will grow unbounded.

**Fix:** Use Python's `RotatingFileHandler` with 10MB max size, 5 backup files.

---

## PRIORITY 7: CODE HYGIENE

### 7.1 Remove the 1.8GB OllamaSetup.exe

`OllamaSetup.exe` (1.8 GB) is sitting in the project root. Even if gitignored, it's dead weight. Delete it.

### 7.2 Remove the NUL File

`NUL` (145 bytes) in the project root is a Windows artifact (likely from a redirected output). Delete it.

### 7.3 Consolidate Documentation

There are 5 overlapping docs in the root: `README.md`, `SUMMARY.md`, `SESSION_NOTES.md`, `TOS_SCRIPT_ANALYSIS.md`, `Jarvis_Trader_Agent_Master_Claude_Code_Session.md`. Some information is repeated across them.

**Recommendation:**
- `README.md` — Keep as quick-start only (current state is good)
- `SUMMARY.md` — Keep as backtest results reference
- Move `SESSION_NOTES.md` content into git commit history and delete
- Keep `TOS_SCRIPT_ANALYSIS.md` as reference
- Archive the 142KB master session doc — it was a working document, not a reference

### 7.4 Add Type Checking

No `mypy` or `pyright` configuration exists. Add `pyproject.toml` with strict type checking for the engine.

### 7.5 Add Linting

No `ruff` or `flake8` configuration. Add `ruff.toml` with trading-appropriate rules (ban `print()` in production code, require type hints, enforce import sorting).

---

## RECOMMENDED IMPLEMENTATION ORDER

### Phase 1: Security & Stability (This Week)
1. Revoke all exposed API keys
2. Scrub git history
3. Add API key auth to safety endpoints
4. Wire PostgreSQL for persistent trade logging
5. Delete OllamaSetup.exe and NUL

### Phase 2: Testing & Confidence (Week 2)
6. Write agent unit tests (SafetyLayer first, then Pipeline)
7. Create repeatable E2E smoke test
8. Add LLM retry logic and cost tracking
9. Add CI/CD pipeline (GitHub Actions)

### Phase 3: Dashboard Trading Controls (Week 3)
10. Add toast notification system
11. Fix KillSwitch error handling
12. Add WebSocket streaming for critical events
13. Wire PerformancePanel to real data
14. Add order entry panel

### Phase 4: Strategy Hardening (Week 4)
15. Walk-forward validation on optimizer params
16. Monte Carlo simulation
17. Consecutive loss counter in SafetyLayer
18. Regime-specific performance breakdown

### Phase 5: Paper Trading (Weeks 5–10)
19. Install IB Gateway (paper account)
20. Wire `ibapi` order routing for MES
21. 30-day forward test (target: April–May 2026)
22. Confirm WhatsApp alert fires on real signal
23. Review results, adjust parameters if needed

### Phase 6: Live Preparation (Post Paper Trading)
24. Open IB account with futures permissions
25. Complete live trading readiness checklist from SUMMARY.md
26. Switch IB Gateway from paper (7497) to live (7496)
27. Start at minimum size: 1 MES contract per signal

---

## Architecture Diagram (Current State)

```
┌─────────────────────────────────────────────────────────────────┐
│                     JARVIS TRADER SYSTEM                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐     ┌──────────────┐     ┌───────────────┐   │
│  │  TOS Charts  │     │  Dashboard   │     │  WhatsApp     │   │
│  │  (Visual)    │     │  Next.js     │     │  (Twilio)     │   │
│  │  Port: N/A   │     │  Port: 3010  │     │  Alerts       │   │
│  └──────────────┘     └──────┬───────┘     └───────┬───────┘   │
│                              │ SWR 5s poll          │           │
│  ┌───────────────────────────┴──────────────────────┴────────┐  │
│  │                    FastAPI ENGINE (port 8010)              │  │
│  │  ┌─────────────────────────────────────────────────────┐  │  │
│  │  │  STAGE 1: Analysts (parallel asyncio.gather)        │  │  │
│  │  │  Technical │ News │ Social │ Fundamental             │  │  │
│  │  └─────────────────────┬───────────────────────────────┘  │  │
│  │  ┌─────────────────────┴───────────────────────────────┐  │  │
│  │  │  STAGE 2: Debate                                    │  │  │
│  │  │  Bull Researcher ↔ Bear Researcher → Orchestrator   │  │  │
│  │  └─────────────────────┬───────────────────────────────┘  │  │
│  │  ┌─────────────────────┴───────────────────────────────┐  │  │
│  │  │  STAGE 3: Trade Decision (Opus)                     │  │  │
│  │  │  BUY / SELL / HOLD + confidence + stop/target       │  │  │
│  │  └─────────────────────┬───────────────────────────────┘  │  │
│  │  ┌─────────────────────┴───────────────────────────────┐  │  │
│  │  │  STAGE 4: Risk Review (2-layer)                     │  │  │
│  │  │  Layer 1: Python hard rules (SafetyLayer)           │  │  │
│  │  │  Layer 2: LLM soft review (Opus)                    │  │  │
│  │  └─────────────────────┬───────────────────────────────┘  │  │
│  │  ┌─────────────────────┴───────────────────────────────┐  │  │
│  │  │  STAGE 5: Fund Manager Approval (Opus)              │  │  │
│  │  │  approve / wait_for_pullback / skip                 │  │  │
│  │  └─────────────────────┬───────────────────────────────┘  │  │
│  │                        │                                   │  │
│  │  ┌─────────────────────┴───────────────────────────────┐  │  │
│  │  │  EXECUTION: Order Router → IBKR (paper 7497)        │  │  │
│  │  └────────────────────────────────────────────────────-┘  │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌─────────────┐  ┌──────────┐  ┌──────────┐  ┌────────────┐   │
│  │ PostgreSQL  │  │  Redis   │  │ QuestDB  │  │  Grafana   │   │
│  │ (trades)    │  │  (cache) │  │  (ticks) │  │ (monitor)  │   │
│  │ NOT WIRED   │  │ NOT USED │  │ NOT USED │  │ NO SOURCE  │   │
│  └─────────────┘  └──────────┘  └──────────┘  └────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

---

## What's Already Great

Let me be clear about what's working, because the instinct after a 30-finding audit is to feel like everything's broken. It's not.

**The 5-stage pipeline architecture is genuinely excellent.** The separation of analysts → debate → decision → risk → approval mirrors how a real trading desk operates. The parallel analyst execution with `asyncio.gather` and graceful degradation on individual failures is exactly right.

**The safety layer is the best part of this codebase.** Hardcoded Python, no LLM reasoning, non-reversible kill switch, multiple circuit breakers — this is how you protect capital. The fact that it runs *before* any LLM agent touches the decision is critical. Don't change this pattern.

**The agent prompts are professional-grade.** "Do not waffle" for the Trader, "missed gains are recoverable, large losses are not" for Risk Manager, "voice of discipline" for Fund Manager — these framings create the right incentive structure for LLM decision-making.

**The backtest results are encouraging.** Positive PF and Sharpe across both in-sample (2024) and out-of-sample (2025, an adversarial year). The MES 1h result (PF 5.27, +47.2%) on real ES=F data is the strongest signal. The strategy surviving 9 consecutive stops in 2025 and still finishing positive is exactly what you want to see from a trend-following system.

**The TOS script library is comprehensive.** 21 unique scripts covering all 5 layers, with a proper integration guide mapping every parameter to the engine. This is the kind of domain knowledge that makes the system defensible.

---

*JARVIS TRADER — System ready for security remediation, then paper trading.*
*The edge is real. The infrastructure needs hardening. The path is clear.*
