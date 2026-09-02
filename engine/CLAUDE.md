# Engine — Python Backend Context

> FastAPI trading engine, port 8010. See parent CLAUDE.md for full project overview.
> Wave 3 instrument expansion (2026-05-21): MES + MGC added as VALIDATION_ONLY — pipeline runs, no paper orders.

## Entry Points

| File | Purpose |
|------|---------|
| `main.py` | FastAPI app, 421 lines, 80+ routes across 24 routers, lifespan orchestrator |
| `config.py` | `TradingConfig` — ALL risk parameters live here |
| `agents/pipeline.py` | 5-stage LLM pipeline orchestrator |
| `risk/safety_layer.py` | Kill switch + hard limits — **hardcoded, never LLM-driven** |
| `backtest/signals.py` | STC canonical params — Tier 3 approval to change |
| `orchestrator/multi_market.py` | Multi-market orchestrator (futures, options, crypto) |
| `learning/` | 4-module learning system (events, feedback, patterns, recommendations) |
| `hooks/` | React hooks module (state management, market data) |
| `routers/` | 24 router files organizing 80+ API endpoints |

## Safety — Non-Negotiable

- `LIVE_TRADING_ENABLED = False` — paper mode only until `JARVIS-MIP-1.0` milestone `M11` and explicit Tier 3 owner authorization; an unqualified phase number never authorizes live trading
- `REQUIRE_HUMAN_APPROVAL = False` — standing decision 2026-08-11, full-visibility trade alerts replace per-trade approval (see `.claude/rules/safety.md`)
- Kill switch: -8% daily loss, -20% drawdown (runtime via `engine/.env`; `config.py` code default is -10%) — do not modify without Tier 3 approval
- Safety layer is **pure Python logic** — never route safety decisions through LLM

## Python Conventions

- Runtime: `.venv/Scripts/python` — never system Python
- Start: `.venv/Scripts/python -m uvicorn main:app --port 8010` (no `--reload` — use `restart_engine.ps1` after changes; reload duplicates IB connections)
- Tests: `.venv/Scripts/python -m pytest tests/ -v` (467+ tests passing)
- Async throughout with graceful sync fallback
- Pydantic v2 for all models
- ruff-clean (no lint errors before commit)
- 400 lines typical per file, 800 max

## Test Files

- `tests/test_safety_layer.py` — Safety invariants (non-negotiable)
- `tests/test_pipeline.py` — 5-stage pipeline logic
- `tests/test_signals.py` — STC signal generation
- `tests/test_learning.py` — Learning system modules
- `tests/test_orchestrator.py` — Multi-market orchestrator
- `tests/test_foundation.py` — Core utilities
- `tests/test_market_modules.py` — Market module integration

## Key Patterns

- All market modules inherit `MarketModule` ABC from `markets/base.py`
- Route prefix: `/api/v1/` for all endpoints
- Auth middleware: `middleware/auth.py` — API key required
- Rate limiting: `middleware/rate_limit.py`
- WebSocket: `websocket/manager.py`

## Active Instruments

| Symbol | TF | WFE | Status |
|--------|----|-----|--------|
| MCL | 1h | 0.82 | HALTED — hypotheses A-E exhausted 2026-05-07; `DO_NOT_TRADE_SYMBOLS`; `paper_config.py enabled=False` |
| MNQ | 1h | 0.57 | HALTED — trend/breakout/ORB all fail gate v2 (55 trades, 0 wins 2026-05-06/07); `DO_NOT_TRADE_SYMBOLS` |
| MGC | 1h | pf_ci_lower 1.0681 (< 1.1 floor, gate-v2 FAIL) | **HALTED 2026-08-16 (PR #691)** — `DO_NOT_TRADE_SYMBOLS`; `paper_config.py enabled=False`. History: HALTED 2026-08-01 (PR #552) after the honest-data-drain DSR correction invalidated its 2026-05-24 gate-v2 PASS (recomputing DSR at the true combined-campaign trial count collapsed its one nominal ALT-path PASS to ~0 — `engine/scripts/recompute_mgc_trend_baseline_dsr.py`, PR #529); REAUTHORIZED 2026-08-10 (PR #598) on a fresh honest gate-v2 CORE PASS — SMA(50,120) trend, atr_trail_mult=2.0, 67 OOS trades, 19/19 windows profitable, all 8 grid combos PF>=1.36; then RE-HALTED 2026-08-16 (PR #691) when a re-evaluation on refreshed data (`MGC_2024-03-04_2026-07-24_1h.csv`, 14,130 bars) FAILed gate v2 — pf_ci_lower 1.0681 (floor >=1.1), mc_95th_dd 4.4212% (alt floor <=4.0), despite dsr 0.9733, p_edge 0.998, and 94 OOS trades all passing. Verdict: `engine/data/gate_v2_verdicts/MGC_trend_rank4.json` (created_at 2026-08-16T15:29Z). Re-enable only on a fresh honest gate-v2 CORE PASS. |
| MES | 1h | 0.75 (p_edge) | APPROVED — paper active, SMA(60,200) trend, atr_trail_mult=2.0; ALT gate v2 PASS; Tier 3 auth 2026-05-24. RV filter (min_rv=9%) validated ALT gate v2 2026-05-24 — NOT yet enabled in paper config; requires 60+ live trades for confirmation |
| M2K | 1h | — | REJECTED — SMA trend ranks 1-3 FAIL + ORB rank1 FAIL + Donchian rank1 FAIL 2026-05-24 (dch: p_edge=0.50, wfo=WEAK, dsr=0.0; cost=catastrophic but wfo blocks ALT); 3 families exhausted at 1h |
| SPY | 1h | 0.00 | REJECTED — WFE run 2026-04-02 — **but see Equities below: trading live in paper anyway** |

### Equities (options underlyings — SPY, QQQ, AAPL, TSLA)

**This table above was never updated when the second asset class went live.** `engine/config.py`'s
`OPTIONS_WATCHLIST` (line ~638) defaults to `['SPY', 'QQQ', 'AAPL', 'TSLA']`, and `main.py`
deliberately routes these four through the options/equities scanner as a separate asset class from
the futures rows above. All four have real paper fills in the live ledger as of 2026-07-25/26
(`paper_trades` table, `engine/data/jarvis_trader.db`, read-only query):

| Symbol | Live paper fills | Last fill | Gate v2 / WFE verdict on file |
|--------|------------------|-----------|-------------------------------|
| SPY | 3 | 2026-07-20 | **REJECTED** — WFE 0.00, run 2026-04-02 (row above). Trading live in paper **despite** this rejection — the config/routing layer does not consult the Active Instruments table. |
| QQQ | 6 | 2026-07-20 | **None found.** No `wfe_snapshots` row for QQQ, no `engine/backtest/results/` artifact, no `run_qqq_*.py` backtest script. |
| AAPL | 9 | 2026-07-17 | **None found.** No `wfe_snapshots` row for AAPL, no `engine/backtest/results/` artifact, no `run_aapl_*.py` backtest script. |
| TSLA | 5 | 2026-07-17 | **None found.** No `wfe_snapshots` row for TSLA, no `engine/backtest/results/` artifact, no `run_tsla_*.py` backtest script. |

Verification method (2026-07-26): queried the live `wfe_snapshots` table directly —
`SELECT symbol, COUNT(*) FROM wfe_snapshots GROUP BY symbol` returns rows only for
`MCL` (615), `MNQ` (626), `MES` (17), `MGC` (1) — zero rows for SPY, QQQ, AAPL, or TSLA. Also
searched `engine/backtest/` for any per-symbol backtest/gate-v2 script or result file
(`run_<symbol>_*.py`, `engine/backtest/results/<SYMBOL>_*`) — SPY has four such scripts (all
pre-2026-04-02, all folded into the REJECTED verdict above); QQQ/AAPL/TSLA have none.

**Net: QQQ, AAPL, and TSLA are auto-submitting live paper orders with no gate-v2/WFE validation on
file at all — not a failing verdict, an absent one. SPY is auto-submitting despite an explicit
REJECTED verdict.** This is a documentation-only correction (this PR does not change routing,
config, or gating behavior).

**Decision (Amo, 2026-08-03): keep all four names (SPY, QQQ, AAPL, TSLA) trading as-is.** No
routing/config change made or requested — this is an explicit, informed acceptance of the gap
above, not a silent one. Revisit if a future gate-v2/WFE run actually fails one of these four.

### Validation-only lifecycle

`VALIDATION_ONLY_INSTRUMENTS` (defined in `engine/agents/pipeline.py`) is currently empty —
both MES and MGC were promoted to active paper trading on 2026-05-24 (Tier 3 auth).
The pipeline runs for all approved symbols; verdicts appear in the dashboard and Discord briefing feed.
The approval gate in `approval/service.py:ensure_approval_allowed()` blocks paper orders for any
symbol remaining in this set with HTTP 409.

Flip-to-active criteria (remove from `VALIDATION_ONLY_INSTRUMENTS` when ALL met):
1. p_positive_edge >= 0.6 on a fresh rolling walk-forward run (ALT path)
2. Gate v2 ALT PASS (`mc_95th_dd<=4%`, `dsr>=0.30`, `rolling_wfo=MODERATE+`, `fixed_params_min_pf>=1.2`)
3. Explicit Tier 3 authorization from Amo
