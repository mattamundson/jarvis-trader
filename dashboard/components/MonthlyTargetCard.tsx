"use client";

import React, { useEffect, useState, useCallback } from "react";
import { RefreshCw } from "lucide-react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchDailyPnLHistory } from "@/lib/api";
import { monthDisplayFor } from "@/lib/monthlyTarget";


const MONTHLY_TARGET = 500;

interface DailyPnLEntry {
  date: string;
  pnl: number;
}

function formatCurrencySigned(value: number): string {
  const abs = Math.abs(value).toFixed(2);
  return value >= 0 ? `+$${abs}` : `-$${abs}`;
}

function formatCurrencyPlain(value: number): string {
  const abs = Math.abs(value).toFixed(2);
  return value >= 0 ? `+$${abs}` : `-$${abs}`;
}

export function MonthlyTargetCard() {
  const [entries, setEntries] = useState<DailyPnLEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchDailyPnLHistory({ days: 62 });
      const rows = res.daily_pnl ?? [];
      setEntries(
        rows.map((r) => ({
          date: String(r.date).slice(0, 10),
          pnl: Number(r.realized_pnl ?? 0),
        }))
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to fetch");
      setEntries([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // "today" is intentionally client-only state -- same hydration guard as
  // DailyPnLCalendarWidget (GT-27) and WeeklyPnLCard (GT-30, PR #503).
  // Computing `new Date()` directly during render makes SSR output
  // (evaluated at server-render/build time) diverge from the client's first
  // hydration pass (evaluated whenever the browser actually loads the page)
  // whenever those two clock reads straddle a month boundary -- changing
  // both which entries count toward "this month" and the "Month Year" label
  // text -- producing a React #418 hydration mismatch. Starting at `null`
  // and setting it in a mount-only effect guarantees the server and the
  // first client render agree (both render the placeholder / empty-month
  // state), then the real month fills in client-side. See
  // lib/monthlyTarget.ts.
  const [today, setToday] = useState<Date | null>(null);
  useEffect(() => {
    setToday(new Date());
  }, []);

  const { yearMonth, monthLabel } = monthDisplayFor(today);

  // `today` is null pre-mount (yearMonth === ""); guard explicitly rather
  // than relying on `"".startsWith("")` being vacuously true for every entry.
  const monthEntries = today ? entries.filter((e) => e.date.startsWith(yearMonth)) : [];
  const monthlyPnl = monthEntries.reduce((sum, e) => sum + e.pnl, 0);
  const tradingDays = monthEntries.length;
  const bestDay = tradingDays > 0
    ? monthEntries.reduce((best, e) => (e.pnl > best.pnl ? e : best), monthEntries[0])
    : null;
  const worstDay = tradingDays > 0
    ? monthEntries.reduce((worst, e) => (e.pnl < worst.pnl ? e : worst), monthEntries[0])
    : null;

  const progress = Math.min(100, (monthlyPnl / MONTHLY_TARGET) * 100);

  let barColor = "bg-warn";
  if (progress >= 100) barColor = "bg-bull";
  else if (progress >= 50) barColor = "bg-info";

  type BadgeVariant = "bull" | "info" | "warn" | "neutral";
  let badgeVariant: BadgeVariant = "neutral";
  let badgeLabel = "NO DATA";

  if (tradingDays > 0) {
    if (monthlyPnl >= MONTHLY_TARGET) {
      badgeVariant = "bull";
      badgeLabel = "TARGET HIT";
    } else if (monthlyPnl >= 0) {
      badgeVariant = "info";
      badgeLabel = "ON TRACK";
    } else {
      badgeVariant = "warn";
      badgeLabel = "BEHIND";
    }
  }

  const pnlColor =
    tradingDays === 0
      ? "text-muted-foreground"
      : monthlyPnl >= 0
      ? "text-bull"
      : "text-bear";

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <CardTitle>Monthly P&L Target</CardTitle>
            <Badge variant={badgeVariant}>{badgeLabel}</Badge>
          </div>
          <button
            onClick={fetchData}
            disabled={loading}
            className="flex items-center gap-1 rounded border border-border px-2 py-1 text-xs text-muted-foreground hover:text-foreground transition-colors disabled:opacity-40"
          >
            <RefreshCw className={`h-3 w-3 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </button>
        </div>
        <p className="text-xs text-muted-foreground pt-0.5">{monthLabel}</p>
      </CardHeader>

      <CardContent className="space-y-4">
        {loading ? (
          <div className="animate-pulse space-y-3">
            <div className="h-10 w-36 bg-muted rounded" />
            <div className="h-2.5 w-full bg-muted rounded-full" />
            <div className="h-3 w-48 bg-muted rounded" />
          </div>
        ) : error ? (
          <p className="text-sm text-bear">Error: {error}</p>
        ) : tradingDays === 0 ? (
          <div className="flex flex-col gap-3">
            <p className="text-sm text-muted-foreground">No trades this month yet.</p>
            {/* still show empty bar */}
            <div className="h-2.5 w-full rounded-full bg-muted overflow-hidden">
              <div className="h-full w-0 rounded-full bg-warn" />
            </div>
            <p className="text-xs text-muted-foreground">
              $0.00 / ${MONTHLY_TARGET} target (0%)
            </p>
          </div>
        ) : (
          <>
            {/* Big P&L number */}
            <p className={`text-4xl font-bold font-mono ${pnlColor}`}>
              {formatCurrencySigned(monthlyPnl)}
            </p>

            {/* Progress bar */}
            <div className="space-y-1.5">
              <div className="h-2.5 w-full rounded-full bg-muted overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all duration-500 ${barColor}`}
                  style={{ width: `${Math.max(0, progress)}%` }}
                />
              </div>
              <p className="text-xs text-muted-foreground">
                {formatCurrencyPlain(monthlyPnl)} / ${MONTHLY_TARGET} target (
                {progress.toFixed(0)}%)
              </p>
            </div>

            {/* Stats row */}
            <div className="grid grid-cols-3 gap-4 pt-1 border-t border-border">
              <div className="space-y-0.5">
                <p className="text-[10px] text-muted-foreground uppercase tracking-wide font-medium">
                  Trading Days
                </p>
                <p className="text-sm font-mono font-bold text-foreground">
                  {tradingDays}
                </p>
              </div>
              <div className="space-y-0.5">
                <p className="text-[10px] text-muted-foreground uppercase tracking-wide font-medium">
                  Best Day
                </p>
                <p className="text-sm font-mono font-bold text-bull">
                  {bestDay ? formatCurrencySigned(bestDay.pnl) : "—"}
                </p>
              </div>
              <div className="space-y-0.5">
                <p className="text-[10px] text-muted-foreground uppercase tracking-wide font-medium">
                  Worst Day
                </p>
                <p className="text-sm font-mono font-bold text-bear">
                  {worstDay ? formatCurrencySigned(worstDay.pnl) : "—"}
                </p>
              </div>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
