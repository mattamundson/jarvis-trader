"use client";

import React, { useEffect, useState, useCallback } from "react";
import { RefreshCw, Calendar } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

const ENGINE_URL = process.env.NEXT_PUBLIC_ENGINE_URL || "http://localhost:8010";

// ── Types ─────────────────────────────────────────────────────────────────────

interface DailyPnLEntry {
  date: string;           // "YYYY-MM-DD"
  pnl: number;
  cumulative_pnl: number;
  trade_count: number;
}

interface CalendarDay {
  dateStr: string;        // "YYYY-MM-DD"
  dayNum: number;         // 1–31
  pnl: number | null;
  tradeCount: number;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Return true if day-of-week is Mon–Fri (0=Sun, 6=Sat). */
function isWeekday(d: Date): boolean {
  const dow = d.getDay();
  return dow >= 1 && dow <= 5;
}

/** Format date to "YYYY-MM-DD" in local time. */
function toDateStr(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

/**
 * Generate the last 30 calendar days that are Mon–Fri, ending today,
 * padded at the front so the first week starts on Monday.
 *
 * Returns an array of CalendarDay entries in chronological order.
 * Cells for days before our window (padding) are represented with dateStr = "".
 */
function buildCalendarDays(
  pnlMap: Map<string, { pnl: number; trade_count: number }>
): (CalendarDay | null)[] {
  // Collect the last 30 weekdays
  const weekdays: Date[] = [];
  const today = new Date();
  today.setHours(0, 0, 0, 0);

  const cursor = new Date(today);
  while (weekdays.length < 30) {
    if (isWeekday(cursor)) {
      weekdays.unshift(new Date(cursor));
    }
    cursor.setDate(cursor.getDate() - 1);
  }

  // Pad front so first day falls on its correct Mon–Fri column (0=Mon … 4=Fri)
  const firstDay = weekdays[0];
  const firstDow = firstDay.getDay(); // 1=Mon … 5=Fri
  const colIndex = firstDow - 1;     // 0=Mon … 4=Fri
  const result: (CalendarDay | null)[] = Array(colIndex).fill(null);

  for (const d of weekdays) {
    const dateStr = toDateStr(d);
    const entry = pnlMap.get(dateStr) ?? null;
    result.push({
      dateStr,
      dayNum: d.getDate(),
      pnl: entry ? entry.pnl : null,
      tradeCount: entry ? entry.trade_count : 0,
    });
  }

  // Pad end to fill last row
  const remainder = result.length % 5;
  if (remainder !== 0) {
    const pad = 5 - remainder;
    for (let i = 0; i < pad; i++) result.push(null);
  }

  return result;
}

function cellBg(pnl: number | null): string {
  if (pnl === null) return "bg-muted/30 border-border/30";
  if (pnl > 100)  return "bg-green-600/80 border-green-500/50";
  if (pnl > 0)    return "bg-green-500/40 border-green-400/40";
  if (pnl < -100) return "bg-red-600/80 border-red-500/50";
  if (pnl < 0)    return "bg-red-500/40 border-red-400/40";
  // pnl === 0 with data
  return "bg-muted/50 border-border/50";
}

function fmtPnl(pnl: number): string {
  const sign = pnl >= 0 ? "+" : "";
  if (Math.abs(pnl) >= 1000) {
    return `${sign}${(pnl / 1000).toFixed(1)}k`;
  }
  return `${sign}${Math.round(pnl)}`;
}

function pnlTextColor(pnl: number | null): string {
  if (pnl === null) return "text-muted-foreground/40";
  if (pnl > 0) return "text-green-100";
  if (pnl < 0) return "text-red-100";
  return "text-muted-foreground";
}

// ── Component ─────────────────────────────────────────────────────────────────

export function DailyPnLCalendarWidget() {
  const [entries, setEntries] = useState<DailyPnLEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastFetched, setLastFetched] = useState<Date | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(
        `${ENGINE_URL}/portfolio/history/daily-pnl?limit=30`
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: DailyPnLEntry[] = await res.json();
      setEntries(Array.isArray(data) ? data : []);
      setLastFetched(new Date());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch");
    } finally {
      setLoading(false);
    }
  }, []);

  // Single fetch on mount — no auto-refresh
  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Build lookup map
  const pnlMap = new Map<string, { pnl: number; trade_count: number }>();
  for (const e of entries) {
    pnlMap.set(e.date, { pnl: e.pnl, trade_count: e.trade_count });
  }

  const cells = buildCalendarDays(pnlMap);
  const rows: (CalendarDay | null)[][] = [];
  for (let i = 0; i < cells.length; i += 5) {
    rows.push(cells.slice(i, i + 5));
  }

  // Summary counts
  let greenDays = 0;
  let redDays = 0;
  let noTradeDays = 0;
  for (const c of cells) {
    if (!c || c.dateStr === "") continue;
    if (c.pnl === null) noTradeDays++;
    else if (c.pnl > 0) greenDays++;
    else redDays++;
  }

  const DOW_HEADERS = ["M", "T", "W", "T", "F"];

  return (
    <Card className="w-full">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Calendar className="h-4 w-4 text-muted-foreground" />
            <CardTitle className="text-sm font-semibold">
              30-Day Trading Calendar
            </CardTitle>
          </div>
          <div className="flex items-center gap-2">
            {lastFetched && !loading && (
              <span className="text-[10px] text-muted-foreground hidden sm:block">
                {lastFetched.toLocaleTimeString([], {
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </span>
            )}
            <button
              onClick={fetchData}
              disabled={loading}
              className="flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs text-muted-foreground hover:text-foreground transition-colors disabled:opacity-40"
            >
              <RefreshCw
                className={`h-3 w-3 ${loading ? "animate-spin" : ""}`}
              />
              Refresh
            </button>
          </div>
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {error && (
          <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-400">
            Error: {error}
          </div>
        )}

        {/* Calendar grid */}
        <div className="space-y-1">
          {/* Day-of-week headers */}
          <div className="grid grid-cols-5 gap-1">
            {DOW_HEADERS.map((d, i) => (
              <div
                key={i}
                className="text-center text-[10px] font-semibold uppercase tracking-wider text-muted-foreground py-1"
              >
                {d}
              </div>
            ))}
          </div>

          {/* Calendar rows */}
          {loading ? (
            // Skeleton
            <div className="grid grid-cols-5 gap-1">
              {Array.from({ length: 30 }).map((_, i) => (
                <div
                  key={i}
                  className="h-14 rounded-md bg-muted/30 animate-pulse border border-border/20"
                />
              ))}
            </div>
          ) : (
            rows.map((row, ri) => (
              <div key={ri} className="grid grid-cols-5 gap-1">
                {row.map((cell, ci) => {
                  if (!cell) {
                    // Empty padding cell
                    return (
                      <div
                        key={ci}
                        className="h-14 rounded-md border border-transparent"
                      />
                    );
                  }
                  return (
                    <div
                      key={ci}
                      className={`h-14 rounded-md border flex flex-col items-center justify-center gap-0.5 transition-opacity ${cellBg(
                        cell.pnl
                      )}`}
                      title={
                        cell.pnl !== null
                          ? `${cell.dateStr}: $${cell.pnl.toFixed(2)} (${cell.tradeCount} trade${cell.tradeCount !== 1 ? "s" : ""})`
                          : `${cell.dateStr}: No trades`
                      }
                    >
                      <span
                        className={`text-[10px] font-medium leading-none ${
                          cell.pnl !== null
                            ? "text-white/70"
                            : "text-muted-foreground/50"
                        }`}
                      >
                        {cell.dayNum}
                      </span>
                      {cell.pnl !== null && (
                        <span
                          className={`text-[9px] font-mono font-bold leading-none ${pnlTextColor(
                            cell.pnl
                          )}`}
                        >
                          {fmtPnl(cell.pnl)}
                        </span>
                      )}
                    </div>
                  );
                })}
              </div>
            ))
          )}
        </div>

        {/* Legend */}
        <div className="flex flex-wrap items-center gap-3 pt-1 border-t border-border/50">
          <span className="text-[10px] text-muted-foreground font-medium uppercase tracking-wide">
            Legend:
          </span>
          <div className="flex items-center gap-1.5">
            <div className="h-3 w-3 rounded-sm bg-green-600/80 border border-green-500/50" />
            <span className="text-[10px] text-muted-foreground">Strong profit (&gt;$100)</span>
          </div>
          <div className="flex items-center gap-1.5">
            <div className="h-3 w-3 rounded-sm bg-green-500/40 border border-green-400/40" />
            <span className="text-[10px] text-muted-foreground">Profit</span>
          </div>
          <div className="flex items-center gap-1.5">
            <div className="h-3 w-3 rounded-sm bg-red-500/40 border border-red-400/40" />
            <span className="text-[10px] text-muted-foreground">Loss</span>
          </div>
          <div className="flex items-center gap-1.5">
            <div className="h-3 w-3 rounded-sm bg-red-600/80 border border-red-500/50" />
            <span className="text-[10px] text-muted-foreground">Strong loss (&gt;$100)</span>
          </div>
          <div className="flex items-center gap-1.5">
            <div className="h-3 w-3 rounded-sm bg-muted/30 border border-border/30" />
            <span className="text-[10px] text-muted-foreground">No trades</span>
          </div>
        </div>

        {/* Summary row */}
        {!loading && (
          <div className="flex flex-wrap items-center gap-2 pt-1">
            <span className="text-[10px] text-muted-foreground font-medium uppercase tracking-wide">
              Summary:
            </span>
            <Badge variant="bull">
              {greenDays} Green {greenDays === 1 ? "day" : "days"}
            </Badge>
            <Badge variant="bear">
              {redDays} Red {redDays === 1 ? "day" : "days"}
            </Badge>
            <Badge variant="neutral">
              {noTradeDays} No-trade {noTradeDays === 1 ? "day" : "days"}
            </Badge>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
