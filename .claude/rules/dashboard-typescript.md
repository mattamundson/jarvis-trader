---
paths:
  - "dashboard/**/*.ts"
  - "dashboard/**/*.tsx"
---

# Dashboard TypeScript Rules

## Framework
- Next.js 15 App Router — default to Server Components
- `"use client"` ONLY when browser APIs or interactivity is needed
- Push `"use client"` as far down the component tree as possible
- No Pages Router patterns (getServerSideProps, etc.)

## API Calls — CRITICAL
- **ALL engine calls via `fetchEngine` / `postEngine` from `lib/api.ts`**
- NEVER write `fetch('http://localhost:8010/...')` or `fetch('${process.env.NEXT_PUBLIC_ENGINE_URL}/...')` directly
- Use `fetchEngine<ResponseType>('/endpoint')` for GET
- Use `postEngine<ResponseType>('/endpoint', body)` for POST

## Components
- Badge variants STRICT: `"bull" | "bear" | "warn" | "info" | "neutral" | "live" | "static"` — no other values ever (`live`/`static` are Trust-Pane data-provenance badges; see `dashboard/components/ui/badge.tsx`)
- Tailwind for all styling — no inline styles (`style={{}}`)
- Radix UI primitives where available
- SWR for client-side data fetching: `useSWR<Type>('/path', fetcher, { refreshInterval })`

## TypeScript
- Strict mode (`strict: true` in tsconfig)
- No `any` types — use `unknown` and narrow
- Type all component props explicitly
- Run `./node_modules/.bin/tsc --noEmit` (NOT `npx tsc`) to type-check

## Build
- `pnpm` only — system npm is broken
- `pnpm run build` must pass before any commit
- If build fails with `.next/**/page.js.nft.json` errors: `pnpm run build:clean`
- Port: 3010 (`pnpm dev`)
