"use client";

import React, { useEffect, useState, useCallback } from "react";
import { RefreshCw } from "lucide-react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchDailyPnLHistory } from "@/lib/api";


interface DailyPnLEntry {
  date: string;
  pnl: number;
}

interface StreakStats {
  currentStreak: number;       // consecutive profitable days from most recent
  currentLossStreak: number;   // consecutive loss days from most recent
  maxStreak: number;           // longest profitable streak in dataset
  totalProfitableDays: number;
  totalLossDays: number;
  totalDays: number;
}

function computeStreaks(entries: DailyPnLEntry[]): StreakStats {
  if (entries.length === 0) {
    return {
      currentStreak: 0,
      currentLossStreak: 0,
      maxStreak: 0,
      totalProfitableDays: 0,
      totalLossDays: 0,
      totalDays: 0,
    };
  }

  // Sort ascending (oldest first)
  const sorted = [...entries].sort(
    (a, b) => new Date(a.date).getTime() - new Date(b.date).getTime()
  );

  let totalProfitableDays = 0;
  let totalLossDays = 0;

  // Compute max streak (scan full dataset)
  let maxStreak = 0;
  let runningStreak = 0;
  for (const entry of sorted) {
    if (entry.pnl > 0) {
      totalProfitableDays++;
      runningStreak++;
      if (runningStreak > maxStreak) maxStreak = runningStreak;
    } else {
      totalLossDays++;
      runningStreak = 0;
    }
  }

  // Compute current streak (walk backwards from newest)
  let currentStreak = 0;
  let currentLossStreak = 0;

  for (let i = sorted.length - 1; i >= 0; i--) {
    const pnl = sorted[i].pnl;
    if (i === sorted.length - 1) {
      // Determine direction from most recent day
      if (pnl > 0) {
        currentStreak = 1;
      } else {
        currentLossStreak = 1;
      }
    } else {
      if (currentStreak > 0) {
        // counting wins
        if (pnl > 0) {
          currentStreak++;
        } else {
          break;
        }
      } else {
        // counting losses
        if (pnl <= 0) {
          currentLossStreak++;
        } else {
          break;
        }
      }
    }
  }

  return {
    currentStreak,
    currentLossStreak,
    maxStreak,
    totalProfitableDays,
    totalLossDays,
    totalDays: sorted.length,
  };
}

export function PnLStreakWidget() {
  const [entries, setEntries] = useState<DailyPnLEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchDailyPnLHistory({ days: 60 });
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

  const stats = computeStreaks(entries);
  const isWinStreak = stats.currentStreak > 0;
  const isLossStreak = stats.currentLossStreak > 0;
  const hasData = stats.totalDays > 0;

  type BadgeVariant = "bull" | "bear" | "warn" | "info" | "neutral";
  let badgeVariant: BadgeVariant = "neutral";
  let badgeLabel = "NO DATA";
  if (hasData) {
    if (isWinStreak) {
      badgeVariant = "bull";
      badgeLabel = "WIN STREAK";
    } else if (isLossStreak) {
      badgeVariant = "bear";
      badgeLabel = "LOSS STREAK";
    } else {
      badgeVariant = "neutral";
      badgeLabel = "NEUTRAL";
    }
  }

  let streakDisplay: React.ReactNode;
  let streakColorClass: string;
  if (!hasData) {
    streakDisplay = "—";
    streakColorClass = "text-muted-foreground";
  } else if (isWinStreak) {
    streakDisplay = `🔥 ${stats.currentStreak} days`;
    streakColorClass = "text-bull";
  } else if (isLossStreak) {
    streakDisplay = `❄️ ${stats.currentLossStreak} days`;
    streakColorClass = "text-bear";
  } else {
    streakDisplay = "—";
    streakColorClass = "text-muted-foreground";
  }

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <CardTitle>Profitable Days Streak</CardTitle>
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
        <p className="text-xs text-muted-foreground pt-0.5">
          Consecutive day performance from most recent session
        </p>
      </CardHeader>

      <CardContent className="space-y-4">
        {loading ? (
          <div className="animate-pulse space-y-3">
            <div className="h-10 w-40 bg-muted rounded" />
            <div className="h-3 w-64 bg-muted rounded" />
            <div className="grid grid-cols-4 gap-4">
              {[0, 1, 2, 3].map((i) => (
                <div key={i} className="space-y-1.5">
                  <div className="h-2.5 w-16 bg-muted rounded" />
                  <div className="h-4 w-10 bg-muted rounded" />
                </div>
              ))}
            </div>
          </div>
        ) : error ? (
          <p className="text-sm text-bear">Error: {error}</p>
        ) : !hasData ? (
          <p className="text-sm text-muted-foreground">No daily P&L data available.</p>
        ) : (
          <>
            {/* Big streak metric */}
            <p className={`text-4xl font-bold font-mono ${streakColorClass}`}>
              {streakDisplay}
            </p>

            {/* Stats row */}
            <div className="grid grid-cols-4 gap-4 pt-1 border-t border-border">
              <div className="space-y-0.5">
                <p className="text-[10px] text-muted-foreground uppercase tracking-wide font-medium">
                  Max Streak
                </p>
                <p className="text-sm font-mono font-bold text-foreground">
                  {stats.maxStreak}d
                </p>
              </div>
              <div className="space-y-0.5">
                <p className="text-[10px] text-muted-foreground uppercase tracking-wide font-medium">
                  Profitable Days
                </p>
                <p className="text-sm font-mono font-bold text-bull">
                  {stats.totalProfitableDays}
                </p>
              </div>
              <div className="space-y-0.5">
                <p className="text-[10px] text-muted-foreground uppercase tracking-wide font-medium">
                  Loss Days
                </p>
                <p className="text-sm font-mono font-bold text-bear">
                  {stats.totalLossDays}
                </p>
              </div>
              <div className="space-y-0.5">
                <p className="text-[10px] text-muted-foreground uppercase tracking-wide font-medium">
                  Total Days
                </p>
                <p className="text-sm font-mono font-bold text-foreground">
                  {stats.totalDays}
                </p>
              </div>
            </div>

            {/* Footnote */}
            <p className="text-xs text-muted-foreground">
              Best streak: {stats.maxStreak} consecutive profitable{" "}
              {stats.maxStreak === 1 ? "day" : "days"}
            </p>
          </>
        )}
      </CardContent>
    </Card>
  );
}
