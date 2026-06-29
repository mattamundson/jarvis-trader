"use client";

import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import {
  dedupCaveat,
  type HonestTrade,
  type HonestTradeSet,
} from "@/lib/honestTrades";
import { useHonestTrades } from "@/lib/useHonestTrades";

// ── Per-direction stat shape ──────────────────────────────────────────────────

interface DirectionStats {
  total: number;
  wins: number;
  losses: number;
  winRate: number; // 0..100
  avgWin: number;
  avgLoss: number; // <= 0
}

function calcDirectionStats(trades: HonestTrade[]): DirectionStats {
  const wins = trades.filter((t) => t.pnl > 0);
  const losses = trades.filter((t) => t.pnl < 0);
  const total = trades.length;
  const winRate = total > 0 ? (wins.length / total) * 100 : 0;
  const avgWin =
    wins.length > 0 ? wins.reduce((s, t) => s + t.pnl, 0) / wins.length : 0;
  const avgLoss =
    losses.length > 0
      ? losses.reduce((s, t) => s + t.pnl, 0) / losses.length
      : 0;
  return { total, wins: wins.length, losses: losses.length, winRate, avgWin, avgLoss };
}

// ── Main widget ───────────────────────────────────────────────────────────────

export function SignalAccuracyWidget() {
  const { honest: set, isLoading: loading, error: loadError } = useHonestTrades(5 * 60 * 1000);
  const error = !!loadError;

  // Derive per-direction stats from deduped trades
  const longTrades = set?.trades.filter(
    (t) => t.direction === "LONG" || t.action === "BUY" || t.action === "LONG"
  ) ?? [];
  const shortTrades = set?.trades.filter(
    (t) => t.direction === "SHORT" || t.action === "SELL" || t.action === "SHORT"
  ) ?? [];

  const long = calcDirectionStats(longTrades);
  const short = calcDirectionStats(shortTrades);

  const totalAll = long.total + short.total;
  const totalWins = long.wins + short.wins;
  const overallWinRate = totalAll > 0 ? (totalWins / totalAll) * 100 : 0;

  const overallVariant: "bull" | "warn" | "bear" =
    overallWinRate >= 55 ? "bull" : overallWinRate >= 45 ? "warn" : "bear";

  const caveat = set ? dedupCaveat(set) : "";

  return (
    <Card>
      <CardHeader className="flex flex-row justify-between items-center">
        <CardTitle>Signal Accuracy</CardTitle>
        {!loading && !error && set && (
          <Badge variant={overallVariant}>
            {overallWinRate.toFixed(1)}% Overall
          </Badge>
        )}
        {loading && !set && <Badge variant="neutral">LOADING…</Badge>}
        {error && <Badge variant="bear">ERROR</Badge>}
      </CardHeader>
      <CardContent>
        {loading ? (
          <p className="text-sm text-muted-foreground text-center py-6">
            Loading trade data…
          </p>
        ) : error ? (
          <p className="text-sm text-muted-foreground text-center py-6">
            Could not load trades — engine offline?
          </p>
        ) : totalAll < 5 ? (
          <p className="text-sm text-muted-foreground text-center py-6">
            Need more trade data (min 5 trades)
          </p>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-4">
              {/* LONG side */}
              <div className="rounded bg-muted p-3">
                <div className="flex justify-between items-center mb-2">
                  <Badge variant="bull">LONG</Badge>
                  <span className="text-xs text-muted-foreground">
                    {long.total} trades
                  </span>
                </div>
                <div className="space-y-1 text-xs">
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Win Rate</span>
                    <span
                      className={cn(
                        "font-mono",
                        long.winRate >= 55
                          ? "text-green-400"
                          : long.winRate < 45
                          ? "text-red-400"
                          : ""
                      )}
                    >
                      {long.total > 0 ? long.winRate.toFixed(1) + "%" : "N/A"}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Wins / Losses</span>
                    <span className="font-mono">
                      {long.wins} / {long.losses}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Avg Win</span>
                    <span className="font-mono text-green-400">
                      {long.wins > 0 ? `+$${long.avgWin.toFixed(2)}` : "—"}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Avg Loss</span>
                    <span className="font-mono text-red-400">
                      {long.losses > 0 ? `-$${Math.abs(long.avgLoss).toFixed(2)}` : "—"}
                    </span>
                  </div>
                </div>
              </div>

              {/* SHORT side */}
              <div className="rounded bg-muted p-3">
                <div className="flex justify-between items-center mb-2">
                  <Badge variant="bear">SHORT</Badge>
                  <span className="text-xs text-muted-foreground">
                    {short.total} trades
                  </span>
                </div>
                <div className="space-y-1 text-xs">
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Win Rate</span>
                    <span
                      className={cn(
                        "font-mono",
                        short.winRate >= 55
                          ? "text-green-400"
                          : short.winRate < 45
                          ? "text-red-400"
                          : ""
                      )}
                    >
                      {short.total > 0 ? short.winRate.toFixed(1) + "%" : "N/A"}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Wins / Losses</span>
                    <span className="font-mono">
                      {short.wins} / {short.losses}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Avg Win</span>
                    <span className="font-mono text-green-400">
                      {short.wins > 0 ? `+$${short.avgWin.toFixed(2)}` : "—"}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Avg Loss</span>
                    <span className="font-mono text-red-400">
                      {short.losses > 0
                        ? `-$${Math.abs(short.avgLoss).toFixed(2)}`
                        : "—"}
                    </span>
                  </div>
                </div>
              </div>
            </div>

            <p className="text-xs text-muted-foreground mt-3">
              {caveat} · Refreshes every 5m
            </p>
          </>
        )}
      </CardContent>
    </Card>
  );
}
