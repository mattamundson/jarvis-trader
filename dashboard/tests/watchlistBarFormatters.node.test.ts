/**
 * GT-29 regression: components/WatchlistBar.tsx's ticker-strip "24h change"
 * chips were rendering change_pct ~100x too large (e.g. a real +0.39% SPY
 * move displayed as "+39.00%") because the component's local
 * formatChangePct() multiplied by 100 a value GET /prices/snapshot already
 * returns percent-scaled (engine/data/market_data.py:
 * `((last - prev) / prev * 100)`). Identical mechanism to GT-18
 * (dashboard/lib/watchlistFormatters.ts, PR #500) against the /watchlist
 * page -- GT-18's own PR description flagged WatchlistBar.tsx as carrying
 * the same bug, out of scope for that PR. This is the GT-29 follow-up.
 *
 * The `preFixFormatChangePct` below reproduces the exact pre-fix formula
 * (verified by reading WatchlistBar.tsx@HEAD before this fix -- the
 * `(pct * 100).toFixed(2)` line) so this test proves both the regression the
 * bug caused AND that the shipped fix (lib/watchlistBarFormatters.ts,
 * imported by WatchlistBar.tsx) no longer exhibits it.
 *
 * Run via: cd dashboard && pnpm run test:unit
 *   (node --test --experimental-strip-types \
 *    --import ./tests/_register-alias.mjs tests/watchlistBarFormatters.node.test.ts)
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { formatChangePct, formatPrice } from "../lib/watchlistBarFormatters.ts";

/** The exact pre-fix WatchlistBar.tsx formula, reproduced for regression proof only. */
function preFixFormatChangePct(pct: number | null): string {
  if (pct == null) return "";
  const sign = pct >= 0 ? "+" : "";
  return `${sign}${(pct * 100).toFixed(2)}%`;
}

test("GT-29 regression: pre-fix formula renders realistic engine values ~100x too large", () => {
  // Realistic already-percent-scaled values, same shape as engine/data/market_data.py
  // and engine/tests/test_prices_router_offline.py fixtures (e.g. SPY 0.40, MES 0.39).
  assert.equal(preFixFormatChangePct(0.4), "+40.00%"); // true move: +0.40%
  assert.equal(preFixFormatChangePct(-0.5), "-50.00%"); // true move: -0.50%
  assert.equal(preFixFormatChangePct(0.39), "+39.00%"); // true move: +0.39%
});

test("formatChangePct: post-fix renders the same fixtures at true magnitude", () => {
  assert.equal(formatChangePct(0.4), "+0.40%");
  assert.equal(formatChangePct(-0.5), "-0.50%");
  assert.equal(formatChangePct(0.39), "+0.39%");
});

test("formatChangePct: does not re-scale -- output equals input to 2dp with a sign", () => {
  assert.equal(formatChangePct(1.5), "+1.50%");
  assert.equal(formatChangePct(-2.25), "-2.25%");
  assert.equal(formatChangePct(0), "+0.00%");
});

test("formatChangePct: null renders empty string (WatchlistBar guards with pct != null before calling)", () => {
  assert.equal(formatChangePct(null), "");
});

test("formatPrice: sub-1000 and >=1000 (thousands separator) branches, matching GT-17's fix", () => {
  assert.equal(formatPrice(325.89), "325.89");
  assert.equal(formatPrice(7494.1), "7,494.10"); // MES-scale futures price
});

test("formatPrice: null renders the em-dash placeholder", () => {
  assert.equal(formatPrice(null), "—");
});
