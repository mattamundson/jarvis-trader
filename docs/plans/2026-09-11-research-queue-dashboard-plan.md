# JARVIS Research Queue Dashboard Enhancement Plan

**Goal:** Preserve the X-bookmarks research-intel synthesis as a read-only dashboard panel on `/jarvis` without changing engine execution, risk configs, kill-switches, or `.env` values.

**Scope:** Dashboard-only, analysis-only.

**Files:**
- `dashboard/components/ResearchQueuePanel.tsx`
- `dashboard/app/jarvis/page.tsx`
- `dashboard/public/jarvis-research-queue-feed.json`
- `dashboard/tests/e2e/jarvis-research-queue.spec.ts`

**Verification gates:**
1. `./node_modules/.bin/tsc --noEmit`
2. `pnpm run build`
3. `pnpm exec playwright test tests/e2e/jarvis-research-queue.spec.ts --config=playwright.config.ts`

**Safety boundary:** Read-only UI/data artifact. No live trading, risk, kill-switch, order-routing, or engine `.env` changes.
