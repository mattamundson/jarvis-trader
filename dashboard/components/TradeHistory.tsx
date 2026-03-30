"use client";

import useSWR from "swr";
import { Clock, TrendingUp, TrendingDown } from "lucide-react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchEngine } from "@/lib/api";
import { formatCurrency } from "@/lib/utils";
import type { TradeRecord } from "@/lib/api";

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

export function TradeHistory() {
  const { data: trades, isLoading, error } = useSWR<TradeRecord[]>(
    "/portfolio/history/trades?limit=50",
    fetcher,
    { refreshInterval: REFRESH_MS }
  );

  const rows = trades ?? [];

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
                    Entry
                  </th>
                  <th className="pb-2 pr-3 text-right font-semibold text-muted-foreground uppercase tracking-wider whitespace-nowrap">
                    Exit
                  </th>
                  <th className="pb-2 pr-3 text-right font-semibold text-muted-foreground uppercase tracking-wider">
                    P&L
                  </th>
                  <th className="pb-2 text-left font-semibold text-muted-foreground uppercase tracking-wider">
                    Status
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/50">
                {rows.map((trade) => {
                  const pnl = trade.realized_pnl;
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

                  return (
                    <tr key={trade.id} className="hover:bg-muted/20 transition-colors">
                      {/* Date/Time */}
                      <td className="py-2 pr-3 font-mono text-muted-foreground whitespace-nowrap">
                        {formatDateTime(trade.entry_time)}
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
                            trade.side === "BUY" ? "text-bull" : "text-bear"
                          }`}
                        >
                          {trade.side}
                        </span>
                      </td>

                      {/* Qty */}
                      <td className="py-2 pr-3 text-right tabular-nums text-foreground">
                        {trade.quantity}
                      </td>

                      {/* Entry Price */}
                      <td className="py-2 pr-3 text-right tabular-nums text-foreground">
                        {formatCurrency(trade.entry_price)}
                      </td>

                      {/* Exit Price */}
                      <td className="py-2 pr-3 text-right tabular-nums text-muted-foreground">
                        {trade.exit_price != null
                          ? formatCurrency(trade.exit_price)
                          : "—"}
                      </td>

                      {/* P&L */}
                      <td className={`py-2 pr-3 text-right tabular-nums font-medium ${pnlColor}`}>
                        <span className="flex items-center justify-end gap-1">
                          {PnlIcon && <PnlIcon className="h-3 w-3 shrink-0" />}
                          {pnl != null ? formatCurrency(pnl) : "—"}
                        </span>
                      </td>

                      {/* Status */}
                      <td className="py-2">
                        <StatusBadge status={trade.status} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function StatusBadge({ status }: { status: TradeRecord["status"] }) {
  if (status === "OPEN") return <Badge variant="info">OPEN</Badge>;
  if (status === "CLOSED") return <Badge variant="bull">CLOSED</Badge>;
  return <Badge variant="warn">CANCELLED</Badge>;
}
