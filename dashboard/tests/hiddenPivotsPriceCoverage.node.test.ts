/**
 * PRB-21 regression: app/hidden-pivots/page.tsx used to poll live prices
 * (GET /prices/snapshot) for every scanned watchlist symbol every 15s. With
 * IB Gateway down, that fell to Polygon (rate-capped at 4 calls/60s on the
 * free plan) and then a CSV-cache floor that only exists for 11 of the 33
 * watchlist symbols -- the other 22 showed "--" with certainty and were
 * still polled every 15s regardless. lib/hiddenPivotsPriceCoverage.ts caps
 * the poll to the symbols GET /hidden-pivots/price-coverage reports as
 * actually covered; pattern/level scanning (GET /hidden-pivots/scan) is
 * untouched and still runs the full watchlist.
 *
 * Run via: cd dashboard && pnpm run test:unit
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { filterToPriceCoveredSymbols } from "../lib/hiddenPivotsPriceCoverage.ts";

test("PRB-21: filters the scanned watchlist down to the covered subset", () => {
  const scanned = ["MES", "MNQ", "SPY", "NFLX", "MSFT"];
  const covered = ["MES", "SPY"];
  assert.deepEqual(filterToPriceCoveredSymbols(scanned, covered), ["MES", "SPY"]);
});

test("PRB-21: preserves scanned order, not coverage-list order", () => {
  const scanned = ["NFLX", "SPY", "MES"];
  const covered = ["MES", "SPY"]; // deliberately different order
  assert.deepEqual(filterToPriceCoveredSymbols(scanned, covered), ["SPY", "MES"]);
});

test("PRB-21: covered symbols not present in the scan are dropped, not added", () => {
  const scanned = ["MES"];
  const covered = ["MES", "SPY", "AAPL"]; // SPY/AAPL weren't scanned this run
  assert.deepEqual(filterToPriceCoveredSymbols(scanned, covered), ["MES"]);
});

test("PRB-21: empty coverage list returns no symbols (not the full watchlist)", () => {
  const scanned = ["MES", "MNQ", "SPY"];
  assert.deepEqual(filterToPriceCoveredSymbols(scanned, []), []);
});

test("PRB-21: undefined coverage (price-coverage not yet loaded) returns empty, never the full watchlist", () => {
  // This is the exact regression: before the fix, the page defaulted to
  // polling every scanned symbol. Deferring to [] until coverage is known
  // means the first render never fires an uncapped /prices/snapshot call.
  const scanned = ["MES", "MNQ", "SPY", "NFLX", "MSFT", "AAPL"];
  assert.deepEqual(filterToPriceCoveredSymbols(scanned, undefined), []);
});

test("PRB-21: empty scan list returns empty regardless of coverage", () => {
  assert.deepEqual(filterToPriceCoveredSymbols([], ["MES", "SPY"]), []);
});
