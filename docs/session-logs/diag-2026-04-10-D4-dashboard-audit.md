# Dashboard Data Flow Audit — 2026-04-10

## Status Update — 2026-04-11

This note is partially superseded by subsequent fixes.

- `TokenProxyMetricsWidget.tsx` now uses `fetchEngine()` rather than a hardcoded
  engine URL
- WebSocket helpers now fall back to `window.location.origin` / proxy-aware
  resolution instead of assuming `localhost:8010`
- The dashboard API proxy route requires `ENGINE_URL` or
  `NEXT_PUBLIC_ENGINE_URL` rather than silently defaulting to localhost
- User-facing dashboard copy has been updated to reference the FastAPI engine
  and dashboard proxy generically instead of telling operators to check
  `port 8010`

Treat the sections below as the 2026-04-10 diagnosis snapshot, not as the
current runtime state.

## Executive Summary

**Status**: Dashboard IS running (port 3010, 25/25 routes built). Engine IS responding (port 8010, health OK). **Root cause of empty-data reports: two hardcoded localhost:8010 URLs bypass the production engine endpoint.**

## Findings

### 1. Build & Infrastructure (PASS)
- Build: `pnpm run build` — **PASS** (25 routes, 0 TypeScript errors, 102 kB shared chunks)
- Dashboard running: **CONFIRMED** (port 3010, 2 listeners, process ID 63368)
- Engine health: **CONFIRMED** (`/health` returns OK, paper_mode=true, kill_switch_inactive)

### 2. API Layer Architecture (PASS)
- **Correct path**: `lib/api.ts` uses `const ENGINE = "/api/engine"` (relative, proxied through Next.js)
- **Rewrite rule**: `next.config.ts` lines 16–18 proxy `/api/engine/:path*` to `NEXT_PUBLIC_ENGINE_URL`
- **Environment**: `.env.local` defines `NEXT_PUBLIC_ENGINE_URL=http://172.19.176.1:8010` (Docker host IP)
- **Validation**: Both endpoints return valid data with correct API key:
  - `GET /api/engine/health` → `{"status":"ok", ...}`
  - `GET /api/engine/portfolio` → `{"total_daily_pnl":180.0, ...}`

### 3. Hardcoded URL Violations (FAIL)

Two files hardcode `http://localhost:8010`, bypassing the rewrite and environment configuration:

| File | Line | Issue | Impact |
|------|------|-------|--------|
| `dashboard/app/components/TokenProxyMetricsWidget.tsx` | 20 | `const API_BASE = "http://localhost:8010"` | Direct fetch to localhost fails on non-localhost networks |
| `dashboard/app/components/EngineOfflineBanner.tsx` | Line in JSX | Fallback text displays `localhost:8010` | UI tells user to start engine on wrong address |

**Why this breaks empty-data reports:**
- TokenProxyMetricsWidget attempts `fetch('http://localhost:8010/metrics/...')` directly
- This request fails silently in the browser console (CORS, DNS, or connection refused)
- Widget shows no error to user, just empty state
- User sees "no live data" but engine is healthy on the Docker host IP

### 4. WebSocket & Settings API (PASS)
- `lib/use-websocket.ts`: Correctly uses `process.env.NEXT_PUBLIC_ENGINE_URL || "http://localhost:8010"` fallback
- `lib/engine-websocket-context.tsx`: Correct fallback pattern
- `lib/settings-api.ts`: Marked as "NEVER hardcode" but no direct violations found

## Root Cause

**Hypothesis**: User is running dashboard on non-localhost (WSL2, Docker, remote host), but `TokenProxyMetricsWidget` hardcodes `localhost:8010`. The component silently fails to fetch, rendering empty metrics. User assumes "no live data" when the data fetch layer is misconfigured.

## Phase 1 Fix (Recommended)

**Option A (Code fix, 2 min)**:
- Replace `const API_BASE = "http://localhost:8010"` in `TokenProxyMetricsWidget.tsx` with a call to a helper that reads `NEXT_PUBLIC_ENGINE_URL`
- Update `EngineOfflineBanner.tsx` to use the same pattern

**Option B (Operator action, immediate)**:
- If dashboard was started via `pnpm dev`, kill it and restart with:
  ```bash
  NEXT_PUBLIC_ENGINE_URL=http://172.19.176.1:8010 pnpm dev
  ```
- This overrides `NEXT_PUBLIC_ENGINE_URL` from `.env.local` at runtime

**Recommended**: Option A + confirm `.env.local` is committed (it is). Then verify `pnpm dev` inherits the env var correctly.

## Data Verification

- Engine `/portfolio` endpoint: Responds with valid portfolio data (daily_pnl=180.0)
- Dashboard home page uses correct `fetchEngine()` layer: SWR polling `/api/engine/health` — works correctly
- The 25 dashboard routes all import from `lib/api.ts` correctly

## Conclusion

Dashboard infrastructure is sound. Two hardcoded URLs in widget components break the environment-aware design. **This is a code smell, not a system failure**. Fix the two violations and the dashboard will show live data correctly.

---

**Next Steps**:
1. Fix `TokenProxyMetricsWidget.tsx` line 20 and `EngineOfflineBanner.tsx`
2. Re-run `pnpm run build` to confirm no new errors
3. Restart dashboard and confirm metrics widget populates
