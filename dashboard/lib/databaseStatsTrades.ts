// Pure helper for the /health dashboard's "Database Statistics" panel
// (components/DatabaseStatsCard.tsx). Split out of the component so it can
// be unit-tested with the node test runner (JSX files can't be imported by
// `node --experimental-strip-types`).
//
// GT-16: `GET /portfolio/history/trades` has always returned a bare JSON
// array (e.g. `[{...}, {...}]`), NOT the `{trades, count}` wrapper its
// sibling endpoints use (`/portfolio/history/decisions` and
// `/alerts/history` both return `{items, count}`). The "Total Trades" tile
// read `.count` / `.trades?.length` off that response -- both `undefined`
// on a bare array (arrays don't have those properties) -- so it always
// rendered 0 regardless of the real trade count (63, at the time this was
// found).
//
// This mirrors the array-or-wrapper defensive parsing already used
// elsewhere against this same endpoint (components/charts/PriceChartPanel.tsx,
// components/EntryQualityWidget.tsx) rather than changing the backend's
// response shape -- components/CumulativeTradingDaysWidget.tsx assumes a
// bare array from this endpoint today, so reshaping the backend would fix
// this tile while silently breaking that widget. See the GT-16 PR
// description for the out-of-scope note on unifying this endpoint's
// contract.

export interface TradesHistoryWrapper {
  trades?: unknown[];
  count?: number;
  error?: string;
  note?: string;
}

export type TradesHistoryPayload = TradesHistoryWrapper | unknown[];

export function deriveTotalTradesCount(
  payload: TradesHistoryPayload | null | undefined,
): number {
  if (Array.isArray(payload)) return payload.length;
  if (!payload || typeof payload !== "object") return 0;
  return payload.count ?? payload.trades?.length ?? 0;
}
