"use client";

import useSWR from "swr";
import { fetchEngine } from "@/lib/api";
import type { UnrealizedPosition, UnrealizedPositionsResponse } from "@/lib/api";

function formatPrice(symbol: string, price: number | null): string {
  if (price === null || price === undefined) return "N/A";
  const upperSym = symbol.toUpperCase();
  if (["MNQ", "MES", "MGC", "NQ", "ES"].includes(upperSym)) {
    return price.toFixed(0);
  }
  return price.toFixed(2);
}

function formatPnL(pnl: number | null): string {
  if (pnl === null || pnl === undefined) return "N/A";
  const sign = pnl >= 0 ? "+" : "";
  return `${sign}$${pnl.toFixed(2)}`;
}

function DirectionBadge({ direction }: { direction: string }) {
  const isLong = direction === "LONG";
  return (
    <span
      className={`inline-flex items-center px-1.5 py-0.5 rounded text-xs font-semibold ${
        isLong
          ? "bg-emerald-900/50 text-emerald-400 border border-emerald-700"
          : "bg-red-900/50 text-red-400 border border-red-700"
      }`}
    >
      {isLong ? "▲ LONG" : "▼ SHORT"}
    </span>
  );
}

function PositionRow({ pos }: { pos: UnrealizedPosition }) {
  const pnlColor =
    pos.unrealized_pnl === null
      ? "text-zinc-400"
      : pos.unrealized_pnl >= 0
      ? "text-emerald-400"
      : "text-red-400";

  return (
    <div className="flex items-start justify-between py-2 border-b border-zinc-800 last:border-0 gap-2">
      <div className="flex flex-col gap-0.5 min-w-0">
        <div className="flex items-center gap-1.5">
          <span className="text-sm font-mono font-semibold text-zinc-100">
            {pos.symbol}
          </span>
          <DirectionBadge direction={pos.direction} />
          <span className="text-xs text-zinc-500">×{pos.quantity}</span>
        </div>
        <div className="text-xs text-zinc-400 font-mono">
          Entry: ${pos.entry_price.toFixed(2)} →{" "}
          <span className="text-zinc-300">
            {pos.current_price !== null
              ? formatPrice(pos.symbol, pos.current_price)
              : "N/A"}
          </span>
        </div>
        <div className="flex gap-2 text-xs text-zinc-500 mt-0.5">
          {pos.stop_loss !== null && (
            <span className="text-red-500/70">
              SL: ${pos.stop_loss.toFixed(2)}
              {pos.stop_distance !== null && (
                <span className="text-zinc-600"> ({pos.stop_distance.toFixed(2)} away)</span>
              )}
            </span>
          )}
          {pos.take_profit !== null && (
            <span className="text-emerald-500/70">
              TP: ${pos.take_profit.toFixed(2)}
              {pos.target_distance !== null && (
                <span className="text-zinc-600"> ({pos.target_distance.toFixed(2)} away)</span>
              )}
            </span>
          )}
        </div>
      </div>
      <div className={`text-sm font-mono font-semibold whitespace-nowrap ${pnlColor}`}>
        {formatPnL(pos.unrealized_pnl)}
      </div>
    </div>
  );
}

export default function UnrealizedPnLWidget() {
  const { data, error, isLoading } = useSWR<UnrealizedPositionsResponse>(
    "/portfolio/paper/positions/unrealized",
    fetchEngine,
    { refreshInterval: 10000 }
  );

  const totalUnrealized =
    data?.reduce((sum, p) => sum + (p.unrealized_pnl ?? 0), 0) ?? null;

  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-zinc-300 tracking-wide uppercase">
          Live Positions
        </h3>
        {totalUnrealized !== null && data && data.length > 0 && (
          <span
            className={`text-sm font-mono font-bold ${
              totalUnrealized >= 0 ? "text-emerald-400" : "text-red-400"
            }`}
          >
            {formatPnL(totalUnrealized)}
          </span>
        )}
      </div>

      {isLoading && (
        <div className="space-y-2">
          {[1, 2].map((i) => (
            <div key={i} className="h-14 bg-zinc-800 rounded animate-pulse" />
          ))}
        </div>
      )}

      {error && !isLoading && (
        <p className="text-xs text-zinc-500 text-center py-4">
          Unable to load positions
        </p>
      )}

      {!isLoading && !error && data && data.length === 0 && (
        <p className="text-xs text-zinc-500 text-center py-6">
          No open positions
        </p>
      )}

      {!isLoading && !error && data && data.length > 0 && (
        <div>
          {data.map((pos) => (
            <PositionRow key={pos.trade_id} pos={pos} />
          ))}
        </div>
      )}
    </div>
  );
}
