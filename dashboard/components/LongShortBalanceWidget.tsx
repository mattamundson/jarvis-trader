"use client";

import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  dedupCaveat,
  type HonestTrade,
} from "@/lib/honestTrades";
import { useHonestTrades } from "@/lib/useHonestTrades";

const BENCHMARK_LONG_PCT = 58;
const BENCHMARK_SHORT_PCT = 42;

interface GroupStats {
  count: number;
  win_rate: number;
  avg_pnl: number;
  total_pnl: number;
}

function calcGroupStats(trades: HonestTrade[]): GroupStats {
  const count = trades.length;
  if (count === 0) {
    return { count: 0, win_rate: 0, avg_pnl: 0, total_pnl: 0 };
  }
  const wins = trades.filter((t) => t.pnl > 0).length;
  const win_rate = (wins / count) * 100;
  const total_pnl = trades.reduce((sum, t) => sum + t.pnl, 0);
  const avg_pnl = total_pnl / count;
  return { count, win_rate, avg_pnl, total_pnl };
}

function fmtPnl(val: number): string {
  const sign = val >= 0 ? "+" : "-";
  return `${sign}$${Math.abs(val).toFixed(2)}`;
}

function pnlClass(val: number): string {
  return val >= 0 ? "text-green-400" : "text-red-400";
}

export function LongShortBalanceWidget() {
  const { honest: set, isLoading: loading, error: loadError } = useHonestTrades(300_000);
  const error = !!loadError;

  // HonestTrade.direction is "LONG" | "SHORT"
  const longTrades = set ? set.trades.filter((t) => t.direction === "LONG") : [];
  const shortTrades = set ? set.trades.filter((t) => t.direction === "SHORT") : [];

  const total = longTrades.length + shortTrades.length;
  const longPct = total > 0 ? (longTrades.length / total) * 100 : 0;
  const shortPct = total > 0 ? (shortTrades.length / total) * 100 : 0;

  const longStats = calcGroupStats(longTrades);
  const shortStats = calcGroupStats(shortTrades);

  // Badge logic: within 10% of benchmark (48–68%) → "bull", heavily skewed >80% → "warn", else → "neutral"
  const badgeVariant: "bull" | "warn" | "neutral" =
    total === 0
      ? "neutral"
      : longPct >= 48 && longPct <= 68
      ? "bull"
      : longPct > 80 || shortPct > 80
      ? "warn"
      : "neutral";

  const badgeLabel =
    badgeVariant === "bull"
      ? "Balanced"
      : badgeVariant === "warn"
      ? "Skewed"
      : "Neutral";

  const tableRows: { label: string; longVal: string; shortVal: string; longClass?: string; shortClass?: string }[] = [
    {
      label: "Count",
      longVal: String(longStats.count),
      shortVal: String(shortStats.count),
    },
    {
      label: "Win Rate",
      longVal: longStats.count > 0 ? `${longStats.win_rate.toFixed(1)}%` : "—",
      shortVal: shortStats.count > 0 ? `${shortStats.win_rate.toFixed(1)}%` : "—",
      longClass:
        longStats.count > 0
          ? longStats.win_rate >= 55
            ? "text-green-400"
            : longStats.win_rate < 45
            ? "text-red-400"
            : ""
          : "",
      shortClass:
        shortStats.count > 0
          ? shortStats.win_rate >= 55
            ? "text-green-400"
            : shortStats.win_rate < 45
            ? "text-red-400"
            : ""
          : "",
    },
    {
      label: "Avg P&L",
      longVal: longStats.count > 0 ? fmtPnl(longStats.avg_pnl) : "—",
      shortVal: shortStats.count > 0 ? fmtPnl(shortStats.avg_pnl) : "—",
      longClass: longStats.count > 0 ? pnlClass(longStats.avg_pnl) : "",
      shortClass: shortStats.count > 0 ? pnlClass(shortStats.avg_pnl) : "",
    },
    {
      label: "Total P&L",
      longVal: longStats.count > 0 ? fmtPnl(longStats.total_pnl) : "—",
      shortVal: shortStats.count > 0 ? fmtPnl(shortStats.total_pnl) : "—",
      longClass: longStats.count > 0 ? pnlClass(longStats.total_pnl) : "",
      shortClass: shortStats.count > 0 ? pnlClass(shortStats.total_pnl) : "",
    },
  ];

  return (
    <Card>
      <CardHeader className="flex flex-row justify-between items-center">
        <div>
          <CardTitle>Long vs Short Balance</CardTitle>
          <p className="text-xs text-muted-foreground mt-0.5">
            Paper vs Backtest Benchmark
          </p>
        </div>
        <Badge variant={badgeVariant}>{badgeLabel}</Badge>
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
        ) : total === 0 ? (
          <p className="text-sm text-muted-foreground text-center py-6">
            No closed trades found yet.
          </p>
        ) : (
          <>
            {/* Visual balance bar */}
            <div className="mb-4">
              <div className="flex rounded-full overflow-hidden h-6 w-full">
                <div
                  className="flex items-center justify-center bg-green-500/80 text-xs font-bold text-white transition-all duration-500"
                  style={{ width: `${longPct}%` }}
                >
                  {longPct >= 12 && `${longPct.toFixed(1)}%`}
                </div>
                <div
                  className="flex items-center justify-center bg-red-500/80 text-xs font-bold text-white transition-all duration-500"
                  style={{ width: `${shortPct}%` }}
                >
                  {shortPct >= 12 && `${shortPct.toFixed(1)}%`}
                </div>
              </div>
              <div className="flex justify-between mt-1 text-xs text-muted-foreground">
                <span className="text-green-400 font-medium">
                  LONG {longPct.toFixed(1)}%
                </span>
                <span className="text-red-400 font-medium">
                  SHORT {shortPct.toFixed(1)}%
                </span>
              </div>
            </div>

            {/* Stats table */}
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-border">
                    <th className="py-1.5 text-left font-medium text-muted-foreground w-1/3" />
                    <th className="py-1.5 text-center font-semibold text-green-400">
                      LONG
                    </th>
                    <th className="py-1.5 text-center font-semibold text-red-400">
                      SHORT
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {tableRows.map((row) => (
                    <tr
                      key={row.label}
                      className="border-b border-border/40 last:border-0"
                    >
                      <td className="py-1.5 text-muted-foreground">
                        {row.label}
                      </td>
                      <td
                        className={`py-1.5 text-center font-mono tabular-nums ${
                          row.longClass ?? ""
                        }`}
                      >
                        {row.longVal}
                      </td>
                      <td
                        className={`py-1.5 text-center font-mono tabular-nums ${
                          row.shortClass ?? ""
                        }`}
                      >
                        {row.shortVal}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Benchmark row */}
            <div className="mt-3 pt-3 border-t border-border/50 flex items-center justify-between text-xs">
              <span className="text-muted-foreground">Backtest Benchmark</span>
              <span className="font-mono text-muted-foreground">
                <span className="text-green-400/80">{BENCHMARK_LONG_PCT}% Long</span>
                {" / "}
                <span className="text-red-400/80">{BENCHMARK_SHORT_PCT}% Short</span>
              </span>
            </div>

            {/* Dedup caveat */}
            <p className="text-[10px] text-muted-foreground mt-2">
              {set ? dedupCaveat(set) : ""} · Refreshes every 5m
            </p>
          </>
        )}
      </CardContent>
    </Card>
  );
}
