/**
 * Formatting helpers for components/widgets/SignalFlowWidget.tsx. Pulled into
 * their own module -- instead of living as an inline expression inside the
 * "use client" component -- so the fix can be unit-tested directly via
 * Node's built-in test runner without importing a JSX-bearing .tsx file
 * (Node's --experimental-strip-types strips TS types but cannot parse JSX;
 * see tests/signalFlowFormatters.node.test.ts).
 *
 * GT-32 (2026-07-27): SignalFlowWidget's per-instrument change_pct comes from
 * GET /prices/snapshot, which is fed by the same engine sources
 * (market_data.py's `((last - prev) / prev * 100)`) as the /watchlist page
 * fixed under GT-18 (PR #500, dashboard/lib/watchlistFormatters.ts) and the
 * ticker strip fixed under GT-29 (PR #504, dashboard/lib/watchlistBarFormatters.ts)
 * -- all three already return percent-scaled values (e.g. `0.39` for a
 * +0.39% move). SignalFlowWidget's inline render multiplied by 100 a second
 * time before calling .toFixed(2), inflating every instrument row's
 * displayed change by ~100x (e.g. a true +0.39% MES move rendered as
 * "+39.00%"). Fix: format the value as-is, matching the GT-18/GT-29 formula
 * exactly.
 *
 * Deliberately a separate module rather than importing GT-18's or GT-29's
 * formatter: as of this fix, PR #500 and PR #504 are both still
 * open/unmerged, so neither module exists on master yet. Once one of them
 * merges, these near-identical formatters should be consolidated into one
 * shared lib/pctFormatters.ts (tracked as follow-up, out of scope for this
 * fix) to avoid the duplicate-bug risk that produced GT-18 -> GT-29 -> GT-32
 * in the first place.
 */

/**
 * Format a change_pct value from GET /prices/snapshot for display.
 * The engine already returns this percent-scaled -- do not re-scale it.
 */
export function formatChangePct(pct: number | null): string {
  if (pct == null) return "";
  const sign = pct >= 0 ? "+" : "";
  return `${sign}${pct.toFixed(2)}%`;
}
