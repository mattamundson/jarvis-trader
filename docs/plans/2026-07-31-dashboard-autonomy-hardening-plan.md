# Dashboard Autonomy Hardening Implementation Plan

<<<<<<< HEAD
=======
> **SUPERSEDED 2026-08-01:** This plan is superseded by
> `C:\Users\mattm\.claude\plans\squishy-discovering-sunrise.md`, which is now the
> current finish-line plan for the dashboard completion work (Phases 4/6/9/10/12
> drain and beyond). Kept on disk per the never-delete rule; do not use this doc
> to pick up new work.

>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
> **For Hermes:** Use this as the current finish-line plan for the JARVIS dashboard hardening/autonomy foundation work. Do not continue open-ended optimization without checking the phase exit criteria below.

**Goal:** Make JARVIS a fast, reliable, test-protected trading operating system dashboard that is ready for safe real-time/autonomy work.

**Architecture:** Keep dashboard changes incremental and measured. Use Next.js dynamic imports only for chart/data-heavy widgets, protect critical routes with Playwright smoke tests, and gate all changes with typecheck + production build + E2E. Autonomy work comes after the dashboard can reliably show correct state and degraded states.

**Tech Stack:** Next.js 15, React, SWR, Playwright, pnpm, FastAPI engine via `/api/engine`, dashboard on port 3010.

---

## Phase 1 — Bundle + route performance hardening

**Status:** In progress; core wins already landed.

**Goal:** Bring all operator-critical dashboard pages into an acceptable first-load range without breaking degraded/offline rendering.

**Finish line:**
- `/`, `/command-center`, `/discord`, `/regime`, `/backtest`, `/performance`, `/validation` build cleanly.
- Target first-load JS:
  - Ideal: under 175 kB for most operator pages.
  - Acceptable: under 225 kB for pages with justified visualization/analytics load.
- Every dynamic-import pass has measurable route-table benefit or is reverted.
- `pnpm run build` passes.

**Current measured wins:**
- `/discord`: ~220 kB → 113 kB first load.
- `/regime`: ~234 kB → 125 kB first load.
- `/backtest`: ~189 kB → 134 kB first load.
- `/performance`: ~221 kB → 160-161 kB first load.

**Remaining candidates:**
- `/validation`: still ~198-199 kB; acceptable but still candidate.
- `/analysis`: ~189 kB; candidate.
- `/today`: ~177 kB; borderline candidate.
- `/trades/[id]/review`: ~184 kB; candidate.

### Task 1.1: Review route table after each production build

**Files:**
- Read build output from `pnpm run build`.

**Command:**
```bash
cd dashboard && pnpm run build
```

**Expected:** build passes; route table lists First Load JS.

**Stop rule:** Do not optimize pages that are already acceptable unless the route table identifies them as current outliers.

### Task 1.2: Defer only chart/data-heavy widgets

**Files:**
- Modify page files under `dashboard/app/**/page.tsx`.

**Pattern:**
```tsx
const DynamicWidget = dynamic(
  () => import("@/components/Widget").then(mod => ({ default: mod.Widget })),
  { ssr: false, loading: () => <Skeleton label="Loading..." /> }
);
```

**Verification:**
```bash
cd dashboard
./node_modules/.bin/tsc --noEmit
pnpm run build
pnpm exec playwright test tests/e2e --reporter=line
```

---

## Phase 2 — E2E regression shield

**Status:** Complete for current critical-route set.

**Goal:** Every operator-critical route has at least a smoke test proving it renders under degraded/offline engine data and does not white-screen.

**Finish line:**
- Existing and new Playwright tests pass.
- Smoke coverage exists for:
  - `/`
  - `/command-center`
  - `/performance`
  - `/validation`
  - `/discord`
  - `/regime`
  - `/backtest`
- Tests use mocked `/api/engine/**` responses where needed.
- Tests assert visible user-facing state, not brittle page-source strings.

### Task 2.1: Add smoke test for `/discord`

**File:**
- Create `dashboard/tests/e2e/discord.spec.ts`

**Verification:**
```bash
cd dashboard && pnpm exec playwright test tests/e2e/discord.spec.ts --reporter=line
```

### Task 2.2: Add smoke test for `/regime`

**File:**
- Create `dashboard/tests/e2e/regime.spec.ts`

**Verification:**
```bash
cd dashboard && pnpm exec playwright test tests/e2e/regime.spec.ts --reporter=line
```

### Task 2.3: Add smoke test for `/backtest`

**File:**
- Create `dashboard/tests/e2e/backtest.spec.ts`

**Verification:**
```bash
cd dashboard && pnpm exec playwright test tests/e2e/backtest.spec.ts --reporter=line
```

### Task 2.4: Run full E2E suite

**Command:**
```bash
cd dashboard && pnpm exec playwright test tests/e2e --reporter=line
```

**Expected:** all E2E tests pass.

**Completed verification:** `pnpm exec playwright test tests/e2e --reporter=line` → 11 passed.

---

## Phase 3 — Real-time freshness / WebSocket revalidation

**Status:** Initial implementation complete for `/command-center` and `/portfolio`.

**Goal:** Critical dashboard cards update quickly after engine events without unsafe SWR typing wrappers.

**Finish line:**
- `/command-center` critical keys revalidate on order/safety/kill-switch events.
- `/portfolio` summary/health/capital revalidate on relevant events.
- TypeScript passes with direct `mutate()` revalidation calls.
- No generic `(key, data?) => void` mutator wrapper.
- E2E suite still passes.

**Safe pattern:**
```tsx
const { data, mutate } = useSWR<KeyType>("/api-key", fetcher, { refreshInterval });

useWebSocket(undefined, (event) => {
  if (event.type === "order_fill" || event.type === "kill_switch" || event.type === "safety_event") {
    mutate();
  }
});
```

**Implementation note:** SWR `shouldRetryOnError` belongs on `useSWR(...)` options, not `mutate(...)` options. The typed revalidation path is `mutate()`.

**Completed verification:** `./node_modules/.bin/tsc --noEmit && pnpm run build && pnpm exec playwright test tests/e2e --reporter=line` → exit 0, 11 passed.

---

## Phase 4 — Operator observability

**Status:** Initial global freshness strip complete.

**Goal:** The dashboard should make system trust state obvious at a glance.

**Finish line:**
- A top-level freshness/status strip reports:
  - Engine reachable/unreachable.
  - WebSocket connected/disconnected.
  - Last successful data refresh.
  - Master API reachable/unreachable.
  - Sample/offline/degraded data labels.
- Degraded states are visible and non-catastrophic.
- E2E covers one degraded state for each critical route.

**Completed:** Added `SystemFreshnessStrip` to the root dashboard layout showing engine reachability, WebSocket connection state, last health check freshness, and last WebSocket event type/age.

**Remaining Phase 4 work:** Add a lightweight master-api reachability endpoint/indicator and expand degraded-state route assertions where useful.

**Completed verification:** `./node_modules/.bin/tsc --noEmit && pnpm run build` → exit 0; `pnpm exec playwright test tests/e2e --reporter=line` → 11 passed.

---

## Phase 5 — Safe autonomy foundation

**Status:** Planned after observability.

**Goal:** Agents can help research, summarize, triage, and recommend without silently changing live risk/execution config.

**Finish line:**
- Clear permission model:
  - Read/analyze/summarize: allowed.
  - Draft recommendations: allowed.
  - Change live risk/execution config: requires safety-review PR.
  - Enable/disable symbols: requires safety-review PR.
- Agent actions are auditable in UI/logs.
- Options and futures receive equal priority in roadmap and UI.
- Daily/weekly loops produce reviewable outputs, not silent config changes.

---

## Current next action

Continue Phase 4: add lightweight master-api reachability observability, then decide whether to proceed to Phase 5 safe autonomy foundation.

## Global verification gate before calling any phase complete

```bash
cd dashboard
./node_modules/.bin/tsc --noEmit
pnpm run build
pnpm exec playwright test tests/e2e --reporter=line
```

A phase is not complete unless those pass or a blocker is documented with the exact failing command and output.
