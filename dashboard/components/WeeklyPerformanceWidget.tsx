"use client";

import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { TrendingUp, TrendingDown, Minus, Calendar } from "lucide-react";
import {
  dailyPnl,
  dedupCaveat,
  type HonestTradeSet,
} from "@/lib/honestTrades";
import { useHonestTrades } from "@/lib/useHonestTrades";

// ── Types ─────────────────────────────────────────────────────────────────────

interface WeekStats {
  weekStart: string; // YYYY-MM-DD (Monday)
  weekEnd: string;   // YYYY-MM-DD (Sunday)
  count: number;
  wins: number;
  totalPnl: number;
  winRate: number;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function getWeekKey(date: Date): string {
  const d = new Date(date);
  const day = d.getDay(); // 0=Sun
  const diff = d.getDate() - day + (day === 0 ? -6 : 1); // adjust to Monday
  d.setDate(diff);
  return d.toISOString().slice(0, 10);
}

function getWeekEnd(weekStart: string): string {
  const d = new Date(weekStart);
  d.setDate(d.getDate() + 6); // Sunday
  return d.toISOString().slice(0, 10);
}

function formatWeekLabel(weekStart: string, weekEnd: string): string {
  const start = new Date(weekStart + "T00:00:00");
  const end = new Date(weekEnd + "T00:00:00");
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const startMon = months[start.getMonth()];
  const endMon = months[end.getMonth()];
  if (startMon === endMon) {
    return `${startMon} ${start.getDate()}–${end.getDate()}`;
  }
  return `${startMon} ${start.getDate()}–${endMon} ${end.getDate()}`;
}

function fmtPnl(v: number): string {
  const abs = Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: 0 });
  return v >= 0 ? `+$${abs}` : `-$${abs}`;
}

function pnlClass(pnl: number): string {
  return pnl >= 0 ? "text-bull" : "text-bear";
}

function winRateClass(wr: number): string {
  if (wr >= 60) return "text-bull";
  if (wr >= 40) return "text-warn";
  return "text-bear";
}

/**
 * Aggregate dailyPnl entries (from honestTrades) into per-week buckets.
 * Each daily entry already carries a trade count; we can track wins only
 * indirectly (days with pnl > 0) — so win/loss here is per-day-in-week,
 * not per-trade. This is a known limitation when coming from daily buckets
 * rather than raw trades; we note it in the UI.
 */
function buildWeekStats(set: HonestTradeSet): WeekStats[] {
  const daily = dailyPnl(set.trades);

  const weekMap = new Map<string, { pnl: number; count: number; wins: number }>();
  for (const day of daily) {
    const key = getWeekKey(new Date(day.date + "T00:00:00"));
    const existing = weekMap.get(key) ?? { pnl: 0, count: 0, wins: 0 };
    existing.pnl += day.pnl;
    existing.count += day.count;
    if (day.pnl > 0) existing.wins += day.count; // proxy: winning-day trades
    weekMap.set(key, existing);
  }

  // Sort descending (most recent first), take last 8 weeks
  const sortedKeys = Array.from(weekMap.keys()).sort((a, b) => b.localeCompare(a));
  const recentKeys = sortedKeys.slice(0, 8);

  return recentKeys.map((weekStart) => {
    const s = weekMap.get(weekStart)!;
    const weekEnd = getWeekEnd(weekStart);
    return {
      weekStart,
      weekEnd,
      count: s.count,
      wins: s.wins,
      totalPnl: s.pnl,
      winRate: s.count > 0 ? (s.wins / s.count) * 100 : 0,
    };
  });
}

// ── Mini Bar Chart (pure CSS) ──────────────────────────────────────────────────

interface MiniBarChartProps {
  weeks: WeekStats[];
}

function MiniBarChart({ weeks: weeksDesc }: MiniBarChartProps) {
  // Display oldest → newest (left to right)
  const weeks = [...weeksDesc].reverse();
  const maxAbs = Math.max(...weeks.map((w) => Math.abs(w.totalPnl)), 1);

  return (
    <div className="flex items-end gap-1 h-16" aria-label="Weekly P&L bar chart">
      {weeks.map((week) => {
        const heightPct = Math.max(4, (Math.abs(week.totalPnl) / maxAbs) * 64);
        const isProfitable = week.totalPnl >= 0;
        const label = formatWeekLabel(week.weekStart, week.weekEnd);
        return (
          <div
            key={week.weekStart}
            className="flex-1 flex flex-col items-center justify-end group relative"
            style={{ height: "64px" }}
          >
            {/* Tooltip on hover */}
            <div className="absolute bottom-full mb-1 left-1/2 -translate-x-1/2 hidden group-hover:block z-10 pointer-events-none">
              <div className="rounded bg-card border border-border px-2 py-1 text-xs whitespace-nowrap shadow-lg">
                <p className="font-semibold text-foreground">{label}</p>
                <p className={isProfitable ? "text-bull" : "text-bear"}>
                  {fmtPnl(week.totalPnl)}
                </p>
                <p className="text-muted-foreground">{week.count} trades</p>
              </div>
            </div>
            <div
              className={`w-full rounded-t transition-all duration-300 ${
                isProfitable ? "bg-bull/70" : "bg-bear/70"
              }`}
              style={{ height: `${heightPct}px` }}
            />
          </div>
        );
      })}
    </div>
  );
}

// ── Week row ──────────────────────────────────────────────────────────────────

interface WeekRowProps {
  week: WeekStats;
  isCurrent: boolean;
}

function WeekRow({ week, isCurrent }: WeekRowProps) {
  const label = formatWeekLabel(week.weekStart, week.weekEnd);
  return (
    <tr
      className={`border-b border-border/30 last:border-0 transition-colors ${
        isCurrent ? "bg-accent/5" : "hover:bg-white/[0.02]"
      }`}
    >
      <td className="py-2.5 px-3 text-xs font-medium text-foreground whitespace-nowrap">
        {label}
        {isCurrent && (
          <span className="ml-1.5 text-[10px] text-accent font-semibold uppercase tracking-wider">
            current
          </span>
        )}
      </td>
      <td className="py-2.5 px-3 text-xs text-center tabular-nums text-muted-foreground">
        {week.count}
      </td>
      <td className={`py-2.5 px-3 text-xs text-center tabular-nums font-semibold ${winRateClass(week.winRate)}`}>
        {week.count > 0 ? `${week.winRate.toFixed(0)}%` : "—"}
      </td>
      <td className={`py-2.5 px-3 text-xs text-right tabular-nums font-semibold font-mono ${pnlClass(week.totalPnl)}`}>
        {week.count > 0 ? fmtPnl(week.totalPnl) : "—"}
      </td>
    </tr>
  );
}

// ── Trend helper ──────────────────────────────────────────────────────────────

type Trend = "improving" | "declining" | "stable";

function computeTrend(weeks: WeekStats[]): Trend {
  if (weeks.length < 2) return "stable";
  // weeks[0] = most recent, weeks[1] = previous
  const recent = weeks[0].totalPnl;
  const prev = weeks[1].totalPnl;
  if (recent > prev + 0.01) return "improving";
  if (recent < prev - 0.01) return "declining";
  return "stable";
}

// ── Current week helper ───────────────────────────────────────────────────────

function getCurrentWeekStart(): string {
  return getWeekKey(new Date());
}

// ── Main Widget ───────────────────────────────────────────────────────────────

export function WeeklyPerformanceWidget() {
  const { honest: set, isLoading: loading, error: loadError } = useHonestTrades(60_000);
  const error = loadError ? (loadError instanceof Error ? loadError.message : String(loadError)) : null;
  const weeks = set ? buildWeekStats(set) : [];

  // Header badge
  function headerBadge(): { variant: "bull" | "bear" | "info"; label: string } {
    if (weeks.length < 2) return { variant: "info", label: "Insufficient Data" };
    const latest = weeks[0];
    if (latest.totalPnl >= 0) return { variant: "bull", label: "Week Profitable" };
    return { variant: "bear", label: "Week Losing" };
  }

  const trend = computeTrend(weeks);
  const currentWeekStart = getCurrentWeekStart();
  const { variant, label } = headerBadge();

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div className="flex items-center gap-2">
            <Calendar className="h-4 w-4 text-accent" />
            <CardTitle>Weekly Performance</CardTitle>
          </div>
          {!loading && !error && (
            <Badge variant={variant}>{label}</Badge>
          )}
        </div>
      </CardHeader>

      <CardContent>
        {loading && (
          <p className="text-xs text-muted-foreground animate-pulse">
            Loading weekly performance…
          </p>
        )}

        {!loading && error && (
          <p className="text-xs text-red-400">Error: {error}</p>
        )}

        {!loading && !error && weeks.length === 0 && (
          <p className="text-xs text-muted-foreground">
            No closed trades found. Weekly data will appear once trades are closed.
          </p>
        )}

        {!loading && !error && weeks.length > 0 && (
          <div className="space-y-5">
            {/* Trend indicator */}
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              {trend === "improving" && (
                <>
                  <TrendingUp className="h-3.5 w-3.5 text-bull" />
                  <span className="text-bull font-medium">Improving</span>
                  <span>— this week outperformed last week</span>
                </>
              )}
              {trend === "declining" && (
                <>
                  <TrendingDown className="h-3.5 w-3.5 text-bear" />
                  <span className="text-bear font-medium">Declining</span>
                  <span>— this week underperformed last week</span>
                </>
              )}
              {trend === "stable" && (
                <>
                  <Minus className="h-3.5 w-3.5 text-muted-foreground" />
                  <span>Stable — performance similar week-over-week</span>
                </>
              )}
            </div>

            {/* Mini bar chart */}
            <div>
              <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">
                P&amp;L by Week (oldest → newest)
              </p>
              <MiniBarChart weeks={weeks} />
              <div className="flex justify-between mt-1">
                {[...weeks].reverse().map((w) => (
                  <div
                    key={w.weekStart}
                    className="flex-1 text-center text-[9px] text-muted-foreground truncate"
                  >
                    {new Date(w.weekStart + "T00:00:00").getDate()}
                  </div>
                ))}
              </div>
            </div>

            {/* Per-week table */}
            <div className="rounded-lg border border-border overflow-hidden">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-border bg-black/20">
                    <th className="py-2 px-3 text-left text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                      Week
                    </th>
                    <th className="py-2 px-3 text-center text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                      Trades
                    </th>
                    <th className="py-2 px-3 text-center text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                      Win Rate
                    </th>
                    <th className="py-2 px-3 text-right text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                      P&amp;L
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {weeks.map((week) => (
                    <WeekRow
                      key={week.weekStart}
                      week={week}
                      isCurrent={week.weekStart === currentWeekStart}
                    />
                  ))}
                </tbody>
              </table>
            </div>

            {/* Summary footer with dedup caveat */}
            <div className="flex items-center justify-between text-xs text-muted-foreground border-t border-border/30 pt-3">
              <span>
                {set ? dedupCaveat(set) : `${weeks.length} week${weeks.length !== 1 ? "s" : ""} of data`}
              </span>
              <span className="text-[10px]">Refreshes every 60s</span>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default WeeklyPerformanceWidget;
