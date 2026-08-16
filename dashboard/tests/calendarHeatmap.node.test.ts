// CalendarHeatmap hydration-guard regression test (GT-33, sibling to GT-27 /
// PR #496 on DailyPnLCalendarWidget and GT-30 / PR #503 on WeeklyPnLCard).
//
// WHY: CalendarHeatmap used to call `new Date()` directly during render to
// build the current month's calendar grid, label, and "is today" highlight.
// SSR output is evaluated at server-render/build time; the client's first
// hydration render is evaluated whenever the browser actually loads the
// page. When those two clock reads straddle a day/month boundary, the
// server and the client disagree on the month label, the grid cells, and
// which cell is "today" -> React error #418. The fix (lib/calendarHeatmap.ts
// + CalendarHeatmap.tsx) starts `today` at `null` and only sets it from a
// mount-only effect -- while `today` is `null` the component renders its
// existing loading skeleton, so both the server render and the client's
// first paint always agree, regardless of what time either one runs at.
//
// This test proves both halves of that mechanism:
//   1. buildCalendarMonth() is genuinely boundary-sensitive (i.e. the bug
//      class is real).
//   2. calendarDisplayFor(null) is constant (`null`) no matter what date
//      it's evaluated "at" -- so a server render and a pre-mount client
//      render can never disagree, closing off the mismatch.
//
// Run: cd dashboard && pnpm run test:unit
//   (node --test --experimental-strip-types "tests/**/*.node.test.ts")

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  buildCalendarMonth,
  calendarDateStr,
  calendarDisplayFor,
} from "../lib/calendarHeatmap.ts";

// ── buildCalendarMonth / calendarDateStr: basic correctness ────────────────

test("buildCalendarMonth reports the correct year/month/label/todayDay", () => {
  const wed = new Date("2026-07-15T12:00:00Z");
  const display = buildCalendarMonth(wed);
  assert.equal(display.year, 2026);
  assert.equal(display.month, 6); // 0-indexed: July
  assert.equal(display.monthLabel, "July 2026");
  assert.equal(display.todayDay, 15);
});

test("buildCalendarMonth pads the grid to complete weeks (length is a multiple of 7)", () => {
  const display = buildCalendarMonth(new Date("2026-07-15T12:00:00Z"));
  assert.equal(display.cells.length % 7, 0);
  // July 2026 has 31 days; padding must be >= 31 non-null cells present.
  assert.equal(display.cells.filter((c) => c !== null).length, 31);
});

test("calendarDateStr formats YYYY-MM-DD with zero-padding", () => {
  assert.equal(calendarDateStr(2026, 0, 5), "2026-01-05");
  assert.equal(calendarDateStr(2026, 11, 25), "2026-12-25");
});

// ── The defect class this guards against ───────────────────────────────────

test("buildCalendarMonth diverges across a month boundary -- proves an unguarded new Date() at render time is unsafe for SSR/hydration", () => {
  // Local-time constructors (not UTC ISO strings) so the boundary crossing
  // is guaranteed regardless of the test runner's timezone -- getFullYear()/
  // getMonth()/toLocaleString() below all read the LOCAL calendar date.
  const julyNight = new Date(2026, 6, 31, 23, 59);
  const augustMorning = new Date(2026, 7, 1, 0, 1);

  const before = buildCalendarMonth(julyNight);
  const after = buildCalendarMonth(augustMorning);

  assert.notEqual(before.monthLabel, after.monthLabel);
  assert.notEqual(before.month, after.month);
  assert.notDeepEqual(
    before.cells,
    after.cells,
    "a server render just before the month boundary and a client hydration render just after it must disagree on the grid when fed raw clock reads -- this is exactly the React #418 hazard"
  );
});

// ── The fix: calendarDisplayFor(null) is a constant placeholder ────────────

test("calendarDisplayFor(null) is null regardless of when it is evaluated", () => {
  assert.equal(calendarDisplayFor(null), null);
  assert.equal(calendarDisplayFor(null), calendarDisplayFor(null));
});

test("calendarDisplayFor(today) resolves to the real calendar once today is set (post-mount)", () => {
  const display = calendarDisplayFor(new Date("2026-07-15T12:00:00Z"));
  assert.ok(display !== null);
  assert.equal(display?.monthLabel, "July 2026");
});
