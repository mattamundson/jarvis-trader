# JARVIS TRADER — Strategic Assessment
**Date**: 2026-04-02 (updated 2026-04-03) | **Method**: 3-agent parallel deep dive, ~250+ files, ~110K LOC
**Classification**: Internal working document — honest assessment for decision-making

---

## Executive Summary

The core trading strategy (STC+ATR+5-Layer Regime) is well-defined, backtested, and coded. Risk controls are best-in-class. The safety layer is bulletproof. **The problem is the execution path: signals do not flow to orders, positions are not tracked in real-time, and the "paper trading" clock is running on synthetic test data.** The 30-day validation has not meaningfully started.

This document provides an honest current state assessment based on direct code inspection — not documentation claims.

---

## I. CURRENT STATE MATRIX

### A. Engine Core — What's Real

| Component | File | Lines | Real % | Notes |
|-----------|------|-------|--------|-------|
| Signal generation | `backtest/signals.py` | 683 | **95%** | 4-layer framework, per-instrument params, fully coded |
| Config/risk params | `config.py` | 296 | **100%** | Pydantic v2, validated, conservative limits |
| 5-stage pipeline | `agents/pipeline.py` | 741 | **90%** | All 5 stages wired, graceful degradation |
| Technical analyst | `agents/technical_analyst.py` | 516 | **85%** | LLM + 20+ indicators via pandas_ta |
| Trader agent | `agents/trader.py` | 385 | **90%** | Claude Opus, position sizing, hard HOLD on kill switch |
| Risk manager | `agents/risk_manager.py` | 356 | **90%** | Two-layer: hard Python rules + soft LLM review |
| Fund manager | `agents/fund_manager.py` | 388 | **90%** | Portfolio-level LLM + human approval gate |
| Debate orchestrator | `agents/debate.py` | 243 | **95%** | Multi-round adversarial, conviction scoring |
| Safety layer | `risk/safety_layer.py` | 889 | **100%** | 25/25 tests, kill switch, 6 pre-trade gates |
| IB Gateway | `execution/ib_gateway.py` | 873 | **95%** | Port 4001 blocked at 3 levels, reconnect, full order types |
| Portfolio tracker | `portfolio/tracker.py` | 704 | **95%** | JSONL+SQLite dual persistence, proper P&L math |
| Position sizing | `utils/position_sizing.py` | ~200 | **100%** | Fixed-fractional, ATR-based, tested |
| EOD scheduler | `schedulers/eod_scheduler.py` | 581 | **90%** | 4 APScheduler jobs, WhatsApp integration |
| Order router | `execution/order_router.py` | 108 | **80%** | Functional but thin — no retry, no resilience |

### B. Dashboard — What's Real

| Component | Status | Notes |
|-----------|--------|-------|
| API proxy layer (`lib/api.ts`) | **FUNCTIONAL** | 30s timeout, retry, API key injection |
| Safety system widgets | **FULLY FUNCTIONAL** | Kill switch, circuit breakers — backed by real SafetyLayer |
| Paper trading (positions/trades) | **FUNCTIONAL** | SQLite-backed, open/close/performance works |
| Portfolio summary | **PLACEHOLDER** | Returns zeroed fallback — MultiMarketOrchestrator not wired |
| Backtest viewer | **FUNCTIONAL** | Reads saved JSON results from disk |
| RL strategies | **FUNCTIONAL** | Full train/deploy/evaluate pipeline |
| Command center | **PARTIAL** | Health/safety real; portfolio zeros; instrument data hardcoded |
| ~80+ components | **BYPASS VIOLATION** | Hardcode `localhost:8010` instead of using `fetchEngine` |

### C. What the Documentation Claims vs Reality

| Documentation Claim | Reality |
|--------------------|---------|
| "Paper trading ACTIVE for MCL/MNQ" | `paper_validation.json` has 5 synthetic trades (prices: 100.0, 105.0). Zero real fills. |
| "Multi-market framework complete" | `markets/orchestrator.py` **does not exist on disk** |
| "90+ API endpoints working" | Many return fallback/empty (portfolio zeros, options needs IBKR, macro needs FRED key) |
| "30-day validation started Day 1" | Validation data is test seed data. Clock is fictional. |
| "All 25 routers functional" | 35 router files found; many return fallback data or are conditionally disabled |
| "1073 passing tests" | True, but 36 are pre-existing failures; backtester/walk_forward/monte_carlo have ZERO tests |
| "Dashboard 22 pages" | 22 confirmed pages, but `/stats` is a 16-line stub |

---

## II. STRATEGY DEFINITION STATUS

### Fully Defined ✅

- **Entry signals**: STC crosses above OS=15 (LONG) or below OB=83 (SHORT)
- **Stop placement**: Entry ± (0.70 × ATR) — per instrument, hardcoded in signals.py
- **Target T1**: Entry ± (1.50 × ATR) — R:R of 2.14:1 (breakeven at 32% win rate)
- **Regime filter**: 5 layers must align — trend, momentum, volatility, structure, volume
- **Per-instrument parameters**: MES, MNQ, MCL, MGC, SPY all researched and documented
- **Risk limits**: Max position 5%, daily loss -2%, drawdown -10%, max 2 contracts — hardcoded

### Not Defined / Not Enforced ❌

| Rule | Status | Impact |
|------|--------|--------|
| Trade management (breakeven stop, partial exit) | Not defined | Unknown P&L behavior between entry and T1 |
| Session timing filter (no entries first 5min/last 15min RTH) | Documented but NOT enforced in code | Pipeline will signal during banned windows |
| Overnight handling (max 1 contract) | Documented but NOT enforced in code | Could hold 2+ overnight |
| Re-entry rules (after stop-out) | Not defined | Could immediately re-enter into same losing condition |
| Multi-instrument allocation | Config limit (20% correlated) but no correlation detection logic | Could stack correlated positions |
| Scaling plan (when to go 1→2 contracts) | Not defined | Arbitrary scaling decision |
| T2/T3 targets or trailing stop | Not defined | Exit is binary: stop or T1 |

---

## III. EXECUTION PATH ANALYSIS

### Current State: BROKEN

```
Signal fires (signals.py) ✅
    ↓
LLM Pipeline (pipeline.py) ✅ — produces TradeDecision
    ↓
TradeDecision logged (decisions_router.py) ✅
    ↓
??? ORDER ROUTING GAP ???
    ↓
OrderRouter.route_order() ❌ — not called by pipeline
    ↓
IB Gateway / Schwab ❌ — not connected in production
    ↓
Fill confirmation ❌ — no fill tracking
    ↓
Position tracking (tracker.py) ❌ — only records manually-logged trades
    ↓
P&L calculation ✅ — works once positions exist
```

### The Gap

`pipeline.py` produces a `TradeDecision` object. That object is logged to the decisions table. It does NOT automatically:
1. Call `OrderRouter.route_order()` with the decision
2. Submit to IB Gateway or Schwab
3. Receive a fill confirmation
4. Record the fill in `PortfolioTracker`

The scheduler (`eod_scheduler.py`) can trigger a pipeline run but the result is not wired to execution.

The WhatsApp alert fires (via Twilio) when a non-HOLD signal is generated. But the alert is for human action — the human is supposed to manually log the paper trade. This is the current "paper trading" workflow: LLM decides, WhatsApp alerts, Matt manually logs.

### What "Paper Trading" Actually Means Right Now

1. Scheduler fires pipeline run
2. Pipeline produces TradeDecision (LONG/SHORT/HOLD)
3. WhatsApp alert sent to Matt's phone
4. Matt manually decides whether to log it as a paper trade via the dashboard UI
5. Dashboard POST to `/portfolio/paper/trade`
6. PortfolioTracker records the trade in SQLite

**This is manual paper trading, not automated paper trading.** The "automation" is the alert — the execution is manual. For the 30-day validation to produce meaningful data, this workflow must be followed consistently every time the system signals.

---

## IV. GAP ANALYSIS — By Severity

### CRITICAL (Blocks Paper Trading Validity)

| Gap | File(s) | Fix Complexity |
|-----|---------|---------------|
| No real paper trades in system (only synthetic test data) | `data/paper_validation.json` | Low — clear and start fresh |
| Pipeline decisions not auto-logged to paper tracker | `pipeline.py`, `tracker.py` | Medium |
| Session timing not enforced (first 5min/last 15min RTH) | `pipeline.py` | Low |
| IB Gateway not connected to paper account | `config.py`, runtime | Low (requires IB TWS running) |
| Paper validation clock "started" on synthetic data | Documentation | Low (reset the clock) |

### HIGH (Degrades System Quality)

| Gap | File(s) | Fix Complexity |
|-----|---------|---------------|
| MultiMarketOrchestrator not wired into lifespan | `main.py` | Medium |
| ~80+ dashboard components bypass fetchEngine | `dashboard/components/` | High (many files) |
| Duplicate RL routes (`/strategies/rl/*` + `/rl/*`) | `routers/` | Low |
| Scheduler-to-execution path incomplete | `eod_scheduler.py`, `pipeline.py` | Medium |
| Portfolio returns zeroed fallback data | `portfolio_router.py` | Medium (depends on orchestrator) |

### MEDIUM (Technical Debt)

| Gap | File(s) | Fix Complexity |
|-----|---------|---------------|
| Backtester/walk_forward/monte_carlo — zero tests | `engine/tests/` | High (new test files needed) |
| Code coverage never measured | `pytest.ini` | Low (run pytest-cov once) |
| Oversized files: schema.py (1,528), backtester.py (955) | `database/`, `backtest/` | High (split files) |
| `datetime.utcnow()` deprecated in Python 3.12 | Multiple files | Medium |
| `/stats` page is a 16-line stub | `dashboard/app/stats/` | Low |

### LOW (Nice to Have)

| Gap | Fix |
|-----|-----|
| README.md outdated | Update docs |
| Two "audit" docs are raw session dumps | Clean up |
| Command center instrument data is hardcoded | Fetch from engine |
| Multiple conflicting "source of truth" documents | Consolidate |

---

## V. API KEY SECURITY — P0 (ACT NOW)

**Exposed keys in git history** (not just `.env` — in committed code):
- Anthropic API key — ACTIVE, in use
- Polygon API key
- Twilio Account SID + Auth Token
- Google OAuth credentials

**Required action before any live trading:**
1. Rotate Anthropic key at console.anthropic.com
2. Revoke Polygon key and generate new one
3. Rotate Twilio credentials
4. Run BFG Repo-Cleaner or `git filter-repo` to purge from history
5. Change default `API_KEY` from `jarvis-dev-key-change-me`

**This is non-negotiable.** Exposed keys = anyone can run LLM inference on Matt's bill.

---

## VI. RL STRATEGY STATUS — SUSPEND

After 11 training runs, no MES model has passed validation gates:
- Best PF: 0.620 (gate: >= 2.0) — fails
- Best Sharpe: -1.966 (gate: >= 1.5) — fails
- Hold rate: consistently too low or too high

**Recommendation**: Suspend RL development until STC+ATR paper trading produces 60+ real trades. The RL system consumes development attention without producing tradeable results. STC+ATR on MCL (WFE 0.82) and MNQ (WFE 0.57) IS the working system.

---

## VII. WHAT TO DO NEXT (PRIORITIZED)

### Immediate (This Session)

1. **Fix critical gaps in execution path** — Wire pipeline TradeDecision to auto-log as paper trade, enforce session timing filters, connect IB Gateway to paper account
2. **Reset paper validation data** — Clear synthetic test data, start fresh with real signals
3. **Set new Day 1** — Today is the real start date

### Near-Term (Sprint 12)

1. Rotate all exposed API keys
2. Wire MultiMarketOrchestrator into lifespan
3. Fix dashboard fetchEngine violations (80+ files)
4. Define missing trading rules (session timing, re-entry, management)
5. Add session timing enforcement in code

### Medium-Term (Before Live Capital)

1. Measure code coverage (run pytest-cov)
2. Add tests for backtester, walk_forward, monte_carlo
3. Complete Schwab OAuth flow
4. Define and document T2/trailing stop logic
5. Define multi-instrument allocation rules

---

*Report generated from direct code inspection of ~250+ source files across engine/ and dashboard/.*
*Cross-referenced against: `prd.json`, `docs/CURRENT_STATE.md`, `data/paper_validation.json`, session logs.*
