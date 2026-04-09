# JARVIS TRADER — Current System State

**Status:** Hardening Phase | **Mode:** Paper Trading Validation | **Last Updated:** April 10, 2026

**See also:** [Strategic command center (index)](strategic/README.md) — executive brief, system map, risk register, execution spine, and analysis passes.

**New runbooks (2026-04-10):** [SECURITY_OPERATOR_CHECKLIST.md](runbooks/SECURITY_OPERATOR_CHECKLIST.md) · [PAPER_SOURCE_OF_TRUTH.md](runbooks/PAPER_SOURCE_OF_TRUTH.md) · [IB_RECONNECT_AND_HEALTH.md](runbooks/IB_RECONNECT_AND_HEALTH.md) · [HEALTH_API_CONTRACT.md](runbooks/HEALTH_API_CONTRACT.md) · [SQLITE_BACKUP.md](runbooks/SQLITE_BACKUP.md)

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

| Symbol | Timeframe | WFE | Status | Notes |
|--------|-----------|-----|--------|-------|
| **MCL** | 1h | 0.82 | APPROVED | Paper trading active |
| **MNQ** | 1h | 0.57 | APPROVED | Paper trading active |
| MGC | 1d | 0.14 | HALTED | Overfit / insufficient sample |
| MES | 1h | 0.09 | **DO NOT TRADE** | WFE too low; research paused |

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

# Risk Parameters (hardcoded in engine/config.py)
MAX_POSITION_SIZE_PCT=0.05
MAX_DAILY_LOSS_PCT=0.02
MAX_DRAWDOWN_PCT=0.10
MAX_ORDERS_PER_MINUTE=10
MAX_SINGLE_ORDER_VALUE=5000.0
MAX_MARGIN_UTILIZATION=0.40

# API Key (rotate locally; never commit real values)
# python scripts/rotate_dev_api_key.py — see docs/setup-guides/DEV_API_KEY_ROTATION.md
API_KEY=<from engine/.env>

# Simulated IB paper routing (optional)
# ALLOW_PAPER_SIMULATED_ORDERS — default False in .env.example. Enables the gated
# SafetyLayer → connector path only; the portfolio paper API (/portfolio/paper/*) and
# WORKING_TODAY smoke do not require this flag.

# Approved Futures
FUTURES_WATCHLIST=MCL,MNQ
```

---

## Safety Invariants

**Non-Negotiable Kill Switch Rules:**

- **Daily Loss Halt:** -2% of account → Auto-activates kill switch
- **Drawdown Halt:** -10% from peak → Auto-activates kill switch
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
| `engine/markets/orchestrator.py` | Multi-market orchestrator |
| `dashboard/lib/api.ts` | All engine API calls via fetchEngine/postEngine |
| `docs/architecture/API_CANONICAL_ENDPOINTS.md` | Canonical routes (validation, RL, Greeks) — avoids FastAPI shadowing |
| `docs/runbooks/PAPER_LEDGER_BOUNDARIES.md` | Paper mode A vs B writers/readers |
| `engine/execution/README.md` | IB: single front door (`ib_gateway.py`) |

---

## Paper Validation Status

**Period:** April 2–May 2, 2026 (30 days)
**Target:** Profit Factor > 1.5, Sharpe > 1.0, Max Drawdown < 10%, Win Rate > 45%

**Instruments:** MCL (1h), MNQ (1h) only
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

