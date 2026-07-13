"use client";

import { useState, useEffect } from "react";
import { RefreshCw, BarChart2 } from "lucide-react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  bySymbolStats,
  dedupCaveat,
  type HonestTradeSet,
  type SymbolStat,
} from "@/lib/honestTrades";
import { useHonestTrades } from "@/lib/useHonestTrades";

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmt$(value: number): string {
  const abs = Math.abs(value);
  const sign = value >= 0 ? "+" : "-";
  return `${sign}$${abs.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function winRateBadge(wr: number): "bull" | "warn" | "bear" {
  if (wr >= 55) return "bull";
  if (wr >= 40) return "warn";
  return "bear";
}

function pnlTextClass(value: number): string {
  if (value > 0) return "text-[#00ff88]";
  if (value < 0) return "text-[#ff4444]";
  return "text-[#888888]";
}

// ── Component ─────────────────────────────────────────────────────────────────

export function TopSymbolsWidget() {
  const { honest: set, isLoading: loading, error: loadError, mutate } = useHonestTrades(0);
  const error = loadError
    ? loadError instanceof Error
      ? loadError.message
      : String(loadError)
    : null;
  const stats: SymbolStat[] = set ? bySymbolStats(set.trades) : [];
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  useEffect(() => {
    if (set) setLastUpdated(new Date());
  }, [set]);

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-3">
        <div className="flex items-center gap-2">
          <BarChart2 className="h-4 w-4 text-[#00ff88]" />
          <CardTitle className="text-sm font-mono tracking-wider uppercase">
            Top Symbols
          </CardTitle>
        </div>
        <div className="flex items-center gap-3">
          {lastUpdated && !loading && (
            <span className="font-mono text-[10px] text-[#555]">
              {lastUpdated.toLocaleTimeString()}
            </span>
          )}
          <button
            onClick={() => mutate()}
            disabled={loading}
            className="flex items-center gap-1.5 rounded px-2 py-1 text-[11px] font-mono text-[#00ff88] bg-[#00ff8812] border border-[#00ff8830] transition-colors disabled:opacity-40"
          >
            <RefreshCw className={`h-3 w-3 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </button>
        </div>
      </CardHeader>

      <CardContent>
        {loading && (
          <div className="flex items-center justify-center py-10">
            <RefreshCw className="h-5 w-5 animate-spin text-[#00ff88]" />
            <span className="ml-2 font-mono text-sm text-[#555]">
              Loading trade history…
            </span>
          </div>
        )}

        {!loading && error && (
          <div className="rounded-lg p-4 font-mono text-sm text-[#ff4444] bg-[#ff444412] border border-[#ff444430]">
            Error: {error}
          </div>
        )}

        {!loading && !error && stats.length === 0 && (
          <div className="py-10 text-center">
            <p className="font-mono text-sm text-[#555]">
              No closed trades yet
            </p>
          </div>
        )}

        {!loading && !error && stats.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full font-mono text-xs">
              <thead>
                <tr className="border-b border-panel-border">
                  {["Symbol", "Trades", "Win%", "Total P&L", "Avg P&L"].map((h) => (
                    <th
                      key={h}
                      className={`pb-2 px-3 font-semibold uppercase tracking-wider text-[10px] text-[#555] ${
                        h === "Symbol" ? "text-left" : "text-right"
                      }`}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {stats.map((row) => {
                  const avgPnl = row.trades > 0 ? row.net / row.trades : 0;
                  return (
                    <tr
                      key={row.symbol}
                      className="hover:bg-white/[0.02] transition-colors border-b border-[#111]"
                    >
                      {/* Symbol */}
                      <td className="py-2.5 px-3 text-left">
                        <span className="font-bold text-[#e0e0e0]">
                          {row.symbol}
                        </span>
                      </td>

                      {/* Trades */}
                      <td className="py-2.5 px-3 text-right tabular-nums text-[#888]">
                        {row.trades}
                      </td>

                      {/* Win% badge */}
                      <td className="py-2.5 px-3 text-right">
                        <div className="flex justify-end">
                          <Badge variant={winRateBadge(row.winRate * 100)}>
                            {(row.winRate * 100).toFixed(1)}%
                          </Badge>
                        </div>
                      </td>

                      {/* Total P&L */}
                      <td className="py-2.5 px-3 text-right tabular-nums font-bold">
                        <span className={pnlTextClass(row.net)}>
                          {fmt$(row.net)}
                        </span>
                      </td>

                      {/* Avg P&L */}
                      <td className="py-2.5 px-3 text-right tabular-nums">
                        <span className={pnlTextClass(avgPnl)}>
                          {fmt$(avgPnl)}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>

            {/* Footer summary */}
            <div className="mt-3 pt-3 flex items-center justify-between border-t border-panel-border">
              <span className="font-mono text-[10px] text-[#555]">
                {set ? dedupCaveat(set) : `${stats.length} symbol${stats.length !== 1 ? "s" : ""}`}
              </span>
              <span
                className={`font-mono text-[10px] font-bold tabular-nums ${pnlTextClass(
                  stats.reduce((s, r) => s + r.net, 0)
                )}`}
              >
                Net P&L:{" "}
                {fmt$(stats.reduce((s, r) => s + r.net, 0))}
              </span>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
