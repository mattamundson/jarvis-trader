// Wiring/contract lock for the SPX intraday analysis module (read-only surface).
//
// Pattern follows the repo's established source-wiring tests (e.g.
// honestTradesUnavailable.node.test.ts): assert the *wiring*, not the runtime,
// so a future edit that accidentally turns this analysis-only panel into an
// order/risk-touching surface fails CI loudly.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";

const DASHBOARD = process.cwd();

function read(rel: string): string {
  return readFileSync(path.join(DASHBOARD, rel), "utf8");
}

test("spx-intraday route is GET-only, dynamic, and analysis-only", () => {
  const src = read("app/api/spx-intraday/route.ts");
  assert.match(src, /export async function GET\(/);
  assert.doesNotMatch(src, /export async function (POST|PUT|PATCH|DELETE)\(/);
  assert.match(src, /force-dynamic/);
  assert.match(src, /ANALYSIS_ONLY/);
  assert.match(src, /orders_enabled: false/);
  assert.match(src, /risk_config_touched: false/);
});

test("spx data layer never touches approval, order, or safety endpoints", () => {
  const src = read("lib/spxIntraday/data.ts");
  for (const banned = ["/approval", "/orders", "/paper", "/safety", "postEngine"]; banned.length > 0; ) {
    const token = banned.pop() as string;
    assert.ok(!src.includes(token), `data.ts must not reference ${token}`);
  }
  assert.match(src, /\/api\/engine\/prices\/snapshot/);
  assert.match(src, /\/api\/engine\/analyze\/bars\//);
  assert.match(src, /Authorization: authorization/);
});

test("spx route forwards the incoming Authorization header to its own engine calls", () => {
  const route = read("app/api/spx-intraday/route.ts");
  assert.match(route, /request\.headers\.get\("authorization"\)/);
  assert.match(route, /fetchSpxIntradayInputs\(origin, request\.headers\.get\("authorization"\)\)/);
});

test("analysis page and card stay order-free and carry the ANALYSIS ONLY label", () => {
  const card = read("components/SpxIntradayAnalysisCard.tsx");
  assert.match(card, /ANALYSIS ONLY/);
  assert.ok(!card.includes("postEngine"), "card must never POST");

  const page = read("app/analysis/spx/page.tsx");
  assert.match(page, /ANALYSIS ONLY/);
  assert.ok(!page.includes("postEngine"), "page must never POST");
});

test("hook polls the dashboard's own read-only route via localFetch", () => {
  const hook = read("hooks/useSpxIntradayAnalysis.ts");
  assert.match(hook, /localFetch/);
  assert.match(hook, /\/api\/spx-intraday/);
  assert.ok(!hook.includes("fetchEngine("), "hook must not bypass the local route");
});

test("mission control mounts the card inside an error boundary", () => {
  const page = read("app/mission-control/page.tsx");
  assert.match(page, /SpxIntradayAnalysisCard/);
  assert.match(page, /WidgetErrorBoundary name="SPX Intraday Decision"/);
});
