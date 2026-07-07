# PR queue (post restart_engine / CI green)

Scheduled follow-ups from the 2026-04-03 plan. Each item should be a **narrow PR** when picked up.

| Order | Topic | Status / notes |
|-------|--------|----------------|
| 1 | **Full test suite in CI** | **Done** — `.github/workflows/ci.yml` runs `pytest engine/tests/` (Apr 2026). |
| 2 | **OrderRouter / `route_order()`** | **Wired** — `approval_router` calls injected `OrderRouter.route_order`; see `engine/routers/approval_router.py`. E2E coverage in `test_approval_to_order_e2e.py`. |
| 3 | **Dev API key hygiene** | **Done** — `scripts/rotate_dev_api_key.py` + [DEV_API_KEY_ROTATION.md](../setup-guides/DEV_API_KEY_ROTATION.md); runbook curls use `<YOUR_ENGINE_API_KEY>`. |
| 4 | **Strategy / trading rules doc** | **Canon** — see [docs/strategy/README.md](../strategy/README.md) (index to `TRADING_RULES.md`, `EQUATIONS.md`). |
| 5 | **Pre-deploy test depth** | **Done** — [deploy-check.yml](../../.github/workflows/deploy-check.yml) runs the same fast/slow pytest slices + `--cov-append` as CI (single runner). [ci.yml](../../.github/workflows/ci.yml) uses parallel fast/slow jobs + coverage merge for wall time. |
| 6 | **CI concurrency** | **Done** — `concurrency` + `cancel-in-progress` on CI and pre-deploy workflows (Apr 2026). |
| 7 | **Trade History + gates UI** | **Done** — `/trades` uses `fetchClosedPaperTrades` → `GET /paper/validation/trades/closed`; `InstrumentValidationScorecard` uses gate `current`; `app/trades/layout.tsx` sets `dynamic = force-dynamic` (Apr 2026). |

Local parity commands mirror [.github/workflows/ci.yml](../../.github/workflows/ci.yml).
