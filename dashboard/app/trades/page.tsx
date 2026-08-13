"use client";

import { POLL_INTERVAL } from "@/lib/polling-config";

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
import { useHonestTrades } from "@/lib/useHonestTrades";
import { dedupCaveat, isHonestUnavailable } from "@/lib/honestTrades";

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
    { refreshInterval: POLL_INTERVAL.SLOW }
  );

  const { data: openData } = useSWR<ExecutionFidelityStatus>(
    "execution-open-trades",
    fetchExecutionOpenTrades,
    { refreshInterval: POLL_INTERVAL.STATUS }
  );

  // Honest deduped trade record — same underlying paper_trades table as the
  // closed-trades table below, but read-time deduped (see lib/honestTrades.ts
  // header: raw endpoints over-count re-logged winners). The per-trade
  // WIN/LOSS badges in the table below still come from the raw
  // /paper/validation/trades/closed endpoint, since it carries entry/exit
  // price + duration fields the deduped record doesn't -- but the aggregate
  // totals must come from here, not from summing that raw table.
  const { honest, isLoading: honestLoading } = useHonestTrades();
  const honestUnavailable = isHonestUnavailable(honest, honestLoading);

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

      {/* Honest Totals (deduped) — canonical aggregate numbers. The raw
          closed-trades table below (and its per-trade WIN/LOSS badges) reads
          straight off paper_trades and can over-count re-logged rows; these
          totals come from the read-time-deduped record instead. */}
      <div className="flex-shrink-0 px-6 py-4 border-b border-border">
        <div className="flex items-center gap-2 mb-2">
          <h2 className="font-mono text-sm font-bold text-foreground">Honest Totals</h2>
          {honest && (
            <Badge variant="info">{dedupCaveat(honest)}</Badge>
          )}
        </div>
        {honestUnavailable ? (
          <p className="text-xs text-muted-foreground">
            Honest trade record unavailable — not falling back to raw totals to avoid
            showing inflated numbers.
          </p>
        ) : !honest ? (
          <p className="text-xs text-muted-foreground">Loading honest totals…</p>
        ) : (
          <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
            <div className="rounded-lg border border-border bg-card/50 px-3 py-2">
              <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Total</p>
              <p className="font-mono text-lg font-bold text-foreground">{honest.trades.length}</p>
            </div>
            <div className="rounded-lg border border-border bg-card/50 px-3 py-2">
              <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Wins</p>
              <p className="font-mono text-lg font-bold text-green-500">{honest.wins}</p>
            </div>
            <div className="rounded-lg border border-border bg-card/50 px-3 py-2">
              <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Losses</p>
              <p className="font-mono text-lg font-bold text-red-500">{honest.losses}</p>
            </div>
            <div className="rounded-lg border border-border bg-card/50 px-3 py-2">
              <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Win Rate</p>
              <p className="font-mono text-lg font-bold text-foreground">
                {(honest.winRate * 100).toFixed(1)}%
              </p>
            </div>
            <div className="rounded-lg border border-border bg-card/50 px-3 py-2">
              <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Total P&L</p>
              <p
                className={`font-mono text-lg font-bold ${
                  honest.net > 0 ? "text-green-500" : honest.net < 0 ? "text-red-500" : "text-muted-foreground"
                }`}
              >
                {honest.net >= 0 ? "+" : ""}
                {honest.net.toFixed(2)}
              </p>
            </div>
          </div>
        )}
      </div>

      {/* Open Positions (live, 15s refresh) */}
      <div className="flex-shrink-0 px-6 py-4 border-b border-border">
        <div className="flex items-center gap-2 mb-2">
          <h2 className="font-mono text-sm font-bold text-foreground">
            Open Positions{" "}
            <span className="text-xs font-normal text-muted-foreground">
              ({openTrades.length} live • refreshes 15s)
            </span>
          </h2>
          {openData && (
            <Badge variant={openData.measuring_real_fills ? "live" : "static"}>
              {openData.measuring_real_fills ? "LIVE FILLS" : "SIMULATED"}
            </Badge>
          )}
        </div>
        {openData?.note && (
          <p className="text-[11px] text-muted-foreground mb-2">{openData.note}</p>
        )}
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
        {trades.length > 0 && (
          <p className="mb-2 text-[11px] text-muted-foreground">
            Raw per-trade rows below (entry/exit price, duration) — may include
            re-logged/duplicate rows and is not deduped. The per-trade &quot;Result&quot; badge
            is informational only; use the &quot;Honest Totals&quot; above for real P&amp;L,
            win count, and loss count.
          </p>
        )}
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
