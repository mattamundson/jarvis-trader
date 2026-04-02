# Dashboard — Next.js Frontend Context

> Next.js 15, TypeScript, Tailwind CSS, port 3010. See parent CLAUDE.md for full project overview.

## Entry Points

| File | Purpose |
|------|---------|
| `app/layout.tsx` | Root layout — theme, nav, providers |
| `lib/api.ts` | `fetchEngine` / `postEngine` — ALL API calls go through here |
| `components/` | Shared UI components |
| `app/` | App Router pages (14 pages total) |

## Critical Rule: Never Hardcode URLs

**ALL engine API calls must use `fetchEngine` / `postEngine` from `lib/api.ts`.**
Never write `fetch('http://localhost:8010/...')` directly.

## TypeScript Conventions

- `'use client'` only when interactivity or browser APIs are needed
- Push `'use client'` as far down the tree as possible
- `pnpm` only — system npm is broken
- Build check: `./node_modules/.bin/tsc --noEmit` (NOT `npx tsc`)
- Dev: `pnpm dev` | Build: `pnpm run build`

## Dashboard Pages (14 total)

```
/ (overview)       /pipeline          /backtest
/positions         /risk              /portfolio
/options           /crypto            /performance
/settings          /agents            /market-analysis
/walk-forward      /polymarket (stub)
```

## Component Conventions

- Badge variants (STRICT): `"bull" | "bear" | "warn" | "info" | "neutral"` — no others
- Tailwind for all styling — no inline styles
- shadcn/ui primitives where applicable
- Dark mode default — dashboard theme

## WebSocket

Real-time data via `hooks/useWebSocket.ts` — connects to engine ws://localhost:8010/ws
