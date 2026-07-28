"use client";

import React, { useState, useEffect } from "react";
import { Calendar, Target, TrendingUp } from "lucide-react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchEngine } from "@/lib/api";
import { computeTradingDaysDisplay, TARGET_TRADING_DAYS } from "@/lib/cumulativeTradingDays";

const TARGET_DAYS = TARGET_TRADING_DAYS;
const REFRESH_MS = 120_000;

// ── Badge helpers ──────────────────────────────────────────────────────────────

type BadgeVariant = "bull" | "bear" | "warn" | "info" | "neutral";

function statusBadgeVariant(tradingDays: number): BadgeVariant {
  if (tradingDays >= 30) return "bull";
  if (tradingDays >= 20) return "info";
  if (tradingDays >= 10) return "warn";
  return "neutral";
}

function statusBadgeLabel(tradingDays: number): string {
  if (tradingDays >= 30) return "TARGET MET";
  if (tradingDays >= 20) return "ON TRACK";
  if (tradingDays >= 10) return "IN PROGRESS";
  return "EARLY STAGE";
}

// ── API type ───────────────────────────────────────────────────────────────────

interface TradeRecord {
  exit_time?: string | null;
  [key: string]: unknown;
}

// ── Component ──────────────────────────────────────────────────────────────────

export function CumulativeTradingDaysWidget() {
  const [trades, setTrades] = useState<TradeRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);

  async function fetchData() {
    try {
      setLoading(true);
      const raw = await fetchEngine(`/portfolio/history/trades`);
      // API returns an array of trades directly
      const arr: TradeRecord[] = Array.isArray(raw) ? raw : [];
      setTrades(arr);
      setError(null);
      setLastRefresh(new Date());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, REFRESH_MS);
    return () => clearInterval(interval);
  }, []);

  // "today" is intentionally client-only state -- same hydration guard as
  // DailyPnLCalendarWidget (GT-27) and WeeklyPnLCard (GT-30, PR #503).
  // Computing `new Date()` directly during render makes SSR output
  // (evaluated at server-render/build time) diverge from the client's first
  // hydration pass (evaluated whenever the browser actually loads the page)
  // whenever those two clock reads straddle a day boundary -- producing a
  // React #418 hydration mismatch on the "Est. completion" label and the
  // 30-day activity dot grid. Starting at `null` and setting it in a
  // mount-only effect guarantees the server and the first client render
  // agree (both render the placeholder), then the real values fill in
  // client-side. See lib/cumulativeTradingDays.ts.
  const [today, setToday] = useState<Date | null>(null);
  useEffect(() => {
    setToday(new Date());
  }, []);

  // ── Derived values ─────────────────────────────────────────────────────────

  // Unique trading days from exit_time
  const tradingDaySet = new Set<string>(
    trades
      .map((t) => (t.exit_time ? String(t.exit_time).slice(0, 10) : null))
      .filter((d): d is string => d !== null && d.length === 10)
  );
  const tradingDays = tradingDaySet.size;
  const hasTrades = tradingDays > 0;

  // Pace: days_with_trades / days_since_first_trade
  const sortedDays = [...tradingDaySet].sort();
  const firstTradeDateStr = sortedDays[0] ?? null;

  const { pace, estCompletionLabel, activityDots } = computeTradingDaysDisplay(
    today,
    tradingDays,
    firstTradeDateStr,
    tradingDaySet,
    TARGET_DAYS
  );

  // Progress
  const daysRemaining = Math.max(0, TARGET_DAYS - tradingDays);
  const progressPct = Math.min(100, (tradingDays / TARGET_DAYS) * 100);
  const pctLabel = `${Math.round(progressPct)}% complete`;

  const badgeVariant = statusBadgeVariant(tradingDays);
  const badgeLabel = statusBadgeLabel(tradingDays);

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Calendar className="h-4 w-4 text-muted-foreground" />
            <CardTitle>Cumulative Trading Days</CardTitle>
          </div>
          <Badge variant={badgeVariant}>{badgeLabel}</Badge>
        </div>
      </CardHeader>

      <CardContent className="space-y-5">
        {/* No trades empty state */}
        {!loading && !hasTrades && !error && (
          <div className="flex flex-col items-center py-6 text-muted-foreground gap-2">
            <Calendar className="h-8 w-8 opacity-40" />
            <p className="text-sm font-medium">No trades yet</p>
            <p className="text-xs opacity-70">
              Trading days will appear here once you have closed trades.
            </p>
          </div>
        )}

        {/* Main content */}
        {(loading || hasTrades || error) && (
          <>
            {/* Large counter */}
            <div className="flex flex-col items-center py-2">
              <span className="text-4xl font-bold font-mono text-foreground">
                {loading ? "—" : tradingDays}
                <span className="text-2xl text-muted-foreground font-normal">
                  {" "}/ {TARGET_DAYS} trading days
                </span>
              </span>
              <span className="text-xs text-muted-foreground mt-1">
                {loading ? "Loading…" : pctLabel}
              </span>
            </div>

            {/* Progress bar */}
            <div className="space-y-1">
              <div className="h-3 bg-muted rounded-full overflow-hidden">
                <div
                  className="h-full rounded-full transition-all duration-500 bg-bull"
                  style={{ width: `${progressPct}%` }}
                />
              </div>
              <div className="flex justify-between text-xs text-muted-foreground mt-1">
                <span>0 days</span>
                <span className="font-medium text-accent">
                  Target: {TARGET_DAYS} days
                </span>
              </div>
            </div>

            {/* Stats row */}
            <div className="grid grid-cols-3 gap-3">
              <div className="rounded-lg bg-muted/40 p-3 flex flex-col gap-1">
                <div className="flex items-center gap-1 text-[10px] text-muted-foreground uppercase tracking-wide font-medium">
                  <Target className="h-3 w-3" />
                  Days Remaining
                </div>
                <span className="text-sm font-mono font-bold text-foreground">
                  {loading ? "…" : daysRemaining === 0 ? "0 ✓" : String(daysRemaining)}
                </span>
              </div>

              <div className="rounded-lg bg-muted/40 p-3 flex flex-col gap-1">
                <div className="flex items-center gap-1 text-[10px] text-muted-foreground uppercase tracking-wide font-medium">
                  <Calendar className="h-3 w-3" />
                  Est. Completion
                </div>
                <span className="text-xs font-mono font-bold text-foreground leading-tight">
                  {loading ? "…" : estCompletionLabel}
                </span>
              </div>

              <div className="rounded-lg bg-muted/40 p-3 flex flex-col gap-1">
                <div className="flex items-center gap-1 text-[10px] text-muted-foreground uppercase tracking-wide font-medium">
                  <TrendingUp className="h-3 w-3" />
                  Trade Pace
                </div>
                <span className="text-sm font-mono font-bold text-foreground">
                  {loading
                    ? "…"
                    : pace > 0
                    ? `${(pace * 5).toFixed(1)} d/wk`
                    : "—"}
                </span>
              </div>
            </div>

            {/* 30-day dot grid — 6 rows × 5 cols */}
            <div className="space-y-2">
              <p className="text-[10px] text-muted-foreground uppercase tracking-wide font-medium">
                Last 30 Days Activity
              </p>
              <div
                className="grid gap-1.5"
                style={{ gridTemplateColumns: "repeat(5, minmax(0, 1fr))" }}
              >
                {activityDots.map(({ dateStr, hasTraded }) => (
                  <div
                    key={dateStr}
                    title={dateStr}
                    className={`aspect-square rounded-full ${
                      hasTraded ? "bg-bull" : "bg-muted"
                    }`}
                  />
                ))}
              </div>
              <div className="flex items-center gap-3 mt-1">
                <div className="flex items-center gap-1">
                  <div className="w-2 h-2 rounded-full bg-bull" />
                  <span className="text-[10px] text-muted-foreground">Traded</span>
                </div>
                <div className="flex items-center gap-1">
                  <div className="w-2 h-2 rounded-full bg-muted" />
                  <span className="text-[10px] text-muted-foreground">No trade</span>
                </div>
              </div>
            </div>
          </>
        )}

        {/* Error state */}
        {error && (
          <div className="rounded-lg bg-destructive/10 border border-destructive/25 p-4 flex flex-col gap-1">
            <p className="text-xs font-medium text-destructive">Error</p>
            <p className="text-xs text-destructive/80">{error}</p>
          </div>
        )}

        {/* Last refresh */}
        {lastRefresh && (
          <div className="text-xs text-muted-foreground text-center pt-1">
            Refreshed {lastRefresh.toLocaleTimeString()}
          </div>
        )}
      </CardContent>
    </Card>
  );
}