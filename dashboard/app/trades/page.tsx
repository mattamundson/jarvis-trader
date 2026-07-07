"use client";

import Link from "next/link";
import useSWR from "swr";
import {
  fetchClosedPaperTrades,
  fetchExecutionOpenTrades,
  type ClosedPaperTradesResponse,
  type ExecutionFidelityStatus,
} from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

function formatDuration(durationSeconds: number): string {
  if (durationSeconds < 60) return `${durationSeconds}s`;
  if (durationSeconds < 3600) {
    const mins = Math.floor(durationSeconds / 60);
    return `${mins}m`;
  }
  const hours = Math.floor(durationSeconds / 3600);
  const mins = Math.floor((durationSeconds % 3600) / 60);
  if (mins === 0) return `${hours}h`;
  return `${hours}h ${mins}m`;
}

function formatPnl(pnl: number): string {
  const sign = pnl > 0 ? "+" : "";
  return `$${sign}${pnl.toFixed(2)}`;
}

function formatPrice(price: number): string {
  return price.toFixed(2);
}

function formatTime(timeStr: string): string {
  try {
    const dt = new Date(timeStr);
    return dt.toLocaleString("en-US", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return timeStr;
  }
}

export default function TradesPage() {
  const { data, error, isLoading } = useSWR<ClosedPaperTradesResponse>(
    "closed-paper-trades",
    fetchClosedPaperTrades,
    { refreshInterval: 30000 }
  );

  const { data: openData } = useSWR<ExecutionFidelityStatus>(
    "execution-open-trades",
    fetchExecutionOpenTrades,
    { refreshInterval: 15000 }
  );

  const trades = data?.trades || [];
  const openTrades = openData?.open_trades || [];

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <p className="text-muted-foreground">Loading trades...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-2">
        <p className="text-destructive font-semibold">Error loading trades</p>
        <p className="text-sm text-muted-foreground">{String(error)}</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex-shrink-0 px-6 py-4 border-b border-border">
        <h1 className="font-mono text-lg font-bold text-foreground">Trade History</h1>
        <p className="text-xs text-muted-foreground mt-1">
          All closed paper trades • Auto-refreshes every 30 seconds
        </p>
      </div>

      {/* Open Positions (live, 15s refresh) */}
      <div className="flex-shrink-0 px-6 py-4 border-b border-border">
        <h2 className="font-mono text-sm font-bold text-foreground mb-2">
          Open Positions{" "}
          <span className="text-xs font-normal text-muted-foreground">
            ({openTrades.length} live • refreshes 15s)
          </span>
        </h2>
        {openTrades.length === 0 ? (
          <p className="text-xs text-muted-foreground">No open positions</p>
        ) : (
          <div className="border border-border rounded-lg overflow-hidden">
            <Table>
              <TableHeader>
                <TableRow className="bg-muted/40">
                  <TableHead className="font-mono text-xs">Symbol</TableHead>
                  <TableHead className="font-mono text-xs">Direction</TableHead>
                  <TableHead className="font-mono text-xs text-right">Qty</TableHead>
                  <TableHead className="font-mono text-xs text-right">Entry Price</TableHead>
                  <TableHead className="font-mono text-xs">Opened At</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {openTrades.map((t, i) => {
                  const isLong = String(t.side).toLowerCase() === "buy";
                  return (
                    <TableRow
                      key={`${t.symbol}-${t.entry_time}-${i}`}
                      className="hover:bg-muted/30 transition-colors"
                    >
                      <TableCell className="font-mono font-semibold text-sm">
                        {t.symbol}
                      </TableCell>
                      <TableCell className="font-mono text-sm">
                        {isLong ? (
                          <span className="text-green-500">LONG</span>
                        ) : (
                          <span className="text-red-500">SHORT</span>
                        )}
                      </TableCell>
                      <TableCell className="font-mono text-sm text-right">
                        {t.quantity}
                      </TableCell>
                      <TableCell className="font-mono text-sm text-right">
                        {formatPrice(t.entry_price)}
                      </TableCell>
                      <TableCell className="font-mono text-xs text-muted-foreground">
                        {formatTime(t.entry_time)}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        )}
      </div>

      {/* Closed Trades Table */}
      <div className="flex-1 overflow-auto px-6 py-4">
        {trades.length === 0 ? (
          <div className="flex items-center justify-center h-40">
            <p className="text-muted-foreground">No closed trades yet</p>
          </div>
        ) : (
          <div className="border border-border rounded-lg overflow-hidden">
            <Table>
              <TableHeader>
                <TableRow className="bg-muted/40">
                  <TableHead className="font-mono text-xs">Symbol</TableHead>
                  <TableHead className="font-mono text-xs">Direction</TableHead>
                  <TableHead className="font-mono text-xs text-right">Entry Price</TableHead>
                  <TableHead className="font-mono text-xs text-right">Exit Price</TableHead>
                  <TableHead className="font-mono text-xs text-right">P&L</TableHead>
                  <TableHead className="font-mono text-xs">Duration</TableHead>
                  <TableHead className="font-mono text-xs">Closed At</TableHead>
                  <TableHead className="font-mono text-xs">Result</TableHead>
                  <TableHead className="font-mono text-xs">Review</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {trades.map((trade) => {
                  const pnl = trade.pnl;
                  let badgeVariant: "bull" | "bear" | "warn" | "info" | "neutral" = "neutral";
                  if (pnl > 0) {
                    badgeVariant = "bull";
                  } else if (pnl < 0) {
                    badgeVariant = "bear";
                  }

                  return (
                    <TableRow
                      key={trade.trade_id}
                      className="hover:bg-muted/30 transition-colors"
                    >
                      <TableCell className="font-mono font-semibold text-sm">
                        {trade.symbol}
                      </TableCell>
                      <TableCell className="font-mono text-sm">
                        {trade.direction === "LONG" ? (
                          <span className="text-green-500">LONG</span>
                        ) : (
                          <span className="text-red-500">SHORT</span>
                        )}
                      </TableCell>
                      <TableCell className="font-mono text-sm text-right">
                        {formatPrice(trade.entry_price)}
                      </TableCell>
                      <TableCell className="font-mono text-sm text-right">
                        {formatPrice(trade.exit_price)}
                      </TableCell>
                      <TableCell className="font-mono text-sm text-right">
                        <span
                          className={
                            pnl > 0
                              ? "text-green-500 font-semibold"
                              : pnl < 0
                                ? "text-red-500 font-semibold"
                                : "text-muted-foreground"
                          }
                        >
                          {formatPnl(pnl)}
                        </span>
                      </TableCell>
                      <TableCell className="font-mono text-sm">
                        {formatDuration(trade.duration_seconds)}
                      </TableCell>
                      <TableCell className="font-mono text-xs text-muted-foreground">
                        {formatTime(trade.exit_time)}
                      </TableCell>
                      <TableCell>
                        <Badge variant={badgeVariant}>
                          {pnl > 0 ? "WIN" : pnl < 0 ? "LOSS" : "BREAK"}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <Link
                          href={`/trades/${trade.trade_id}/review`}
                          className="text-xs text-blue-400 underline hover:text-blue-300"
                        >
                          Review →
                        </Link>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="flex-shrink-0 px-6 py-3 border-t border-border text-xs text-muted-foreground">
        {trades.length} closed trades
      </div>
    </div>
  );
}
