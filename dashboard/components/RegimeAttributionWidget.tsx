"use client";

import useSWR from "swr";
import { fetchEngine } from "@/lib/api";
import type { RegimeStatsResponse, RegimeStatRow } from "@/lib/api";

const REFRESH_MS = 120_000; // 2 min

function fetcher<T>(url: string): Promise<T> {
  return fetchEngine<T>(url);
}

function regimeColor(regime: string): { bar: string; text: string } {
  const r = regime.toLowerCase();
  if (r.includes("bull") || r.includes("trend") && !r.includes("bear"))
    return { bar: "bg-green-500", text: "text-green-400" };
  if (r.includes("bear"))
    return { bar: "bg-red-500", text: "text-red-400" };
  if (r.includes("range") || r.includes("consolidat"))
    return { bar: "bg-yellow-500", text: "text-yellow-400" };
  if (r.includes("volat"))
    return { bar: "bg-orange-500", text: "text-orange-400" };
  return { bar: "bg-sky-500", text: "text-sky-400" };
}

function pnlColor(pnl: number): string {
  if (pnl > 0) return "text-green-400";
  if (pnl < 0) return "text-red-400";
  return "text-muted-foreground";
}

function RegimeRow({ row, maxTrades }: { row: RegimeStatRow; maxTrades: number }) {
  const { bar, text } = regimeColor(row.regime);
  const barPct = maxTrades > 0 ? (row.trade_count / maxTrades) * 100 : 0;
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between text-xs">
        <span className={`font-mono font-medium truncate max-w-[140px] ${text}`}>
          {row.regime.toUpperCase()}
        </span>
        <div className="flex items-center gap-3 text-right">
          <span className="text-muted-foreground tabular-nums w-10">
            {row.win_rate_pct.toFixed(0)}%
          </span>
          <span className={`tabular-nums w-16 ${pnlColor(row.total_pnl)}`}>
            {row.total_pnl >= 0 ? "+" : ""}${row.total_pnl.toFixed(0)}
          </span>
          <span className="text-muted-foreground/60 tabular-nums w-10">
            {row.trade_count}t
          </span>
        </div>
      </div>
      <div className="relative h-1 w-full rounded-full bg-white/10 overflow-hidden">
        <div
          className={`absolute inset-y-0 left-0 rounded-full ${bar}`}
          style={{ width: `${barPct}%`, opacity: 0.6 + (row.win_rate_pct / 100) * 0.4 }}
        />
        {/* Win-rate overlay */}
        <div
          className="absolute inset-y-0 left-0 rounded-full bg-green-400/30"
          style={{ width: `${row.win_rate_pct}%` }}
        />
      </div>
    </div>
  );
}

export function RegimeAttributionWidget() {
  const { data, error, isLoading } = useSWR<RegimeStatsResponse>(
    "/journal/regime-stats",
    fetcher,
    { refreshInterval: REFRESH_MS }
  );

  const maxTrades = data
    ? Math.max(...data.regimes.map((r) => r.trade_count), 1)
    : 1;

  return (
    <div className="rounded-xl border border-border bg-card p-4 space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Regime Attribution
        </p>
        {data && (
          <span className="text-[10px] text-muted-foreground/50">
            {data.total_closed_trades} closed trades
          </span>
        )}
      </div>

      {isLoading && (
        <div className="space-y-2">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-8 rounded bg-white/5 animate-pulse" />
          ))}
        </div>
      )}

      {error && (
        <p className="text-xs text-red-400/70">Engine unavailable — retrying…</p>
      )}

      {data && !isLoading && data.regimes.length === 0 && (
        <div className="py-4 text-center">
          <p className="text-xs text-muted-foreground/50">
            No closed trades yet — regime breakdown will appear here
          </p>
        </div>
      )}

      {data && !isLoading && data.regimes.length > 0 && (
        <>
          {/* Column headers */}
          <div className="flex items-center justify-between text-[10px] text-muted-foreground/50 px-0">
            <span>REGIME</span>
            <div className="flex items-center gap-3">
              <span className="w-10 text-right">WIN%</span>
              <span className="w-16 text-right">P&amp;L</span>
              <span className="w-10 text-right">TRADES</span>
            </div>
          </div>

          <div className="space-y-3">
            {data.regimes.map((row) => (
              <RegimeRow key={row.regime} row={row} maxTrades={maxTrades} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
