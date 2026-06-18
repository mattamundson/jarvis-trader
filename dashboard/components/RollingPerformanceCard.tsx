"use client";

import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { BarChart2 } from "lucide-react";
import {
  type HonestTrade,
  dailyPnl,
  perTradeSharpe,
  dedupCaveat,
} from "@/lib/honestTrades";
import { useHonestTrades } from "@/lib/useHonestTrades";

const WINDOWS = [7, 14, 30] as const;

function fmt(v: number | null, decimals = 2): string {
  if (v === null || v === undefined) return "N/A";
  return v.toFixed(decimals);
}

function fmtPct(v: number | null): string {
  if (v === null || v === undefined) return "N/A";
  return `${(v * 100).toFixed(1)}%`;
}

function fmtUsd(v: number): string {
  return v >= 0 ? `+$${v.toFixed(2)}` : `-$${Math.abs(v).toFixed(2)}`;
}

/** Trades that closed within the last `days` days (UTC). */
function filterByWindow(trades: HonestTrade[], days: number): HonestTrade[] {
  const cutoff = Date.now() - days * 24 * 60 * 60 * 1000;
  return trades.filter((t) => {
    if (!t.exit_time) return false;
    return Date.parse(t.exit_time) >= cutoff;
  });
}

interface DerivedRollingMetrics {
  tradeCount: number;
  grossPnl: number;
  winRate: number | null;
  avgPnlPerTrade: number | null;
  profitFactor: number | null;
  /** Per-trade Sharpe (mean/stdev of trade P&L). NOT annualized. */
  perTradeSharpeVal: number | null;
  windowStart: string;
  windowEnd: string;
}

function deriveRolling(trades: HonestTrade[], days: number): DerivedRollingMetrics {
  const windowed = filterByWindow(trades, days);
  const n = windowed.length;

  const grossPnl = windowed.reduce((s, t) => s + t.pnl, 0);
  const wins = windowed.filter((t) => t.pnl > 0);
  const losses = windowed.filter((t) => t.pnl < 0);
  const grossWin = wins.reduce((s, t) => s + t.pnl, 0);
  const grossLoss = Math.abs(losses.reduce((s, t) => s + t.pnl, 0));

  const winRate = n > 0 ? wins.length / n : null;
  const avgPnlPerTrade = n > 0 ? grossPnl / n : null;
  const profitFactor = grossLoss > 0 ? grossWin / grossLoss : null;
  const perTradeSharpeVal = perTradeSharpe(windowed);

  // Window date range from dailyPnl helper
  const dp = dailyPnl(windowed);
  const windowStart = dp.length > 0 ? dp[0].date : "";
  const windowEnd = dp.length > 0 ? dp[dp.length - 1].date : "";

  return { tradeCount: n, grossPnl, winRate, avgPnlPerTrade, profitFactor, perTradeSharpeVal, windowStart, windowEnd };
}

export function RollingPerformanceCard() {
  const [rollingWindow, setRollingWindow] = useState<7 | 14 | 30>(30);
  const { honest: honestSet, isLoading: loading, error: fetchErrorObj } = useHonestTrades(300_000);
  const fetchError = !!fetchErrorObj;

  const metrics = honestSet
    ? deriveRolling(honestSet.trades, rollingWindow)
    : null;

  const pfPass = metrics?.profitFactor !== null && (metrics?.profitFactor ?? 0) >= 2.0;
  // per-trade Sharpe threshold: >= 0.5 (different scale than annualized)
  const sharpePass =
    metrics?.perTradeSharpeVal !== null && (metrics?.perTradeSharpeVal ?? 0) >= 0.5;

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm flex items-center gap-2">
            <BarChart2 className="h-4 w-4" />
            Rolling Performance
          </CardTitle>
          <div className="flex gap-1">
            {WINDOWS.map((w) => (
              <button
                key={w}
                onClick={() => setRollingWindow(w)}
                className={`px-2 py-0.5 text-xs rounded ${
                  rollingWindow === w
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                {w}d
              </button>
            ))}
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {loading ? (
          <div className="animate-pulse space-y-2">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="h-4 bg-muted rounded" />
            ))}
          </div>
        ) : fetchError || !metrics ? (
          <p className="text-sm text-muted-foreground">No data available</p>
        ) : metrics.tradeCount === 0 ? (
          <p className="text-sm text-muted-foreground">No trades in last {rollingWindow} days</p>
        ) : (
          <div className="space-y-2 text-sm">
            <div className="grid grid-cols-2 gap-x-4 gap-y-1">
              <div className="flex justify-between">
                <span className="text-muted-foreground">Trades</span>
                <span className="font-mono">{metrics.tradeCount}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Gross P&amp;L</span>
                <span className={`font-mono ${metrics.grossPnl >= 0 ? "text-green-500" : "text-red-400"}`}>
                  {fmtUsd(metrics.grossPnl)}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Win Rate</span>
                <span className="font-mono">{fmtPct(metrics.winRate)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Avg/Trade</span>
                <span className={`font-mono ${(metrics.avgPnlPerTrade ?? 0) >= 0 ? "text-green-500" : "text-red-400"}`}>
                  {metrics.avgPnlPerTrade !== null ? fmtUsd(metrics.avgPnlPerTrade) : "N/A"}
                </span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-muted-foreground">Prof. Factor</span>
                <div className="flex items-center gap-1">
                  <span className="font-mono">{fmt(metrics.profitFactor)}</span>
                  {metrics.profitFactor !== null && (
                    <Badge variant={pfPass ? "bull" : "bear"} className="text-xs py-0 h-4">
                      {pfPass ? "✓" : "✗"}
                    </Badge>
                  )}
                </div>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-muted-foreground" title="Per-trade Sharpe (mean/stdev of trade P&L, not annualized)">
                  Sharpe*
                </span>
                <div className="flex items-center gap-1">
                  <span className="font-mono">{fmt(metrics.perTradeSharpeVal)}</span>
                  {metrics.perTradeSharpeVal !== null && (
                    <Badge variant={sharpePass ? "bull" : "bear"} className="text-xs py-0 h-4">
                      {sharpePass ? "✓" : "✗"}
                    </Badge>
                  )}
                </div>
              </div>
            </div>
            <div className="pt-1 border-t text-xs text-muted-foreground space-y-0.5">
              {metrics.windowStart && (
                <div>{metrics.windowStart} &rarr; {metrics.windowEnd}</div>
              )}
              <div>
                *Per-trade Sharpe (mean/stdev, not annualized) &middot;{" "}
                {honestSet ? dedupCaveat(honestSet) : ""}
              </div>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
