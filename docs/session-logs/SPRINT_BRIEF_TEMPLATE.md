# Sprint brief (paste at start of a new chat)

Copy this block into a new session when you want aggressive, bounded work.

---

## Definition of done (today)

<!-- One sentence. Example: -->
<!-- "Engine 8010 + dashboard 3010; smoke_working_today.ps1 passes; no changes to safety_layer kill-switch math." -->

-

## Authoritative paper path for this sprint

<!-- e.g. Portfolio API only / or gated connector with ALLOW_PAPER_SIMULATED_ORDERS documented -->

-

## Allowed to touch

<!-- dirs or files, e.g. `dashboard/app/portfolio/`, `engine/routers/portfolio_router.py` -->

-

## Do not touch without `/review`

<!-- e.g. `engine/risk/safety_layer.py` kill math, `engine/config.py` Tier-3 risk defaults -->

-

## Verification commands (must pass before "done")

1. `cd engine && .venv\Scripts\python -m pytest engine/tests/test_<relevant>.py -q --tb=short`
2. `cd dashboard && pnpm run build`
3. `.\scripts\smoke_working_today.ps1` (engine running on 8010)

<!-- Adjust paths for your OS; add curl one-liners if needed. -->

## Branch

-

---

See also: [docs/runbooks/WORKING_TODAY.md](../runbooks/WORKING_TODAY.md).
