# JARVIS TRADER — Current System State

**Status:** Paper Trading Validation | **Mode:** Paper only (IB Gateway 4002) | **Last Updated:** August 11, 2026

> **Current reality (2026-07-29):** MGC is **HALTED**, not approved — the 2026-05-24
> Tier-3 "APPROVED" verdict did not survive the honest-data-drain DSR correction
> (memory `project_honest_data_drain_zero_survivors_2026_07_27`): rebuilding non-contaminated
> continuous-futures reference data and recomputing DSR at the true 54-70 combined-campaign trial
> count collapsed MGC's one nominal ALT-path PASS (dsr 0.869307 → ~0.000002). MGC moved into
> `DO_NOT_TRADE_SYMBOLS` and `paper_config.py enabled=False` on 2026-07-29. **MES remains
> APPROVED and actively trading** — it is Amo's most-traded vehicle and must never be added to
> `DO_NOT_TRADE_SYMBOLS` or disabled without his explicit, direct instruction. The June 2026
> "MES + MGC active" status below is now stale for MGC only; the April 2026 static table further
> below (MCL/MNQ approved, MES/MGC do-not-trade) was already noted as stale/inverted before this
> correction. For live instrument status always prefer the `/validation` scorecard over the
> static table below.

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

_Updated 2026-07-29 — honest-data-drain DSR correction halted MGC. Live status: `/validation`._

| Symbol | Timeframe | Edge | Status | Notes |
|--------|-----------|------|--------|-------|
| MGC | 1h | p_edge 0.6842 (superseded) | **HALTED 2026-07-29** | `DO_NOT_TRADE` — nominal ALT gate-v2 PASS collapsed to dsr~0 once corrected for the true trial count (honest-data-drain, 2026-07-27) |
| MES | 1h | p_edge 0.75 | **APPROVED — paper active** | SMA(60,200) trend, atr_trail_mult=2.0; ALT gate-v2 PASS. Not subject to the honest-data-drain halt applied to MGC — this is Amo's most-traded vehicle, must never be halted without his explicit direction |
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
REQUIRE_HUMAN_APPROVAL=False   # standing decision, confirmed by Amo 2026-08-11 -- not a test leftover

# IB Gateway
IBKR_HOST=127.0.0.1
IBKR_PORT=4002
IBKR_CLIENT_ID=1
IB_ACCOUNT_ID=YOUR_ACCOUNT_ID

# Risk Parameters (live values from engine/.env, the source of truth --
# engine/config.py's Field() defaults are fallbacks only and can differ)
MAX_POSITION_SIZE_PCT=0.10
MAX_DAILY_LOSS_PCT=0.08
MAX_DRAWDOWN_PCT=0.20
MAX_ORDERS_PER_MINUTE=10
MAX_SINGLE_ORDER_VALUE=100000.0
MAX_MARGIN_UTILIZATION=0.40
MAX_CONTRACTS_PER_INSTRUMENT=4
MAX_OVERNIGHT_CONTRACTS=2

# API Key (rotate locally; never commit real values)
# python scripts/rotate_dev_api_key.py — see docs/setup-guides/DEV_API_KEY_ROTATION.md
API_KEY=<from engine/.env>

# Simulated IB paper routing (optional)
# ALLOW_PAPER_SIMULATED_ORDERS — default False in .env.example. Enables the gated
# SafetyLayer → connector path only; the portfolio paper API (/portfolio/paper/*) and
# WORKING_TODAY smoke do not require this flag.

# Approved Futures
# config.py code default. Tradeable set is gated separately: MCL + MNQ + MGC are HALTED
# (DO_NOT_TRADE_SYMBOLS); MES is the active paper instrument (Tier-3 2026-05-24).
FUTURES_WATCHLIST=MCL,MNQ,MES
```

---

## Safety Invariants

**Non-Negotiable Kill Switch Rules:**

- **Daily Loss Halt:** -8% of account (`MAX_DAILY_LOSS_PCT` in `engine/.env`; `config.py`'s Field() default is a lower, unused fallback) → Auto-activates kill switch
- **Drawdown Halt:** -20% from peak (`MAX_DRAWDOWN_PCT` in `engine/.env`, the source of truth for the live value; matches the `config.py` code default) → Auto-activates kill switch
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

**Period:** MES + MGC active paper validation 2026-05-24 through 2026-07-29 (Tier-3 auth). MGC then
HALTED 2026-07-29 (honest-data-drain DSR correction invalidated its underlying gate-v2 PASS); MES
continues uninterrupted — not subject to that halt. The prior MCL/MNQ window (Apr 2–May 2, 2026) is
closed — both instruments are also HALTED (`DO_NOT_TRADE`).
**Target:** Profit Factor > 1.5, Sharpe > 1.0, Max Drawdown < 10%, Win Rate > 45%

**Instruments:** MES active — MGC HALTED 2026-07-29 alongside MCL + MNQ (all three now in
`DO_NOT_TRADE`).
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

