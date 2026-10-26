import assert from "node:assert/strict";
import { test } from "node:test";
import { buildDrawdownProjection } from "../lib/drawdownProjection.ts";

const LIVE = {
  currentDrawdownFraction: 0.06482792315887562,
  haltFraction: 0.2,
  equity: 14416.3161,
  avgLossDollars: 101.7731,
};

test("current drawdown matches the kill-switch fraction, not closed-trade max drawdown", () => {
  const proj = buildDrawdownProjection(LIVE);
  assert.ok(proj);
  assert.ok(Math.abs(proj.current_dd_pct - 6.482792315887562) < 1e-9);
  assert.equal(proj.max_drawdown_pct, 20);

  const closedTradeMaxDdPct = (1981.7035 / (14426.5661 + 1981.7035)) * 100;
  assert.ok(Math.abs(closedTradeMaxDdPct - 12.077) < 0.01);
  assert.ok(Math.abs(proj.current_dd_pct - closedTradeMaxDdPct) > 1);
});

test("trades remaining are counted in dollars from the same peak", () => {
  const proj = buildDrawdownProjection(LIVE);
  assert.ok(proj);
  const peak = LIVE.equity / (1 - LIVE.currentDrawdownFraction);
  const dollarsUntilHalt = LIVE.equity - peak * (1 - 0.2);
  assert.ok(Math.abs(proj.peak_equity - peak) < 1e-6);
  assert.equal(proj.trades_remaining, Math.floor(dollarsUntilHalt / 101.7731));
  assert.equal(proj.trades_remaining, 20);
});
