# Codebase analysis passes A–D (condensed)

Single reference for optional “analysis pass” milestones. Expand in future sessions if needed.

## Pass A — Routers, risk, backtest

- **Routers:** [`engine/routers/`](../../engine/routers/) — 24 modules; `main.py` mounts health, safety, portfolio (prefix `/portfolio`), pipeline, backtest, market, etc.
- **Risk:** [`engine/risk/safety_layer.py`](../../engine/risk/safety_layer.py) — hardcoded kill switch, circuit breakers, order validation; [`engine/routers/safety_router.py`](../../engine/routers/safety_router.py) exposes `/safety/*`.
- **Backtest:** [`engine/backtest/`](../../engine/backtest/) — `signals.py` canonical STC/regime; `paper_runner.py` optional engine sync.

## Pass B — Dashboard ↔ engine

- **API surface:** [`dashboard/lib/api.ts`](../../dashboard/lib/api.ts) — all calls via `fetchEngine` / `postEngine` to `/api/engine`.
- **Representative UI routes:** `/` dashboard, `/paper` (paper command widgets), `/command-center`, `/portfolio` (if present), `/backtest` — each should proxy the same paths as `api.ts` (no hardcoded `localhost:8010` in components).

## Pass C — Learning, markets, pipeline

- **Learning:** [`engine/learning/`](../../engine/learning/) — events, feedback, patterns, recommendations.
- **Markets:** [`engine/markets/`](../../engine/markets/) — orchestrator for futures/options/crypto modules.
- **Pipeline:** [`engine/agents/pipeline.py`](../../engine/agents/pipeline.py) — five-stage LLM flow; `POST /pipeline/run` in [`pipeline_router.py`](../../engine/routers/pipeline_router.py).

## Pass D — Ops

- **Process manager:** PM2 ecosystem files (if used) + `start_jarvis.bat` for Windows.
- **Env:** Engine `API_KEY`, optional `JARVIS_ENGINE_URL` / `JARVIS_API_KEY` on runner host; dashboard `NEXT_PUBLIC_ENGINE_API_KEY`.
- **Scripts:** [`engine/scripts/verify_p0_paper_ib.py`](../../engine/scripts/verify_p0_paper_ib.py), [`scripts/hooks/check-secrets.sh`](../../scripts/hooks/check-secrets.sh).

## CI parity

GitHub Actions [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml): `ruff` + `mypy` + full `pytest engine/tests/` + `pnpm run build` in `dashboard/`. Local gates should match before push.
