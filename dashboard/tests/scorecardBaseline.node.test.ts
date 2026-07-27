// Regression test for GT-20: the /validation "Backtest Reference — Total
// Return" pill (and the mirrored Phase 1 Trading Roadmap chip) rendered
// "-0.1%" for a real -5.25% loss because `total_return_pct` was formatted
// without scaling from the engine's FRACTION convention (e.g. -0.0525 means
// -5.25%; see engine/backtest/metrics.py's locked unit-convention comment)
// to a whole-number percent. pickApprovedBacktestBaseline() in
// lib/scorecardBaseline.ts is the single source for totalReturnLabel, which
// feeds both surfaces — one fix here covers both.
//
// Run: cd dashboard && pnpm run test:unit
//   (node --test --experimental-strip-types "tests/**/*.node.test.ts")

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  pickApprovedBacktestBaseline,
  type BacktestBaselineRow,
} from "../lib/scorecardBaseline.ts";

test("scorecardBaseline: total_return_pct fraction is scaled to a whole-number percent", () => {
  // Reproduces the exact GT-20 repro case: total_pnl=-5253.30 on a
  // $100,000 initial capital -> true total return is -5.2533%, stored on
  // full_metrics.total_return_pct as the fraction -0.0525 per the engine's
  // locked convention. PF (0.21) and Sharpe (-2.09) are included to mirror
  // the real payload and confirm they pass through unaffected (the bug was
  // scoped to total_return_pct only).
  const row: BacktestBaselineRow = {
    symbol: "MES",
    interval: "1h",
    full_metrics: {
      profit_factor: 0.21,
      sharpe_ratio: -2.09,
      win_rate: 0.42,
      max_drawdown_pct: 0.18,
      total_return_pct: -0.0525,
      total_pnl: -5253.3,
      total_trades: 40,
      symbol: "MES",
    },
  };

  const baseline = pickApprovedBacktestBaseline([row]);
  assert.ok(baseline, "expected a baseline to be picked");
  // Was "-0.1%" before the fix (formatted the raw fraction as if it were
  // already a whole-number percent). Correct scaled value is -5.25% ->
  // toFixed(1) rounds to -5.3%.
  assert.equal(baseline!.totalReturnLabel, "-5.3%");
  // Unaffected fields, verified to still read correctly (they were already
  // correct per the GT-20 report; asserting they stay that way).
  assert.equal(baseline!.profitFactor, 0.21);
  assert.equal(baseline!.sharpeRatio, -2.09);
});

test("scorecardBaseline: positive total_return_pct fraction is scaled and sign-prefixed", () => {
  const row: BacktestBaselineRow = {
    symbol: "MGC",
    interval: "1h",
    full_metrics: {
      profit_factor: 1.8,
      sharpe_ratio: 1.2,
      total_return_pct: 0.199,
      total_pnl: 19900,
      total_trades: 25,
      symbol: "MGC",
    },
  };

  const baseline = pickApprovedBacktestBaseline([row]);
  assert.ok(baseline);
  assert.equal(baseline!.totalReturnLabel, "+19.9%");
});

test("scorecardBaseline: falls back to top-level total_return fraction when full_metrics is absent", () => {
  // engine/backtest/run_backtest.py and run_all_backtests.py also persist a
  // top-level `total_return` fraction on some saved JSON shapes; the same
  // scaling must apply on that fallback path.
  const row: BacktestBaselineRow = {
    symbol: "SPY",
    interval: "1h",
    total_return: 0.0155,
  };

  const baseline = pickApprovedBacktestBaseline([row]);
  assert.ok(baseline);
  assert.equal(baseline!.totalReturnLabel, "+1.6%");
});
