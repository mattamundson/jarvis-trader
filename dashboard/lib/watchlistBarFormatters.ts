/**
 * Formatting helpers for components/WatchlistBar.tsx (the top-of-dashboard
 * ticker strip). Pulled into their own module -- instead of living as local
 * functions inside the "use client" component -- so they can be unit-tested
 * directly via Node's built-in test runner without importing a JSX-bearing
 * .tsx file (Node's --experimental-strip-types strips TS types but cannot
 * parse JSX; see tests/watchlistBarFormatters.node.test.ts).
 *
 * GT-29 (2026-07-27): WatchlistBar's change_pct comes from GET
 * /prices/snapshot, which is fed by the same engine sources (market_data.py's
 * `((last - prev) / prev * 100)`) as the /watchlist endpoint fixed under
 * GT-18 (PR #500, dashboard/lib/watchlistFormatters.ts) -- both already
 * return percent-scaled values (e.g. `0.39` for a +0.39% move). The previous
 * WatchlistBar implementation multiplied by 100 a second time before
 * formatting, inflating every ticker-strip chip's displayed change by ~100x
 * (e.g. a true +0.39% SPY move rendered as "+39.00%"). Fix: format the value
 * as-is, matching the GT-18 formula exactly.
 *
 * Deliberately a separate module from lib/watchlistFormatters.ts rather than
 * importing it: as of this fix, PR #500 (GT-17/GT-18, branch
 * fix/gt-17-18-watchlist-price-pct) is still open/unmerged, so that file
 * does not exist on master yet. Once #500 merges, these two near-identical
 * modules should be consolidated into one shared formatter (tracked as
 * follow-up, out of scope for this fix) to avoid the duplicate-bug risk that
 * created GT-29 in the first place.
 */

export function formatPrice(price: number | null): string {
  if (price == null) return "—";
  if (price >= 1000) {
    return price.toLocaleString("en-US", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  }
  return price.toFixed(2);
}

/**
 * Format a change_pct value from GET /prices/snapshot for display.
 * The engine already returns this percent-scaled -- do not re-scale it.
 */
export function formatChangePct(pct: number | null): string {
  if (pct == null) return "";
  const sign = pct >= 0 ? "+" : "";
  return `${sign}${pct.toFixed(2)}%`;
}
