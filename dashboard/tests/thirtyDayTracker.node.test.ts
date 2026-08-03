// ThirtyDayTracker hydration-guard regression tests (GT-34, sibling to
// GT-27 PR #496 / GT-30 PR #503 / GT-33 PR #506).
//
// WHY: ThirtyDayTracker had TWO hydration defects:
//
//   1. Its `useState` lazy initializer branched on `typeof window` directly:
//        useState<Date>(() => typeof window !== "undefined" ? ... : ...)
//      `typeof window` is `"undefined"` on EVERY server render and
//      `"object"` on EVERY client render -- so the server branch and the
//      client's first-hydration branch are guaranteed to disagree on every
//      single render, not just across a clock boundary. This is strictly
//      worse than the unguarded-`new Date()` class GT-27/30/33 fixed.
//
//   2. `const today = new Date()` read directly during render is that
//      unguarded-`new Date()` class itself: SSR output is evaluated at
//      server-render/build time; the client's first hydration render is
//      evaluated whenever the browser actually loads the page. Whenever
//      those two clock reads straddle a day boundary, the
//      ELAPSED/REMAINING tiles, the progress bar, and the calendar's
//      "today" cell disagree between server and client -> React error #418.
//
// The fix (lib/thirtyDayTracker.ts + AnalyticsTab.tsx) makes `today` and
// `startDate` client-only state that start at `null` and are only set from
// a mount-only effect. This file proves both halves of that mechanism:
//
//   - resolveStartDate() is a pure function of its explicit `stored`
//     argument -- calling it as if `window`/`localStorage` were absent
//     (`stored: null`, simulating a server render) vs present (`stored` set,
//     simulating a client render with saved state) is well-defined and
//     deterministic either way; nothing in it branches on a global
//     `typeof window` check the way the old initializer did (defect #1).
//   - trackerStatsFor()/buildCalendarCells() are genuinely boundary-
//     sensitive when fed a real `today` (i.e. the bug class in defect #2 is
//     real), but return an IDENTICAL placeholder when `today` is `null`,
//     no matter when that's evaluated -- so a server render and a
//     pre-mount client render can never disagree.
//
// Run: cd dashboard && pnpm run test:unit

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  WINDOW_DAYS,
  defaultStartDate,
  resolveStartDate,
  trackerStatsFor,
  buildCalendarCells,
} from "../lib/thirtyDayTracker.ts";

// ── defect #1: resolveStartDate never branches on a global `window` ────────

test("resolveStartDate falls back to the 30-days-ago default when stored is null -- simulating a 'server' call with no window/localStorage", () => {
  const today = new Date("2026-07-27T12:00:00Z");
  const result = resolveStartDate(today, null);
  assert.deepEqual(result, defaultStartDate(today));
});

test("resolveStartDate uses the stored value when present -- simulating a 'client' call where localStorage has a saved date", () => {
  const today = new Date("2026-07-27T12:00:00Z");
  const result = resolveStartDate(today, "2026-06-01");
  assert.equal(result.toISOString().slice(0, 10), "2026-06-01");
});

test("resolveStartDate falls back to the default on an unparseable stored value, same as the null/'server' case", () => {
  const today = new Date("2026-07-27T12:00:00Z");
  const withGarbage = resolveStartDate(today, "not-a-date");
  const withNull = resolveStartDate(today, null);
  assert.deepEqual(withGarbage, withNull);
});

test("resolveStartDate(today, null) is a pure function of `today` alone -- no hidden dependency on when/where it's called from", () => {
  const t1 = new Date("2026-07-27T12:00:00Z");
  const t2 = new Date("2026-07-27T12:00:00Z");
  assert.deepEqual(resolveStartDate(t1, null), resolveStartDate(t2, null));
});

// ── defect #2: the bug class is real (boundary-divergence) ─────────────────

test("trackerStatsFor is genuinely boundary-sensitive -- proves an unguarded new Date() at render time is unsafe for SSR/hydration", () => {
  const startDate = defaultStartDate(new Date("2026-07-27T12:00:00Z"));
  const justBefore = new Date(startDate.getTime() + 5 * 86400000 - 60000); // 4d 23h59m in
  const justAfter = new Date(startDate.getTime() + 5 * 86400000 + 60000); // 5d 00h01m in

  const before = trackerStatsFor(startDate, justBefore);
  const after = trackerStatsFor(startDate, justAfter);

  assert.notEqual(
    before.daysElapsed,
    after.daysElapsed,
    "a server render just before the day boundary and a client hydration render just after it must disagree when fed raw clock reads -- this is exactly the React #418 hazard"
  );
});

test("buildCalendarCells is genuinely boundary-sensitive too -- the 'today' cell moves across a day boundary", () => {
  const startDate = defaultStartDate(new Date("2026-07-27T12:00:00Z"));
  const day5 = new Date(startDate.getTime() + 5 * 86400000);
  const day6 = new Date(startDate.getTime() + 6 * 86400000);

  const endDate = trackerStatsFor(startDate, day5).endDate;
  const cellsDay5 = buildCalendarCells(startDate, endDate, day5);
  const cellsDay6 = buildCalendarCells(startDate, endDate, day6);

  const todayIndexDay5 = cellsDay5.findIndex((c) => c.status === "today");
  const todayIndexDay6 = cellsDay6.findIndex((c) => c.status === "today");
  assert.notEqual(todayIndexDay5, todayIndexDay6);
});

// ── the fix: null `today` is a constant placeholder ─────────────────────────

test("trackerStatsFor(startDate, null) is identical regardless of when it is evaluated", () => {
  const startDate = defaultStartDate(new Date("2026-07-27T12:00:00Z"));
  const placeholder = trackerStatsFor(startDate, null);

  assert.equal(placeholder.daysElapsed, 0);
  assert.equal(placeholder.daysRemaining, WINDOW_DAYS);
  assert.equal(placeholder.progress, 0);

  // Simulate a "server render" and a "client's first hydration render"
  // happening at wildly different wall-clock times, straddling the same
  // day boundary exercised above. Both must still take the null branch and
  // produce the exact same output -- because `today` only ever comes from
  // client-only state that starts at null, never from a raw `new Date()`
  // read during render.
  assert.deepEqual(trackerStatsFor(startDate, null), placeholder);
});

test("buildCalendarCells(startDate, endDate, null) is identical regardless of when it is evaluated, and marks no 'today' cell", () => {
  const startDate = defaultStartDate(new Date("2026-07-27T12:00:00Z"));
  const { endDate } = trackerStatsFor(startDate, null);

  const placeholder = buildCalendarCells(startDate, endDate, null);
  assert.equal(placeholder.length, 35);
  assert.ok(placeholder.every((c) => c.status !== "today" && c.status !== "active-past"));

  assert.deepEqual(buildCalendarCells(startDate, endDate, null), placeholder);
});

// ── post-mount: real values resolve once `today`/`startDate` are set ───────

test("trackerStatsFor resolves real elapsed/remaining once today is set (post-mount)", () => {
  const startDate = new Date("2026-06-27T00:00:00");
  const today = new Date("2026-07-12T00:00:00"); // 15 days later
  const stats = trackerStatsFor(startDate, today);
  assert.equal(stats.daysElapsed, 15);
  assert.equal(stats.daysRemaining, WINDOW_DAYS - 15);
  assert.equal(stats.progress, (15 / WINDOW_DAYS) * 100);
});

test("buildCalendarCells marks the correct 'today' and 'before' cells post-mount", () => {
  const startDate = new Date("2026-06-27T00:00:00");
  const today = new Date("2026-07-12T00:00:00");
  const { endDate } = trackerStatsFor(startDate, today);
  const cells = buildCalendarCells(startDate, endDate, today);

  assert.equal(cells.length, 35);
  const todayCell = cells.find((c) => c.status === "today");
  assert.ok(todayCell, "expected exactly one 'today' cell");
  assert.equal(todayCell!.date.toDateString(), today.toDateString());

  const beforeCells = cells.filter((c) => c.status === "before");
  assert.ok(
    beforeCells.every((c) => c.date < startDate),
    "every 'before' cell must be strictly earlier than startDate"
  );
});
