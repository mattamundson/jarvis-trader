"use client";

import { useEffect, useState } from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { BarChart2 } from "lucide-react";

const ENGINE_URL = process.env.NEXT_PUBLIC_ENGINE_URL || "http://localhost:8010";

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

interface TradeHistoryResponse {
  trades: TradeRecord[];
  count: number;
}

interface SymbolStats {
  symbol: string;
  count: number;
  wins: number;
  totalPnl: number;
  avgPnl: number;
  winRate: number;
  avgHoldMinutes: number;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function winRateBadgeVariant(rate: number): "bull" | "warn" | "bear" {
  if (rate >= 60) return "bull";
  if (rate >= 40) return "warn";
  return "bear";
}

function formatPnl(value: number): string {
  const abs = Math.abs(value).toFixed(2);
  return value >= 0 ? `+$${abs}` : `-$${abs}`;
}

function formatHoldTime(minutes: number): string {
  if (minutes < 60) return `${Math.round(minutes)}m`;
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  return m > 0 ? `${h}h ${m}m` : `${h}h`;
}

function buildSymbolStats(trades: TradeRecord[]): SymbolStats[] {
  const closed = trades.filter(
    (t) => t.status === "CLOSED" && t.exit_time !== null
  );

  const map = new Map<string, SymbolStats>();

  for (const trade of closed) {
    const existing = map.get(trade.symbol);

    const entryMs = new Date(trade.entry_time).getTime();
    const exitMs = new Date(trade.exit_time as string).getTime();
    const holdMinutes = (exitMs - entryMs) / 60000;

    if (!existing) {
      map.set(trade.symbol, {
        symbol: trade.symbol,
        count: 1,
        wins: trade.realized_pnl > 0 ? 1 : 0,
        totalPnl: trade.realized_pnl,
        avgPnl: trade.realized_pnl,
        winRate: trade.realized_pnl > 0 ? 100 : 0,
        avgHoldMinutes: holdMinutes,
      });
    } else {
      const newCount = existing.count + 1;
      const newWins = existing.wins + (trade.realized_pnl > 0 ? 1 : 0);
      const newTotalPnl = existing.totalPnl + trade.realized_pnl;
      const newAvgHold =
        (existing.avgHoldMinutes * existing.count + holdMinutes) / newCount;

      map.set(trade.symbol, {
        symbol: trade.symbol,
        count: newCount,
        wins: newWins,
        totalPnl: newTotalPnl,
        avgPnl: newTotalPnl / newCount,
        winRate: (newWins / newCount) * 100,
        avgHoldMinutes: newAvgHold,
      });
    }
  }

  return Array.from(map.values()).sort((a, b) => b.totalPnl - a.totalPnl);
}

// ── Component ─────────────────────────────────────────────────────────────────

export function WinRateBySymbolWidget() {
  const [stats, setStats] = useState<SymbolStats[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchData = () => {
    setLoading(true);
    setError(null);
    fetch(
      `${ENGINE_URL}/portfolio/history/trades?status=CLOSED&limit=200`
    )
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json() as Promise<TradeHistoryResponse>;
      })
      .then((data) => {
        setStats(buildSymbolStats(data.trades));
        setLoading(false);
      })
      .catch((e: unknown) => {
        const msg = e instanceof Error ? e.message : String(e);
        setError(msg);
        setLoading(false);
      });
  };

  useEffect(() => {
    fetchData();
    const id = setInterval(fetchData, 60_000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Overall win rate across all symbols
  const overallStats =
    stats && stats.length > 0
      ? (() => {
          const totalTrades = stats.reduce((s, r) => s + r.count, 0);
          const totalWins = stats.reduce((s, r) => s + r.wins, 0);
          return {
            symbols: stats.length,
            winRate: totalTrades > 0 ? (totalWins / totalTrades) * 100 : 0,
            totalTrades,
          };
        })()
      : null;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <BarChart2 className="h-4 w-4 text-muted-foreground" />
            <CardTitle>Win Rate by Symbol</CardTitle>
          </div>
          <Badge variant="info">info</Badge>
        </div>
      </CardHeader>

      <CardContent>
        {/* Loading skeleton */}
        {loading && !stats && (
          <div className="space-y-3">
            {[...Array(3)].map((_, i) => (
              <div key={i} className="h-14 rounded bg-muted animate-pulse" />
            ))}
          </div>
        )}

        {/* Error state */}
        {error && !loading && (
          <p className="text-xs text-bear py-2">Failed to load trade history: {error}</p>
        )}

        {/* Empty state */}
        {stats && stats.length === 0 && (
          <p className="text-xs text-muted-foreground py-2">
            No closed trades found.
          </p>
        )}

        {/* Symbol rows */}
        {stats && stats.length > 0 && (
          <div className="space-y-4">
            {stats.map((row) => {
              const variant = winRateBadgeVariant(row.winRate);
              const pnlClass =
                row.totalPnl > 0
                  ? "text-bull"
                  : row.totalPnl < 0
                  ? "text-bear"
                  : "text-muted-foreground";
              const avgPnlClass =
                row.avgPnl > 0
                  ? "text-bull"
                  : row.avgPnl < 0
                  ? "text-bear"
                  : "text-muted-foreground";

              return (
                <div key={row.symbol} className="space-y-1.5">
                  {/* Row header */}
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono font-bold text-sm text-foreground">
                      {row.symbol}
                    </span>
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-muted-foreground">
                        {row.count} trade{row.count !== 1 ? "s" : ""}
                      </span>
                      <Badge variant={variant}>
                        {row.winRate.toFixed(1)}% WR
                      </Badge>
                    </div>
                  </div>

                  {/* Win rate progress bar */}
                  <div className="flex items-center gap-2">
                    <div className="flex-1 h-1.5 bg-muted rounded-full overflow-hidden">
                      <div
                        className="h-full bg-bull rounded-full"
                        style={{ width: `${row.winRate}%` }}
                      />
                    </div>
                    <span className="text-xs tabular-nums text-muted-foreground w-10 text-right">
                      {row.winRate.toFixed(1)}%
                    </span>
                  </div>

                  {/* Stats row */}
                  <div className="flex items-center gap-3 text-xs">
                    <span>
                      P&amp;L:{" "}
                      <span className={`font-mono font-semibold ${pnlClass}`}>
                        {formatPnl(row.totalPnl)}
                      </span>
                    </span>
                    <span className="text-muted-foreground">&middot;</span>
                    <span>
                      Avg:{" "}
                      <span className={`font-mono font-semibold ${avgPnlClass}`}>
                        {formatPnl(row.avgPnl)}/trade
                      </span>
                    </span>
                    <span className="text-muted-foreground">&middot;</span>
                    <span className="text-muted-foreground">
                      Avg Hold:{" "}
                      <span className="text-foreground font-mono">
                        {formatHoldTime(row.avgHoldMinutes)}
                      </span>
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* Summary footer */}
        {overallStats && (
          <div className="mt-4 pt-3 border-t border-border flex items-center justify-between text-xs text-muted-foreground">
            <span>
              {overallStats.symbols} symbol{overallStats.symbols !== 1 ? "s" : ""} tracked
            </span>
            <span>
              Overall win rate:{" "}
              <span className="font-mono font-semibold text-foreground">
                {overallStats.winRate.toFixed(1)}%
              </span>{" "}
              ({overallStats.totalTrades} trades)
            </span>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
