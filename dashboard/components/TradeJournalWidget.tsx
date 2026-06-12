"use client";

import React, { useMemo, useState } from "react";
import useSWR from "swr";
import { ChevronDown } from "lucide-react";
import { fetchEngine, type TradeJournalEntry } from "@/lib/api";

const SYMBOLS = ["All", "MCL", "MNQ"];
const REGIMES = [
  "All",
  "TRENDING_BULL",
  "TRENDING_BEAR",
  "RANGE_BOUND",
  "COMPRESSION",
  "EXHAUSTED",
];

function fetcher<T = unknown>(url: string): Promise<T> {
  return fetchEngine<T>(url);
}

export function TradeJournalWidget() {
  const [selectedSymbol, setSelectedSymbol] = useState("All");
  const [selectedRegime, setSelectedRegime] = useState("All");

  // Build query string
  const queryParams = new URLSearchParams();
  if (selectedSymbol !== "All") {
    queryParams.append("symbol", selectedSymbol);
  }
  if (selectedRegime !== "All") {
    queryParams.append("regime", selectedRegime);
  }
  queryParams.append("limit", "50");

  const endpoint = `/journal/trade-journal?${queryParams.toString()}`;

  const { data: trades, isLoading, error } = useSWR<TradeJournalEntry[]>(
    endpoint,
    fetcher,
    { refreshInterval: 60000 }
  );

  // Filter and sort
  const filteredTrades = useMemo(() => {
    if (!trades) return [];
    // Already filtered by query, but sort by entry_time DESC
    return [...trades].sort(
      (a, b) =>
        new Date(b.entry_time).getTime() - new Date(a.entry_time).getTime()
    );
  }, [trades]);

  const noTrades = !isLoading && (!trades || trades.length === 0);

  return (
    <div className="rounded-xl border border-border bg-card p-4 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-semibold text-foreground">Trade Journal</p>
          <p className="text-xs text-muted-foreground">
            Full signal provenance with regime, structure, bias
          </p>
        </div>
      </div>

      {/* Filters */}
      <div className="flex gap-3">
        <div className="flex-1">
          <label className="text-xs text-muted-foreground block mb-1">
            Symbol
          </label>
          <div className="relative">
            <select
              value={selectedSymbol}
              onChange={(e) => setSelectedSymbol(e.target.value)}
              className="w-full rounded-lg border border-border bg-background px-3 py-1.5 text-sm appearance-none cursor-pointer focus:outline-none focus:ring-1 focus:ring-accent"
            >
              {SYMBOLS.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
            <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 h-4 w-4 pointer-events-none text-muted-foreground" />
          </div>
        </div>

        <div className="flex-1">
          <label className="text-xs text-muted-foreground block mb-1">
            Regime
          </label>
          <div className="relative">
            <select
              value={selectedRegime}
              onChange={(e) => setSelectedRegime(e.target.value)}
              className="w-full rounded-lg border border-border bg-background px-3 py-1.5 text-sm appearance-none cursor-pointer focus:outline-none focus:ring-1 focus:ring-accent"
            >
              {REGIMES.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
            <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 h-4 w-4 pointer-events-none text-muted-foreground" />
          </div>
        </div>
      </div>

      {/* Loading state */}
      {isLoading && (
        <div className="space-y-2">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-8 bg-muted rounded animate-pulse" />
          ))}
        </div>
      )}

      {/* Error state */}
      {error && (
        <div className="text-xs text-bear bg-bear/10 border border-bear/30 rounded-lg p-3">
          Failed to load trades. Please try again.
        </div>
      )}

      {/* Empty state */}
      {noTrades && (
        <div className="text-center py-6 text-xs text-muted-foreground">
          No trades found for selected filters.
        </div>
      )}

      {/* Table */}
      {!isLoading && !error && filteredTrades.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border">
                <th className="text-left py-2 px-2 text-muted-foreground font-medium">
                  Date
                </th>
                <th className="text-left py-2 px-2 text-muted-foreground font-medium">
                  Symbol
                </th>
                <th className="text-left py-2 px-2 text-muted-foreground font-medium">
                  Dir
                </th>
                <th className="text-left py-2 px-2 text-muted-foreground font-medium">
                  Regime
                </th>
                <th className="text-left py-2 px-2 text-muted-foreground font-medium">
                  Bias
                </th>
                <th className="text-right py-2 px-2 text-muted-foreground font-medium">
                  P&L
                </th>
                <th className="text-left py-2 px-2 text-muted-foreground font-medium">
                  Signals
                </th>
              </tr>
            </thead>
            <tbody>
              {filteredTrades.map((trade) => {
                const entryDate = new Date(trade.entry_time);
                const dateStr = entryDate.toLocaleDateString("en-US", {
                  month: "short",
                  day: "numeric",
                });

                const isLong = (trade.side ?? "").toLowerCase().includes("buy");
                const dirColor = isLong ? "text-bull" : "text-bear";
                const dirLabel = isLong ? "LONG" : "SHORT";

                const pnlColor =
                  trade.pnl === null
                    ? "text-muted-foreground"
                    : trade.pnl > 0
                    ? "text-bull"
                    : "text-bear";

                const signals = [];
                if (trade.stc_contrib) signals.push("STC");
                if (trade.orb_contrib) signals.push("ORB");
                if (trade.vwap_contrib) signals.push("VWAP");
                const signalStr = signals.length > 0 ? signals.join("+") : "—";

                return (
                  <tr
                    key={trade.id}
                    className="border-b border-border/50 hover:bg-muted/30 transition-colors"
                  >
                    <td className="py-2 px-2 text-muted-foreground font-mono">
                      {dateStr}
                    </td>
                    <td className="py-2 px-2 font-semibold">{trade.symbol}</td>
                    <td className={`py-2 px-2 font-bold ${dirColor}`}>
                      {dirLabel}
                    </td>
                    <td className="py-2 px-2 text-xs">
                      {trade.regime ? (
                        <span className="px-2 py-0.5 bg-accent/10 text-accent rounded">
                          {trade.regime.substring(0, 3)}
                        </span>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td className="py-2 px-2 text-xs">
                      {trade.bias || "—"}
                    </td>
                    <td className={`py-2 px-2 font-mono font-bold text-right ${pnlColor}`}>
                      {trade.pnl !== null ? `$${trade.pnl.toFixed(0)}` : "—"}
                    </td>
                    <td className="py-2 px-2 text-xs font-mono text-muted-foreground">
                      {signalStr}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Footer */}
      <div className="text-xs text-muted-foreground border-t border-border pt-2">
        Showing {filteredTrades.length} trades (polling every 60s)
      </div>
    </div>
  );
}
