// Keeps tests/e2e/_routes.ts honest against the real app/ directory.
//
// This is the test that makes route coverage self-maintaining: add a page.tsx
// without a manifest entry and this FAILS, so a new route cannot quietly ship
// with zero E2E coverage.

import test from "node:test";
import assert from "node:assert/strict";
import { readdirSync, statSync } from "node:fs";
import { join, relative, sep, dirname } from "node:path";
import { fileURLToPath } from "node:url";

import { ROUTES, LANDMARK_DEBT } from "./e2e/_routes.ts";

const HERE = dirname(fileURLToPath(import.meta.url));
const APP_DIR = join(HERE, "..", "app");

function collectPageFiles(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) collectPageFiles(full, out);
    else if (entry === "page.tsx") out.push(full);
  }
  return out;
}

function routeFromFile(file: string): string {
  const segments = relative(APP_DIR, file).split(sep).slice(0, -1);
  // Route groups -- (trading), (research) -- are URL-invisible. Drop them so
  // introducing route groups does not require rewriting every manifest entry.
  const visible = segments.filter((s) => !(s.startsWith("(") && s.endsWith(")")));
  return visible.length === 0 ? "/" : "/" + visible.join("/");
}

const actualRoutes = collectPageFiles(APP_DIR).map(routeFromFile).sort();
const manifestRoutes = ROUTES.map((r) => r.path).sort();

test("every app/ route has a manifest entry", () => {
  const missing = actualRoutes.filter((r) => !manifestRoutes.includes(r));
  assert.deepEqual(
    missing,
    [],
    `Route(s) exist in dashboard/app but are absent from tests/e2e/_routes.ts: ${missing.join(", ")}. ` +
      `Add an entry so the route gets E2E smoke coverage.`,
  );
});

test("every manifest entry corresponds to a real route", () => {
  const stale = manifestRoutes.filter((r) => !actualRoutes.includes(r));
  assert.deepEqual(
    stale,
    [],
    `Manifest entr(ies) in tests/e2e/_routes.ts have no page.tsx: ${stale.join(", ")}. ` +
      `Remove them, or the suite is asserting against routes that no longer exist.`,
  );
});

test("manifest has no duplicate paths", () => {
  const seen = new Set<string>();
  const dupes: string[] = [];
  for (const p of manifestRoutes) {
    if (seen.has(p)) dupes.push(p);
    seen.add(p);
  }
  assert.deepEqual(dupes, [], `Duplicate manifest paths: ${dupes.join(", ")}`);
});

test("redirect entries declare a target", () => {
  for (const r of ROUTES.filter((x) => x.kind === "redirect")) {
    assert.ok(
      r.target && r.target.startsWith("/"),
      `Redirect route ${r.path} must declare a target path so the smoke test can assert where it lands.`,
    );
  }
});

test("dynamic entries declare a sample path", () => {
  for (const r of ROUTES.filter((x) => x.kind === "dynamic")) {
    assert.ok(
      r.samplePath && !r.samplePath.includes("["),
      `Dynamic route ${r.path} must declare a concrete samplePath to exercise.`,
    );
  }
});

// Ratchet. Pages sharing the generic "JARVIS TRADER" <h1> cannot prove the right
// page rendered, so they carry landmark: null. That debt may shrink, never grow
// -- otherwise new routes quietly join the untestable pile.
const LANDMARK_DEBT_CEILING = 21;

test("landmark debt does not grow", () => {
  assert.ok(
    LANDMARK_DEBT <= LANDMARK_DEBT_CEILING,
    `${LANDMARK_DEBT} page routes lack a distinctive landmark, ceiling is ${LANDMARK_DEBT_CEILING}. ` +
      `Give the new route a landmark that actually appears on it -- do not raise the ceiling.`,
  );
  assert.ok(
    LANDMARK_DEBT >= LANDMARK_DEBT_CEILING - 3,
    `Landmark debt dropped to ${LANDMARK_DEBT} (ceiling ${LANDMARK_DEBT_CEILING}). ` +
      `Lower LANDMARK_DEBT_CEILING to ${LANDMARK_DEBT} to lock the improvement in.`,
  );
});
