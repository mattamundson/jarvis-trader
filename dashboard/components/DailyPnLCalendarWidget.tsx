"use client";

import React, { useEffect, useState } from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { dailyPnl } from "@/lib/honestTrades";
import { useHonestTrades } from "@/lib/useHonestTrades";
import { dailyPnlCalendarDisplayFor, toYMD } from "@/lib/dailyPnlCalendar";


// ── Types ──────────────────────────────────────────────────────────────────────

interface DailyPnLMap {
  [date: string]: number; // YYYY-MM-DD -> sum of realized_pnl
}

// ── Helpers ────────────────────────────────────────────────────────────────────

function formatPnl(value: number): string {
  const abs = Math.abs(value).toFixed(2);
  return value >= 0 ? `+$${abs}` : `-$${abs}`;
}

function formatDateLabel(d: Date): string {
  return d.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

/**
 * Cell background classes based on P&L magnitude.
 * @param pnl  undefined = no data for that day
 * @param isToday  whether to add ring highlight
 */
function cellClasses(pnl: number | undefined, isToday: boolean): string {
  let bg: string;
  if (pnl === undefined) {
    bg = "bg-muted/30";
  } else if (pnl > 200) {
    bg = "bg-emerald-600";
  } else if (pnl > 100) {
    bg = "bg-emerald-500";
  } else if (pnl > 0) {
    bg = "bg-emerald-400/70";
  } else if (pnl < -200) {
    bg = "bg-red-600";
  } else if (pnl < -100) {
    bg = "bg-red-500";
  } else if (pnl < 0) {
    bg = "bg-red-400/70";
  } else {
    // pnl === 0 with data
    bg = "bg-muted/30";
  }
  const ring = isToday
    ? " ring-2 ring-offset-1 ring-offset-card ring-white/60"
    : "";
  return `${bg}${ring}`;
}

// ── Component ──────────────────────────────────────────────────────────────────

export function DailyPnLCalendarWidget() {
  const { honest: set, isLoading: loading, error: loadError } = useHonestTrades(120_000);
  const error = !!loadError;

  // "today" is intentionally client-only state -- same hydration guard as
  // WeeklyPnLCard (GT-30, PR #503) and the other GT-33 date-guard fixes
  // (CalendarHeatmap, CumulativeTradingDaysWidget, MonthlyTargetCard).
  // Computing `new Date()` directly during render makes SSR output
  // (evaluated at server-render/build time) diverge from the client's first
  // hydration pass (evaluated whenever the browser actually loads the page
  // -- which can be hours/days later for a statically-optimized route)
  // whenever those two clock reads straddle a day/month boundary --
  // producing a React #418 hydration mismatch on the month label, the day
  // grid, and the "is today" cell highlight. Starting at `null` and setting
  // it in a mount-only effect guarantees the server and the first client
  // render agree (both render the existing empty-calendar state), then the
  // real calendar fills in client-side. See lib/dailyPnlCalendar.ts.
  //
  // NOTE: this file is also touched by still-open PR #496 (GT-27) with a
  // non-extracted version of the same guard -- see GT-33's PR description
  // for the reconciliation note.
  const [today, setToday] = useState<Date | null>(null);
  useEffect(() => {
    setToday(new Date());
  }, []);

  // dailyPnl() returns {date, pnl, count}[] grouped by close date
  const dailyPnlMap: DailyPnLMap | null = set
    ? (() => {
        const records = dailyPnl(set.trades);
        const map: DailyPnLMap = {};
        for (const r of records) {
          map[r.date] = (map[r.date] ?? 0) + r.pnl;
        }
        return map;
      })()
    : null;

  // ── Derived values ──────────────────────────────────────────────────────────

  const { calDays, todayStr, monthLabel } = dailyPnlCalendarDisplayFor(today);

  // Compute summary stats from days that have data
  const pnlValues: number[] = [];
  for (const d of calDays) {
    const v = dailyPnlMap?.[toYMD(d)];
    if (v !== undefined) pnlValues.push(v);
  }

  const bestDay = pnlValues.length > 0 ? Math.max(...pnlValues) : null;
  const worstDay = pnlValues.length > 0 ? Math.min(...pnlValues) : null;
  const avgDay =
    pnlValues.length > 0
      ? pnlValues.reduce((a, b) => a + b, 0) / pnlValues.length
      : null;

  // Leading empty cells so first weekday lands in correct Mon–Fri column
  const firstDay = calDays[0];
  // Mon=0 … Fri=4 (JS getDay: Mon=1 … Fri=5)
  const firstDow = firstDay ? firstDay.getDay() - 1 : 0;
  const leadingCount = Math.max(0, firstDow);

  // ── Render ──────────────────────────────────────────────────────────────────

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>Daily P&amp;L Calendar</CardTitle>
          <span className="font-mono text-[10px] text-muted-foreground">
            {monthLabel}
          </span>
        </div>
      </CardHeader>

      <CardContent>
        {/* ── Loading skeleton ── */}
        {loading && (
          <>
            <div className="grid grid-cols-5 gap-1 mb-1">
              {["Mo", "Tu", "We", "Th", "Fr"].map((d) => (
                <div
                  key={d}
                  className="text-center font-mono text-[10px] text-muted-foreground"
                >
                  {d}
                </div>
              ))}
            </div>
            <div className="grid grid-cols-5 gap-1">
              {Array.from({ length: 30 }).map((_, i) => (
                <div
                  key={i}
                  className="h-8 w-full rounded bg-muted/30 animate-pulse"
                />
              ))}
            </div>
          </>
        )}

        {/* ── Error state ── */}
        {!loading && error && (
          <div className="flex items-center justify-center h-32">
            <span className="font-mono text-xs text-muted-foreground">
              Calendar data unavailable
            </span>
          </div>
        )}

        {/* ── Empty state ── */}
        {!loading && !error && dailyPnlMap !== null && calDays.length === 0 && (
          <div className="flex items-center justify-center h-32">
            <span className="font-mono text-xs text-muted-foreground">
              No trade data yet
            </span>
          </div>
        )}

        {/* ── Calendar ── */}
        {!loading && !error && dailyPnlMap !== null && calDays.length > 0 && (
          <>
            {/* Day-of-week header */}
            <div className="grid grid-cols-5 gap-1 mb-1">
              {["Mo", "Tu", "We", "Th", "Fr"].map((d) => (
                <div
                  key={d}
                  className="text-center font-mono text-[10px] text-muted-foreground"
                >
                  {d}
                </div>
              ))}
            </div>

            {/* Grid cells */}
            <div className="grid grid-cols-5 gap-1">
              {/* Leading padding cells */}
              {Array.from({ length: leadingCount }).map((_, i) => (
                <div
                  key={`pad-${i}`}
                  className="h-8 w-full rounded bg-muted/10"
                />
              ))}

              {/* Day cells */}
              {calDays.map((d) => {
                const ymd = toYMD(d);
                const pnl = dailyPnlMap[ymd];
                const isToday = ymd === todayStr;
                const cls = cellClasses(pnl, isToday);
                const tooltip =
                  pnl !== undefined
                    ? `${formatDateLabel(d)}: ${formatPnl(pnl)}`
                    : formatDateLabel(d);

                return (
                  <div
                    key={ymd}
                    title={tooltip}
                    className={`h-8 w-full rounded cursor-default transition-opacity hover:opacity-80 ${cls}`}
                  />
                );
              })}
            </div>

            {/* Summary stats */}
            {pnlValues.length > 0 ? (
              <div className="grid grid-cols-3 gap-3 mt-4 pt-3 border-t border-border">
                <div className="flex flex-col items-center gap-0.5">
                  <span className="font-mono text-[10px] text-muted-foreground uppercase tracking-wider">
                    Best Day
                  </span>
                  <span className="font-mono text-sm font-bold text-emerald-400 tabular-nums">
                    {bestDay !== null ? formatPnl(bestDay) : "—"}
                  </span>
                </div>
                <div className="flex flex-col items-center gap-0.5">
                  <span className="font-mono text-[10px] text-muted-foreground uppercase tracking-wider">
                    Worst Day
                  </span>
                  <span className="font-mono text-sm font-bold text-red-400 tabular-nums">
                    {worstDay !== null ? formatPnl(worstDay) : "—"}
                  </span>
                </div>
                <div className="flex flex-col items-center gap-0.5">
                  <span className="font-mono text-[10px] text-muted-foreground uppercase tracking-wider">
                    Avg Day
                  </span>
                  <span
                    className={`font-mono text-sm font-bold tabular-nums ${
                      avgDay !== null && avgDay >= 0
                        ? "text-emerald-400"
                        : "text-red-400"
                    }`}
                  >
                    {avgDay !== null ? formatPnl(avgDay) : "—"}
                  </span>
                </div>
              </div>
            ) : (
              <div className="mt-4 pt-3 border-t border-border">
                <span className="font-mono text-xs text-muted-foreground block text-center">
                  No trade data yet
                </span>
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
