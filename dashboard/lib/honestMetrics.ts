/**
 * Honest-metrics layer — single source of truth for trade-record P&L.
 *
 * THE CONTRACT
 * ------------
 * Raw engine tables (`daily_pnl`, `trade_reviews`) over-count: one winner has
 * been logged ~6x, inflating the record to a fabricated +$19,889 / PF 1.49 when
 * the deduplicated reality is -$1,378 / PF 0.88. Any panel that displays a
 * TRADE-RECORD number (net realized, win/loss, profit factor, per-trade list)
 * MUST read it through this module, never from the raw tables directly.
 *
 * The honest source is the read-time deduplicated view exposed by the master-api
 * (`GET /master/trading/realized`, wrapped by fetchRealizedPnl). It dedupes by
 * logical trade key at read time, so it is correct even while the writer-side
 * bugs remain.
 *
 * NOTE ON SCOPE: portfolio EQUITY / unrealized panels (e.g. /portfolio) measure a
 * different quantity (mark-to-market balance) and are intentionally NOT routed
 * here. This layer is specifically for the closed-trade record. Panels still
 * reading trade-record numbers from raw tables should migrate to
 * useHonestRealized()/summarizeRealized() — track them in the dashboard README.
 */

import { type RealizedPnl } from "@/lib/masterApi";

/** Normalized, display-ready honest trade-record summary. */
export interface HonestPnlSummary {
  netRealized: number;
  trades: number;
  wins: number;
  losses: number;
  winRate: number; // 0..1
  profitFactor: number;
  /** Re-logged rows collapsed by the dedupe (0 when the raw table is clean). */
  relogsCollapsed: number;
  /** True when the engine record was actually available. */
  ok: boolean;
}

/** Collapse a RealizedPnl payload into the normalized summary. */
export function summarizeRealized(data: RealizedPnl): HonestPnlSummary {
  const es = data.engine_sim;
  return {
    netRealized: es.net_realized,
    trades: es.trades,
    wins: es.wins,
    losses: es.losses,
    winRate: es.win_rate,
    profitFactor: es.profit_factor,
    relogsCollapsed: Math.max(0, es.raw_rows - es.trades),
    ok: es.ok,
  };
}

// NOTE: the honest realized record is fetched through the shared
// `useHonestTrades()` hook (SWR key "honest-trades") so every consumer dedupes
// to one /master/trading/realized request. `summarizeRealized` above is the pure
// transform for any panel that wants the normalized summary from that record —
// do NOT re-introduce a separate SWR key/fetcher here (it would double-fetch).
