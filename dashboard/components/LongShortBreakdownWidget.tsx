"use client";

import { useEffect, useState, useCallback } from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { TrendingUp, TrendingDown, ArrowUp, ArrowDown } from "lucide-react";
import { fetchEngine } from "@/lib/api";


// ── Types ─────────────────────────────────────────────────────────────────────

interface TradeRecord {
  id: number;
  symbol: string;
  side: string;
  quantity: number;
  entry_price: number;
  exit_price: number;
  realized_pnl: number;
  status: string;
  entry_time: string;
  exit_time: string | null;
  notes: string | null;
}

interface TradesResponse {
  trades: TradeRecord[];
  count: number;
}

interface DirectionStats {
  count: number;
  wins: number;
  totalPnl: number;
  winRate: number; // percentage 0-100
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function isLong(side: string): boolean {
  const s = side.toLowerCase();
  return s.includes("buy") || s === "long";
}

function isShort(side: string): boolean {
  const s = side.toLowerCase();
  return s.includes("sell") || s === "short";
}

function winRateClass(wr: number): string {
  if (wr >= 60) return "text-bull";
  if (wr >= 40) return "text-warn";
  return "text-bear";
}

function pnlClass(pnl: number): string {
  return pnl >= 0 ? "text-bull" : "text-bear";
}

function fmt(v: number, decimals = 2): string {
  return v.toFixed(decimals);
}

function fmtPnl(v: number): string {
  const abs = Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: 0 });
  return v >= 0 ? `+$${abs}` : `-$${abs}`;
}

// ── Metric cell ───────────────────────────────────────────────────────────────

interface MetricRowProps {
  label: string;
  value: string;
  valueClass?: string;
}

function MetricRow({ label, value, valueClass = "text-foreground" }: MetricRowProps) {
  return (
    <div className="flex items-center justify-between py-1.5 border-b border-border/30 last:border-0">
      <span className="text-xs text-muted-foreground uppercase tracking-wider">{label}</span>
      <span className={`text-sm font-semibold font-mono tabular-nums ${valueClass}`}>{value}</span>
    </div>
  );
}

// ── Direction column ──────────────────────────────────────────────────────────

interface DirectionColumnProps {
  direction: "LONG" | "SHORT";
  stats: DirectionStats;
}

function DirectionColumn({ direction, stats }: DirectionColumnProps) {
  const isLongDir = direction === "LONG";
  const avgPnl = stats.count > 0 ? stats.totalPnl / stats.count : 0;

  return (
    <div
      className={`rounded-lg border p-4 flex flex-col gap-2 ${
        isLongDir
          ? "border-bull/20 bg-bull/5"
          : "border-bear/20 bg-bear/5"
      }`}
    >
      {/* Column header */}
      <div className="flex items-center gap-2 mb-1">
        <div
          className={`flex h-7 w-7 items-center justify-center rounded-md ${
            isLongDir ? "bg-bull/15" : "bg-bear/15"
          }`}
        >
          {isLongDir ? (
            <TrendingUp className="h-4 w-4 text-bull" />
          ) : (
            <TrendingDown className="h-4 w-4 text-bear" />
          )}
        </div>
        <span
          className={`text-xs font-bold uppercase tracking-widest ${
            isLongDir ? "text-bull" : "text-bear"
          }`}
        >
          {direction}
        </span>
      </div>

      {/* Win Rate — large display */}
      <div className="text-center py-2">
        <p className="text-xs text-muted-foreground uppercase tracking-wider mb-0.5">Win Rate</p>
        <p className={`text-3xl font-bold font-mono tabular-nums ${winRateClass(stats.winRate)}`}>
          {stats.count > 0 ? `${fmt(stats.winRate, 1)}%` : "—"}
        </p>
      </div>

      {/* Metrics */}
      <div className="mt-1">
        <MetricRow label="Trades" value={String(stats.count)} />
        <MetricRow
          label="Total P&L"
          value={stats.count > 0 ? fmtPnl(stats.totalPnl) : "—"}
          valueClass={stats.count > 0 ? pnlClass(stats.totalPnl) : "text-muted-foreground"}
        />
        <MetricRow
          label="Avg P&L"
          value={stats.count > 0 ? fmtPnl(avgPnl) : "—"}
          valueClass={stats.count > 0 ? pnlClass(avgPnl) : "text-muted-foreground"}
        />
      </div>
    </div>
  );
}

// ── Comparison bar ────────────────────────────────────────────────────────────

interface ComparisonBarProps {
  longCount: number;
  shortCount: number;
}

function ComparisonBar({ longCount, shortCount }: ComparisonBarProps) {
  const total = longCount + shortCount;
  if (total === 0) return null;

  const longPct = (longCount / total) * 100;
  const shortPct = (shortCount / total) * 100;

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span className="flex items-center gap-1">
          <ArrowUp className="h-3 w-3 text-bull" />
          LONG ({longCount})
        </span>
        <span className="flex items-center gap-1">
          SHORT ({shortCount})
          <ArrowDown className="h-3 w-3 text-bear" />
        </span>
      </div>
      <div className="h-2.5 w-full rounded-full overflow-hidden flex bg-background/30">
        <div
          className="h-full bg-bull/70 rounded-l-full transition-all duration-500"
          style={{ width: `${longPct}%` }}
        />
        <div
          className="h-full bg-bear/70 rounded-r-full transition-all duration-500"
          style={{ width: `${shortPct}%` }}
        />
      </div>
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span>{fmt(longPct, 0)}%</span>
        <span>{fmt(shortPct, 0)}%</span>
      </div>
    </div>
  );
}

// ── Main Widget ───────────────────────────────────────────────────────────────

export function LongShortBreakdownWidget() {
  const [longStats, setLongStats] = useState<DirectionStats>({
    count: 0,
    wins: 0,
    totalPnl: 0,
    winRate: 0,
  });
  const [shortStats, setShortStats] = useState<DirectionStats>({
    count: 0,
    wins: 0,
    totalPnl: 0,
    winRate: 0,
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchTrades = useCallback(async () => {
    try {
      const raw: unknown = await fetchEngine(
        `/portfolio/history/trades?status=CLOSED&limit=200`
      );
      const trades: TradeRecord[] = Array.isArray(raw)
        ? raw
        : ((raw as { trades?: TradeRecord[] }).trades ?? []);

      // Filter: exit_time non-null, status CLOSED
      const closed = trades.filter(
        (t: TradeRecord) => t.exit_time !== null && t.status === "CLOSED"
      );

      const newLong: DirectionStats = { count: 0, wins: 0, totalPnl: 0, winRate: 0 };
      const newShort: DirectionStats = { count: 0, wins: 0, totalPnl: 0, winRate: 0 };

      for (const trade of closed) {
        const pnl = trade.realized_pnl ?? 0;

        if (isLong(trade.side)) {
          newLong.count++;
          newLong.totalPnl += pnl;
          if (pnl > 0) newLong.wins++;
        } else if (isShort(trade.side)) {
          newShort.count++;
          newShort.totalPnl += pnl;
          if (pnl > 0) newShort.wins++;
        }
      }

      newLong.winRate = newLong.count > 0 ? (newLong.wins / newLong.count) * 100 : 0;
      newShort.winRate = newShort.count > 0 ? (newShort.wins / newShort.count) * 100 : 0;

      setLongStats(newLong);
      setShortStats(newShort);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load trades");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchTrades();
    const interval = setInterval(fetchTrades, 60_000);
    return () => clearInterval(interval);
  }, [fetchTrades]);

  // Determine edge badge
  function edgeBadgeVariant(): "bull" | "bear" | "neutral" {
    if (longStats.count === 0 && shortStats.count === 0) return "neutral";
    if (longStats.winRate > shortStats.winRate) return "bull";
    if (shortStats.winRate > longStats.winRate) return "bear";
    return "neutral";
  }

  function edgeBadgeLabel(): string {
    if (longStats.count === 0 && shortStats.count === 0) return "No Data";
    if (longStats.winRate > shortStats.winRate) return "LONG Edge";
    if (shortStats.winRate > longStats.winRate) return "SHORT Edge";
    return "Equal";
  }

  const hasData = longStats.count > 0 || shortStats.count > 0;
  const winRateDiff = Math.abs(longStats.winRate - shortStats.winRate);
  const longHasEdge = longStats.winRate > shortStats.winRate;
  const shortHasEdge = shortStats.winRate > longStats.winRate;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between flex-wrap gap-2">
          <CardTitle>Long vs Short Breakdown</CardTitle>
          {!loading && !error && (
            <Badge variant={edgeBadgeVariant()}>{edgeBadgeLabel()}</Badge>
          )}
        </div>
      </CardHeader>

      <CardContent>
        {loading && (
          <p className="text-xs text-muted-foreground animate-pulse">
            Loading trade history…
          </p>
        )}

        {!loading && error && (
          <p className="text-xs text-red-400">Error: {error}</p>
        )}

        {!loading && !error && !hasData && (
          <p className="text-xs text-muted-foreground">
            No closed trades found. Data will appear once trades are closed.
          </p>
        )}

        {!loading && !error && hasData && (
          <div className="space-y-5">
            {/* Two-column grid */}
            <div className="grid grid-cols-2 gap-4">
              <DirectionColumn direction="LONG" stats={longStats} />
              <DirectionColumn direction="SHORT" stats={shortStats} />
            </div>

            {/* Comparison bar */}
            <ComparisonBar longCount={longStats.count} shortCount={shortStats.count} />

            {/* Summary insight */}
            <div className="rounded-lg border border-border/50 bg-background/20 px-4 py-3">
              {longHasEdge && (
                <p className="text-xs text-muted-foreground">
                  <span className="text-bull font-semibold">LONG edge:</span>{" "}
                  +{fmt(winRateDiff, 1)}% win rate vs SHORT
                  {longStats.totalPnl > 0 && (
                    <span className="ml-2 text-bull">
                      ({fmtPnl(longStats.totalPnl)} total)
                    </span>
                  )}
                </p>
              )}
              {shortHasEdge && (
                <p className="text-xs text-muted-foreground">
                  <span className="text-bear font-semibold">SHORT edge:</span>{" "}
                  +{fmt(winRateDiff, 1)}% win rate vs LONG
                  {shortStats.totalPnl > 0 && (
                    <span className="ml-2 text-bull">
                      ({fmtPnl(shortStats.totalPnl)} total)
                    </span>
                  )}
                </p>
              )}
              {!longHasEdge && !shortHasEdge && (
                <p className="text-xs text-muted-foreground">
                  <span className="text-muted-foreground font-semibold">Balanced:</span>{" "}
                  LONG and SHORT have equal win rates ({fmt(longStats.winRate, 1)}%)
                </p>
              )}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default LongShortBreakdownWidget;
