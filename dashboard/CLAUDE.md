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

## Security: Secrets Rotation Procedure

For Live Order Flow Feed and dashboard security, rotate secrets quarterly (90 days) or immediately after any suspected compromise.

### Secrets Inventory

| Secret | Used By | Rotation Impact |
|--------|---------|----------------|
| `FLOW_INGEST_TOKEN` | `/api/flow/ingest` auth, Windows pusher `push_flow.py` | Medium — pusher will fail until updated locally |
| `CRON_SECRET` | Vercel Cron auth for `/api/cron/*` endpoints | Low — only Vercel platform uses this |
| `DASHBOARD_AUTH_USER` / `DASHBOARD_AUTH_PASS` | Dashboard Basic Auth (middleware) | High — all users must re-login |
| `API_KEY` | Engine ↔ Dashboard proxy, watchdog heartbeat | High — dashboard/engine link breaks |
| `DISCORD_WEBHOOK_FLOW_ALERTS` | Flow alerts (Discord primary channel) | Low — alerts degrade to email fallback |
| `RESEND_API_KEY` | Email fallback alerts | Low — alerts degrade to Discord only (if Discord works) |
| `BLOB_READ_WRITE_TOKEN` | Vercel Blob storage for `flow/latest.json` | Critical — flow feed stops working |

### Rotation Steps

1. **Generate new secret** (use strong random generator, min 32 chars):
   ```bash
   openssl rand -base64 32
   ```

2. **Update in Vercel dashboard** (Settings → Environment Variables):
   - Set new value for target secret
   - Deploy to take effect (automatic redeploy on env var change)

3. **Update external consumers** (if applicable):
   - `FLOW_INGEST_TOKEN`: Update `~/tape/.env` on Windows PC, restart pusher
   - `API_KEY`: Update `engine/.env`, restart engine (if changed)
   - `DASHBOARD_AUTH_*`: Notify users of new credentials

4. **Verify rotation** (monitor for 24h):
   - Check `/api/flow/health` — data still updating?
   - Check Vercel logs — any 401 errors from pusher/watchdog?
   - Check alert channels — Discord/email still working?

5. **Document rotation** in `docs/security-log.md`:
   ```
   ## 2026-10-28 - Quarterly Rotation
   - Rotated: FLOW_INGEST_TOKEN, CRON_SECRET
   - Reason: Routine 90-day rotation
   - Impact: None (pusher updated, alerts stable)
   ```

### Emergency Rotation (Suspected Compromise)

If any secret is suspected compromised:
1. Rotate **immediately** (don't wait for maintenance window)
2. Review Vercel logs (`/api/flow/ingest`, `/api/cron/*`) for unauthorized access
3. Check audit logs (structured JSON logs with `type: "security_audit"`)
4. Alert Matt via Discord + email
5. Consider rotating ALL secrets in inventory as precaution
