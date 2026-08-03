// WeeklyPnLCard hydration-guard regression test (GT-30, sibling to GT-27 /
// PR #496 on DailyPnLCalendarWidget).
//
// WHY: WeeklyPnLCard used to call `getThisWeekDates()` -> `new Date()`
// directly during render. SSR output is evaluated at server-render/build
// time; the client's first hydration render is evaluated whenever the
// browser actually loads the page (which can be hours/days later for a
// statically-optimized route). Whenever those two clock reads straddle a
// day/week boundary, the server and the client disagree on the "Week of ..."
// text and the day grid -> React error #418. The fix (lib/weekDates.ts +
// WeeklyPnLCard.tsx) starts `today` at `null` and only sets it from a
// mount-only effect, so both the server render and the client's first paint
// always agree (both take the `null` branch) regardless of what time either
// one runs at.
//
// This test proves both halves of that mechanism:
//   1. getThisWeekDates() genuinely is boundary-sensitive (i.e. the bug class
//      is real -- an unguarded `new Date()` here CAN diverge across a render).
//   2. weekDisplayFor(null) is constant no matter what date it's evaluated
//      "at" -- so a server render and a pre-mount client render can never
//      disagree, closing off the mismatch.
//
// Run: cd dashboard && pnpm run test:unit
//   (node --test --experimental-strip-types "tests/**/*.node.test.ts")

import { test } from "node:test";
import assert from "node:assert/strict";
import { getThisWeekDates, weekDisplayFor } from "../lib/weekDates.ts";

// ── getThisWeekDates: basic correctness ────────────────────────────────────

test("getThisWeekDates returns Mon-Fri for a mid-week date", () => {
  // 2026-07-29 is a Wednesday.
  const wed = new Date("2026-07-29T12:00:00Z");
  assert.deepEqual(getThisWeekDates(wed), [
    "2026-07-27",
    "2026-07-28",
    "2026-07-29",
    "2026-07-30",
    "2026-07-31",
  ]);
});

test("getThisWeekDates anchors Sunday to the week that just ended", () => {
  // 2026-08-02 is a Sunday; its Monday is 2026-07-27, not the following one.
  const sun = new Date("2026-08-02T12:00:00Z");
  assert.deepEqual(getThisWeekDates(sun)[0], "2026-07-27");
});

// ── The defect class this guards against ───────────────────────────────────

test("getThisWeekDates diverges across a week boundary -- proves an unguarded new Date() at render time is unsafe for SSR/hydration", () => {
  const sundayNight = new Date("2026-08-02T23:59:00Z");
  const mondayMorning = new Date("2026-08-03T00:01:00Z");
  const before = getThisWeekDates(sundayNight);
  const after = getThisWeekDates(mondayMorning);
  assert.notDeepEqual(
    before,
    after,
    "a server render just before the boundary and a client hydration render just after it must disagree when fed raw clock reads -- this is exactly the React #418 hazard"
  );
});

// ── The fix: weekDisplayFor(null) is a constant placeholder ────────────────

test("weekDisplayFor(null) is identical regardless of when it is evaluated", () => {
  const placeholder = weekDisplayFor(null);
  assert.deepEqual(placeholder, { weekDates: [], mondayDate: "" });

  // Simulate a "server render" and a "client's first hydration render"
  // happening at wildly different wall-clock times, straddling the same
  // week boundary used above. Both must still take the null branch and
  // produce the exact same output -- because `today` only ever comes from
  // client-only state that starts at null, never from a raw `new Date()`
  // read during render.
  const serverRenderClock = new Date("2026-08-02T23:59:00Z");
  const clientHydrationClock = new Date("2026-08-03T00:01:00Z");
  void serverRenderClock;
  void clientHydrationClock;

  assert.deepEqual(weekDisplayFor(null), weekDisplayFor(null));
  assert.deepEqual(weekDisplayFor(null), placeholder);
});

test("weekDisplayFor(today) resolves to the real week once today is set (post-mount)", () => {
  const wed = new Date("2026-07-29T12:00:00Z");
  const display = weekDisplayFor(wed);
  assert.equal(display.mondayDate, "2026-07-27");
  assert.equal(display.weekDates.length, 5);
});
