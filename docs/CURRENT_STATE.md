# JARVIS TRADER — Current System State

**Status:** Paper Trading Validation | **Mode:** Paper only (IB Gateway 4002) | **Last Updated:** July 9, 2026

> **Current reality (2026-07-09):** Engine health was **not re-verified live** as part of this
> update — check `/health` before relying on this doc for live status. Approved paper instruments
> unchanged from the prior snapshot — **MES + MGC are active (Tier-3 2026-05-24); MCL + MNQ are
> HALTED (`DO_NOT_TRADE`)**.
>
> **Trade #287 stop-enforcement chain (2026-07-07/09):** PR #324 fixed two wiring bugs that let a
> trade $191.83 over the $50/ticket risk cap through with zero risk computed (merged); PR #325
> fixed an LLM-call concurrency/timeout issue in the same window (merged). The resulting "naked
> row" gap (`paper_trades.stop_loss` persisting `NULL` despite a real stop existing) surfaced three
> independent fix attempts (#326 tightened the catastrophe-cap backstop 750→300; #331 added a
> DB-level backfill preferring IB's real resting stop; #335 added a `stop_loss` parameter to
> `PortfolioTracker.open_trade()` and threaded it through each caller; #356 duplicated part of
> #335) — reconciled into one PR rather than merged separately, since they overlapped on the same
> functions/files. The reconciled fix: `open_trade()` now accepts `stop_loss` directly (root fix,
> from #335); the IB-position-reconcile path prefers a real resting IB stop and falls back to a
> synthesized one from the catastrophe-cap budget only when IB holds none (combining #331 + #335);
> `main.py`'s periodic OMS-fallback resolution now also persists the stop it finds (from #331); the
> catastrophe-cap default is $300, not $750 (from #326, applied to #335's renamed public
> `max_loss_usd_from_env`). Full writeup:
> [`docs/incident-notes/2026-07-07-trade-287-stop-enforcement-chain.md`](incident-notes/2026-07-07-trade-287-stop-enforcement-chain.md).
> For live instrument status always prefer the `/validation` scorecard over the static table below.

**See also:** [Strategic command center (index)](strategic/README.md) — executive brief, system map, risk register, execution spine, and analysis passes.

**New runbooks (2026-04-10):** [SECURITY_OPERATOR_CHECKLIST.md](runbooks/SECURITY_OPERATOR_CHECKLIST.md) · [PAPER_SOURCE_OF_TRUTH.md](runbooks/PAPER_SOURCE_OF_TRUTH.md) · [IB_RECONNECT_AND_HEALTH.md](runbooks/IB_RECONNECT_AND_HEALTH.md) · [HEALTH_API_CONTRACT.md](runbooks/HEALTH_API_CONTRACT.md) · [SQLITE_BACKUP.md](runbooks/SQLITE_BACKUP.md) · [MARKET_DATA_WATERFALL.md](runbooks/MARKET_DATA_WATERFALL.md)

**Paper ledger reconciliation (P0-2):** `python scripts/reconcile_paper_sources.py` — compares SQLite `paper_trades` vs optional `paper_runner` JSON under `engine/backtest/results/`.

---

## Architecture Overview

**5-Stage LLM Pipeline + Multi-Market Orchestrator + Safety Layer**

1. **Stage 1:** Parallel analysis (TechnicalAnalyst, NewsAnalyst, SocialAnalyst, FundamentalistAgent)
2. **Stage 2:** Debate (BullResearcher, BearResearcher, DebateOrchestrator)
3. **Stage 3:** Decision (TraderAgent)
4. **Stage 4:** Risk (RiskManagerAgent — full VETO power)
5. **Stage 5:** Approval (FundManagerAgent)

**Framework:** FastAPI + Next.js + PostgreSQL + Redis + QuestDB
**Endpoints:** 80+ routes across 24 specialized routers

---

## Approved Instruments

_Updated 2026-06-04 from `engine/CLAUDE.md` canon (Tier-3 auth 2026-05-24). Live status: `/validation`._

| Symbol | Timeframe | Edge | Status | Notes |
|--------|-----------|------|--------|-------|
| **MGC** | 1h | p_edge 0.6842 | **APPROVED — paper active** | SMA(50,120) trend, atr_trail_mult=2.0; ALT gate-v2 PASS |
| **MES** | 1h | p_edge 0.75 | **APPROVED — paper active** | SMA(60,200) trend, atr_trail_mult=2.0; ALT gate-v2 PASS |
| MCL | 1h | WFE 0.82 | HALTED | `DO_NOT_TRADE` — hypotheses A–E exhausted 2026-05-07 |
| MNQ | 1h | WFE 0.57 | HALTED | `DO_NOT_TRADE` — trend/breakout/ORB all fail gate-v2 |
| M2K | 1h | — | REJECTED | SMA/ORB/Donchian rank-1 all FAIL 2026-05-24 |

---

## Ports & Network

| Service | Port | Mode | Status |
|---------|------|------|--------|
| Engine API | 8010 | Local | Running |
| Dashboard | 3010 | Local | Running |
| IB Gateway | 4002 | Paper | Required |
| IB Gateway | 4001 | Live | PERMANENTLY BLOCKED |

**Note:** Port 7497 (TWS desktop) is NOT used. IB Gateway communicates on 4002 (paper) / 4001 (live).

---

## Configuration

### Core .env Fields

```bash
# Safety & Autonomy
PAPER_TRADING=True
LIVE_TRADING_ENABLED=False
REQUIRE_HUMAN_APPROVAL=True

# IB Gateway
IBKR_HOST=127.0.0.1
IBKR_PORT=4002
IBKR_CLIENT_ID=1
IB_ACCOUNT_ID=YOUR_ACCOUNT_ID

# Risk Parameters (hardcoded in engine/config.py, reconciled to .env live truth 2026-06-25)
MAX_POSITION_SIZE_PCT=0.10
MAX_DAILY_LOSS_PCT=0.06
MAX_DRAWDOWN_PCT=0.20   # config.py code default; engine/.env remains the source of truth for the live value
MAX_ORDERS_PER_MINUTE=10
MAX_SINGLE_ORDER_VALUE=100000.0
MAX_MARGIN_UTILIZATION=0.40

# API Key (rotate locally; never commit real values)
# python scripts/rotate_dev_api_key.py — see docs/setup-guides/DEV_API_KEY_ROTATION.md
API_KEY=<from engine/.env>

# Simulated IB paper routing (optional)
# ALLOW_PAPER_SIMULATED_ORDERS — default False in .env.example. Enables the gated
# SafetyLayer → connector path only; the portfolio paper API (/portfolio/paper/*) and
# WORKING_TODAY smoke do not require this flag.

# Approved Futures
# config.py code default. Tradeable set is gated separately: MCL + MNQ are HALTED
# (DO_NOT_TRADE_SYMBOLS); MES + MGC are the active paper instruments (Tier-3 2026-05-24).
FUTURES_WATCHLIST=MCL,MNQ,MES
```

---

## Safety Invariants

**Non-Negotiable Kill Switch Rules:**

- **Daily Loss Halt:** -6% of account (reconciled to `.env` live truth 2026-06-25; `$10K` aggressive profile) → Auto-activates kill switch
- **Drawdown Halt:** -20% from peak (`config.py` code default, reconciled to `.env` live truth 2026-06-25) → Auto-activates kill switch. `engine/.env` remains the source of truth for the live value.
- **Manual Halt:** Operator can activate anytime via API or dashboard
- **Consecutive Loss Limits:** 3→half-size, 5→quarter-size, 7→halt (24 hours)

**Hardcoded in:** `engine/risk/safety_layer.py` (never LLM-based)

---

## Key File Locations

| File | Purpose |
|------|---------|
| `engine/main.py` | FastAPI app, 421 lines, route dispatcher |
| `engine/config.py` | TradingConfig — all risk parameters |
| `engine/agents/pipeline.py` | 5-stage orchestrator |
| `engine/risk/safety_layer.py` | Kill switch, hard limits, order validation |
| `engine/backtest/signals.py` | STC signal logic (CANONICAL parameter source) |
| `engine/orchestrator/multi_market.py` | Multi-market orchestrator |
| `dashboard/lib/api.ts` | All engine API calls via fetchEngine/postEngine |
| `docs/architecture/API_CANONICAL_ENDPOINTS.md` | Canonical routes (validation, RL, Greeks) — avoids FastAPI shadowing |
| `docs/runbooks/PAPER_LEDGER_BOUNDARIES.md` | Paper mode A vs B writers/readers |
| `engine/execution/README.md` | IB: single front door (`ib_gateway.py`) |

---

## Paper Validation Status

**Period:** MES + MGC active paper validation since 2026-05-24 (Tier-3 auth). The prior MCL/MNQ window (Apr 2–May 2, 2026) is closed — both instruments are now HALTED (`DO_NOT_TRADE`).
**Target:** Profit Factor > 1.5, Sharpe > 1.0, Max Drawdown < 10%, Win Rate > 45%

**Instruments:** MES (1h), MGC (1h) — active paper. MCL + MNQ HALTED (`DO_NOT_TRADE`).
**Broker:** IB Gateway (paper), port 4002
**Mode:** All orders logged but NOT submitted (PAPER_TRADING=True)

**Success Criteria:**
- All profitability metrics met
- System health: 99.5% broker uptime, 0 unhandled exceptions
- Safety layer: kill switch tested ≥5 times
- Zero critical bugs without code changes

---

## Running the System

```bash
# Start Engine (Python 3.12 venv) — do NOT use --reload with IB Gateway connected
cd engine && .venv/Scripts/python -m uvicorn main:app --port 8010
# Windows: ..\\restart_engine.ps1 from repo root after config changes

# Start Dashboard
cd dashboard && pnpm dev

# Both (Windows)
start_jarvis.bat

# Pre-flight checks
curl http://localhost:8010/health
curl http://localhost:8010/v1/broker/status
curl http://localhost:3010
```

---

## Next Steps (Phase 3 — Live Trading)

When paper validation completes successfully:
1. Extend position sizing from 0.25x → 0.50x → 1.00x over weeks 1-3
2. Change IBKR_PORT from 4002 (paper) to 4001 (live) — **ONLY after explicit approval**
3. Set LIVE_TRADING_ENABLED=True + maintain REQUIRE_HUMAN_APPROVAL=True for week 1

All live trading changes require **Tier 3 confirmation** from the trader.

---

**Document Version:** 1.0 | **Lines:** 150 | **Scope:** System snapshot, not development log

