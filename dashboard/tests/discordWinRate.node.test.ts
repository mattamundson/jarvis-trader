// Regression test for GT-07: /discord Win Rate chart double-converted an
// already-percentage `avg_win_rate` field, showing 100% for every symbol
// (real spread 66-82%) and would render a real 76.63 value as "7663.0%".
//
// engine/routers/discord_router.py's `AVG(win_rate) as avg_win_rate` is on a
// 0-100 scale already (engine/discord/signal_context.py's own header
// comment: "The discord_bot_signals table stores win_rate as a percentage
// (0-100), not a ratio"). lib/discordWinRate.ts's `winRatePercent` is the
// single point of truth for turning that field into a display percent and
// must NOT re-multiply by 100.
//
// Run: cd dashboard && pnpm run test:unit

import { test } from "node:test";
import assert from "node:assert/strict";
import { winRatePercent } from "../lib/discordWinRate.ts";

test("winRatePercent: passes an already-percentage value through unchanged", () => {
  // Real fixture shape: avg_win_rate is 0-100 already.
  assert.equal(winRatePercent(76.63).toFixed(1), "76.6");
  assert.notEqual(winRatePercent(76.63), 7663); // the GT-07 double-conversion bug
});

test("winRatePercent: 100 stays 100, not 10000", () => {
  assert.equal(winRatePercent(100), 100);
});

test("winRatePercent: null/undefined/NaN fall back to 0", () => {
  assert.equal(winRatePercent(null), 0);
  assert.equal(winRatePercent(undefined), 0);
  assert.equal(winRatePercent(NaN), 0);
});

test("winRatePercent: 0 stays 0 (falsy but valid)", () => {
  assert.equal(winRatePercent(0), 0);
});
