// Contract lock for the JARVIS readiness scorecard API.
// This route is dashboard-local and read-only: it derives a scorecard from report
// artifacts and must not become an execution/risk/safety mutation surface.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";

const DASHBOARD = process.cwd();

function read(rel: string): string {
  return readFileSync(path.join(DASHBOARD, rel), "utf8");
}

test("readiness scorecard API is GET-only, dynamic, no-store, and read-only", () => {
  const route = read("app/api/jarvis/readiness-scorecard/route.ts");
  assert.match(route, /export async function GET\(/);
  assert.doesNotMatch(route, /export async function (POST|PUT|PATCH|DELETE)\(/);
  assert.match(route, /force-dynamic/);
  assert.match(route, /READ_ONLY_ANALYSIS/);
  assert.match(route, /source_health/);
  assert.match(route, /Cache-Control/);
  assert.match(route, /no-store/);
});

test("readiness scorecard builder reads report artifacts, not live execution surfaces", () => {
  const src = read("lib/readinessScorecard.ts");
  for (const token of ["fetch(", "postEngine", "/orders", "/approval", "/safety/status", "kill_switch_active =", "live_trading ="]) {
    assert.ok(!src.includes(token), `readiness scorecard builder must not reference ${token}`);
  }
  assert.match(src, /JARVIS_DASHBOARD_RECOMMENDATION_AUDIT_LATEST\.json/);
  assert.match(src, /JARVIS_RECOMMENDATION_ATTRIBUTION_AUDIT_LATEST\.json/);
  assert.match(src, /JARVIS_RECOMMENDATION_BASELINE_COMPARISON_LATEST\.json/);
  assert.match(src, /reportFreshness/);
  assert.match(src, /Infinity/);
});

test("jarvis page fetches scorecard through the API route", () => {
  const panel = read("components/ReadinessScorecardPanel.tsx");
  assert.match(panel, /\/api\/jarvis\/readiness-scorecard/);
  assert.doesNotMatch(panel, /jarvis-readiness-scorecard\.json/);
});
