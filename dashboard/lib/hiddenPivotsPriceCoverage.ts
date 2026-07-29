/**
 * PRB-21: the Hidden Pivots page (app/hidden-pivots/page.tsx) polls live
 * prices for its scanned watchlist every 15s via GET /prices/snapshot. With
 * IB Gateway down, price falls to Polygon (engine/data/market_data.py
 * PolygonDataConnector, hard-capped at 4 calls/60s on the free plan) and then
 * to a CSV backtest-cache read (Tier 5) as the last resort. Only symbols that
 * have ever been backtested have a cache file, so the other watchlist
 * symbols hit "unavailable" with certainty whenever the earlier tiers both
 * miss -- there is no floor to poll for.
 *
 * `GET /hidden-pivots/price-coverage` (engine/routers/hidden_pivots_router.py)
 * reports which watchlist symbols currently have that cache floor. This
 * module is pulled out of page.tsx -- instead of living as an inline
 * useMemo -- so the filtering logic can be unit-tested directly via Node's
 * built-in test runner without importing a JSX-bearing .tsx file (see
 * tests/hiddenPivotsPriceCoverage.node.test.ts), matching the pattern used
 * for lib/watchlistBarFormatters.ts.
 *
 * Pattern/level scanning (GET /hidden-pivots/scan) is intentionally
 * untouched by this filter -- it always covers the full watchlist. Only the
 * live-price ticker poll is capped.
 */

/**
 * Restrict `scannedSymbols` (the full watchlist as returned by the scan) to
 * the subset that has a real price-fallback floor.
 *
 * `coveredSymbols` is `undefined` while GET /hidden-pivots/price-coverage
 * hasn't resolved yet (e.g. first render) -- in that window this returns an
 * empty list rather than falling back to the full watchlist, so the price
 * poll never fires an uncapped request before coverage is known. That is the
 * exact over-poll PRB-21 fixes; deferring is safer than guessing.
 */
export function filterToPriceCoveredSymbols(
  scannedSymbols: string[],
  coveredSymbols: string[] | undefined
): string[] {
  if (!coveredSymbols) return [];
  const covered = new Set(coveredSymbols);
  return scannedSymbols.filter((s) => covered.has(s));
}
