"use client";

import { TrendingUp, TrendingDown, Trophy, AlertTriangle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
} from "@/components/ui/card";
import {
  dedupCaveat,
  durationMinutes,
  type HonestTrade,
  type HonestTradeSet,
} from "@/lib/honestTrades";
import { useHonestTrades } from "@/lib/useHonestTrades";

// Columns dropped vs. prior raw version:
//   - Entry price / exit price (not in honest record)
//   - Status filter (honest record = closed trades only)

function formatHoldTime(t: HonestTrade): string {
  const mins = durationMinutes(t);
  if (mins === null) return "—";
  const h = Math.floor(mins / 60);
  const m = Math.round(mins % 60);
  if (h === 0) return `${m}m`;
  if (m === 0) return `${h}h`;
  return `${h}h ${m}m`;
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
    <div className={`animate-pulse rounded bg-muted/30 ${className ?? ""}`} />
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
  trade: HonestTrade;
  label: "Best" | "Worst";
}

function TradeDetailPanel({ trade, label }: TradeDetailPanelProps) {
  const isBest = label === "Best";
  const pnl = trade.pnl;
  const holdTime = formatHoldTime(trade);
  const sideVariant: "bull" | "bear" =
    trade.direction === "LONG" ? "bull" : "bear";

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
        <Badge variant={sideVariant}>{trade.direction}</Badge>
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

      {/* Hold time + entry date */}
      <div className="flex items-center gap-1 font-mono text-xs text-muted-foreground">
        <span>Duration: {holdTime}</span>
      </div>

      {/* Entry time */}
      <div className="font-mono text-[10px] text-muted-foreground/70">
        {trade.entry_time
          ? new Date(trade.entry_time).toLocaleDateString()
          : "—"}
      </div>
    </div>
  );
}

// ── Compact rank list ─────────────────────────────────────────────────────────

interface RankListProps {
  trades: HonestTrade[];
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
        trades.map((trade, idx) => (
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
            <span className={`font-mono text-xs font-bold tabular-nums ${pnlColor(trade.pnl)}`}>
              {formatPnl(trade.pnl)}
            </span>
          </div>
        ))
      )}
    </div>
  );
}

// ── Main Widget ───────────────────────────────────────────────────────────────

export function BestWorstTradeWidget() {
  const { honest: set, isLoading: loading, error: loadError } = useHonestTrades(60_000);
  const error = loadError ? (loadError instanceof Error ? loadError.message : String(loadError)) : null;

  // Sort by pnl descending
  const sorted: HonestTrade[] = set
    ? [...set.trades].sort((a, b) => b.pnl - a.pnl)
    : [];

  const bestTrade = sorted[0] ?? null;
  const worstTrade = sorted[sorted.length - 1] ?? null;
  const top3Winners = sorted.slice(0, 3);
  const top3Losers = sorted.slice(-3).reverse();

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
        ) : sorted.length === 0 ? (
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

            {/* Dedup caveat footer */}
            {set && (
              <p className="text-[10px] font-mono text-muted-foreground/60 text-center">
                {dedupCaveat(set)}
              </p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
