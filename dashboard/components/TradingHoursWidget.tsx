"use client";

import { useEffect, useState } from "react";
import { Clock, TrendingUp, TrendingDown, Activity, Info } from "lucide-react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  dedupCaveat,
  type HonestTrade,
  type HonestTradeSet,
} from "@/lib/honestTrades";
import { useHonestTrades } from "@/lib/useHonestTrades";


// ── Types ─────────────────────────────────────────────────────────────────────

interface HourStats {
  hour: number;
  count: number;
  wins: number;
  totalPnl: number;
  avgPnl: number;
  winRate: number;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatHour(hour: number): string {
  if (hour === 0) return "12am";
  if (hour < 12) return `${hour}am`;
  if (hour === 12) return "12pm";
  return `${hour - 12}pm`;
}

function formatPnl(pnl: number): string {
  const abs = Math.abs(pnl);
  const formatted =
    abs >= 1000
      ? `$${(abs / 1000).toFixed(1)}k`
      : `$${abs.toFixed(0)}`;
  return pnl >= 0 ? `+${formatted}` : `-${formatted}`;
}

function buildHourStats(trades: HonestTrade[]): HourStats[] {
  const map = new Map<number, { count: number; wins: number; totalPnl: number }>();

  for (const trade of trades) {
    // guard null entry_time
    if (!trade.entry_time) continue;
    const parsedMs = Date.parse(trade.entry_time);
    if (Number.isNaN(parsedMs)) continue;

    const hour = new Date(parsedMs).getHours();
    const existing = map.get(hour) ?? { count: 0, wins: 0, totalPnl: 0 };
    existing.count++;
    if (trade.pnl > 0) existing.wins++;
    existing.totalPnl += trade.pnl;
    map.set(hour, existing);
  }

  return Array.from(map.entries())
    .map(([hour, data]) => ({
      hour,
      count: data.count,
      wins: data.wins,
      totalPnl: data.totalPnl,
      avgPnl: data.count > 0 ? data.totalPnl / data.count : 0,
      winRate: data.count > 0 ? data.wins / data.count : 0,
    }))
    .sort((a, b) => a.hour - b.hour);
}

// ── CSS Bar Chart ─────────────────────────────────────────────────────────────

interface HourBarProps {
  stat: HourStats;
  maxAbsPnl: number;
  isBest: boolean;
  isWorst: boolean;
}

function HourBar({ stat, maxAbsPnl, isBest, isWorst }: HourBarProps) {
  const [hovered, setHovered] = useState(false);
  const heightPct = maxAbsPnl > 0 ? Math.abs(stat.totalPnl) / maxAbsPnl : 0;
  const barHeightPx = Math.max(4, Math.round(heightPct * 72)); // max 72px (h-18 = 4.5rem)
  const isPositive = stat.totalPnl >= 0;
  const barColorClass = isPositive ? "bg-bull" : "bg-bear";

  return (
    <div
      className="relative flex flex-col items-center gap-0.5 group"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      {/* Hover tooltip */}
      {hovered && (
        <div className="absolute bottom-full mb-2 z-20 w-40 rounded-lg border border-border bg-card shadow-lg p-2.5 text-xs pointer-events-none">
          <p className="font-semibold text-foreground mb-1">{formatHour(stat.hour)}</p>
          <p className="text-muted-foreground">{stat.count} trade{stat.count !== 1 ? "s" : ""}</p>
          <p className={isPositive ? "text-bull" : "text-bear"}>
            Total P&L: {formatPnl(stat.totalPnl)}
          </p>
          <p className="text-muted-foreground">
            Avg P&L: {formatPnl(stat.avgPnl)}
          </p>
          <p className="text-muted-foreground">
            WR: {(stat.winRate * 100).toFixed(0)}%
          </p>
          {isBest && <p className="text-bull font-medium mt-0.5">Best hour</p>}
          {isWorst && <p className="text-bear font-medium mt-0.5">Worst hour</p>}
        </div>
      )}

      {/* Bar */}
      <div className="flex items-end h-[80px]">
        <div
          className={`w-6 rounded-t-sm transition-opacity ${barColorClass} ${
            isBest || isWorst ? "ring-1 ring-offset-1 ring-offset-card" : ""
          } ${isBest ? "ring-bull" : isWorst ? "ring-bear" : ""}`}
          style={{ height: `${barHeightPx}px` }}
        />
      </div>

      {/* Hour label */}
      <p className="text-[10px] text-muted-foreground whitespace-nowrap">
        {formatHour(stat.hour)}
      </p>
    </div>
  );
}

// ── Main Widget ───────────────────────────────────────────────────────────────

export function TradingHoursWidget() {
  const { honest, isLoading: loading, error: loadError } = useHonestTrades(60_000);
  const error = loadError ? (loadError instanceof Error ? loadError.message : String(loadError)) : null;
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  useEffect(() => {
    if (honest) setLastUpdated(new Date());
  }, [honest]);

  // Derive stats at render time
  const hourStats: HourStats[] = honest ? buildHourStats(honest.trades) : [];
  const totalTrades = honest ? honest.trades.length : 0;
  const caveat = honest ? dedupCaveat(honest) : "";

  // Derived stats
  const insufficient = totalTrades < 5;

  const bestHour =
    hourStats.length > 0
      ? hourStats.reduce((best, cur) => (cur.totalPnl > best.totalPnl ? cur : best), hourStats[0])
      : null;

  const worstHour =
    hourStats.length > 0
      ? hourStats.reduce((worst, cur) => (cur.totalPnl < worst.totalPnl ? cur : worst), hourStats[0])
      : null;

  const mostActiveHour =
    hourStats.length > 0
      ? hourStats.reduce((active, cur) => (cur.count > active.count ? cur : active), hourStats[0])
      : null;

  const maxAbsPnl =
    hourStats.length > 0
      ? Math.max(...hourStats.map((s) => Math.abs(s.totalPnl)), 1)
      : 1;

  // Header badge
  const headerBadge = (): "bull" | "info" | "neutral" => {
    if (insufficient) return "info";
    if (bestHour && bestHour.totalPnl > 0) return "bull";
    return "neutral";
  };

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div className="flex items-center gap-2">
            <Clock className="h-4 w-4 text-muted-foreground" />
            <CardTitle>Trading Hours Performance</CardTitle>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant={headerBadge()}>
              {insufficient
                ? "Insufficient Data"
                : bestHour && bestHour.totalPnl > 0
                ? `Best: ${formatHour(bestHour.hour)}`
                : "No Best Hour"}
            </Badge>
            {lastUpdated && (
              <span className="text-[10px] text-muted-foreground">
                Updated {lastUpdated.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
              </span>
            )}
          </div>
        </div>
      </CardHeader>

      <CardContent>
        {loading && (
          <p className="text-xs text-muted-foreground animate-pulse py-4">
            Loading trade history…
          </p>
        )}

        {!loading && error && (
          <p className="text-xs text-red-400 py-2">Error: {error}</p>
        )}

        {!loading && !error && insufficient && (
          <div className="flex items-start gap-2 py-3 text-xs text-muted-foreground">
            <Info className="h-3.5 w-3.5 mt-0.5 shrink-0" />
            <p>
              Not enough data yet — need at least 5 closed trades to show hourly
              performance breakdown.
            </p>
          </div>
        )}

        {!loading && !error && !insufficient && hourStats.length > 0 && (
          <div className="space-y-5">
            {/* Bar chart */}
            <div>
              <div className="flex items-end gap-1 h-[104px] overflow-x-auto pb-1">
                {hourStats.map((stat) => (
                  <HourBar
                    key={stat.hour}
                    stat={stat}
                    maxAbsPnl={maxAbsPnl}
                    isBest={bestHour?.hour === stat.hour}
                    isWorst={worstHour?.hour === stat.hour}
                  />
                ))}
              </div>
              <div className="flex items-center gap-4 mt-2 text-[10px] text-muted-foreground">
                <span className="flex items-center gap-1">
                  <span className="inline-block w-2.5 h-2.5 rounded-sm bg-bull" />
                  Positive P&L
                </span>
                <span className="flex items-center gap-1">
                  <span className="inline-block w-2.5 h-2.5 rounded-sm bg-bear" />
                  Negative P&L
                </span>
                <span className="flex items-center gap-1 ml-auto">
                  <Info className="h-3 w-3" />
                  CTX futures: peak activity 8am–3pm CT
                </span>
              </div>
            </div>

            {/* Summary stats */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              {/* Best hour */}
              <div className="rounded-lg border border-border/50 bg-background/20 px-3 py-2.5 space-y-1">
                <div className="flex items-center gap-1 text-[10px] text-muted-foreground uppercase tracking-wider">
                  <TrendingUp className="h-3 w-3 text-bull" />
                  Best Hour
                </div>
                {bestHour ? (
                  <>
                    <p className="text-sm font-semibold font-mono text-bull">
                      {formatHour(bestHour.hour)}
                    </p>
                    <p className="text-[10px] text-muted-foreground">
                      {formatPnl(bestHour.totalPnl)} &middot;{" "}
                      {(bestHour.winRate * 100).toFixed(0)}% WR
                    </p>
                  </>
                ) : (
                  <p className="text-sm text-muted-foreground">—</p>
                )}
              </div>

              {/* Worst hour */}
              <div className="rounded-lg border border-border/50 bg-background/20 px-3 py-2.5 space-y-1">
                <div className="flex items-center gap-1 text-[10px] text-muted-foreground uppercase tracking-wider">
                  <TrendingDown className="h-3 w-3 text-bear" />
                  Worst Hour
                </div>
                {worstHour ? (
                  <>
                    <p className="text-sm font-semibold font-mono text-bear">
                      {formatHour(worstHour.hour)}
                    </p>
                    <p className="text-[10px] text-muted-foreground">
                      {formatPnl(worstHour.totalPnl)} &middot;{" "}
                      {(worstHour.winRate * 100).toFixed(0)}% WR
                    </p>
                  </>
                ) : (
                  <p className="text-sm text-muted-foreground">—</p>
                )}
              </div>

              {/* Most active */}
              <div className="rounded-lg border border-border/50 bg-background/20 px-3 py-2.5 space-y-1">
                <div className="flex items-center gap-1 text-[10px] text-muted-foreground uppercase tracking-wider">
                  <Activity className="h-3 w-3 text-info" />
                  Most Active
                </div>
                {mostActiveHour ? (
                  <>
                    <p className="text-sm font-semibold font-mono text-foreground">
                      {formatHour(mostActiveHour.hour)}
                    </p>
                    <p className="text-[10px] text-muted-foreground">
                      {mostActiveHour.count} trade{mostActiveHour.count !== 1 ? "s" : ""}
                    </p>
                  </>
                ) : (
                  <p className="text-sm text-muted-foreground">—</p>
                )}
              </div>

              {/* Total analyzed */}
              <div className="rounded-lg border border-border/50 bg-background/20 px-3 py-2.5 space-y-1">
                <div className="flex items-center gap-1 text-[10px] text-muted-foreground uppercase tracking-wider">
                  <Clock className="h-3 w-3" />
                  Analyzed
                </div>
                <p className="text-sm font-semibold font-mono text-foreground">
                  {totalTrades}
                </p>
                <p className="text-[10px] text-muted-foreground">
                  across {hourStats.length} active hour{hourStats.length !== 1 ? "s" : ""}
                </p>
              </div>
            </div>

            {/* Per-hour detail table */}
            <div className="overflow-x-auto rounded-lg border border-border/50">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-border bg-black/20">
                    <th className="px-3 py-2 text-muted-foreground font-medium uppercase tracking-wider">
                      Hour
                    </th>
                    <th className="px-3 py-2 text-muted-foreground font-medium uppercase tracking-wider text-center">
                      Trades
                    </th>
                    <th className="px-3 py-2 text-muted-foreground font-medium uppercase tracking-wider text-center">
                      Win Rate
                    </th>
                    <th className="px-3 py-2 text-muted-foreground font-medium uppercase tracking-wider text-right">
                      Avg P&L
                    </th>
                    <th className="px-3 py-2 text-muted-foreground font-medium uppercase tracking-wider text-right">
                      Total P&L
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {hourStats.map((stat) => {
                    const isBest = bestHour?.hour === stat.hour;
                    const isWorst = worstHour?.hour === stat.hour;
                    return (
                      <tr
                        key={stat.hour}
                        className={`border-b border-border/30 transition-colors ${
                          isBest
                            ? "bg-bull/5"
                            : isWorst
                            ? "bg-bear/5"
                            : "hover:bg-white/[0.02]"
                        }`}
                      >
                        <td className="px-3 py-2 font-mono font-medium text-foreground">
                          {formatHour(stat.hour)}
                          {isBest && (
                            <Badge variant="bull" className="ml-1.5 text-[9px] py-0">
                              best
                            </Badge>
                          )}
                          {isWorst && (
                            <Badge variant="bear" className="ml-1.5 text-[9px] py-0">
                              worst
                            </Badge>
                          )}
                        </td>
                        <td className="px-3 py-2 text-center tabular-nums text-muted-foreground">
                          {stat.count}
                        </td>
                        <td
                          className={`px-3 py-2 text-center tabular-nums font-medium ${
                            stat.winRate >= 0.6
                              ? "text-bull"
                              : stat.winRate >= 0.4
                              ? "text-warn"
                              : "text-bear"
                          }`}
                        >
                          {(stat.winRate * 100).toFixed(0)}%
                        </td>
                        <td
                          className={`px-3 py-2 text-right tabular-nums font-mono ${
                            stat.avgPnl >= 0 ? "text-bull" : "text-bear"
                          }`}
                        >
                          {formatPnl(stat.avgPnl)}
                        </td>
                        <td
                          className={`px-3 py-2 text-right tabular-nums font-mono font-semibold ${
                            stat.totalPnl >= 0 ? "text-bull" : "text-bear"
                          }`}
                        >
                          {formatPnl(stat.totalPnl)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {/* Dedup caveat */}
            {caveat && (
              <p className="text-[10px] text-muted-foreground flex items-center gap-1">
                <Info className="h-3 w-3 shrink-0" />
                {caveat}
              </p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default TradingHoursWidget;
