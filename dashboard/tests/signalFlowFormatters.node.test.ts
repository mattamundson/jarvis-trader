/**
 * GT-32 regression: components/widgets/SignalFlowWidget.tsx's per-instrument
 * "24h change" chip was rendering change_pct ~100x too large (e.g. a real
 * +0.39% MES move displayed as "+39.00%") because the component's inline
 * render multiplied by 100 a value GET /prices/snapshot already returns
 * percent-scaled (engine/data/market_data.py:
 * `((last - prev) / prev * 100)`). Identical mechanism to GT-18
 * (dashboard/lib/watchlistFormatters.ts, PR #500, /watchlist page) and GT-29
 * (dashboard/lib/watchlistBarFormatters.ts, PR #504, ticker strip) -- this
 * is the third independent occurrence of the same bug class.
 *
 * The `preFixFormatChangePct` below reproduces the exact pre-fix formula
 * (verified by reading SignalFlowWidget.tsx@HEAD before this fix -- the
 * `(price.change_pct * 100).toFixed(2)` line at ~205) so this test proves
 * both the regression the bug caused AND that the shipped fix
 * (lib/signalFlowFormatters.ts, imported by SignalFlowWidget.tsx) no longer
 * exhibits it.
 *
 * Run via: cd dashboard && pnpm run test:unit
 *   (node --test --experimental-strip-types \
 *    --import ./tests/_register-alias.mjs tests/signalFlowFormatters.node.test.ts)
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { formatChangePct } from "../lib/signalFlowFormatters.ts";

/** The exact pre-fix SignalFlowWidget.tsx formula, reproduced for regression proof only. */
function preFixFormatChangePct(pct: number | null): string {
  if (pct == null) return "";
  const sign = pct >= 0 ? "+" : "";
  return `${sign}${(pct * 100).toFixed(2)}%`;
}

test("GT-32 regression: pre-fix formula renders realistic engine values ~100x too large", () => {
  // Realistic already-percent-scaled values, same shape as engine/data/market_data.py
  // and engine/tests/test_prices_router_offline.py fixtures (e.g. MES 0.39, MCL -0.5).
  assert.equal(preFixFormatChangePct(0.39), "+39.00%"); // true move: +0.39%
  assert.equal(preFixFormatChangePct(-0.5), "-50.00%"); // true move: -0.50%
  assert.equal(preFixFormatChangePct(0.4), "+40.00%"); // true move: +0.40%
});

test("formatChangePct: post-fix renders the same fixtures at true magnitude", () => {
  assert.equal(formatChangePct(0.39), "+0.39%");
  assert.equal(formatChangePct(-0.5), "-0.50%");
  assert.equal(formatChangePct(0.4), "+0.40%");
});

test("formatChangePct: does not re-scale -- output equals input to 2dp with a sign", () => {
  assert.equal(formatChangePct(1.5), "+1.50%");
  assert.equal(formatChangePct(-2.25), "-2.25%");
  assert.equal(formatChangePct(0), "+0.00%");
});

test("formatChangePct: null renders empty string (SignalFlowWidget guards with change_pct != null before calling)", () => {
  assert.equal(formatChangePct(null), "");
});
