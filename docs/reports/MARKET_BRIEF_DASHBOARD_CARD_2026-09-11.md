# Market Brief Machine-Score Dashboard Card — 2026-09-11

## Scope
Added an ANALYSIS_ONLY Mission Control compact card for the machine-scored morning market brief.

## Files
- `dashboard/app/api/market-brief/route.ts` — read-only Next API route.
- `dashboard/lib/marketBrief/*` — payload types, markdown JSON extraction, summary/degraded-state logic, server artifact loader.
- `dashboard/hooks/useMarketBrief.ts` — SWR hook.
- `dashboard/components/MarketBriefCard.tsx` — Mission Control UI card.
- `dashboard/app/mission-control/page.tsx` — card placement near runtime snapshot + SPX decision card.
- `dashboard/tests/marketBrief.node.test.ts` — parser/summary contract tests.
- `dashboard/tests/e2e/mission-control-market-brief.spec.ts` — fresh-server UI smoke.

## Data source
Default source directory:
`C:/Users/mattm/master-jarvis/second-brain/reports/night-shift`

Current artifact parsed during verification:
`C:/Users/mattm/master-jarvis/second-brain/reports/night-shift/MORNING_BRIEF_MACHINE_SCORED_PREVIEW_2026-09-11.md`

The route extracts the fenced JSON under `### Market machine payload (JSON)` and returns degraded/stale states instead of confident numbers when missing or old.

## Verification
- `pnpm exec tsc --noEmit --pretty false` → pass.
- `node --test --experimental-strip-types --import ./tests/_register-alias.mjs tests/marketBrief.node.test.ts` → 4 passed.
- `pnpm run build` → pass; `/api/market-brief` appears in route table; `/mission-control` builds.
- `pnpm exec playwright test tests/e2e/mission-control-market-brief.spec.ts --config=playwright.fresh.config.ts` → 1 passed.
- Real API smoke via isolated `next start -p 3014` and HTTP GET `/api/market-brief` → HTTP 200, `mode=ANALYSIS_ONLY`, `orders_enabled=false`, `risk_config_touched=false`, `sourceQuality=fresh`, continuation `79.5`, rotation `20.5`, failure `0`, SPY gap `-0.5994`, ES pivot `7616.75`.

## Safety boundary
ANALYSIS_ONLY. No broker execution, no order routing, no live trading/risk/kill-switch config changes, no `.env` edits, no DO_NOT_TRADE symbol changes.

## Git checkpoint
- Worktree: `C:/Users/mattm/ThinkorSwim/wt-market-brief-dashboard-20260911`
- Branch: `feat/market-brief-dashboard-card-20260911`
- Local commit: `e1aca32a feat(dashboard): add market brief machine-score card`
- Remote: not pushed.

## Next recommended tranche
Add historical calibration for continuation/rotation/failure probabilities so the deterministic machine score becomes statistically calibrated rather than heuristic.
