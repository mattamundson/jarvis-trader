// Per-panel pull-time / stale warning helpers.
// Run: cd dashboard && pnpm run test:unit

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  ageMs,
  freshnessLevel,
  formatPullTimeCt,
  staleWarning,
} from "../lib/panelFreshness.ts";

const NOW = new Date("2026-11-05T23:10:00Z"); // 17:10 CT (UTC-6)

test("ageMs returns null for missing pull time", () => {
  assert.equal(ageMs(null, NOW), null);
  assert.equal(ageMs(undefined, NOW), null);
});

test("freshnessLevel live / delayed / stale thresholds", () => {
  assert.equal(freshnessLevel(new Date(NOW.getTime() - 10_000), { now: NOW }), "live");
  assert.equal(freshnessLevel(new Date(NOW.getTime() - 90_000), { now: NOW }), "delayed");
  assert.equal(freshnessLevel(new Date(NOW.getTime() - 400_000), { now: NOW }), "stale");
  assert.equal(freshnessLevel(null, { now: NOW }), "missing");
});

test("formatPullTimeCt uses America/Chicago", () => {
  // 23:10Z on 2026-11-05 is 17:10 CT (CDT ended; CST = UTC-6)
  assert.equal(formatPullTimeCt(NOW, NOW), "17:10:00 CT");
});

test("staleWarning only fires when missing or stale", () => {
  assert.equal(staleWarning(new Date(NOW.getTime() - 10_000), { now: NOW }), null);
  assert.match(staleWarning(new Date(NOW.getTime() - 400_000), { now: NOW }) ?? "", /Stale/);
  assert.match(staleWarning(null, { now: NOW }) ?? "", /No pull time/);
});
