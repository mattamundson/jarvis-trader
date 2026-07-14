"use client";

import React, { useEffect, useState } from "react";
import { RefreshCw, BarChart2, Calendar, TrendingUp } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import {
  dailyPnl,
  dedupCaveat,
  type HonestTradeSet,
} from "@/lib/honestTrades";
import { useHonestTrades } from "@/lib/useHonestTrades";


// ── Types ────────────────────────────────────────────────────────────────────

interface DayBucket {
  dateKey: string; // "2026-03-29"
  label: string;   // "Mar 29"
  count: number;
  totalPnl: number;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

/** Return "YYYY-MM-DD" for a Date object, in local time */
function toDateKey(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

/** Return "Mon DD" label, e.g. "Mar 29" */
function toLabel(dateKey: string): string {
  const [year, month, day] = dateKey.split("-").map(Number);
  const d = new Date(year, month - 1, day);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

/** Build last N calendar day buckets from today backwards */
function buildBuckets(days: number): DayBucket[] {
  const buckets: DayBucket[] = [];
  const today = new Date();
  today.setHours(0, 0, 0, 0);

  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(today);
    d.setDate(today.getDate() - i);
    const dateKey = toDateKey(d);
    buckets.push({ dateKey, label: toLabel(dateKey), count: 0, totalPnl: 0 });
  }

  return buckets;
}

// ── Widget ───────────────────────────────────────────────────────────────────

export function DailyTradeCountWidget() {
  const { honest: tradeSet, isLoading: loading, error: loadError, mutate: fetchData } = useHonestTrades(0);
  const error = loadError ? (loadError instanceof Error ? loadError.message : String(loadError)) : null;
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  useEffect(() => {
    if (tradeSet) setLastUpdated(new Date());
  }, [tradeSet]);

  // Derive buckets at render time from the honest trade set
  const buckets: DayBucket[] = (() => {
    if (!tradeSet) return [];
    // dailyPnl returns {date, pnl, count}[] keyed by YYYY-MM-DD (UTC exit date)
    const byDay = dailyPnl(tradeSet.trades);
    const dailyMap = new Map<string, { pnl: number; count: number }>(
      byDay.map((d) => [d.date, { pnl: d.pnl, count: d.count }])
    );
    // Build 14-day buckets and merge deduped daily data
    const dayBuckets = buildBuckets(14);
    for (const bucket of dayBuckets) {
      const dayData = dailyMap.get(bucket.dateKey);
      if (dayData) {
        bucket.count = dayData.count;
        bucket.totalPnl = dayData.pnl;
      }
    }
    return dayBuckets;
  })();

  // ── Derived stats ──────────────────────────────────────────────────────────

  const totalTrades = buckets.reduce((sum, b) => sum + b.count, 0);
  const activeDays = buckets.filter((b) => b.count >= 1);
  const zeroDays = buckets.filter((b) => b.count === 0).length;
  const avgTradesPerActiveDay =
    activeDays.length > 0
      ? activeDays.reduce((sum, b) => sum + b.count, 0) / activeDays.length
      : 0;

  const mostActiveDay = buckets.reduce<DayBucket | null>((best, b) => {
    if (!best || b.count > best.count) return b;
    return best;
  }, null);

  const maxCount = Math.max(...buckets.map((b) => b.count), 1);

  // Badge logic: bull ≥ 2/day, warn ≥ 1/day, bear < 1/day
  const badgeVariant: "bull" | "warn" | "bear" =
    avgTradesPerActiveDay >= 2
      ? "bull"
      : avgTradesPerActiveDay >= 1
      ? "warn"
      : "bear";

  const badgeLabel =
    badgeVariant === "bull"
      ? "Active"
      : badgeVariant === "warn"
      ? "Low Activity"
      : "Insufficient Activity";

  // Bar color per day
  function barColor(bucket: DayBucket): string {
    if (bucket.count === 0) return "#374151"; // gray-700
    if (bucket.totalPnl > 0) return "#22c55e"; // green-500
    if (bucket.totalPnl < 0) return "#ef4444"; // red-500
    return "#6b7280"; // gray-500 — trades present but breakeven
  }

  return (
    <div className="rounded-xl border border-border bg-card p-5 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent/10">
            <BarChart2 className="h-4 w-4 text-accent" />
          </div>
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Daily Trade Count
            </p>
            <div className="flex items-center gap-2 mt-0.5">
              <span className="text-lg font-bold font-mono tabular-nums text-foreground">
                {totalTrades}
              </span>
              <span className="text-xs text-muted-foreground">trades / 14 days</span>
              <Badge variant={badgeVariant}>{badgeLabel}</Badge>
            </div>
          </div>
        </div>

        <button
          onClick={() => fetchData()}
          disabled={loading}
          className="flex items-center gap-1.5 rounded-lg border border-border bg-background px-2.5 py-1.5 text-xs text-muted-foreground hover:text-foreground hover:bg-accent/5 transition-colors disabled:opacity-50"
          aria-label="Refresh daily trade count"
        >
          <RefreshCw className={`h-3 w-3 ${loading ? "animate-spin" : ""}`} />
          {loading ? "Loading…" : "Refresh"}
        </button>
      </div>

      {/* Error state */}
      {error && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-xs text-red-400">
          Unable to load trades: {error}
        </div>
      )}

      {/* Bar chart */}
      {!error && (
        <div className="space-y-1">
          {/* Bars */}
          <div className="flex items-end gap-1 h-24">
            {buckets.map((bucket) => {
              const heightPct =
                bucket.count === 0
                  ? 4 // show a tiny stub for zero-trade days
                  : Math.max(8, Math.round((bucket.count / maxCount) * 100));

              return (
                <div
                  key={bucket.dateKey}
                  className="flex-1 flex flex-col items-center justify-end gap-0.5 h-full"
                  title={`${bucket.label}: ${bucket.count} trade${bucket.count !== 1 ? "s" : ""}${
                    bucket.count > 0
                      ? ` — P&L: $${bucket.totalPnl.toFixed(0)}`
                      : " (no trades)"
                  }`}
                >
                  <div
                    style={{
                      height: `${heightPct}%`,
                      backgroundColor: barColor(bucket),
                      width: "100%",
                      borderRadius: "3px 3px 0 0",
                      transition: "height 0.3s ease",
                      opacity: bucket.count === 0 ? 0.35 : 1,
                    }}
                  />
                </div>
              );
            })}
          </div>

          {/* X-axis labels — show every 7th label to avoid crowding */}
          <div className="flex items-start gap-1">
            {buckets.map((bucket, idx) => (
              <div key={bucket.dateKey} className="flex-1 flex justify-center">
                {idx === 0 || idx === 6 || idx === 13 ? (
                  <span className="text-[10px] text-muted-foreground leading-tight text-center whitespace-nowrap">
                    {bucket.label}
                  </span>
                ) : null}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Legend */}
      {!error && (
        <div className="flex items-center gap-4 text-[10px] text-muted-foreground">
          <span className="flex items-center gap-1">
            <span className="inline-block w-2.5 h-2.5 rounded-sm bg-green-500" />
            Profitable day
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block w-2.5 h-2.5 rounded-sm bg-red-500" />
            Losing day
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block w-2.5 h-2.5 rounded-sm bg-gray-700 opacity-40" />
            No trades
          </span>
        </div>
      )}

      {/* Summary stats */}
      {!error && (
        <div className="grid grid-cols-3 gap-3 pt-1 border-t border-border">
          {/* Avg trades per active day */}
          <div className="space-y-0.5">
            <div className="flex items-center gap-1 text-[10px] text-muted-foreground uppercase tracking-wider">
              <TrendingUp className="h-3 w-3" />
              Avg / Active Day
            </div>
            <p className="text-sm font-bold font-mono tabular-nums text-foreground">
              {activeDays.length > 0 ? avgTradesPerActiveDay.toFixed(1) : "—"}
            </p>
            <p className="text-[10px] text-muted-foreground">
              {activeDays.length} active day{activeDays.length !== 1 ? "s" : ""}
            </p>
          </div>

          {/* Most active day */}
          <div className="space-y-0.5">
            <div className="flex items-center gap-1 text-[10px] text-muted-foreground uppercase tracking-wider">
              <BarChart2 className="h-3 w-3" />
              Most Active
            </div>
            {mostActiveDay && mostActiveDay.count > 0 ? (
              <>
                <p className="text-sm font-bold font-mono tabular-nums text-foreground">
                  {mostActiveDay.count} trade{mostActiveDay.count !== 1 ? "s" : ""}
                </p>
                <p className="text-[10px] text-muted-foreground">{mostActiveDay.label}</p>
              </>
            ) : (
              <p className="text-sm font-bold text-muted-foreground">—</p>
            )}
          </div>

          {/* Zero-trade days */}
          <div className="space-y-0.5">
            <div className="flex items-center gap-1 text-[10px] text-muted-foreground uppercase tracking-wider">
              <Calendar className="h-3 w-3" />
              Idle Days
            </div>
            <p className="text-sm font-bold font-mono tabular-nums text-foreground">
              {zeroDays}
            </p>
            <p className="text-[10px] text-muted-foreground">
              engine offline / weekend
            </p>
          </div>
        </div>
      )}

      {/* Dedup caveat footer */}
      {!error && tradeSet && tradeSet.relogged > 0 && (
        <p className="text-[10px] text-muted-foreground/70 border-t border-border pt-1">
          {dedupCaveat(tradeSet)}
        </p>
      )}

      {/* Last updated */}
      {lastUpdated && (
        <p className="text-[10px] text-muted-foreground text-right">
          Updated {lastUpdated.toLocaleTimeString()}
        </p>
      )}
    </div>
  );
}
