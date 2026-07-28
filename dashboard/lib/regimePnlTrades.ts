// Pure helper for RegimePnLBreakdownWidget.tsx
// (components/RegimePnLBreakdownWidget.tsx). Split out of the component so
// the response-shape parsing can be unit-tested with the node test runner
// (JSX files can't be imported by `node --experimental-strip-types`).
//
// GT-28: `GET /portfolio/history/trades` has always returned a bare JSON
// array (e.g. `[{...}, {...}]`) -- see engine/routers/portfolio_router.py's
// `portfolio_history_trades()`, which builds a `list[dict]` named `out` and
// ends with a bare `return out` (no `{trades: [...]}` wrapper anywhere in
// that handler). RegimePnLBreakdownWidget.tsx fetched this endpoint and
// destructured `json.trades` off the response -- `undefined` on a bare
// array (arrays don't have a `.trades` property) -- so
// `setTrades(json.trades ?? [])` always set an empty list. The widget never
// errored; it silently rendered "Regime data not yet available" regardless
// of how many closed trades actually existed.
//
// Same defect class as GT-16 (components/DatabaseStatsCard.tsx /
// lib/databaseStatsTrades.ts) against this same endpoint -- that fix's note
// on the endpoint's inconsistent contract across widgets still applies:
// some widgets assume a bare array, others assume `{trades, count}`. This
// helper defensively accepts either shape rather than depending on the
// backend response staying a bare array.

export interface RegimeTradeRecord {
  trade_id?: string;
  symbol?: string;
  side?: string;
  pnl?: number;
  status?: string;
  // regime may be a top-level field (from some code paths)
  regime?: string;
  // strategy_params JSON blob -- regime stored here as regime or regime_type
  strategy_params?: {
    regime?: string;
    regime_type?: string;
    [key: string]: unknown;
  } | null;
}

export interface TradesHistoryWrapper {
  trades?: RegimeTradeRecord[];
  count?: number;
  error?: string;
  note?: string;
}

export type TradesHistoryPayload = TradesHistoryWrapper | RegimeTradeRecord[];

/**
 * Normalize the /portfolio/history/trades response into a plain trade
 * array, regardless of whether the engine returns a bare array (the real,
 * current shape) or a `{trades: [...]}` wrapper (what the widget used to
 * assume). Unknown/malformed payloads resolve to `[]` rather than throwing,
 * matching the widget's existing "just show empty state" behavior on a bad
 * response.
 */
export function parseTradesHistoryResponse(
  payload: TradesHistoryPayload | null | undefined,
): RegimeTradeRecord[] {
  if (Array.isArray(payload)) return payload;
  if (!payload || typeof payload !== "object") return [];
  return payload.trades ?? [];
}
