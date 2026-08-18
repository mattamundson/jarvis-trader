// Pure trade-marker derivation for the /analysis price chart (GT-10).
//
// WHY: GET /portfolio/history/trades carries a trade's real direction on the
// `side` field (buy | sell | buy_to_open | sell_to_open, normalized upstream
// to BUY | SELL | HOLD). There is no `action` field on that payload. Reading
// a nonexistent field silently returns undefined instead of throwing, which
// is how every marker on the chart ended up rendered as a flat "hold" instead
// of the real 42 buy / 21 sell split. Kept side-effect-free and dependency-free
// (no lightweight-charts import) so it's testable under `node --test` without
// mounting the chart or SWR.
//
// Run: cd dashboard && pnpm run test:unit

export interface TradeMarkerInput {
  symbol?: string | null;
  side?: string | null;
  entry_time?: string | null;
  entry_price?: number | null;
  exit_time?: string | null;
  realized_pnl?: number | null;
}

export interface TradeMarker {
  time: number;
  position: "aboveBar" | "belowBar";
  shape: "arrowUp" | "arrowDown";
  color: string;
  text: string;
}

export const UP = "#00ff88";
export const DOWN = "#ff4466";

export function toUnix(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const ms = new Date(iso).getTime();
  return Number.isFinite(ms) ? Math.floor(ms / 1000) : null;
}

/**
 * Normalize a trade's direction to "buy" | "sell" | "hold" by reading the
 * real `side` column. Never reads a nonexistent `action` field.
 */
export function deriveTradeSide(trade: TradeMarkerInput): "buy" | "sell" | "hold" {
  const raw = String(trade.side ?? "").toLowerCase();
  if (raw.includes("buy")) return "buy";
  if (raw.includes("sell")) return "sell";
  return "hold";
}

/**
 * Build entry/exit markers for closed trades on the selected symbol, clipped
 * to the loaded bar window so off-chart history doesn't clutter the axis.
 */
export function buildTradeMarkers(
  trades: TradeMarkerInput[] | undefined,
  symbol: string,
  firstBarTime: number | null,
  lastBarTime: number | null,
): TradeMarker[] {
  if (!trades?.length || firstBarTime == null || lastBarTime == null) return [];
  const out: TradeMarker[] = [];

  for (const t of trades) {
    if (!t.symbol || !(t.symbol === symbol || t.symbol.startsWith(symbol))) continue;
    const side = deriveTradeSide(t);
    const isLong = side === "buy";

    const entryT = toUnix(t.entry_time);
    if (entryT != null && entryT >= firstBarTime && entryT <= lastBarTime) {
      out.push({
        time: entryT,
        position: isLong ? "belowBar" : "aboveBar",
        shape: isLong ? "arrowUp" : "arrowDown",
        color: isLong ? UP : DOWN,
        text: `${side.toUpperCase()} ${t.entry_price}`,
      });
    }

    const exitT = toUnix(t.exit_time);
    if (exitT != null && exitT >= firstBarTime && exitT <= lastBarTime) {
      const pnl = t.realized_pnl;
      out.push({
        time: exitT,
        position: isLong ? "aboveBar" : "belowBar",
        shape: isLong ? "arrowDown" : "arrowUp",
        color: (pnl ?? 0) >= 0 ? UP : DOWN,
        text: pnl != null ? `${pnl >= 0 ? "+" : ""}${pnl.toFixed(0)}` : "EXIT",
      });
    }
  }

  // lightweight-charts requires markers in ascending time order.
  out.sort((a, b) => a.time - b.time);
  return out;
}
