# JARVIS TRADER — Current System State

**Status:** Paper Trading Validation | **Mode:** Paper only (IB Gateway 4002) | **Last Updated:** August 11, 2026

> **Trading eligibility is no longer tracked in this file (PRB-25, 2026-07-30).** This
> doc's old "Approved Instruments" table was a hand-maintained snapshot that repeatedly
> went stale and contradicted live reality — most recently it showed MES/MGC "APPROVED —
> paper active" while the engine's own live gates reported both `overall_pass=false`. A
> markdown table requires a human to remember to update it every time a gate verdict
> changes, so re-syncing it once would only start the same drift again. **For current
> trading eligibility, always use the live [Trading Eligibility](../dashboard/app/trading-eligibility/page.tsx)
> dashboard page** (`/trading-eligibility`), which reads directly from
> `GET /paper/validation/approved-paper-gates` on every load — it cannot go stale the way
> a doc can. The rest of this file (architecture, ports, config, safety invariants, key
> file locations, run instructions) is durable reference material, not eligibility data,
> and is kept below.

> **Current reality (2026-06-04, verified against live `/health`):** Engine healthy on
> 8010 — `status=ok`, `ibkr_connected/data_connected=true`, `ibgateway_alive=true` (4002),
> `llm_path_healthy=true`, `tv_mcp=healthy`. Dashboard on 3010. `brier_30d_rolling` is still
> null (calibration populates as paper trades accrue). A dashboard honesty/safety +
> Stark-enhancement branch (`worktree-dashboard-honesty-safety`) is staged but not yet
> pushed/merged; its `[safety-review]` equity-peak clamp activates on the next
> `restart_engine.ps1`.

> **PRB-02 correction (2026-07-29, PR held for Amo's review — not yet merged):** the "APPROVED —
> paper active" status this file used to show for MES and MGC (before PRB-25 retired the static
> table below in favor of the live Trading Eligibility page) does NOT currently survive
> verification. Live
> `GET /paper/validation/approved-paper-gates` shows `overall_pass: false` for BOTH symbols right
> now (MES: profit_factor 1.79 < 2.0 target, win_rate 43.75% < 55%, 16/60 trades, 15/30 days;
> MGC: win_rate 44% < 55%, 25/60 trades, 19/30 days, **max_drawdown 18.27% vs a 15% target —
> already breaching**). Root cause: `gate_v2_policy.is_ungate_eligible(symbol)` was symbol-wide —
> an unrelated strategy's PASS (`MES_stark_gapfill_long_rank1.json`, a gap-fill scanner MES's
> live SMA-trend router never invokes) was authorizing MES's actually-traded, actually-failing
> trend strategy. MGC's authorizing verdict (`MGC_trend_baseline.json`, dsr=0.999375) is a
> multiple-testing artifact of the same class the 2026-07-27 honest-data-drain loop already
> found and corrected elsewhere — recomputed at the true campaign trial count (54–70, per
> `~/.claude/loops/jarvis-honest-data-drain/ledger.json`) its DSR collapses to 0.0, below both
> gate floors. See `engine/data/GATE_V2_FDR_ANALYSIS.md` §6 and PRB-02 in
> `~/.claude/loops/jarvis-prod-readiness/backlog.json`. The code fix (branch
> `fix/prb-02-gate-v2-symbol-wide-eligibility`) makes eligibility strategy-specific and is
> sufficient by itself to halt MES's autonomous order routing once merged + deployed; MGC
> additionally needs its live, intentionally-gitignored verdict file manually superseded
> (git cannot carry that data change — see the PR description) before MGC is actually halted
> too. This banner should be updated again once Amo decides and the fix deploys.

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

**This section is retired as of PRB-25 (2026-07-30) — see the banner at the top of this
file.** It used to hold a static, hand-maintained table of per-symbol approval status;
that table is exactly what went stale and contradicted the live gates twice in one night
(most recently the PRB-02 finding below, before this table was even removed). Use the live
[Trading Eligibility](../dashboard/app/trading-eligibility/page.tsx) dashboard page
(`/trading-eligibility`) instead — it is sourced directly from
`GET /paper/validation/approved-paper-gates` and reflects the engine's actual current
verdict per symbol, including per-gate pass/fail detail (profit factor, Sharpe, win rate,
trade count, days active, max drawdown, deflated Sharpe).

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

# Risk Parameters (hardcoded in engine/config.py, reconciled to .env live truth 2026-06-25)
MAX_POSITION_SIZE_PCT=0.10
MAX_DAILY_LOSS_PCT=0.06
MAX_DRAWDOWN_PCT=0.20   # config.py code default; engine/.env remains the source of truth for the live value
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
# config.py code default. Tradeable set is gated separately by DO_NOT_TRADE_SYMBOLS +
# gate-v2 verdicts — see the live Trading Eligibility page for current per-symbol status,
# this list is not an eligibility statement.
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

**Which instruments are currently active/halted is eligibility data — see the banner at
the top of this file. Use the live [Trading Eligibility](../dashboard/app/trading-eligibility/page.tsx)
page, not this section, for current per-symbol status.**

**Target:** Profit Factor > 1.5, Sharpe > 1.0, Max Drawdown < 10%, Win Rate > 45%

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

**Document Version:** 1.1 (PRB-25 eligibility-pointer edit, 2026-07-30) | **Scope:** System snapshot, not development log. Trading eligibility specifically: not authoritative here — see the live Trading Eligibility dashboard page.

