"use client";

import { CalendarDays } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  exitDate,
  dedupCaveat,
  type HonestTrade,
  type HonestTradeSet,
} from "@/lib/honestTrades";
import { useHonestTrades } from "@/lib/useHonestTrades";

// ── Types ─────────────────────────────────────────────────────────────────────

interface MonthBucket {
  key: string; // "YYYY-MM"
  label: string; // "Mar 2026"
  total_pnl: number;
  /** distinct close-date count within the month */
  trading_days: number;
  total_trades: number;
  win_days: number;
  loss_days: number;
  /** best single-trade P&L in the month */
  best_day: number;
  /** worst single-trade P&L in the month */
  worst_day: number;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatMonthLabel(key: string): string {
  // key = "YYYY-MM"
  const [year, month] = key.split("-");
  const date = new Date(Number(year), Number(month) - 1, 1);
  return date.toLocaleDateString("en-US", { month: "short", year: "numeric" });
}

function formatPnl(value: number): string {
  const sign = value >= 0 ? "+" : "";
  return `${sign}$${Math.abs(value).toFixed(2)}`;
}

function pnlVariant(value: number): "bull" | "bear" | "neutral" {
  if (value > 0) return "bull";
  if (value < 0) return "bear";
  return "neutral";
}

function winDaysColorClass(winDays: number, lossDays: number): string {
  if (winDays > lossDays) return "text-bull";
  if (lossDays > winDays) return "text-bear";
  return "text-muted-foreground";
}

/**
 * Group honest trades by YYYY-MM of their exit date.
 * "win_days"/"loss_days" are counted at the day level (by close date),
 * not the trade level — preserving the original widget's meaning of
 * "how many calendar days was this month green/red."
 */
function groupByMonth(trades: HonestTrade[]): MonthBucket[] {
  const map = new Map<string, MonthBucket>();

  // First pass: aggregate per trade
  const dayPnl = new Map<string, number>(); // "YYYY-MM-DD" -> daily pnl

  for (const t of trades) {
    const d = exitDate(t);
    if (!d) continue;
    const key = d.slice(0, 7); // "YYYY-MM"

    if (!map.has(key)) {
      map.set(key, {
        key,
        label: formatMonthLabel(key),
        total_pnl: 0,
        trading_days: 0,
        total_trades: 0,
        win_days: 0,
        loss_days: 0,
        best_day: -Infinity,
        worst_day: Infinity,
      });
    }

    const bucket = map.get(key)!;
    bucket.total_pnl += t.pnl;
    bucket.total_trades += 1;

    // Track per-trade extremes for best/worst columns
    if (t.pnl > bucket.best_day) bucket.best_day = t.pnl;
    if (t.pnl < bucket.worst_day) bucket.worst_day = t.pnl;

    // Accumulate day P&L for win_days / loss_days
    dayPnl.set(d, (dayPnl.get(d) ?? 0) + t.pnl);
  }

  // Second pass: compute day-level win/loss counts and trading_days per month
  for (const [date, pnl] of dayPnl) {
    const key = date.slice(0, 7);
    const bucket = map.get(key);
    if (!bucket) continue;
    bucket.trading_days += 1;
    if (pnl > 0) bucket.win_days += 1;
    else if (pnl < 0) bucket.loss_days += 1;
  }

  // Fix sentinels for months with no trades (shouldn't happen, but guard)
  for (const bucket of map.values()) {
    if (bucket.best_day === -Infinity) bucket.best_day = 0;
    if (bucket.worst_day === Infinity) bucket.worst_day = 0;
  }

  // Sort descending by key (most recent first), cap at 12
  return [...map.values()]
    .sort((a, b) => b.key.localeCompare(a.key))
    .slice(0, 12);
}

// ── Skeleton ──────────────────────────────────────────────────────────────────

function Skeleton() {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm flex items-center gap-2">
          <CalendarDays className="h-4 w-4" />
          Monthly Breakdown
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-2">
          {[1, 2, 3].map((i) => (
            <div key={i} className="animate-pulse h-8 bg-muted rounded" />
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

// ── Widget ────────────────────────────────────────────────────────────────────

export function MonthlyBreakdownWidget() {
  const { honest: tradeSet, isLoading: loading, error: loadError } = useHonestTrades(5 * 60 * 1000);
  const error = !!loadError;
  const months = tradeSet ? groupByMonth(tradeSet.trades) : [];

  if (loading) return <Skeleton />;

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm flex items-center gap-2">
          <CalendarDays className="h-4 w-4" />
          Monthly Breakdown
        </CardTitle>
      </CardHeader>
      <CardContent>
        {error && (
          <p className="text-sm text-muted-foreground">
            Unable to load monthly data
          </p>
        )}

        {!error && months.length === 0 && (
          <p className="text-sm text-muted-foreground">No monthly data yet</p>
        )}

        {!error && months.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full font-mono text-xs">
              <thead>
                <tr className="border-b border-border">
                  {[
                    { label: "Month", align: "text-left" },
                    { label: "Trading Days", align: "text-right" },
                    { label: "Total P&L", align: "text-right" },
                    { label: "Best Trade", align: "text-right" },
                    { label: "Worst Trade", align: "text-right" },
                    { label: "Win Days", align: "text-right" },
                  ].map(({ label, align }) => (
                    <th
                      key={label}
                      className={`pb-2 px-2 font-semibold uppercase tracking-wider text-muted-foreground text-[10px] ${align}`}
                    >
                      {label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {months.map((m) => (
                  <tr
                    key={m.key}
                    className="hover:bg-muted/20 transition-colors border-b border-border/50"
                  >
                    {/* Month */}
                    <td className="py-2 px-2 font-semibold tabular-nums">
                      {m.label}
                    </td>

                    {/* Trading Days */}
                    <td className="py-2 px-2 text-right tabular-nums text-muted-foreground">
                      {m.trading_days}
                    </td>

                    {/* Total P&L */}
                    <td className="py-2 px-2 text-right">
                      <Badge variant={pnlVariant(m.total_pnl)}>
                        {formatPnl(m.total_pnl)}
                      </Badge>
                    </td>

                    {/* Best Trade */}
                    <td className="py-2 px-2 text-right">
                      <Badge variant={pnlVariant(m.best_day)}>
                        {formatPnl(m.best_day)}
                      </Badge>
                    </td>

                    {/* Worst Trade */}
                    <td className="py-2 px-2 text-right">
                      <Badge variant={pnlVariant(m.worst_day)}>
                        {formatPnl(m.worst_day)}
                      </Badge>
                    </td>

                    {/* Win Days */}
                    <td className="py-2 px-2 text-right tabular-nums">
                      <span className={winDaysColorClass(m.win_days, m.loss_days)}>
                        {m.win_days}
                        <span className="text-muted-foreground text-[9px]">
                          /{m.trading_days}
                        </span>
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {/* Dedup caveat footer */}
            {tradeSet && (
              <p className="px-2 pt-2 text-[10px] text-muted-foreground">
                {dedupCaveat(tradeSet)}
              </p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
