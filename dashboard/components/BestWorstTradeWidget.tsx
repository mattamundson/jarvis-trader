"use client";

import { useEffect, useState } from "react";
import { TrendingUp, TrendingDown, Trophy, AlertTriangle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
} from "@/components/ui/card";
import type { TradeRecord } from "@/lib/api";
import { fetchEngine } from "@/lib/api";


interface TradesResponse {
  trades: TradeRecord[];
  count: number;
}

function formatHoldTime(entryTime: string, exitTime: string): string {
  const diffMs = new Date(exitTime).getTime() - new Date(entryTime).getTime();
  if (isNaN(diffMs) || diffMs < 0) return "—";
  const totalMinutes = Math.floor(diffMs / 60_000);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  if (hours === 0) return `${totalMinutes}m`;
  if (minutes === 0) return `${hours}h`;
  return `${hours}h ${minutes}m`;
}

function formatPnl(pnl: number): string {
  const abs = Math.abs(pnl).toFixed(2);
  return pnl >= 0 ? `+$${abs}` : `-$${abs}`;
}

function pnlColor(pnl: number): string {
  return pnl >= 0 ? "text-bull" : "text-bear";
}

// ── Skeleton ──────────────────────────────────────────────────────────────────

function Skeleton({ className }: { className?: string }) {
  return (
    <div
      className={`animate-pulse rounded bg-muted/30 ${className ?? ""}`}
    />
  );
}

function SkeletonCard() {
  return (
    <div className="space-y-3">
      <Skeleton className="h-5 w-24" />
      <Skeleton className="h-8 w-32" />
      <Skeleton className="h-4 w-40" />
      <Skeleton className="h-4 w-28" />
    </div>
  );
}

// ── Trade Detail Panel ────────────────────────────────────────────────────────

interface TradeDetailPanelProps {
  trade: TradeRecord;
  label: "Best" | "Worst";
}

function TradeDetailPanel({ trade, label }: TradeDetailPanelProps) {
  const isBest = label === "Best";
  const pnl = trade.realized_pnl ?? 0;
  const holdTime =
    trade.exit_time ? formatHoldTime(trade.entry_time, trade.exit_time) : "—";
  const sideVariant: "bull" | "bear" =
    trade.side.toUpperCase() === "BUY" ? "bull" : "bear";

  return (
    <div
      className={`rounded-lg border p-4 flex flex-col gap-3 ${
        isBest
          ? "border-bull/20 bg-bull/5"
          : "border-bear/20 bg-bear/5"
      }`}
    >
      {/* Header row */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          {isBest ? (
            <Trophy className="h-4 w-4 text-bull" />
          ) : (
            <AlertTriangle className="h-4 w-4 text-bear" />
          )}
          <span
            className={`font-mono text-xs font-bold uppercase tracking-wider ${
              isBest ? "text-bull" : "text-bear"
            }`}
          >
            {label} Trade
          </span>
        </div>
        <Badge variant={sideVariant}>{trade.side.toUpperCase()}</Badge>
      </div>

      {/* Symbol + P&L */}
      <div className="flex items-end justify-between">
        <span className="font-mono text-xl font-bold text-foreground">
          {trade.symbol}
        </span>
        <span className={`font-mono text-2xl font-bold ${pnlColor(pnl)}`}>
          {formatPnl(pnl)}
        </span>
      </div>

      {/* Price flow */}
      <div className="flex items-center gap-1 font-mono text-xs text-muted-foreground">
        <span className="text-foreground">{trade.entry_price.toFixed(2)}</span>
        <span className="mx-1">→</span>
        <span className="text-foreground">
          {trade.exit_price != null ? trade.exit_price.toFixed(2) : "—"}
        </span>
        <span className="ml-auto">{holdTime}</span>
      </div>

      {/* Entry time */}
      <div className="font-mono text-[10px] text-muted-foreground/70">
        {new Date(trade.entry_time).toLocaleDateString()}
      </div>
    </div>
  );
}

// ── Compact rank list ─────────────────────────────────────────────────────────

interface RankListProps {
  trades: TradeRecord[];
  type: "winners" | "losers";
}

function RankList({ trades, type }: RankListProps) {
  const isWinners = type === "winners";

  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-2 mb-2">
        {isWinners ? (
          <TrendingUp className="h-3.5 w-3.5 text-bull" />
        ) : (
          <TrendingDown className="h-3.5 w-3.5 text-bear" />
        )}
        <span
          className={`font-mono text-[10px] font-bold uppercase tracking-wider ${
            isWinners ? "text-bull" : "text-bear"
          }`}
        >
          Top 3 {isWinners ? "Winners" : "Losers"}
        </span>
      </div>

      {trades.length === 0 ? (
        <p className="font-mono text-xs text-muted-foreground py-2">No data</p>
      ) : (
        trades.map((trade, idx) => {
          const pnl = trade.realized_pnl ?? 0;
          return (
            <div
              key={trade.id}
              className="flex items-center gap-2 rounded border border-border/50 bg-card/50 px-3 py-1.5"
            >
              <span
                className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full font-mono text-[10px] font-bold ${
                  isWinners
                    ? "bg-bull/10 text-bull"
                    : "bg-bear/10 text-bear"
                }`}
              >
                {idx + 1}
              </span>
              <span className="font-mono text-xs font-medium text-foreground flex-1">
                {trade.symbol}
              </span>
              <span className={`font-mono text-xs font-bold tabular-nums ${pnlColor(pnl)}`}>
                {formatPnl(pnl)}
              </span>
            </div>
          );
        })
      )}
    </div>
  );
}

// ── Main Widget ───────────────────────────────────────────────────────────────

export function BestWorstTradeWidget() {
  const [trades, setTrades] = useState<TradeRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchTrades = async () => {
    try {
      const raw: unknown = await fetchEngine<unknown>(
        `/portfolio/history/trades?status=CLOSED&limit=200`
      );
      const rows: TradeRecord[] = Array.isArray(raw)
        ? raw
        : ((raw as { trades?: TradeRecord[] }).trades ?? []);

      const closed = rows.filter(
        (t: TradeRecord) =>
          t.status === "CLOSED" && t.exit_time != null && t.realized_pnl != null
      );

      // Sort descending by realized_pnl for best → worst
      closed.sort(
        (a: TradeRecord, b: TradeRecord) =>
          (b.realized_pnl ?? 0) - (a.realized_pnl ?? 0),
      );
      setTrades(closed);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch trades");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTrades();
    const interval = setInterval(fetchTrades, 60_000);
    return () => clearInterval(interval);
  }, []);

  const bestTrade = trades[0] ?? null;
  const worstTrade = trades[trades.length - 1] ?? null;
  const top3Winners = trades.slice(0, 3);
  const top3Losers = trades.slice(-3).reverse();

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3">
        <CardTitle>Best &amp; Worst Trades</CardTitle>
        <Badge variant="info">All Time</Badge>
      </CardHeader>

      <CardContent>
        {error && (
          <p className="mb-4 text-sm text-bear">Engine error: {error}</p>
        )}

        {loading ? (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <SkeletonCard />
            <SkeletonCard />
          </div>
        ) : trades.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground">
            No closed trades found
          </p>
        ) : (
          <div className="space-y-6">
            {/* Best / Worst panels */}
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              {bestTrade && (
                <TradeDetailPanel trade={bestTrade} label="Best" />
              )}
              {worstTrade && worstTrade.id !== bestTrade?.id && (
                <TradeDetailPanel trade={worstTrade} label="Worst" />
              )}
              {worstTrade && worstTrade.id === bestTrade?.id && (
                <div className="flex items-center justify-center rounded-lg border border-border/40 bg-muted/10 p-4">
                  <p className="font-mono text-xs text-muted-foreground">
                    Only one closed trade
                  </p>
                </div>
              )}
            </div>

            {/* Top 3 compact lists */}
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <RankList trades={top3Winners} type="winners" />
              <RankList trades={top3Losers} type="losers" />
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
