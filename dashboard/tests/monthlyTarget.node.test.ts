// MonthlyTargetCard hydration-guard regression test (GT-33, sibling to
// GT-27 / PR #496 on DailyPnLCalendarWidget and GT-30 / PR #503 on
// WeeklyPnLCard).
//
// WHY: MonthlyTargetCard used to call `getCurrentYearMonth()` and
// `getMonthLabel()` -> `new Date()` directly during render. SSR output is
// evaluated at server-render/build time; the client's first hydration
// render is evaluated whenever the browser actually loads the page. When
// those two clock reads straddle a month boundary, the server and the
// client disagree on which entries count toward "this month" and on the
// "Month Year" label text -> React error #418. The fix (lib/monthlyTarget.ts
// + MonthlyTargetCard.tsx) starts `today` at `null` and only sets it from a
// mount-only effect, so both the server render and the client's first paint
// always agree (both take the `null` branch) regardless of what time either
// one runs at.
//
// This test proves both halves of that mechanism:
//   1. getCurrentYearMonth()/getMonthLabel() are genuinely boundary-sensitive
//      (i.e. the bug class is real).
//   2. monthDisplayFor(null) is constant no matter what date it's evaluated
//      "at" -- so a server render and a pre-mount client render can never
//      disagree, closing off the mismatch.
//
// Run: cd dashboard && pnpm run test:unit
//   (node --test --experimental-strip-types "tests/**/*.node.test.ts")

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  getCurrentYearMonth,
  getMonthLabel,
  monthDisplayFor,
} from "../lib/monthlyTarget.ts";

// ── getCurrentYearMonth / getMonthLabel: basic correctness ─────────────────

test("getCurrentYearMonth returns YYYY-MM for a mid-month date", () => {
  assert.equal(getCurrentYearMonth(new Date("2026-07-15T12:00:00Z")), "2026-07");
});

test("getMonthLabel returns a human-readable month + year", () => {
  assert.equal(getMonthLabel(new Date("2026-07-15T12:00:00Z")), "July 2026");
});

// ── The defect class this guards against ───────────────────────────────────

test("getCurrentYearMonth/getMonthLabel diverge across a month boundary -- proves an unguarded new Date() at render time is unsafe for SSR/hydration", () => {
  // Local-time constructors (not UTC ISO strings) so the boundary crossing
  // is guaranteed regardless of the test runner's timezone -- both helpers
  // read the LOCAL calendar date (getFullYear()/getMonth()/toLocaleString()).
  const julyNight = new Date(2026, 6, 31, 23, 59);
  const augustMorning = new Date(2026, 7, 1, 0, 1);

  assert.notEqual(getCurrentYearMonth(julyNight), getCurrentYearMonth(augustMorning));
  assert.notEqual(
    getMonthLabel(julyNight),
    getMonthLabel(augustMorning),
    "a server render just before the month boundary and a client hydration render just after it must disagree when fed raw clock reads -- this is exactly the React #418 hazard"
  );
});

// ── The fix: monthDisplayFor(null) is a constant placeholder ───────────────

test("monthDisplayFor(null) is identical regardless of when it is evaluated", () => {
  const placeholder = monthDisplayFor(null);
  assert.deepEqual(placeholder, { yearMonth: "", monthLabel: "" });

  assert.deepEqual(monthDisplayFor(null), monthDisplayFor(null));
  assert.deepEqual(monthDisplayFor(null), placeholder);
});

test("monthDisplayFor(today) resolves to the real month once today is set (post-mount)", () => {
  const display = monthDisplayFor(new Date("2026-07-15T12:00:00Z"));
  assert.equal(display.yearMonth, "2026-07");
  assert.equal(display.monthLabel, "July 2026");
});
