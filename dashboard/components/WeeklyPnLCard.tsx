"use client";

import React, { useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchDailyPnLHistory } from "@/lib/api";


// ── Types ─────────────────────────────────────────────────────────────────────

interface DailyPnLEntry {
  date: string;   // "YYYY-MM-DD"
  pnl: number;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function getThisWeekDates(): string[] {
  const now = new Date();
  const day = now.getDay(); // 0=Sun
  const monday = new Date(now);
  monday.setDate(now.getDate() - (day === 0 ? 6 : day - 1));
  return Array.from({ length: 5 }, (_, i) => {
    const d = new Date(monday);
    d.setDate(monday.getDate() + i);
    return d.toISOString().slice(0, 10);
  });
}

function formatDollar(value: number): string {
  const abs = Math.abs(value);
  const formatted = abs.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  if (value > 0) return `+$${formatted}`;
  if (value < 0) return `-$${formatted}`;
  return `$${formatted}`;
}

const DAY_LETTERS = ["M", "T", "W", "T", "F"];

function totalColorClass(loading: boolean, weekTotal: number): string {
  if (loading) return "text-[#555]";
  if (weekTotal > 0) return "text-[#00ff88]";
  if (weekTotal < 0) return "text-[#ff4444]";
  return "text-[#888888]";
}

function cellTextClass(pnl: number | null): string {
  if (pnl === null) return "text-[#444]";
  if (pnl > 0) return "text-[#00ff88]";
  if (pnl < 0) return "text-[#ff4444]";
  return "text-[#888]";
}

function cellBorderClass(pnl: number | null): string {
  if (pnl === null) return "border-panel-border";
  if (pnl > 0) return "border-[#00ff8833]";
  if (pnl < 0) return "border-[#ff444433]";
  return "border-[#88888833]";
}

function avgDayColorClass(loading: boolean, avgDay: number): string {
  if (loading) return "text-[#555]";
  if (avgDay > 0) return "text-[#00ff88]";
  if (avgDay < 0) return "text-[#ff4444]";
  return "text-[#888]";
}

function bestDayColorClass(loading: boolean, hasEntries: boolean): string {
  if (loading) return "text-[#555]";
  return hasEntries ? "text-[#00ff88]" : "text-[#888]";
}

// ── Component ─────────────────────────────────────────────────────────────────

export function WeeklyPnLCard() {
  const [entries, setEntries] = useState<DailyPnLEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function fetchData() {
    setLoading(true);
    setError(null);
    try {
      const payload = await fetchDailyPnLHistory({ days: 21 });
      const rows = payload.daily_pnl ?? [];
      setEntries(
        rows.map((r) => ({
          date: String(r.date).slice(0, 10),
          pnl: Number(r.realized_pnl ?? 0),
        }))
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Build week map
  const weekDates = getThisWeekDates();
  const mondayDate = weekDates[0];

  const pnlByDate = new Map<string, number>();
  for (const entry of entries) {
    pnlByDate.set(entry.date, entry.pnl);
  }

  const weekPnLs: (number | null)[] = weekDates.map((d) => {
    const v = pnlByDate.get(d);
    return v !== undefined ? v : null;
  });

  const foundEntries = weekPnLs.filter((v) => v !== null) as number[];
  const weekTotal = foundEntries.reduce((sum, v) => sum + v, 0);
  const tradingDaysThisWeek = foundEntries.length;

  const avgDay = tradingDaysThisWeek > 0 ? weekTotal / tradingDaysThisWeek : 0;
  const bestDay =
    foundEntries.length > 0 ? Math.max(...foundEntries) : 0;

  // Badge
  type BadgeVariant = "bull" | "bear" | "neutral";
  let badgeVariant: BadgeVariant;
  let badgeLabel: string;
  if (weekTotal > 0) {
    badgeVariant = "bull";
    badgeLabel = "PROFITABLE";
  } else if (weekTotal < 0) {
    badgeVariant = "bear";
    badgeLabel = "LOSS WEEK";
  } else {
    badgeVariant = "neutral";
    badgeLabel = "FLAT";
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle className="font-mono text-sm uppercase tracking-wider">
          This Week
        </CardTitle>
        <button
          onClick={fetchData}
          disabled={loading}
          className="p-1 rounded transition-colors hover:bg-white/10 disabled:opacity-40"
          title="Refresh"
        >
          <RefreshCw
            className={`h-3.5 w-3.5 text-[#555] ${loading ? "animate-spin" : ""}`}
          />
        </button>
      </CardHeader>

      <CardContent className="space-y-4">
        {error ? (
          <p className="font-mono text-xs text-red-400">{error}</p>
        ) : (
          <>
            {/* Big total + badge */}
            <div className="flex items-center gap-3">
              <span
                className={`font-mono text-3xl font-bold tabular-nums leading-none ${totalColorClass(loading, weekTotal)}`}
              >
                {loading ? "$—" : formatDollar(weekTotal)}
              </span>
              {!loading && (
                <Badge variant={badgeVariant}>
                  {weekTotal > 0 ? "bull" : weekTotal < 0 ? "bear" : "neutral"}{" "}
                  {badgeLabel}
                </Badge>
              )}
            </div>

            {/* 5-column day grid */}
            <div className="grid grid-cols-5 gap-2">
              {weekDates.map((date, i) => {
                const pnl = weekPnLs[i];

                return (
                  <div
                    key={date}
                    className={`rounded-lg p-2 flex flex-col items-center gap-1 bg-panel border ${cellBorderClass(pnl)}`}
                  >
                    <span className="font-mono text-[10px] font-bold uppercase tracking-wider text-[#555]">
                      {DAY_LETTERS[i]}
                    </span>
                    <span
                      className={`font-mono text-[11px] font-semibold tabular-nums text-center leading-tight ${cellTextClass(pnl)}`}
                    >
                      {loading
                        ? "—"
                        : pnl === null
                        ? "—"
                        : formatDollar(pnl)}
                    </span>
                  </div>
                );
              })}
            </div>

            {/* Stats row */}
            <div className="grid grid-cols-3 gap-3 pt-3 border-t border-panel-border">
              <div className="flex flex-col items-center gap-0.5">
                <span className="font-mono text-[10px] uppercase tracking-wider text-[#555]">
                  Active Days
                </span>
                <span className="font-mono text-lg font-bold tabular-nums text-[#e0e0e0]">
                  {loading ? "—" : tradingDaysThisWeek}
                </span>
              </div>
              <div className="flex flex-col items-center gap-0.5">
                <span className="font-mono text-[10px] uppercase tracking-wider text-[#555]">
                  Avg Day
                </span>
                <span
                  className={`font-mono text-lg font-bold tabular-nums ${avgDayColorClass(loading, avgDay)}`}
                >
                  {loading || tradingDaysThisWeek === 0
                    ? "—"
                    : formatDollar(avgDay)}
                </span>
              </div>
              <div className="flex flex-col items-center gap-0.5">
                <span className="font-mono text-[10px] uppercase tracking-wider text-[#555]">
                  Best Day
                </span>
                <span
                  className={`font-mono text-lg font-bold tabular-nums ${bestDayColorClass(loading, foundEntries.length > 0)}`}
                >
                  {loading || foundEntries.length === 0
                    ? "—"
                    : formatDollar(bestDay)}
                </span>
              </div>
            </div>

            {/* Week of note */}
            <p className="font-mono text-[10px] text-center text-[#444]">
              Week of {mondayDate}
            </p>
          </>
        )}
      </CardContent>
    </Card>
  );
}
