# Dashboard Proxy Runtime Recovery — 1 Hour Plan

> **For Hermes:** Execute this plan task-by-task with verification after each major step.

**Goal:** Restore the dashboard PM2 process to a stable production state, verify that authenticated page loads and server-side engine proxy calls work again, then publish the next ROI queue.

**Architecture:** The dashboard is currently crashing in PM2 because the production build artifacts are missing or stale. The dashboard also relies on server-side env injection for `ENGINE_API_KEY` and Basic Auth via `dashboard/.env.local`. The fastest path is: rebuild the production bundle, restart PM2 with the current env, verify local + tailnet behavior, then only after runtime is stable, publish the next ranked ROI tasks.

**Tech Stack:** Next.js 15, PM2, Playwright, curl, TypeScript, repo docs + session logs.

---

## Current verified state

- `dashboard/.env.local` exists and contains:
  - `DASHBOARD_AUTH_USER`
  - `DASHBOARD_AUTH_PASS`
  - `ENGINE_API_KEY`
- PM2 dashboard process is currently in `waiting restart` and has repeated restarts.
- PM2 logs show the active failure mode:
  - `Could not find a production build in the '.next' directory`
  - missing `.next/prerender-manifest.json`
- Dashboard proxy code reads `ENGINE_API_KEY` server-side in `app/api/engine/[...path]/route.ts`.
- Dashboard Basic Auth middleware is present in `middleware.ts`.

---

## Top 10 ROI tasks for the next hour

### 1) Rebuild the dashboard production bundle
**Objective:** Recreate `.next` so PM2 has a valid production build to serve.

**Files:**
- Read: `dashboard/package.json`
- Build output: `dashboard/.next/`

**Run:**
```bash
cd C:/Users/mattm/ThinkorSwim/jarvis-trader/dashboard
pnpm run build
```

**Success signal:** `next build` completes and `.next/BUILD_ID` exists.

---

### 2) Restart dashboard PM2 with the fresh build
**Objective:** Clear the restart loop and bring `jarvis-dashboard` online.

**Files:**
- Runtime: PM2 `jarvis-dashboard`

**Run:**
```bash
pm2 restart jarvis-dashboard --update-env
pm2 list --no-color
```

**Success signal:** status becomes `online` with non-zero uptime.

---

### 3) Verify unauthenticated and authenticated page behavior
**Objective:** Prove Basic Auth is still enforced locally and over tailnet.

**Files:**
- `dashboard/middleware.ts`
- `dashboard/.env.local`

**Run:**
```bash
curl -I -m 10 http://127.0.0.1:3010/
curl -I -m 10 -u "$DASHBOARD_AUTH_USER:$DASHBOARD_AUTH_PASS" http://127.0.0.1:3010/
```

**Success signal:** unauthenticated request returns `401`, authenticated request returns `200`.

---

### 4) Verify engine proxy auth injection
**Objective:** Confirm `ENGINE_API_KEY` is being injected server-side into `/api/engine/*`.

**Files:**
- `dashboard/app/api/engine/[...path]/route.ts`
- `dashboard/lib/engineProxyHeaders.ts`

**Run:**
```bash
curl -I -m 10 http://127.0.0.1:3010/api/engine/health
curl -I -m 10 http://127.0.0.1:3010/api/engine/safety/status
```

**Success signal:** `/api/engine/health` returns `200`; protected routes stop returning `401` when the dashboard runtime is healthy and env is loaded.

---

### 5) Verify tailnet path end-to-end
**Objective:** Ensure the externally reachable dashboard path behaves the same as localhost.

**Files:**
- PM2 / tailnet runtime

**Run:**
```bash
curl -I -m 10 http://amoszn.taild02579.ts.net/
curl -I -m 10 http://amoszn.taild02579.ts.net/api/engine/health
```

**Success signal:** tailnet root and proxied engine health return `200`.

---

### 6) Run dashboard typecheck
**Objective:** Catch any source-level regressions introduced during the recovery pass.

**Files:**
- Entire `dashboard/` TypeScript tree

**Run:**
```bash
cd C:/Users/mattm/ThinkorSwim/jarvis-trader/dashboard
./node_modules/.bin/tsc --noEmit
```

**Success signal:** exit code 0.

---

### 7) Run fresh Playwright smoke
**Objective:** Prove the page shell and auth/proxy behavior under the fresh-server config.

**Files:**
- `dashboard/playwright.fresh.config.ts`
- `dashboard/tests/e2e/*`

**Run:**
```bash
cd C:/Users/mattm/ThinkorSwim/jarvis-trader/dashboard
pnpm run test:e2e:fresh
```

**Success signal:** smoke passes with no failing pages.

---

### 8) Save the PM2 process snapshot
**Objective:** Preserve the working runtime state for reboot recovery.

**Files:**
- `C:\Users\mattm\.pm2\dump.pm2`

**Run:**
```bash
pm2 save
```

**Success signal:** PM2 reports the list was saved successfully.

---

### 9) Update the dashboard state log
**Objective:** Record the verified runtime state so future recovery starts from facts.

**Files:**
- `docs/session-logs/DASHBOARD_STATE.md`

**Run:**
- Append a concise note only after the runtime is verified.

**Success signal:** log reflects the new state without speculation.

---

### 10) Publish the next ROI task queue
**Objective:** Re-rank the remaining work after the runtime is stable.

**Files:**
- `todo_list`
- optional: `docs/plans/` or a handoff note

**Run:**
- Re-evaluate the remaining tasks after the verified runtime pass.
- Keep only tasks that still unblock runtime, data integrity, or safety.

**Success signal:** a fresh top-10 queue exists and the next highest-ROI item is already started.

---

## Strategy for the hour

1. **Fix the root blocker first:** the dashboard is not serving because the build artifact is missing.
2. **Restore the service, then trust nothing:** restart PM2 only after the build exists.
3. **Verify the exact user-facing paths:** local root, engine proxy, and tailnet.
4. **Only then spend time on hygiene:** typecheck, Playwright, PM2 save, docs, next task queue.

## Completion criteria

- PM2 dashboard online.
- Local `:3010` authenticated and serving.
- `:3010/api/engine/health` returns `200`.
- Tailnet root and engine proxy return `200`.
- Typecheck and fresh Playwright smoke pass.
- PM2 snapshot saved.
- Next ROI batch identified.
