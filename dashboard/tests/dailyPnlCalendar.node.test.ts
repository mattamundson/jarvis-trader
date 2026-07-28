// DailyPnLCalendarWidget hydration-guard regression test (GT-33, closing
// GT-27's own target -- PR #496, still open/unmerged, added a non-extracted
// version of this same guard directly in the component; see this file's
// header comment in ../lib/dailyPnlCalendar.ts and the GT-33 PR description
// for the reconciliation note).
//
// WHY: DailyPnLCalendarWidget used to call `new Date()` directly during
// render (via buildCalendarDays()/toYMD(new Date())/the month label) to
// build the 30-day Mon-Fri calendar grid. SSR output is evaluated at
// server-render/build time; the client's first hydration render is
// evaluated whenever the browser actually loads the page. When those two
// clock reads straddle a day/month boundary, the server and the client
// disagree on the month label, the day grid, and which cell is "today" ->
// React error #418. The fix (lib/dailyPnlCalendar.ts +
// DailyPnLCalendarWidget.tsx) starts `today` at `null` and only sets it from
// a mount-only effect, so both the server render and the client's first
// paint always agree (both take the `null` branch, which resolves to the
// component's existing "No trade data yet" empty state), regardless of what
// time either one runs at.
//
// This test proves both halves of that mechanism:
//   1. buildCalendarDays() is genuinely boundary-sensitive (i.e. the bug
//      class is real).
//   2. dailyPnlCalendarDisplayFor(null) is constant no matter what date it's
//      evaluated "at" -- so a server render and a pre-mount client render
//      can never disagree, closing off the mismatch.
//
// Run: cd dashboard && pnpm run test:unit
//   (node --test --experimental-strip-types "tests/**/*.node.test.ts")

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  buildCalendarDays,
  toYMD,
  dailyPnlCalendarDisplayFor,
} from "../lib/dailyPnlCalendar.ts";

// ── buildCalendarDays / toYMD: basic correctness ────────────────────────────

test("buildCalendarDays returns only Mon-Fri dates spanning the past 30 calendar days", () => {
  const wed = new Date("2026-07-29T12:00:00Z");
  const days = buildCalendarDays(wed);
  assert.ok(days.length > 0 && days.length <= 30);
  for (const d of days) {
    const dow = d.getDay();
    assert.ok(dow >= 1 && dow <= 5, "every returned day must be Mon-Fri");
  }
  // Last entry must be `today` itself.
  assert.equal(toYMD(days[days.length - 1]), "2026-07-29");
});

test("toYMD formats YYYY-MM-DD with zero-padding", () => {
  assert.equal(toYMD(new Date("2026-01-05T12:00:00Z")), "2026-01-05");
});

// ── The defect class this guards against ───────────────────────────────────

test("dailyPnlCalendarDisplayFor's monthLabel/todayStr diverge across a month boundary -- proves an unguarded new Date() at render time is unsafe for SSR/hydration", () => {
  // Local-time constructors (not UTC ISO strings) so the boundary crossing
  // is guaranteed regardless of the test runner's timezone -- monthLabel
  // (toLocaleDateString) and todayStr (toYMD, which reads local
  // getFullYear()/getMonth()/getDate()) both read the LOCAL calendar date.
  const julyNight = new Date(2026, 6, 31, 23, 59);
  const augustMorning = new Date(2026, 7, 1, 0, 1);

  const before = dailyPnlCalendarDisplayFor(julyNight);
  const after = dailyPnlCalendarDisplayFor(augustMorning);

  assert.notEqual(before.monthLabel, after.monthLabel);
  assert.notEqual(
    before.todayStr,
    after.todayStr,
    "a server render just before the month boundary and a client hydration render just after it must disagree on the 'is today' cell when fed raw clock reads -- this is exactly the React #418 hazard"
  );
});

// ── The fix: dailyPnlCalendarDisplayFor(null) is a constant placeholder ────

test("dailyPnlCalendarDisplayFor(null) is identical regardless of when it is evaluated", () => {
  const placeholder = dailyPnlCalendarDisplayFor(null);
  assert.deepEqual(placeholder, { calDays: [], todayStr: "", monthLabel: "" });
  assert.deepEqual(dailyPnlCalendarDisplayFor(null), placeholder);
});

test("dailyPnlCalendarDisplayFor(today) resolves to the real calendar once today is set (post-mount)", () => {
  const display = dailyPnlCalendarDisplayFor(new Date("2026-07-29T12:00:00Z"));
  assert.equal(display.monthLabel, "July 2026");
  assert.equal(display.todayStr, "2026-07-29");
  assert.ok(display.calDays.length > 0);
});
