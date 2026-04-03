# PR queue (post restart_engine / CI green)

Scheduled follow-ups from the 2026-04-03 plan. Each item should be a **narrow PR** when picked up.

| Order | Topic | Status / notes |
|-------|--------|----------------|
| 1 | **Full test suite in CI** | **Done** — `.github/workflows/ci.yml` runs `pytest engine/tests/` (Apr 2026). |
| 2 | **OrderRouter / `route_order()`** | **Wired** — `approval_router` calls injected `OrderRouter.route_order`; see `engine/routers/approval_router.py`. E2E coverage in `test_approval_to_order_e2e.py`. |
| 3 | **Dev API key hygiene** | **Ops** — copy `engine/.env.example` to `.env`; set `API_KEY` and `NEXT_PUBLIC_ENGINE_API_KEY` to the same random value (never commit `.env`). |
| 4 | **Strategy / trading rules doc** | **Canon** — see [docs/strategy/README.md](../strategy/README.md) (index to `TRADING_RULES.md`, `EQUATIONS.md`). |
| 5 | **Pre-deploy test depth** | Optional — [deploy-check.yml](../../.github/workflows/deploy-check.yml) still runs a **Tier-1** pytest slice for speed; align with full suite if you want parity. |

Local parity commands mirror [.github/workflows/ci.yml](../../.github/workflows/ci.yml).
