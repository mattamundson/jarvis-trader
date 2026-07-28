// Regression test for GT-26 (dashboard-integrity backlog, 2026-07-27).
//
// A structural Playwright audit recorded 502s across 10 routes (root, backtest,
// command-center, journal-review, parallel-paper, performance, research-log,
// scorecard, stats, validation) on paths with a doubled "master/master" segment,
// e.g. GET /api/master/master/trading/realized and /api/master/master/status.
// The doubled segment looked like the same class of bug as the confirmed
// /llm/llm/test double-prefix (see memory project_llm_cascade_kimi_topup_2026_07_26),
// so it was tracked as a suspected proxy/rewrite misconfiguration.
//
// Investigated live 2026-07-27 -- the hypothesis did NOT hold:
//   - app/api/master/[...path]/route.ts is a pure passthrough: it forwards whatever
//     comes after "/api/master/" verbatim to `${MASTER_API_URL}/${path}`, adding no
//     prefix of its own.
//   - The upstream master-api service's OWN routes are namespaced under "master/"
//     (confirmed by AGENTS.md's "External service: master-api" section and by
//     MasterApiCircuitBreaker.test.ts's doc comment, both of which cite
//     "/master/status" and "/master/trading/realized" as the real upstream paths).
//   - Live proxy test: both the "doubled" path (/api/master/master/trading/realized)
//     and a hypothetical "single" path (/api/master/trading/realized) returned the
//     identical 502 `{"error":"master_proxy_failed", ..., "message":"fetch failed"}`
//     from the proxy, because the external master-api service (port 8030 -- a
//     separate, out-of-repo service that is "not started by the engine/dashboard",
//     per AGENTS.md) was simply not running. Confirmed via a direct TCP check on
//     127.0.0.1:8030 (connection refused) at the same time.
//
// Conclusion: BASE ("/api/master") is only the local Next.js proxy mount point;
// "master/..." in each call below is the upstream service's own route namespace.
// The doubled segment is intentional and load-bearing -- stripping it would silently
// misroute every one of these calls (e.g. to /status instead of /master/status) the
// next time master-api actually is reachable, which is a worse failure mode than the
// honest 502 it replaces. This test locks in the constructed URLs so nobody "fixes"
// the duplication away based on how it looks in a browser network tab.
//
// Run: cd dashboard && node --test --experimental-strip-types --import ./tests/_register-alias.mjs tests/masterApiProxyPaths.node.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  fetchMasterStatus,
  fetchFinancesDetail,
  fetchRealizedPnl,
  fetchMasterSchedulerStatus,
  fetchMasterSchedulerRuns,
} from "../lib/masterApi.ts";

function withMockedFetch(url: string, body: unknown, fn: () => Promise<unknown>) {
  const original = globalThis.fetch;
  let capturedUrl: string | null = null;
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    capturedUrl = typeof input === "string" ? input : input.toString();
    return new Response(JSON.stringify(body), { status: 200 });
  }) as typeof fetch;
  return fn()
    .then(() => capturedUrl)
    .finally(() => {
      globalThis.fetch = original;
    });
}

test("fetchMasterStatus requests /api/master/master/status (doubled segment is intentional)", async () => {
  const url = await withMockedFetch("", {}, () =>
    fetchMasterStatus().catch(() => undefined),
  );
  assert.equal(url, "/api/master/master/status");
});

test("fetchFinancesDetail requests /api/master/master/finances/detail", async () => {
  const url = await withMockedFetch("", {}, () =>
    fetchFinancesDetail().catch(() => undefined),
  );
  assert.equal(url, "/api/master/master/finances/detail");
});

test("fetchRealizedPnl requests /api/master/master/trading/realized", async () => {
  const url = await withMockedFetch("", {}, () =>
    fetchRealizedPnl().catch(() => undefined),
  );
  assert.equal(url, "/api/master/master/trading/realized");
});

test("fetchMasterSchedulerStatus requests /api/master/master/scheduler/status", async () => {
  const url = await withMockedFetch("", {}, () =>
    fetchMasterSchedulerStatus().catch(() => undefined),
  );
  assert.equal(url, "/api/master/master/scheduler/status");
});

test("fetchMasterSchedulerRuns requests /api/master/master/scheduler/runs?limit=8", async () => {
  const url = await withMockedFetch("", {}, () =>
    fetchMasterSchedulerRuns().catch(() => undefined),
  );
  assert.equal(url, "/api/master/master/scheduler/runs?limit=8");
});
