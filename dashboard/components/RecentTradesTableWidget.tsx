"use client";

import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { fetchEngine } from "@/lib/api";
import { OfflineFallback } from "@/components/OfflineFallback";
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
} from "@/components/ui/card";


interface Trade {
  trade_id?: string;
  symbol: string;
  action: string;
  entry_price?: number | null;
  exit_price?: number | null;
  pnl?: number | null;
  entry_time?: string | null;
  exit_time?: string | null;
  status?: string;
}

interface TradesResponse {
  trades?: Trade[];
}

function deriveDirection(action: string): "LONG" | "SHORT" {
  const a = action.toUpperCase();
  if (a === "BUY" || a === "LONG" || a === "BUY_LONG") return "LONG";
  return "SHORT";
}

function formatDuration(entry?: string | null, exit?: string | null): string {
  if (!entry || !exit) return "—";
  const diffMs = new Date(exit).getTime() - new Date(entry).getTime();
  if (isNaN(diffMs) || diffMs < 0) return "—";
  const totalMinutes = Math.floor(diffMs / 60_000);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  if (hours === 0) return `${minutes}m`;
  return minutes === 0 ? `${hours}hr` : `${hours}hr ${minutes}m`;
}

function formatPnl(pnl?: number | null): { text: string; className: string } {
  if (pnl == null) return { text: "—", className: "text-muted-foreground" };
  const abs = Math.abs(pnl).toFixed(2);
  if (pnl >= 0) return { text: `+$${abs}`, className: "text-green-400" };
  return { text: `-$${abs}`, className: "text-red-400" };
}

export function RecentTradesTableWidget() {
  const [trades, setTrades] = useState<Trade[]>([]);
  const [error, setError] = useState<string | null>(null);

  const fetchTrades = async () => {
    try {
      const raw: unknown = await fetchEngine(
        `/portfolio/history/trades?limit=10&status=CLOSED`
      );
      const list: Trade[] = Array.isArray(raw)
        ? raw
        : ((raw as { trades?: Trade[] }).trades ?? []);
      setTrades(list);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch");
    }
  };

  useEffect(() => {
    fetchTrades();
    const interval = setInterval(fetchTrades, 120_000);
    return () => clearInterval(interval);
  }, []);

  const totalPnl = trades.reduce((sum, t) => sum + (t.pnl ?? 0), 0);
  const totalPnlFormatted = formatPnl(trades.length > 0 ? totalPnl : null);

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3">
        <CardTitle className="text-base font-semibold">Recent Trades</CardTitle>
        <Badge variant="neutral">Refreshes every 2m</Badge>
      </CardHeader>
      <CardContent>
        {error && (
          <OfflineFallback variant="card" message="Trade history unavailable — engine offline" className="mb-2" />
        )}
        {trades.length === 0 ? (
          <p className="text-sm text-muted-foreground text-center py-6">
            No closed trades yet
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-muted-foreground uppercase">
                  <th className="text-left pb-2 w-7">#</th>
                  <th className="text-left pb-2">Symbol</th>
                  <th className="text-left pb-2">Action</th>
                  <th className="text-right pb-2">Entry</th>
                  <th className="text-right pb-2">Exit</th>
                  <th className="text-right pb-2">P&amp;L</th>
                  <th className="text-right pb-2">Duration</th>
                </tr>
              </thead>
              <tbody>
                {trades.map((trade, i) => {
                  const direction = deriveDirection(trade.action);
                  const pnl = formatPnl(trade.pnl);
                  return (
                    <tr
                      key={trade.trade_id ?? `${trade.symbol}-${i}`}
                      className="border-t border-border"
                    >
                      <td className="py-1.5 font-mono text-muted-foreground">
                        {i + 1}
                      </td>
                      <td className="py-1.5 font-mono font-medium">
                        {trade.symbol}
                      </td>
                      <td className="py-1.5">
                        <Badge variant={direction === "LONG" ? "bull" : "bear"}>
                          {direction}
                        </Badge>
                      </td>
                      <td className="py-1.5 text-right font-mono">
                        {trade.entry_price != null
                          ? trade.entry_price.toFixed(2)
                          : "—"}
                      </td>
                      <td className="py-1.5 text-right font-mono">
                        {trade.exit_price != null
                          ? trade.exit_price.toFixed(2)
                          : "—"}
                      </td>
                      <td
                        className={`py-1.5 text-right font-mono font-medium ${pnl.className}`}
                      >
                        {pnl.text}
                      </td>
                      <td className="py-1.5 text-right font-mono text-muted-foreground">
                        {formatDuration(trade.entry_time, trade.exit_time)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
              <tfoot>
                <tr className="border-t-2 border-border">
                  <td
                    colSpan={5}
                    className="pt-2 text-xs text-muted-foreground font-mono uppercase tracking-wider"
                  >
                    Total ({trades.length} trades)
                  </td>
                  <td
                    className={`pt-2 text-right font-mono font-semibold ${totalPnlFormatted.className}`}
                  >
                    {totalPnlFormatted.text}
                  </td>
                  <td />
                </tr>
              </tfoot>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
