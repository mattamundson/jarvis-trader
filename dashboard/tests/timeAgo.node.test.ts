// ApprovalPanel `timeAgo` regression test (GT-33 audit).
//
// UNLIKE the other 4 GT-33 fixes (cumulativeTradingDays, monthlyTarget,
// calendarHeatmap, dailyPnlCalendar) and GT-27/GT-30, this file does NOT
// test a hydration-guard mechanism, because ApprovalPanel doesn't need one
// for `timeAgo`: its only call site is gated behind useSWR's
// `isLoading`/`data` readiness, so it never executes on the shared
// server-render / first-hydration-render pass -- see the full reasoning in
// lib/timeAgo.ts and the GT-33 PR description's per-file judgment-call
// notes. This test instead just proves ordinary correctness of the
// extracted pure function (still valuable: it used to read the clock
// internally via `new Date()`, which made it untestable without faking the
// system clock).
//
// Run: cd dashboard && pnpm run test:unit
//   (node --test --experimental-strip-types "tests/**/*.node.test.ts")

import { test } from "node:test";
import assert from "node:assert/strict";
import { timeAgo } from "../lib/timeAgo.ts";

test('timeAgo returns "just now" for sub-minute deltas', () => {
  const now = new Date("2026-07-15T12:00:30Z");
  assert.equal(timeAgo("2026-07-15T12:00:00Z", now), "just now");
});

test("timeAgo returns minutes for sub-hour deltas", () => {
  const now = new Date("2026-07-15T12:34:00Z");
  assert.equal(timeAgo("2026-07-15T12:00:00Z", now), "34m ago");
});

test("timeAgo returns hours for sub-day deltas", () => {
  const now = new Date("2026-07-15T15:00:00Z");
  assert.equal(timeAgo("2026-07-15T12:00:00Z", now), "3h ago");
});

test("timeAgo falls back to the raw ISO string at/after 24h", () => {
  const created = "2026-07-14T12:00:00Z";
  const now = new Date("2026-07-15T12:00:01Z");
  assert.equal(timeAgo(created, now), created);
});

test("timeAgo is a pure function of (isoString, now) -- no hidden clock dependency", () => {
  const now = new Date("2026-07-15T12:34:00Z");
  const a = timeAgo("2026-07-15T12:00:00Z", now);
  const b = timeAgo("2026-07-15T12:00:00Z", now);
  assert.equal(a, b);
});
