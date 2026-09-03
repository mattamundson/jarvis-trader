# SPX Intraday Analysis Dashboard MVP Plan

## Finish line
Build and verify a read-only SPX Intraday Decision Panel in the JARVIS dashboard. It must refresh live, show current market state, level status, EOD probability bands/scenarios, bull/bear evidence, data freshness, and explicit ANALYSIS_ONLY mode. No engine/risk/kill-switch/order-routing changes.

## Steps
1. Add typed contracts under dashboard/lib/spxIntraday/.
2. Add pure metrics/probability/verdict modules with unit tests.
3. Add dashboard API route app/api/spx-intraday/route.ts returning honest degraded payloads when live data is unavailable.
4. Add SWR hook and SpxIntradayAnalysisCard component.
5. Mount the card on Mission Control and add a focused /analysis/spx page if low-friction.
6. Verify with typecheck, unit tests, build, and Playwright smoke. If pre-existing failures remain, classify honestly.

## Safety boundaries
- Dashboard-only, read-only analytics.
- No order endpoints.
- No approval queue changes.
- No paper/live risk config changes.
- No kill-switch changes.
- Any future trading-action integration requires [safety-review] PR.
