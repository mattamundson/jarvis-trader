# JARVIS TRADER — Paper Trading Readiness Checklist
**Date**: 2026-04-03 | **Basis**: 3-agent direct codebase verification
**Target**: 30-day forward validation (MCL + MNQ, 1h, April–May 2026)
**Gates**: PF >= 2.0, Sharpe >= 1.5, WR >= 55%, Trades >= 60, DD <= 15%, Days >= 30

---

## Critical Path to First Real Paper Trade

```
[1] ~~Mount approval_router in main.py~~       DONE — mounted at main.py line 1000
    ↓
[2] ~~Build scheduled pipeline execution~~     DONE — SignalScanner at engine/scanner/signal_scanner.py
    ↓
[3] Rotate exposed API keys                    [1 hour — external action]
    ↓
[4] Add Polygon.io API key for data            [5 minutes — external action]
    ↓
[5] Wire IB connector to real paper account    [2-4 hours — setup + code]
    ↓
[6] Run first real pipeline → approval → trade  [30 minutes — smoke test]
```

Items 3-4 can be done TODAY. Item 5 is the path to genuine broker execution.

---

## Status Key

| Symbol | Meaning |
|--------|---------|
| DONE | Verified working by agent code inspection |
| PARTIAL | Code exists but has known gap(s) |
| BLOCKED | Cannot proceed until dependency resolved |
| NOT STARTED | Work not yet begun |

---

## I. Pipeline Signal Generation

| Prerequisite | Status | File(s) | Notes |
|-------------|--------|---------|-------|
| STC oscillator computes correctly | **DONE** | `backtest/signals.py` (683 lines) | OS=15, OB=83, per-instrument params |
| 5-layer regime filter executes | **DONE** | `backtest/signals.py` | Regime Map + Structure Map + Bias + Entry Timing + Risk Gate |
| Per-instrument parameters set | **DONE** | `backtest/signals.py` | MCL (OS=15, Stop=0.90x), MNQ (OS=15, Stop=0.70x) |
| 5-stage LLM pipeline runs end-to-end | **DONE** | `agents/pipeline.py` (741 lines) | All 5 stages wired with graceful degradation |
| Pipeline produces TradeDecision | **DONE** | `agents/pipeline.py:analyze_and_decide()` | Returns final_action, entry_price, stop, target |
| Pipeline auto-logs decisions | **DONE** | `routers/pipeline_router.py:_run_pipeline_and_log()` | Lines 273-408 — routes to approval or auto-log |

---

## II. Human Approval Flow

| Prerequisite | Status | File(s) | Notes |
|-------------|--------|---------|-------|
| `requires_human` flag enforced in pipeline | **DONE** | `routers/pipeline_router.py` lines 295-336 | Queues pending approval when True |
| Pending approvals database table | **DONE** | `database/migrations.py` migration 008 | `pending_trade_approvals` with 11 columns |
| Database CRUD mixin | **DONE** | `database/_mixins_pending_approvals.py` (147 lines) | insert/list/get/resolve with thread-safe locking |
| Approval backend API endpoints | **DONE** | `routers/approval_router.py` (169 lines) | GET /pending-approvals, POST /{id}/approve, POST /{id}/reject |
| Approval serializer | **DONE** | `approval/snapshot.py` (56 lines) | pipeline_result_for_approval_snapshot() |
| Dashboard ApprovalPanel component | **DONE** | `dashboard/components/ApprovalPanel.tsx` (206 lines) | SWR polling every 5s, approve/reject buttons |
| Dashboard API types and helpers | **DONE** | `dashboard/lib/api.ts` | PendingApproval, getPendingApprovals(), postApprovePending() |
| ApprovalPanel mounted on command-center | **DONE** | `dashboard/app/command-center/page.tsx` line 486 | Component rendered in page |
| Approval tests | **DONE** | `engine/tests/test_approvals.py` (723 lines) | 7 classes, 25+ test cases |
| **approval_router mounted in main.py** | **DONE** | `engine/main.py` lines 106, 745, 1000 | Imported at line 106, inject_approval_deps() at line 745, include_router() at line 1000 |

**Bottom line**: The approval flow is fully wired and operational.

---

## III. Paper Trade Recording

| Prerequisite | Status | File(s) | Notes |
|-------------|--------|---------|-------|
| Portfolio tracker ledger (JSONL) | **DONE** | `portfolio/tracker.py` (704 lines) | Dual persistence JSONL + SQLite |
| Paper trade database table | **DONE** | `database/schema.py` | `paper_trades` table with full schema |
| Auto-log paper trades from pipeline | **DONE** (when requires_human=False) | `routers/pipeline_router.py` lines 338-393 | Calls `paper_tracker.add_paper_trade()` |
| Manual paper trade entry endpoint | **DONE** | `routers/portfolio_router.py` | POST /portfolio/paper/trade |
| Paper trade P&L calculation | **DONE** | `portfolio/tracker.py` | Fixed-fractional, ATR-based, instrument multipliers |
| Paper positions dashboard widget | **DONE** | `dashboard/components/PaperTradingPanel.tsx` | Lists open positions, close button |
| Paper performance dashboard widget | **DONE** | Multiple dashboard components | P&L, win rate, Sharpe |

---

## IV. Broker Execution (IB Gateway)

| Prerequisite | Status | File(s) | Notes |
|-------------|--------|---------|-------|
| IB Gateway library (ib_async) integrated | **DONE** | `execution/ib_gateway.py` (873 lines) | Full order types, reconnect with backoff |
| Port 4001 (live) permanently blocked | **DONE** | `execution/ib_gateway.py` | Triple-layer enforcement at config + connect time |
| IB Gateway connector code | **PARTIAL** | `execution/ib_gateway_connector.py` | "Live connection NOT YET IMPLEMENTED" — simulation layer only |
| Real IB paper account connection | **NOT STARTED** | Runtime | Requires IB TWS/Gateway running at localhost:4002 |
| IB account ID configured in .env | **NOT STARTED** | `engine/.env` | Need IB_ACCOUNT_ID=DU[paper_account_id] |
| OrderRouter wired to pipeline | **NOT STARTED** | `execution/order_router.py` | `route_order()` defined but never called from production code |
| Pipeline → IB paper account order submission | **NOT STARTED** | `execution/ib_gateway.py` | `place_paper_order()` exists but not called from pipeline |

**What this means**: Paper trades are currently logged to the JARVIS ledger only. No orders are submitted to IB Gateway. The +$7 smoke trades from April 2 were simulated fills (random slippage), not real IB paper account executions.

**IB Setup Steps** (30-minute task):
1. Log into IBKR and create/access paper trading account
2. Download IB Gateway 1045 (already installed at `C:\Jts\ibgateway\1045\ibgateway.exe`)
3. Enable Socket API: File > Global Configuration > API > Enable ActiveX and Socket Clients
4. Set API port to 4002
5. Add to `engine/.env`: `IB_ACCOUNT_ID=DU[your_paper_account_id]`
6. Run `.\restart_engine.ps1`

---

## V. Signal Automation

| Prerequisite | Status | File(s) | Notes |
|-------------|--------|---------|-------|
| Manual pipeline trigger works | **DONE** | POST /pipeline/run | Executes all 5 stages |
| TradingView webhook trigger works | **DONE** | `routers/webhook_router.py` | Accepts TOS Pine Script webhook |
| Scheduled pipeline execution | **DONE** | `scanner/signal_scanner.py` (247 lines) | SignalScanner mounted in main.py lines 751-758; scans MCL/MNQ every 60 min during futures hours |
| Morning signal scan (9:31 ET) | **DONE** | `scanner/signal_scanner.py` | market_open_scan job runs at 9:31 ET |
| RTH-only signal gating | **NOT STARTED** | `agents/pipeline.py` | No session timing enforcement |
| Session timing filter (no entry first 5min/last 15min) | **NOT STARTED** | `agents/pipeline.py` | Documented rule, not coded |

**CORRECTION (2026-04-03)**: SignalScanner provides automated scanning. Manual triggering is still available but is no longer the only option.

---

## VI. Safety Controls

| Prerequisite | Status | File(s) | Notes |
|-------------|--------|---------|-------|
| Kill switch functional | **DONE** | `risk/safety_layer.py` | All 25+ tests pass |
| Daily loss halt (-2%) | **DONE** | `risk/safety_layer.py` | Hardcoded, tested |
| Drawdown halt (-10%) | **DONE** | `risk/safety_layer.py` | Hardcoded, tested |
| Max 2 contracts per instrument | **DONE** | `config.py` + `safety_layer.py` | Code-enforced |
| LIVE_TRADING_ENABLED=False | **DONE** | `config.py` | Startup check fails if True |
| REQUIRE_HUMAN_APPROVAL=True | **DONE** | `config.py` + `pipeline_router.py` | Enforced at Stage 5 output |
| Port 4001 blocked | **DONE** | `execution/ib_gateway.py` | Triple-layer, tested |
| Overnight max 1 contract | PARTIAL | `config.py` | Config defined; not code-enforced in runtime checks |
| Session timing enforcement | **NOT STARTED** | None | Documented, not coded |
| Correlated exposure check (20%) | PARTIAL | `config.py` | Config limit; no multi-position aggregation logic |

---

## VII. Data Infrastructure

| Prerequisite | Status | Notes |
|-------------|--------|-------|
| IB Gateway market data feed | **DONE** (when connected) | Primary data source |
| Polygon.io API key | **NOT STARTED** | Placeholder in .env — needed for data fallback |
| Finnhub API key | **NOT STARTED** | Placeholder in .env — news data |
| FRED macro data | **DONE** | CSV download, no key needed |
| Data waterfall (IBKR → Polygon → CSV cache) | **DONE** | Graceful degradation, no silent zeros |
| Paper validation data cleared and reset | **NOT STARTED** | `data/paper_validation.json` contains synthetic test data |

---

## VIII. Security

| Prerequisite | Status | Notes |
|-------------|--------|-------|
| Rotate Anthropic API key | **NOT STARTED** | Exposed in git history — ACTIVE key at risk |
| Rotate Polygon API key | **NOT STARTED** | Exposed in git history |
| Rotate Twilio credentials | **NOT STARTED** | Account SID + Auth Token exposed |
| Revoke Google OAuth credentials | **NOT STARTED** | client_secret in committed code |
| Change default API_KEY | **NOT STARTED** | `jarvis-dev-key-change-me` still in use |
| BFG Repo-Cleaner or git filter-repo | **NOT STARTED** | Required to purge keys from git history |

**This is a P0 security issue. Must be resolved before any live trading and before sharing the repository with anyone.**

---

## IX. Dashboard

| Prerequisite | Status | File(s) | Notes |
|-------------|--------|---------|-------|
| Build passes with 0 TypeScript errors | **DONE** | `dashboard/` | All 26 routes build cleanly |
| Safety system widgets functional | **DONE** | Multiple components | Kill switch, circuit breakers — real SafetyLayer data |
| Paper trading panel functional | **DONE** | `PaperTradingPanel.tsx` | Open/close positions, P&L display |
| Approval panel accessible | **DONE** | `ApprovalPanel.tsx` | Component built; approval_router mounted at main.py line 1000 |
| Portfolio summary widget | PARTIAL | `dashboard/components/` | MultiMarketOrchestrator not wired → returns zeros |
| Command center portfolio data | PARTIAL | `dashboard/app/command-center/page.tsx` | Some instrument data hardcoded |

---

## Summary: Day 2 Paper Trading Reality Check

### What CAN happen today (CORRECTED — as of 2026-04-03):
- SignalScanner fires automatically during futures hours → pipeline runs → signal generated → queued for human approval → ApprovalPanel shows it → Matt clicks Approve → paper trade auto-logged to JARVIS ledger (NOT sent to IB broker)

### What CAN also happen manually:
- Matt runs pipeline via POST /pipeline/run → same flow as above

### What WILL happen after full wiring:
- Scheduled scanner fires at 9:35 CT → pipeline runs → signal generated → queued → Matt approves → ORDER sent to IB paper account → real fill received → position tracked with real entry price

---

## Readiness Score

| Category | Score | Blocker |
|----------|-------|---------|
| Pipeline signal generation | 9/10 | Session timing enforcement not yet coded |
| Human approval flow | 9/10 | CORRECTED: approval_router is mounted and operational |
| Paper trade recording | 8/10 | Works for ledger; not wired to broker |
| Broker execution | 2/10 | Simulation-only; real IB connection NOT implemented |
| Signal automation | 8/10 | CORRECTED: SignalScanner scans MCL/MNQ every 60 min |
| Safety controls | 9/10 | Missing session timing enforcement |
| Data infrastructure | 6/10 | Missing Polygon + Finnhub keys |
| Security | 2/10 | API keys exposed in git history |
| Dashboard | 9/10 | CORRECTED: Approval panel is accessible via mounted router |

**Overall paper trading readiness: ~7.5/10**

The system is substantially more ready than previously assessed. Two of the largest blockers (approval_router, signal scanner) were already implemented. The primary remaining gap is wiring the IB Gateway connector to a real paper account for genuine broker execution rather than simulated fills.

---

*Checklist generated from direct agent code inspection. All statuses verified against actual files.*
*Target date for paper trading readiness: April 4-5, 2026 (with focused execution on blockers above).*
