/**
 * Formatting helpers for the /watchlist page's "Live Price Feed" table
 * (app/watchlist/page.tsx). Pulled into their own module — instead of living
 * as local functions inside the page — so they can be unit-tested directly
 * via Node's built-in test runner without importing the whole page component
 * tree (see tests/watchlistFormatters.node.test.ts, modeled on the existing
 * lib/position-sizing.ts / tests/position-sizing.test.ts pattern).
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
 * Format a 24h change_pct value from GET /watchlist for display.
 *
 * GT-18 (2026-07-27): the engine's /watchlist change_pct is already
 * percent-scaled — market_data.py's IBKR tier computes
 * `(last - prev) / prev * 100` and the Schwab tier passes through Schwab's
 * `netPercentChangeInDouble`, both already in percent units (e.g. `7.05` for
 * a +7.05% move). The previous implementation multiplied by 100 again,
 * inflating every watchlist row's displayed 24h change by ~100x (e.g. a true
 * +0.07% move rendered as "+7.05%"). Fix: format the value as-is.
 *
 * Note: components/WatchlistBar.tsx has the identical `pct * 100` pattern
 * against the same underlying data (via /prices/snapshot, which shares the
 * same get_snapshot_price()/get_current_price() sources) and is very likely
 * the same bug — but it isn't on the /watchlist page and is out of scope for
 * GT-18 (see PR body).
 */
export function formatChangePct(pct: number | null): string {
  if (pct == null) return "—";
  const sign = pct >= 0 ? "+" : "";
  return `${sign}${pct.toFixed(2)}%`;
}
