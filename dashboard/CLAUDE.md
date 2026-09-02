# Dashboard — Next.js Frontend Context

> Next.js 15, TypeScript, Tailwind CSS, port 3010. See parent CLAUDE.md for full project overview.

## Entry Points

| File | Purpose |
|------|---------|
| `app/layout.tsx` | Root layout — theme, nav, providers |
| `lib/api.ts` | `fetchEngine` / `postEngine` — ALL API calls go through here |
| `components/` | Shared UI components |
| `app/` | App Router pages (50 routes total — see `tests/e2e/_routes.ts`, the single source of truth for route coverage) |

## Critical Rule: Never Hardcode URLs

**ALL engine API calls must use `fetchEngine` / `postEngine` from `lib/api.ts`.**
Never write direct absolute engine URLs in dashboard code.
Use the dashboard proxy and environment-aware helpers instead of assuming a direct
engine host or port.

## TypeScript Conventions

- `'use client'` only when interactivity or browser APIs are needed
- Push `'use client'` as far down the tree as possible
- `pnpm` only — system npm is broken
- Build check: `./node_modules/.bin/tsc --noEmit` (NOT `npx tsc`)
- Dev: `pnpm dev` | Build: `pnpm run build` | If Windows fails with missing `.next/**/page.js.nft.json`, run `pnpm run build:clean` (wipes `.next` then builds)

## Dashboard Pages (50 routes total)

The page/redirect/dynamic-route list has grown well past any hand-maintained
snapshot and gone stale here more than once. Do not re-list routes in this
file — read `tests/e2e/_routes.ts` (`ROUTES`), which `tests/routeManifest.node.test.ts`
enforces against the actual `app/**/page.tsx` tree, so it cannot drift.

## Component Conventions

- Badge variants (STRICT): `"bull" | "bear" | "warn" | "info" | "neutral" | "live" | "static"` — no others (`live`/`static` are Trust-Pane data-provenance badges)
- Tailwind for all styling — no inline styles
- shadcn/ui primitives where applicable
- Dark mode default — dashboard theme

## WebSocket

Real-time data via `hooks/useWebSocket.ts` — resolves through
`NEXT_PUBLIC_ENGINE_URL` when set, otherwise falls back to the current dashboard
origin so Next.js proxying can handle the engine connection.
