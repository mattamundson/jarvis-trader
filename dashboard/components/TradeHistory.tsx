"use client";

import { useState } from "react";
import useSWR from "swr";
import { Clock, TrendingUp, TrendingDown } from "lucide-react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchEngine } from "@/lib/api";
import { formatCurrency } from "@/lib/utils";
import type { TradeRecord } from "@/lib/api";
import { TradeReviewPanel } from "./TradeReviewPanel";

const REFRESH_MS = 30_000;

function fetcher<T>(path: string): Promise<T> {
  return fetchEngine<T>(path);
}

function formatDateTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  const date = d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  const time = d.toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
  return `${date} ${time}`;
}

const GRADE_STYLES: Record<string, string> = {
  A: "bg-emerald-500/15 text-emerald-400 border border-emerald-500/30",
  B: "bg-teal-500/15 text-teal-400 border border-teal-500/30",
  C: "bg-yellow-500/15 text-yellow-400 border border-yellow-500/30",
  D: "bg-orange-500/15 text-orange-400 border border-orange-500/30",
  F: "bg-red-500/15 text-red-400 border border-red-500/30",
};

function GradeBadge({
  grade,
  reviewStatus,
}: {
  grade: string | null;
  reviewStatus: string | null;
}) {
  if (grade && GRADE_STYLES[grade]) {
    return (
      <span
        className={`inline-flex items-center justify-center w-6 h-6 rounded text-[10px] font-bold ${GRADE_STYLES[grade]}`}
      >
        {grade}
      </span>
    );
  }
  if (reviewStatus === "pending") {
    return (
      <span className="inline-flex items-center justify-center w-6 h-6 rounded text-[10px] font-bold bg-muted/40 text-muted-foreground border border-border animate-pulse">
        …
      </span>
    );
  }
  if (reviewStatus === "failed") {
    return (
      <span className="inline-flex items-center justify-center w-6 h-6 rounded text-[10px] font-bold bg-muted/40 text-muted-foreground border border-border">
        ?
      </span>
    );
  }
  return <span className="text-muted-foreground/40">—</span>;
}

export function TradeHistory() {
  const [selectedTradeId, setSelectedTradeId] = useState<string | null>(null);

  const { data: trades, isLoading, error } = useSWR<TradeRecord[]>(
    "/portfolio/history/trades?limit=50",
    fetcher,
    { refreshInterval: REFRESH_MS }
  );

  const rows = trades ?? [];

  function toggleRow(tradeId: string) {
    setSelectedTradeId((prev) => (prev === tradeId ? null : tradeId));
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2">
            <Clock className="h-4 w-4 text-muted-foreground" />
            Trade History
          </CardTitle>
          <span className="text-xs text-muted-foreground tabular-nums">
            {rows.length > 0 ? `${rows.length} records` : ""}
          </span>
        </div>
      </CardHeader>
      <CardContent>
        {isLoading && (
          <div className="flex items-center justify-center py-8">
            <div className="h-4 w-4 rounded-full border-2 border-accent border-t-transparent animate-spin mr-2" />
            <span className="text-xs text-muted-foreground">Loading trade history…</span>
          </div>
        )}

        {error && !isLoading && (
          <p className="text-center text-xs text-bear py-6">
            Failed to load trade history — engine may be offline.
          </p>
        )}

        {!isLoading && !error && rows.length === 0 && (
          <p className="text-center text-sm text-muted-foreground py-8">
            No trade history yet
          </p>
        )}

        {!isLoading && !error && rows.length > 0 && (
          <>
            <div className="overflow-x-auto -mx-1">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-border">
                    <th className="pb-2 pr-3 text-left font-semibold text-muted-foreground uppercase tracking-wider whitespace-nowrap">
                      Date / Time
                    </th>
                    <th className="pb-2 pr-3 text-left font-semibold text-muted-foreground uppercase tracking-wider">
                      Symbol
                    </th>
                    <th className="pb-2 pr-3 text-left font-semibold text-muted-foreground uppercase tracking-wider">
                      Side
                    </th>
                    <th className="pb-2 pr-3 text-right font-semibold text-muted-foreground uppercase tracking-wider">
                      Qty
                    </th>
                    <th className="pb-2 pr-3 text-right font-semibold text-muted-foreground uppercase tracking-wider whitespace-nowrap">
                      Price
                    </th>
                    <th className="pb-2 pr-3 text-right font-semibold text-muted-foreground uppercase tracking-wider">
                      P&L
                    </th>
                    <th className="pb-2 text-center font-semibold text-muted-foreground uppercase tracking-wider">
                      Grade
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/50">
                  {rows.map((trade) => {
                    const pnl = trade.pnl;
                    const pnlColor =
                      pnl == null
                        ? "text-muted-foreground"
                        : pnl > 0
                        ? "text-bull"
                        : pnl < 0
                        ? "text-bear"
                        : "text-muted-foreground";
                    const PnlIcon =
                      pnl != null && pnl > 0
                        ? TrendingUp
                        : pnl != null && pnl < 0
                        ? TrendingDown
                        : null;
                    const isSelected = selectedTradeId === trade.trade_id;

                    return (
                      <tr
                        key={trade.trade_id}
                        onClick={() => toggleRow(trade.trade_id)}
                        className={`cursor-pointer transition-colors ${
                          isSelected
                            ? "bg-accent/10 hover:bg-accent/15"
                            : "hover:bg-muted/20"
                        }`}
                      >
                        {/* Date/Time */}
                        <td className="py-2 pr-3 font-mono text-muted-foreground whitespace-nowrap">
                          {formatDateTime(trade.timestamp)}
                        </td>

                        {/* Symbol */}
                        <td className="py-2 pr-3">
                          <span className="font-mono font-semibold text-foreground">
                            {trade.symbol}
                          </span>
                        </td>

                        {/* Side */}
                        <td className="py-2 pr-3">
                          <span
                            className={`font-mono font-bold ${
                              trade.action === "BUY" ? "text-bull" : "text-bear"
                            }`}
                          >
                            {trade.action}
                          </span>
                        </td>

                        {/* Qty */}
                        <td className="py-2 pr-3 text-right tabular-nums text-foreground">
                          {trade.quantity}
                        </td>

                        {/* Price */}
                        <td className="py-2 pr-3 text-right tabular-nums text-foreground">
                          {formatCurrency(trade.price)}
                        </td>

                        {/* P&L */}
                        <td className={`py-2 pr-3 text-right tabular-nums font-medium ${pnlColor}`}>
                          <span className="flex items-center justify-end gap-1">
                            {PnlIcon && <PnlIcon className="h-3 w-3 shrink-0" />}
                            {pnl != null ? formatCurrency(pnl) : "—"}
                          </span>
                        </td>

                        {/* Grade */}
                        <td className="py-2 text-center">
                          <GradeBadge
                            grade={trade.grade}
                            reviewStatus={trade.review_status}
                          />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {/* Review Panel — expands below table when a row is selected */}
            {selectedTradeId && (
              <div className="mt-4 border-t border-border pt-4">
                <TradeReviewPanel
                  tradeId={selectedTradeId}
                  onClose={() => setSelectedTradeId(null)}
                />
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
