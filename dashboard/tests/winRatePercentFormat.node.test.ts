// Regression test for GT-36 (2026-07-28 dashboard-integrity audit):
// InstrumentValidationScorecard.tsx rendered `${(row.wr * 100).toFixed(0)}%`,
// but row.wr already comes pre-scaled to a whole-number percent from the
// engine (`engine/routers/paper_validation_router.py::_build_validation_gate_rows`
// computes `current = round(win_rate_pct, 2)` where win_rate_pct is already
// `winning_trades / total_trades * 100`, and the gate object carries
// `unit: "%"`). The extra `* 100` turned a real 43.75% win rate into
// "4375%". Fixed by extracting the render logic into
// lib/instrumentValidationRows.ts::formatWinRatePct so it's unit-testable
// without rendering JSX (node --test can't parse JSX).
//
// Run: cd dashboard && pnpm run test:unit
//   (node --experimental-strip-types --import ./tests/_register-alias.mjs --test "tests/**/*.node.test.ts")

import { test } from "node:test";
import assert from "node:assert/strict";
import { formatWinRatePct } from "../lib/instrumentValidationRows.ts";

test("formatWinRatePct: a real 43.75% win rate renders 44%, not 4375%", () => {
  // Reproduces the exact GT-36 repro shape: engine returns current=43.75
  // (already percent-scaled). Pre-fix this rendered "4375%".
  assert.equal(formatWinRatePct(43.75), "44%");
});

test("formatWinRatePct: renders an em dash for null (no live gate data)", () => {
  assert.equal(formatWinRatePct(null), "—");
});

test("formatWinRatePct: rounds to the nearest whole percent, no extra scaling", () => {
  assert.equal(formatWinRatePct(0), "0%");
  assert.equal(formatWinRatePct(100), "100%");
  assert.equal(formatWinRatePct(52.4), "52%");
  assert.equal(formatWinRatePct(52.5), "53%" /* Number.toFixed rounds half-up here */);
});
