#!/usr/bin/env node
// Bundle-size budget gate (Phase 1.5).
//
//   node scripts/check-bundle-budget.mjs <path-to-build-log>
//
// Parses the `next build` route table and enforces a First Load JS budget.
// It reads a log rather than running its own build on purpose: dashboard-build
// already pays ~2 minutes for one, and a second build would double that for a
// number the first one already printed.
//
// Baseline measured on master at 1584f15 (2026-08-01), 51 non-api routes,
// max 234 kB, min 103 kB. Every threshold below is set against that measurement,
// not against the figures in the completion plan -- those predate the
// static/dynamic double-import defect being understood and at least one of them
// is demonstrably stale (the plan records /regime as optimized 234 -> 125 kB;
// it measures 234 kB on master today).

import { readFileSync } from "node:fs";

const HARD_KB = 225; // fail
const WARN_KB = 175; // report, do not fail

// Routes permitted to exceed HARD_KB, each with a reason and the size recorded
// when it was granted. This is debt, not approval -- an entry means "known and
// accepted for now", and the recorded size is a ceiling: if the route grows
// past it the build still fails.
const ALLOWLIST = new Map([
  ["/regime", { kb: 234, why: "charting-heavy regime view; over budget on master at the time the gate landed. Phase 5.3 owns the fix." }],
]);

const logPath = process.argv[2];
if (!logPath) {
  console.error("usage: check-bundle-budget.mjs <build-log>");
  process.exit(2);
}

function toKB(tok) {
  const m = tok.match(/^([\d.]+)\s*(B|kB|MB)$/);
  if (!m) return null;
  const v = parseFloat(m[1]);
  return m[2] === "B" ? v / 1024 : m[2] === "MB" ? v * 1024 : v;
}

const lines = readFileSync(logPath, "utf8").split(/\r?\n/);
const routes = [];
for (const line of lines) {
  // Route rows carry a render-mode glyph: o static, f dynamic, etc.
  if (!/[○●ƒλ]/.test(line)) continue;
  const r = line.match(/(\/[^\s]*)/);
  if (!r) continue;
  const sizes = [...line.matchAll(/([\d.]+\s*(?:B|kB|MB))/g)].map((m) => m[1].replace(/\s+/g, " "));
  if (sizes.length < 2) continue; // "First Load JS shared by all" rows etc.
  const kb = toKB(sizes[sizes.length - 1]);
  if (kb === null) continue;
  routes.push({ route: r[1], kb });
}

// A silently-empty parse would turn this gate into a no-op that reports success,
// which is worse than not having it. Fail loudly instead.
if (routes.length === 0) {
  console.error("ERROR: parsed 0 route rows from the build log.");
  console.error("The `next build` route table format likely changed, or the log is truncated.");
  console.error("Refusing to report success from a gate that measured nothing.");
  process.exit(1);
}

const pages = routes.filter((r) => !r.route.startsWith("/api/"));
const over = [];
const warn = [];
const staleAllow = new Set(ALLOWLIST.keys());

for (const r of pages) {
  staleAllow.delete(r.route);
  const allowed = ALLOWLIST.get(r.route);
  if (allowed) {
    if (r.kb > allowed.kb) {
      over.push(`${r.route} ${r.kb} kB exceeds its recorded allowlist ceiling of ${allowed.kb} kB`);
    }
    continue;
  }
  if (r.kb > HARD_KB) over.push(`${r.route} ${r.kb} kB over hard budget ${HARD_KB} kB`);
  else if (r.kb > WARN_KB) warn.push(`${r.route} ${r.kb} kB`);
}

console.log(`Parsed ${routes.length} route rows (${pages.length} non-api).`);
console.log(`Budget: hard ${HARD_KB} kB, warn ${WARN_KB} kB. Allowlisted: ${[...ALLOWLIST.keys()].join(", ") || "none"}`);

if (warn.length) {
  console.log(`\nWARN (${warn.length} route(s) over ${WARN_KB} kB, not failing):`);
  for (const w of warn) console.log(`  ${w}`);
}

// An allowlist entry for a route that no longer exists silently grants immunity
// to nothing, and hides the fact that the debt was paid. Surface it.
if (staleAllow.size) {
  console.log(`\nNOTE stale allowlist entr(ies) -- no such route in the build: ${[...staleAllow].join(", ")}`);
  console.log("     Remove them from ALLOWLIST.");
}

if (over.length) {
  console.error(`\nFAIL bundle budget (${over.length}):`);
  for (const o of over) console.error(`  ${o}`);
  console.error("\nLazy-load the heavy widget with next/dynamic, or justify it in ALLOWLIST with a reason.");
  process.exit(1);
}

console.log("\nBundle budget OK.");
