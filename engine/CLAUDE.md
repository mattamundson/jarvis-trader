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

- `LIVE_TRADING_ENABLED = False` — paper mode only until Phase 3
- `REQUIRE_HUMAN_APPROVAL = True` — all order confirmations
- Kill switch: -6% daily loss, -20% drawdown (both `config.py` code defaults, reconciled to `engine/.env` live truth 2026-06-25) — do not modify without Tier 3 approval
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
| MGC | 1h | 0.6842 (p_edge) | APPROVED — paper active, SMA(50,120) trend, atr_trail_mult=2.0; ALT gate v2 PASS; Tier 3 auth 2026-05-24. RV filter (min_rv=9%) validated CORE gate v2 2026-05-24 (p_edge=1.0, wfo=STRONG, mc_dd=0.65%, cost=catastrophic) — NOT yet enabled; requires 60+ live MGC trades for calibration |
| MES | 1h | 0.75 (p_edge) | APPROVED — paper active, SMA(60,200) trend, atr_trail_mult=2.0; ALT gate v2 PASS; Tier 3 auth 2026-05-24. RV filter (min_rv=9%) validated ALT gate v2 2026-05-24 — NOT yet enabled in paper config; requires 60+ live trades for confirmation |
| M2K | 1h | — | REJECTED — SMA trend ranks 1-3 FAIL + ORB rank1 FAIL + Donchian rank1 FAIL 2026-05-24 (dch: p_edge=0.50, wfo=WEAK, dsr=0.0; cost=catastrophic but wfo blocks ALT); 3 families exhausted at 1h |
| SPY | 1h | 0.00 | REJECTED — WFE run 2026-04-02 |

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
