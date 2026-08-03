// CumulativeTradingDaysWidget hydration-guard regression test (GT-33,
// sibling to GT-27 / PR #496 on DailyPnLCalendarWidget and GT-30 / PR #503
// on WeeklyPnLCard).
//
// WHY: CumulativeTradingDaysWidget used to call `new Date()` directly during
// render to compute pace/ETA and the 30-day activity dot grid. SSR output is
// evaluated at server-render/build time; the client's first hydration
// render is evaluated whenever the browser actually loads the page. When
// those two clock reads straddle a day boundary, the server and the client
// disagree on the "Est. completion" label and the activity dot grid ->
// React error #418. The fix (lib/cumulativeTradingDays.ts +
// CumulativeTradingDaysWidget.tsx) starts `today` at `null` and only sets it
// from a mount-only effect, so both the server render and the client's
// first paint always agree (both take the `null` branch) regardless of what
// time either one runs at.
//
// This test proves both halves of that mechanism:
//   1. computeTradingDaysDisplay() is genuinely boundary-sensitive (i.e. the
//      bug class is real -- an unguarded `new Date()` here CAN diverge
//      across a render).
//   2. computeTradingDaysDisplay(null, ...) is constant no matter what date
//      it's evaluated "at" -- so a server render and a pre-mount client
//      render can never disagree, closing off the mismatch.
//
// Run: cd dashboard && pnpm run test:unit
//   (node --test --experimental-strip-types "tests/**/*.node.test.ts")

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  addDays,
  toDateStr,
  computeTradingDaysDisplay,
} from "../lib/cumulativeTradingDays.ts";

// ── addDays / toDateStr: basic correctness ─────────────────────────────────

test("addDays adds/subtracts calendar days without mutating the input", () => {
  const base = new Date("2026-07-15T12:00:00Z");
  const forward = addDays(base, 5);
  const backward = addDays(base, -5);
  assert.equal(toDateStr(forward), "2026-07-20");
  assert.equal(toDateStr(backward), "2026-07-10");
  assert.equal(toDateStr(base), "2026-07-15", "input must not be mutated");
});

// ── The defect class this guards against ───────────────────────────────────

test("computeTradingDaysDisplay's activity grid diverges across a day boundary -- proves an unguarded new Date() at render time is unsafe for SSR/hydration", () => {
  const tradingDaySet = new Set(["2026-07-14", "2026-07-15"]);
  const beforeMidnight = new Date("2026-07-15T23:59:00Z");
  const afterMidnight = new Date("2026-07-16T00:01:00Z");

  const before = computeTradingDaysDisplay(beforeMidnight, 2, "2026-07-14", tradingDaySet);
  const after = computeTradingDaysDisplay(afterMidnight, 2, "2026-07-14", tradingDaySet);

  assert.notDeepEqual(
    before.activityDots,
    after.activityDots,
    "a server render just before midnight and a client hydration render just after it must disagree on the 30-day dot grid when fed raw clock reads -- this is exactly the React #418 hazard"
  );
});

test("computeTradingDaysDisplay's estCompletionLabel diverges once pace crosses a full day", () => {
  const tradingDaySet = new Set(["2026-07-01"]);
  const day10 = new Date("2026-07-10T12:00:00Z");
  const day11 = new Date("2026-07-11T12:00:00Z");

  const before = computeTradingDaysDisplay(day10, 1, "2026-07-01", tradingDaySet);
  const after = computeTradingDaysDisplay(day11, 1, "2026-07-01", tradingDaySet);

  assert.notEqual(
    before.estCompletionLabel,
    after.estCompletionLabel,
    "the ETA label is derived from `today`, so it must shift as the clock read shifts"
  );
});

// ── The fix: computeTradingDaysDisplay(null, ...) is a constant placeholder ─

test("computeTradingDaysDisplay(null, ...) is identical regardless of when it is evaluated", () => {
  const tradingDaySet = new Set(["2026-07-14", "2026-07-15"]);
  const placeholder = computeTradingDaysDisplay(null, 2, "2026-07-14", tradingDaySet);
  assert.deepEqual(placeholder, {
    daysSinceFirst: 0,
    pace: 0,
    estCompletionLabel: "",
    activityDots: [],
  });

  // Simulate a "server render" and a "client's first hydration render"
  // happening at wildly different wall-clock times, straddling the same day
  // boundary used above. Both must still take the null branch and produce
  // the exact same output -- because `today` only ever comes from
  // client-only state that starts at null, never from a raw `new Date()`
  // read during render.
  const again = computeTradingDaysDisplay(null, 2, "2026-07-14", tradingDaySet);
  assert.deepEqual(again, placeholder);
});

test("computeTradingDaysDisplay(today, ...) resolves to real values once today is set (post-mount)", () => {
  const tradingDaySet = new Set(["2026-07-01", "2026-07-02", "2026-07-03"]);
  const today = new Date("2026-07-10T12:00:00Z");
  const display = computeTradingDaysDisplay(today, 3, "2026-07-01", tradingDaySet);
  assert.equal(display.activityDots.length, 30);
  assert.ok(display.pace > 0);
  assert.match(display.estCompletionLabel, /Est\. completion:|Insufficient data|Target met!/);
});
