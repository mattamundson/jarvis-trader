# Plan — Public Read-Only Market Brief Site

## Finish line

Create the first safe 24/7-public tranche for Market Brief: a public-safe page and public JSON route that can be deployed to Vercel/Cloudflare without exposing trading controls.

## Scope

- Add `/market-brief-public` as a read-only public page.
- Add `/api/public-market-brief/latest` as a sanitized JSON route.
- Exempt only these public paths from Basic Auth middleware.
- Keep `/mission-control`, `/api/market-brief`, `/api/engine/*`, `/api/master/*`, trading routes and all control surfaces protected.
- No broker, order routing, risk config, kill-switch, `.env`, or DO_NOT_TRADE changes.

## Acceptance criteria

1. Public JSON route returns `ANALYSIS_ONLY`, `orders_enabled=false`, `risk_config_touched=false`.
2. Public JSON route excludes `sourcePath` and internal local filesystem paths.
3. Public page renders the base-rate block and provisional/no-edge conditional disclosure.
4. Middleware unit coverage proves public paths bypass auth while trading/control paths do not.
5. Typecheck, build, and targeted route tests pass.
6. Deploy guidance remains Vercel/Cloudflare-ready, but no paid/cloud resource is created without explicit approval.
