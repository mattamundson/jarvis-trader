"use client";

import { useEffect, useState } from "react";
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { fetchDailyPnLHistory } from "@/lib/api";
import { calendarDateStr, calendarDisplayFor } from "@/lib/calendarHeatmap";

interface DailyPnlEntry {
  date: string;
  pnl: number;
  num_trades: number;
  balance?: number;
}

export function CalendarHeatmap() {
  const [records, setRecords] = useState<DailyPnlEntry[]>([]);
  const [loading, setLoading] = useState(true);

  // "today" is intentionally client-only state -- same hydration guard as
  // DailyPnLCalendarWidget (GT-27) and WeeklyPnLCard (GT-30, PR #503).
  // Computing `new Date()` directly during render makes SSR output
  // (evaluated at server-render/build time) diverge from the client's first
  // hydration pass (evaluated whenever the browser actually loads the page)
  // whenever those two clock reads straddle a day/month boundary --
  // producing a React #418 hydration mismatch on the month label, the
  // calendar grid, and the "is today" ring highlight. Starting at `null`
  // and setting it in a mount-only effect guarantees the server and the
  // first client render agree (both render the loading skeleton), then the
  // real calendar fills in client-side. See lib/calendarHeatmap.ts.
  const [today, setToday] = useState<Date | null>(null);
  useEffect(() => {
    setToday(new Date());
  }, []);

  useEffect(() => {
    const load = async () => {
      try {
        const data = await fetchDailyPnLHistory({ days: 90 });
        const raw = data.daily_pnl ?? [];
        setRecords(
          raw.map((r) => ({
            date: String(r.date).slice(0, 10),
            pnl: Number(r.realized_pnl ?? 0),
            num_trades: Number(
              r.num_trades ?? (r as { total_trades?: number }).total_trades ?? 0
            ),
          }))
        );
      } catch {
        // ignore fetch errors — show empty calendar
      } finally {
        setLoading(false);
      }
    };

    load();
    const interval = setInterval(load, 5 * 60 * 1000);
    return () => clearInterval(interval);
  }, []);

  // Build calendar for the current month
  const calendar = calendarDisplayFor(today);

  if (loading || !calendar) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>P&L Calendar</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="h-48 animate-pulse rounded bg-muted" />
        </CardContent>
      </Card>
    );
  }

  const { year, month, monthLabel, cells, todayDay } = calendar;

  // Map date string -> record for O(1) lookup
  const pnlMap = new Map<string, DailyPnlEntry>();
  for (const r of records) {
    pnlMap.set(r.date, r);
  }

  const dateStr = (d: number) => calendarDateStr(year, month, d);

  // Monthly summary
  const monthRecords = records.filter((r) => {
    const rd = new Date(r.date);
    return rd.getFullYear() === year && rd.getMonth() === month;
  });
  const monthPnl = monthRecords.reduce((s, r) => s + r.pnl, 0);
  const tradingDays = monthRecords.filter((r) => r.num_trades > 0).length;

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-semibold">P&L Calendar</CardTitle>
          <span
            className={cn(
              "text-sm font-semibold font-mono",
              monthPnl > 0
                ? "text-green-400"
                : monthPnl < 0
                ? "text-red-400"
                : "text-muted-foreground"
            )}
          >
            {monthPnl >= 0 ? "+" : ""}${monthPnl.toFixed(0)}&nbsp;&bull;&nbsp;
            {tradingDays}d
          </span>
        </div>
        <p className="text-xs text-muted-foreground mt-0.5">{monthLabel}</p>
      </CardHeader>

      <CardContent className="pt-0">
        {/* Day-of-week headers */}
        <div className="grid grid-cols-7 gap-1 mb-1">
          {["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"].map((d) => (
            <div
              key={d}
              className="text-center text-[10px] text-muted-foreground font-medium py-0.5"
            >
              {d}
            </div>
          ))}
        </div>

        {/* Calendar grid */}
        <div className="grid grid-cols-7 gap-1">
          {cells.map((day, i) => {
            if (day === null) {
              return <div key={`blank-${i}`} className="min-h-[40px]" />;
            }

            const rec = pnlMap.get(dateStr(day));
            const pnl = rec?.pnl ?? 0;
            const hasTrades = rec !== undefined && rec.num_trades > 0;
            // `todayDay`/`month`/`year` all come from the same `today`
            // clock read (see calendarDisplayFor), so day === todayDay is
            // sufficient -- no separate month/year re-check needed.
            const isToday = day === todayDay;

            return (
              <div
                key={day}
                title={
                  rec
                    ? `${rec.num_trades} trade${rec.num_trades !== 1 ? "s" : ""} — $${pnl.toFixed(2)}`
                    : String(day)
                }
                className={cn(
                  "rounded p-1 text-center text-xs min-h-[40px] flex flex-col items-center justify-center gap-0.5 transition-colors",
                  isToday && "ring-1 ring-accent",
                  hasTrades && pnl > 0 && "bg-green-500/20 text-green-400",
                  hasTrades && pnl < 0 && "bg-red-500/20 text-red-400",
                  hasTrades && pnl === 0 && "bg-muted text-muted-foreground",
                  !hasTrades && "text-muted-foreground"
                )}
              >
                <span className="font-medium leading-none">{day}</span>
                {hasTrades && (
                  <span className="text-[10px] leading-none">
                    {pnl >= 0 ? "+" : ""}$
                    {Math.abs(pnl) >= 100
                      ? Math.round(pnl).toString()
                      : pnl.toFixed(0)}
                  </span>
                )}
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}
