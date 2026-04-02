# Engine — Python Backend Context

> FastAPI trading engine, port 8010. See parent CLAUDE.md for full project overview.

## Entry Points

| File | Purpose |
|------|---------|
| `main.py` | FastAPI app, 421 lines, 80+ routes across 24 routers, lifespan orchestrator |
| `config.py` | `TradingConfig` — ALL risk parameters live here |
| `agents/pipeline.py` | 5-stage LLM pipeline orchestrator |
| `risk/safety_layer.py` | Kill switch + hard limits — **hardcoded, never LLM-driven** |
| `backtest/signals.py` | STC canonical params — Tier 3 approval to change |
| `markets/orchestrator.py` | Multi-market orchestrator (futures, options, crypto) |
| `learning/` | 4-module learning system (events, feedback, patterns, recommendations) |
| `hooks/` | React hooks module (state management, market data) |
| `routers/` | 24 router files organizing 80+ API endpoints |

## Safety — Non-Negotiable

- `LIVE_TRADING_ENABLED = False` — paper mode only until Phase 3
- `REQUIRE_HUMAN_APPROVAL = True` — all order confirmations
- Kill switch: -2% daily loss, -10% drawdown — do not modify without Tier 3 approval
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
| MCL | 1h | 0.82 | APPROVED — paper active |
| MNQ | 1h | 0.57 | APPROVED — paper active |
| MGC | 1d | 0.14 | HALTED |
| MES | 1h | 0.09 | DO NOT TRADE |
