"use client";

import { useState } from "react";
import { ChevronLeft, ChevronRight, CalendarDays } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
} from "@/components/ui/card";
import {
  dedupCaveat,
  type HonestTrade,
  type HonestTradeSet,
} from "@/lib/honestTrades";
import { useHonestTrades } from "@/lib/useHonestTrades";

// ── Types ──────────────────────────────────────────────────────────────────────

interface DayData {
  totalPnl: number;
  tradeCount: number;
  trades: HonestTrade[];
}

// ── Helpers ────────────────────────────────────────────────────────────────────

function getCalendarDays(year: number, month: number): (Date | null)[] {
  const firstDay = new Date(year, month, 1);
  const lastDay = new Date(year, month + 1, 0);
  const startDow = firstDay.getDay();
  const days: (Date | null)[] = Array(startDow).fill(null);
  for (let d = 1; d <= lastDay.getDate(); d++) {
    days.push(new Date(year, month, d));
  }
  return days;
}

function toDateKey(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function formatPnl(pnl: number): string {
  const abs = Math.abs(pnl).toFixed(2);
  return pnl >= 0 ? `+$${abs}` : `-$${abs}`;
}

function formatPnlShort(pnl: number): string {
  const abs = Math.abs(pnl);
  const str = abs >= 1000 ? `${(abs / 1000).toFixed(1)}k` : abs.toFixed(0);
  return pnl >= 0 ? `+$${str}` : `-$${str}`;
}

const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

const DOW_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

// ── Day Cell ───────────────────────────────────────────────────────────────────

interface DayCellProps {
  date: Date;
  dayData: DayData | undefined;
  isToday: boolean;
}

function DayCell({ date, dayData, isToday }: DayCellProps) {
  const [hovered, setHovered] = useState(false);
  const dayNum = date.getDate();

  let bgClass = "bg-muted/30";
  let borderClass = "border-border/30";
  let textClass = "text-muted-foreground";

  if (dayData) {
    if (dayData.totalPnl > 0) {
      bgClass = "bg-bull/20";
      borderClass = "border-bull/40";
      textClass = "text-bull";
    } else if (dayData.totalPnl < 0) {
      bgClass = "bg-bear/20";
      borderClass = "border-bear/40";
      textClass = "text-bear";
    } else {
      bgClass = "bg-warn/20";
      borderClass = "border-warn/40";
      textClass = "text-warn";
    }
  }

  const todayRing = isToday ? "ring-1 ring-info/60" : "";

  return (
    <div
      className={`relative flex flex-col items-center justify-start rounded border ${bgClass} ${borderClass} ${todayRing} cursor-default select-none overflow-visible`}
      style={{ width: 40, height: 40, padding: "2px 3px" }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      {/* Day number */}
      <span className={`font-mono text-[11px] font-semibold leading-tight ${textClass}`}>
        {dayNum}
      </span>

      {dayData && dayData.tradeCount > 0 && (
        <span className={`font-mono text-[9px] leading-tight ${textClass} opacity-80`}>
          {dayData.tradeCount}t
        </span>
      )}

      {dayData && dayData.tradeCount > 0 && (
        <span className={`font-mono text-[8px] leading-tight ${textClass} tabular-nums`}>
          {formatPnlShort(dayData.totalPnl)}
        </span>
      )}

      {/* Tooltip */}
      {hovered && dayData && (
        <div
          className="absolute z-50 bottom-full left-1/2 mb-1 w-48 rounded-lg border border-border bg-card p-2 shadow-xl text-left pointer-events-none"
          style={{ transform: "translateX(-50%)" }}
        >
          <div className="font-mono text-[10px] font-bold text-foreground mb-1">
            {MONTH_NAMES[date.getMonth()]} {dayNum}
          </div>
          <div className="font-mono text-[10px] text-muted-foreground mb-1">
            {dayData.tradeCount} trade{dayData.tradeCount !== 1 ? "s" : ""}
          </div>
          <div className={`font-mono text-[11px] font-bold ${textClass}`}>
            Net P&amp;L: {formatPnl(dayData.totalPnl)}
          </div>
          {dayData.trades.slice(0, 4).map((t) => (
            <div key={t.id} className="font-mono text-[9px] text-muted-foreground mt-0.5 flex justify-between">
              <span>{t.symbol}</span>
              <span className={t.pnl >= 0 ? "text-bull" : "text-bear"}>
                {formatPnl(t.pnl)}
              </span>
            </div>
          ))}
          {dayData.trades.length > 4 && (
            <div className="font-mono text-[9px] text-muted-foreground mt-0.5">
              +{dayData.trades.length - 4} more
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Empty/Padding Cell ─────────────────────────────────────────────────────────

function EmptyCell() {
  return (
    <div
      style={{ width: 40, height: 40 }}
      className="rounded border border-transparent bg-transparent"
    />
  );
}

// ── Skeleton ───────────────────────────────────────────────────────────────────

function Skeleton({ className }: { className?: string }) {
  return <div className={`animate-pulse rounded bg-muted/30 ${className ?? ""}`} />;
}

// ── Main Widget ────────────────────────────────────────────────────────────────

export function TradeCalendarWidget() {
  const today = new Date();

  const [viewYear, setViewYear] = useState(today.getFullYear());
  const [viewMonth, setViewMonth] = useState(today.getMonth());
  const { honest: set, isLoading: loading, error: loadError } = useHonestTrades(60_000);
  const error = loadError
    ? loadError instanceof Error
      ? loadError.message
      : String(loadError)
    : null;

  // ── Build day map ─────────────────────────────────────────────────────────────

  const trades: HonestTrade[] = set?.trades ?? [];

  const dayMap: Record<string, DayData> = {};
  for (const trade of trades) {
    if (!trade.exit_time) continue;
    const exitDate = new Date(trade.exit_time);
    const key = toDateKey(exitDate);
    if (!dayMap[key]) {
      dayMap[key] = { totalPnl: 0, tradeCount: 0, trades: [] };
    }
    dayMap[key].totalPnl += trade.pnl;
    dayMap[key].tradeCount += 1;
    dayMap[key].trades.push(trade);
  }

  const calendarDays = getCalendarDays(viewYear, viewMonth);
  const todayKey = toDateKey(today);

  // ── Month navigation ─────────────────────────────────────────────────────────

  function prevMonth() {
    if (viewMonth === 0) {
      setViewMonth(11);
      setViewYear((y) => y - 1);
    } else {
      setViewMonth((m) => m - 1);
    }
  }

  function nextMonth() {
    if (viewMonth === 11) {
      setViewMonth(0);
      setViewYear((y) => y + 1);
    } else {
      setViewMonth((m) => m + 1);
    }
  }

  // ── Summary stats (for viewed month) ─────────────────────────────────────────

  const monthDays = Object.entries(dayMap).filter(([key]) => {
    const d = new Date(key + "T00:00:00");
    return d.getFullYear() === viewYear && d.getMonth() === viewMonth;
  });

  const tradingDays = monthDays.length;
  const profitableDays = monthDays.filter(([, d]) => d.totalPnl > 0).length;
  const losingDays = monthDays.filter(([, d]) => d.totalPnl < 0).length;

  let bestDay: { pnl: number; date: string } | null = null;
  let worstDay: { pnl: number; date: string } | null = null;

  for (const [key, d] of monthDays) {
    if (bestDay === null || d.totalPnl > bestDay.pnl) {
      bestDay = { pnl: d.totalPnl, date: key };
    }
    if (worstDay === null || d.totalPnl < worstDay.pnl) {
      worstDay = { pnl: d.totalPnl, date: key };
    }
  }

  const profitPct =
    tradingDays > 0 ? ((profitableDays / tradingDays) * 100).toFixed(1) : "0.0";
  const losePct =
    tradingDays > 0 ? ((losingDays / tradingDays) * 100).toFixed(1) : "0.0";

  // ── Render ───────────────────────────────────────────────────────────────────

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3">
        <div className="flex items-center gap-2">
          <CalendarDays className="h-4 w-4 text-info" />
          <CardTitle>Trade Calendar</CardTitle>
        </div>
        <div className="flex items-center gap-1">
          <Badge variant="info">
            {MONTH_NAMES[viewMonth]} {viewYear}
          </Badge>
          {!loading && (
            <span className="font-mono text-[10px] text-muted-foreground ml-1">
              Auto-refresh 60s
            </span>
          )}
        </div>
      </CardHeader>

      <CardContent>
        {error && (
          <p className="mb-4 font-mono text-xs text-bear">
            Engine error: {error}
          </p>
        )}

        {/* Month nav */}
        <div className="flex items-center justify-between mb-3">
          <button
            onClick={prevMonth}
            className="flex h-7 w-7 items-center justify-center rounded border border-border/50 bg-muted/30 text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors"
            aria-label="Previous month"
          >
            <ChevronLeft className="h-4 w-4" />
          </button>
          <span className="font-mono text-sm font-semibold text-foreground">
            {MONTH_NAMES[viewMonth]} {viewYear}
          </span>
          <button
            onClick={nextMonth}
            className="flex h-7 w-7 items-center justify-center rounded border border-border/50 bg-muted/30 text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors"
            aria-label="Next month"
          >
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>

        {loading ? (
          <div className="space-y-2">
            <div className="grid grid-cols-7 gap-1">
              {DOW_LABELS.map((d) => (
                <Skeleton key={d} className="h-5 w-full" />
              ))}
            </div>
            <div className="grid grid-cols-7 gap-1">
              {Array.from({ length: 35 }).map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          </div>
        ) : (
          <>
            {/* Day-of-week header */}
            <div className="grid grid-cols-7 gap-1 mb-1">
              {DOW_LABELS.map((label) => (
                <div
                  key={label}
                  className="flex items-center justify-center font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground"
                  style={{ height: 20 }}
                >
                  {label}
                </div>
              ))}
            </div>

            {/* Calendar grid */}
            <div className="grid grid-cols-7 gap-1">
              {calendarDays.map((date, idx) => {
                if (date === null) {
                  return <EmptyCell key={`pad-${idx}`} />;
                }
                const key = toDateKey(date);
                const isToday = key === todayKey;
                const dow = date.getDay();
                const isWeekend = dow === 0 || dow === 6;

                if (isWeekend) {
                  return (
                    <div
                      key={key}
                      className="flex items-center justify-center rounded border border-border/10 bg-transparent"
                      style={{ width: 40, height: 40 }}
                    >
                      <span className="font-mono text-[10px] text-muted-foreground/30">
                        {date.getDate()}
                      </span>
                    </div>
                  );
                }

                return (
                  <DayCell
                    key={key}
                    date={date}
                    dayData={dayMap[key]}
                    isToday={isToday}
                  />
                );
              })}
            </div>

            {/* Legend */}
            <div className="mt-3 flex items-center gap-4 flex-wrap">
              <div className="flex items-center gap-1.5">
                <div className="h-3 w-3 rounded border border-bull/40 bg-bull/20" />
                <span className="font-mono text-[10px] text-muted-foreground">Profitable</span>
              </div>
              <div className="flex items-center gap-1.5">
                <div className="h-3 w-3 rounded border border-bear/40 bg-bear/20" />
                <span className="font-mono text-[10px] text-muted-foreground">Loss</span>
              </div>
              <div className="flex items-center gap-1.5">
                <div className="h-3 w-3 rounded border border-warn/40 bg-warn/20" />
                <span className="font-mono text-[10px] text-muted-foreground">Breakeven</span>
              </div>
              <div className="flex items-center gap-1.5">
                <div className="h-3 w-3 rounded border border-border/30 bg-muted/30" />
                <span className="font-mono text-[10px] text-muted-foreground">No trades</span>
              </div>
            </div>

            {/* Summary stats */}
            <div className="mt-4 rounded-lg border border-border/40 bg-muted/10 p-3">
              <div className="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-3 lg:grid-cols-5">
                <div>
                  <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                    Trading Days
                  </p>
                  <p className="font-mono text-sm font-bold text-foreground tabular-nums">
                    {tradingDays}
                  </p>
                </div>
                <div>
                  <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                    Profitable
                  </p>
                  <p className="font-mono text-sm font-bold text-bull tabular-nums">
                    {profitableDays}{" "}
                    <span className="text-[10px] font-normal text-muted-foreground">
                      ({profitPct}%)
                    </span>
                  </p>
                </div>
                <div>
                  <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                    Losing
                  </p>
                  <p className="font-mono text-sm font-bold text-bear tabular-nums">
                    {losingDays}{" "}
                    <span className="text-[10px] font-normal text-muted-foreground">
                      ({losePct}%)
                    </span>
                  </p>
                </div>
                <div>
                  <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                    Best Day
                  </p>
                  {bestDay ? (
                    <p className="font-mono text-sm font-bold text-bull tabular-nums">
                      {formatPnl(bestDay.pnl)}{" "}
                      <span className="text-[10px] font-normal text-muted-foreground">
                        {bestDay.date.slice(5)}
                      </span>
                    </p>
                  ) : (
                    <p className="font-mono text-sm text-muted-foreground">—</p>
                  )}
                </div>
                <div>
                  <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                    Worst Day
                  </p>
                  {worstDay ? (
                    <p className="font-mono text-sm font-bold text-bear tabular-nums">
                      {formatPnl(worstDay.pnl)}{" "}
                      <span className="text-[10px] font-normal text-muted-foreground">
                        {worstDay.date.slice(5)}
                      </span>
                    </p>
                  ) : (
                    <p className="font-mono text-sm text-muted-foreground">—</p>
                  )}
                </div>
              </div>
            </div>

            {/* Dedup caveat */}
            {set && (
              <p className="mt-2 text-[10px] font-mono text-muted-foreground/60 text-center">
                {dedupCaveat(set)}
              </p>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
