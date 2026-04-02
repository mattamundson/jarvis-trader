"use client";

import React, { useState, useEffect } from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { fetchEngine } from "@/lib/api";


// ── Types ──────────────────────────────────────────────────────────────────────

interface TradeRecord {
  id: number;
  symbol: string;
  side: "BUY" | "SELL";
  realized_pnl: number | null;
  status: "OPEN" | "CLOSED" | "CANCELLED";
  entry_time: string;
  exit_time: string | null;
}

interface DailyPnLMap {
  [date: string]: number; // YYYY-MM-DD -> sum of realized_pnl
}

// ── Helpers ────────────────────────────────────────────────────────────────────

function formatPnl(value: number): string {
  const abs = Math.abs(value).toFixed(2);
  return value >= 0 ? `+$${abs}` : `-$${abs}`;
}

function toYMD(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${dd}`;
}

function formatDateLabel(d: Date): string {
  return d.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

/**
 * Returns list of Mon–Fri dates spanning the past 30 calendar days
 * (from 29 days ago through today, inclusive).
 */
function buildCalendarDays(): Date[] {
  const days: Date[] = [];
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  for (let i = 29; i >= 0; i--) {
    const d = new Date(today);
    d.setDate(today.getDate() - i);
    const dow = d.getDay(); // 0=Sun, 6=Sat
    if (dow >= 1 && dow <= 5) {
      days.push(d);
    }
  }
  return days;
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
  const [dailyPnl, setDailyPnl] = useState<DailyPnLMap | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  async function fetchData() {
    // 1. Try primary endpoint
    try {
      const primaryRes = await fetchEngine(`/analytics/daily-pnl`);
      if (primaryRes.ok) {
        const data: unknown = await primaryRes.json();
        if (
          data !== null &&
          typeof data === "object" &&
          !Array.isArray(data)
        ) {
          setDailyPnl(data as DailyPnLMap);
          setLoading(false);
          setError(false);
          return;
        }
      }
    } catch {
      // fall through to fallback
    }

    // 2. Fallback: compute from closed trades
    try {
      const tradesRes = await fetch(
        `/portfolio/history/trades?status=CLOSED&limit=500`
      );
      if (!tradesRes.ok) throw new Error("trades fetch failed");

      const raw: unknown = await tradesRes.json();
      let trades: TradeRecord[];
      if (Array.isArray(raw)) {
        trades = raw as TradeRecord[];
      } else if (
        raw !== null &&
        typeof raw === "object" &&
        Array.isArray((raw as { trades?: unknown }).trades)
      ) {
        trades = (raw as { trades: TradeRecord[] }).trades;
      } else {
        trades = [];
      }

      const map: DailyPnLMap = {};
      for (const t of trades) {
        if (
          t.status !== "CLOSED" ||
          t.realized_pnl == null ||
          !t.exit_time
        ) {
          continue;
        }
        const date = t.exit_time.slice(0, 10); // YYYY-MM-DD
        map[date] = (map[date] ?? 0) + t.realized_pnl;
      }

      setDailyPnl(map);
      setLoading(false);
      setError(false);
    } catch {
      setError(true);
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 120_000);
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Derived values ──────────────────────────────────────────────────────────

  const calDays = buildCalendarDays();
  const todayStr = toYMD(new Date());

  // Compute summary stats from days that have data
  const pnlValues: number[] = [];
  for (const d of calDays) {
    const v = dailyPnl?.[toYMD(d)];
    if (v !== undefined) pnlValues.push(v);
  }

  const bestDay = pnlValues.length > 0 ? Math.max(...pnlValues) : null;
  const worstDay = pnlValues.length > 0 ? Math.min(...pnlValues) : null;
  const avgDay =
    pnlValues.length > 0
      ? pnlValues.reduce((a, b) => a + b, 0) / pnlValues.length
      : null;

  const now = new Date();
  const monthLabel = now.toLocaleDateString("en-US", {
    month: "long",
    year: "numeric",
  });

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
        {!loading && !error && dailyPnl !== null && calDays.length === 0 && (
          <div className="flex items-center justify-center h-32">
            <span className="font-mono text-xs text-muted-foreground">
              No trade data yet
            </span>
          </div>
        )}

        {/* ── Calendar ── */}
        {!loading && !error && dailyPnl !== null && calDays.length > 0 && (
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
                const pnl = dailyPnl[ymd];
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
                    {bestDay !== null ? formatPnl(bestDay) : "\u2014"}
                  </span>
                </div>
                <div className="flex flex-col items-center gap-0.5">
                  <span className="font-mono text-[10px] text-muted-foreground uppercase tracking-wider">
                    Worst Day
                  </span>
                  <span className="font-mono text-sm font-bold text-red-400 tabular-nums">
                    {worstDay !== null ? formatPnl(worstDay) : "\u2014"}
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
                    {avgDay !== null ? formatPnl(avgDay) : "\u2014"}
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
