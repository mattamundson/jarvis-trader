# Comprehensive plan execution — 2026-04-02

Automated / documentation deliverables from the jarvis comprehensive implementation plan (plan file not edited).

## P0 — Operational

- **P0.1** — Runbook updated with §4.5 (`verify_p0_paper_ib.py`). Live IB Gateway sign-off remains **operator** when Gateway is up; script records engine HTTP checks.
- **P0.2** — [IB_CONNECTOR_OVERVIEW.md](../runbooks/IB_CONNECTOR_OVERVIEW.md)
- **P0.3** — Optional paper order smoke stays in [P0_PAPER_IB_VERIFICATION.md](../runbooks/P0_PAPER_IB_VERIFICATION.md) §5 (human).
- **P0.4–P0.6** — [PAPER_DATA_SOURCES.md](../runbooks/PAPER_DATA_SOURCES.md) (A+B default; dashboard B-first).

## P1 — Reliability

- **Health contract** — `GET /health/full` uses `response_model=FullHealthResponse`; `GET /safety/status` uses extended `SafetyStatusResponse`.
- **Rate limits** — `app.state.limiter` + `RateLimitExceeded` handler in `main.py`; `GET /safety/status` `@limiter.limit("10/minute")`. `storage_uri` set to `memory://` for `limits>=5`.
- **Git** — Local `git status` reported `fatal: bad object HEAD` (workspace/repo repair needed outside this pass).
- **Secrets** — Re-run `scripts/hooks/check-secrets.sh` before push (bash).

## P2 — Agents

- [ANTHROPIC_BILLING_AND_PIPELINE_SMOKE.md](../runbooks/ANTHROPIC_BILLING_AND_PIPELINE_SMOKE.md); `engine/scripts/smoke_pipeline.py`.
- **Degraded UX** — `EngineAvailabilityHint` in root layout (engine reachability via `/api/engine/health`).

## P3 — Quality

- **Contract tests** — `engine/tests/test_api_contract_minimal.py` (portfolio + safety shapes, real tracker/safety).
- **Dashboard** — `fetchEngine`/`postEngine` default generic `any` to unblock strict `unknown`; many widgets fixed: `fetchEngine` returns JSON (not `Response`); raw `fetch` paths now `await res.json()` where `json`/`data`/`raw` were undefined.

## P4 — Research

- [GATED_SYMBOLS_WFE_PLAYBOOK.md](../research/GATED_SYMBOLS_WFE_PLAYBOOK.md)

## Analysis passes A–D

- [CODEBASE_ANALYSIS_PASS_SUMMARY.md](../architecture/CODEBASE_ANALYSIS_PASS_SUMMARY.md)

## Verification run

- `pytest tests/test_api_contract_minimal.py tests/test_auth_and_rate_limit.py` — 18 passed (with `slowapi` installed).
- `pnpm run build` (dashboard) — success, 21 routes.

## Follow-up (command-center / Stark pass)

- **`POST /safety/kill-switch` (legacy JSON)** — Fixed argument order: dashboard body was passed as `reason` query instead of `body`; now `activate_kill_switch(None, KillSwitchActivateBody(...))` in `engine/routers/safety_router.py`.
- Re-verified: `pytest` contract + auth + `test_safety_layer` (43 tests) green; `pnpm run build` green.
