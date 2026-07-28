// Regression test for GT-08: /parallel-paper's Max DD tile and comparison
// table rendered a real -200.32% drawdown as "-2.0%" -- a 100x understated
// risk figure. Root cause was fmtPct's now-removed "already in percent form"
// branch (`if (Math.abs(val) > 2) return val.toFixed(1) + "%"`), which
// silently skipped the *100 scaling for any fraction with |val| > 2. GET
// /portfolio/paper/account/{id}/stats (engine/routers/portfolio_router.py)
// always returns max_dd as a true fraction of running peak -- it never
// pre-multiplies by 100 -- so -2.0032 genuinely means -200.32%, not -2.0%.
//
// Run: cd dashboard && pnpm run test:unit

import { test } from "node:test";
import assert from "node:assert/strict";
import { fmt, fmtPct, fmtCalmar, statColor } from "../lib/parallelPaperFormat.ts";

// ── fmtPct ───────────────────────────────────────────────────────────────────

test("fmtPct: a -2.0032 max_dd fraction formats to ~-200.3%, not -2.0%", () => {
  assert.equal(fmtPct(-2.0032), "-200.3%");
});

test("fmtPct: ordinary sub-1 fractions still scale correctly", () => {
  assert.equal(fmtPct(0.6667), "66.7%");
  assert.equal(fmtPct(-0.05), "-5.0%");
  assert.equal(fmtPct(0), "0.0%");
});

test("fmtPct: fractions with magnitude > 2 (severe but real drawdowns) scale too", () => {
  // A thin-peak equity curve can legitimately produce |max_dd| well past 2
  // (e.g. peak = $10, trough = -$15 => dd = -2.5 => -250%).
  assert.equal(fmtPct(-2.5), "-250.0%");
  assert.equal(fmtPct(3.14), "314.0%");
});

test("fmtPct: null/undefined/NaN/Infinity render as em-dash", () => {
  assert.equal(fmtPct(null), "—");
  assert.equal(fmtPct(undefined), "—");
  assert.equal(fmtPct(NaN), "—");
  assert.equal(fmtPct(Infinity), "—");
  assert.equal(fmtPct(-Infinity), "—");
});

test("fmtPct: only truly extreme magnitudes (>1000) are flagged as data errors", () => {
  assert.equal(fmtPct(1001), "—(data err)");
  assert.equal(fmtPct(-1001), "—(data err)");
  // 999 is large (99,900%) but still rendered -- not treated as corrupted.
  assert.equal(fmtPct(999), "99900.0%");
});

// ── fmt ──────────────────────────────────────────────────────────────────────

test("fmt: default 2-decimal formatting, em-dash on null", () => {
  assert.equal(fmt(1.23456), "1.23");
  assert.equal(fmt(null), "—");
  assert.equal(fmt(2, 0), "2");
});

// ── fmtCalmar ────────────────────────────────────────────────────────────────

test("fmtCalmar: passthrough via fmt, clamps only extreme magnitudes", () => {
  assert.equal(fmtCalmar(1.5), "1.50");
  assert.equal(fmtCalmar(1500), "—(data err)");
  assert.equal(fmtCalmar(null), "—");
});

// ── statColor ────────────────────────────────────────────────────────────────

test("statColor: sign vs higherBetter direction", () => {
  assert.equal(statColor(5, true), "text-green-400");
  assert.equal(statColor(-5, true), "text-red-400");
  assert.equal(statColor(-5, false), "text-green-400"); // e.g. max_dd: more negative is worse, less negative (closer to 0) or positive reads green here only when val>0
  assert.equal(statColor(null), "text-muted-foreground");
});
