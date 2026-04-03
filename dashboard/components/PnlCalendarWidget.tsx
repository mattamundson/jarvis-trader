"use client";

import React, { useState } from "react";
import useSWR from "swr";
import { fetchEngine } from "@/lib/api";

// ── Types ─────────────────────────────────────────────────────────────────────

interface DailyPnl {
  date: string;        // "2026-04-01"
  pnl: number;
  trade_count: number;
}

interface TradesByDayItem {
  date: string;
  trades: number;
  pnl: number;
  win_rate: number;
}

interface TradesByDayResponse {
  days: TradesByDayItem[];
}

// ── Constants ─────────────────────────────────────────────────────────────────

const WEEKS = 13;
const DAYS = WEEKS * 7; // 91 calendar days

// Color thresholds in USD
const COLORS = {
  none:      "#1a1a1a",  // no trade data
  profit_xs: "#134a2f",  // $0.01 – $49
  profit_sm: "#1a6b3f",  // $50 – $149
  profit_md: "#22a05a",  // $150 – $299
  profit_lg: "#00ff88",  // $300+
  loss_xs:   "#3a1010",  // -$0.01 – -$49
  loss_sm:   "#5a1515",  // -$50 – -$149
  loss_md:   "#881e1e",  // -$150 – -$299
  loss_lg:   "#ff3333",  // -$300+
  zero:      "#1a1a2e",  // traded, flat
} as const;

function pnlColor(pnl: number | undefined): string {
  if (pnl === undefined) return COLORS.none;
  if (pnl === 0) return COLORS.zero;
  if (pnl > 0) {
    if (pnl < 50)  return COLORS.profit_xs;
    if (pnl < 150) return COLORS.profit_sm;
    if (pnl < 300) return COLORS.profit_md;
    return COLORS.profit_lg;
  }
  // loss
  const abs = Math.abs(pnl);
  if (abs < 50)  return COLORS.loss_xs;
  if (abs < 150) return COLORS.loss_sm;
  if (abs < 300) return COLORS.loss_md;
  return COLORS.loss_lg;
}

function pnlBorderColor(pnl: number | undefined): string {
  if (pnl === undefined) return "#222";
  if (pnl === 0) return "#2a2a3e";
  if (pnl > 0) return "#00ff8833";
  return "#ff333333";
}

// ── Date helpers ──────────────────────────────────────────────────────────────

function toYMD(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function formatDateFull(d: Date): string {
  return d.toLocaleDateString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function formatPnl(v: number): string {
  const abs = Math.abs(v).toFixed(2);
  return v >= 0 ? `+$${abs}` : `-$${abs}`;
}

/**
 * Build a grid of 13 columns (weeks) x 7 rows (Sun=0…Sat=6).
 * The last column's Saturday aligns to "today".
 * Returns an array of 91 Date|null slots in [week][dow] order,
 * flattened as week-major (col 0 all rows, col 1 all rows…).
 */
function buildGrid(): { weeks: (Date | null)[][]; startDate: Date } {
  const today = new Date();
  today.setHours(0, 0, 0, 0);

  // Anchor the grid so today lands at the bottom-right (last column, today's DOW row)
  // We fill backwards from today to cover WEEKS complete columns.
  const todayDow = today.getDay(); // 0=Sun…6=Sat

  // The last column = the week containing today. Pad forward to Saturday if needed.
  const daysAfterToday = 6 - todayDow; // days left in this week after today

  const weeks: (Date | null)[][] = [];

  // Build week by week, starting from the oldest
  for (let w = 0; w < WEEKS; w++) {
    const week: (Date | null)[] = [];
    for (let d = 0; d < 7; d++) {
      // Position in the grid: slot index from oldest (week-major order)
      const slotIndex = w * 7 + d;
      // Offset from today: negative = past, 0 = today, positive = future
      const lastSlot = WEEKS * 7 - 1;
      const offsetFromToday = slotIndex - lastSlot + daysAfterToday;

      const date = new Date(today);
      date.setDate(today.getDate() + offsetFromToday);

      // Mark future days (after today) as null
      if (offsetFromToday > 0) {
        week.push(null);
      } else {
        week.push(date);
      }
    }
    weeks.push(week);
  }

  // The start date is the first non-null slot
  const startDate = new Date(today);
  startDate.setDate(today.getDate() - (WEEKS * 7 - 1 - daysAfterToday));

  return { weeks, startDate };
}

/** Returns month labels positioned over the correct week columns */
function buildMonthLabels(weeks: (Date | null)[][]): { label: string; colIndex: number }[] {
  const labels: { label: string; colIndex: number }[] = [];
  let lastMonth = -1;
  for (let w = 0; w < weeks.length; w++) {
    const firstDay = weeks[w].find((d) => d !== null);
    if (firstDay) {
      const m = firstDay.getMonth();
      if (m !== lastMonth) {
        labels.push({
          label: firstDay.toLocaleDateString("en-US", { month: "short" }),
          colIndex: w,
        });
        lastMonth = m;
      }
    }
  }
  return labels;
}

// ── Fetcher ───────────────────────────────────────────────────────────────────

async function fetchPnlByDay(): Promise<DailyPnl[]> {
  const data = await fetchEngine<TradesByDayResponse>(`/analytics/trades/by-day?days=91`);
  const days = Array.isArray(data?.days) ? data.days : [];
  return days.map((d) => ({
    date: d.date,
    pnl: d.pnl,
    trade_count: d.trades,
  }));
}

// ── Tooltip ───────────────────────────────────────────────────────────────────

interface TooltipState {
  visible: boolean;
  x: number;
  y: number;
  date: string;
  pnl: number | undefined;
  tradeCount: number | undefined;
}

// ── Skeleton ──────────────────────────────────────────────────────────────────

function CalendarSkeleton() {
  return (
    <div className="animate-pulse">
      <div className="flex gap-1 mb-1">
        {Array.from({ length: WEEKS }).map((_, i) => (
          <div key={i} className="flex-1 h-3 rounded" style={{ backgroundColor: "#1a1a1a" }} />
        ))}
      </div>
      <div className="flex gap-1">
        {Array.from({ length: WEEKS }).map((_, w) => (
          <div key={w} className="flex flex-col gap-1 flex-1">
            {Array.from({ length: 7 }).map((_, d) => (
              <div
                key={d}
                className="rounded"
                style={{ backgroundColor: "#1a1a1a", aspectRatio: "1" }}
              />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Main Component ────────────────────────────────────────────────────────────

export function PnlCalendarWidget() {
  const { data: pnlDays, error, isLoading } = useSWR<DailyPnl[]>(
    "/analytics/trades/by-day?days=91",
    fetchPnlByDay,
    {
      refreshInterval: 5 * 60 * 1000, // 5 minutes
      revalidateOnFocus: false,
    }
  );

  const [tooltip, setTooltip] = useState<TooltipState>({
    visible: false,
    x: 0,
    y: 0,
    date: "",
    pnl: undefined,
    tradeCount: undefined,
  });

  // Build lookup map from fetched data
  const pnlMap = React.useMemo<Record<string, DailyPnl>>(() => {
    if (!pnlDays) return {};
    const m: Record<string, DailyPnl> = {};
    for (const d of pnlDays) {
      m[d.date] = d;
    }
    return m;
  }, [pnlDays]);

  const { weeks } = React.useMemo(() => buildGrid(), []);
  const monthLabels = React.useMemo(() => buildMonthLabels(weeks), [weeks]);

  const todayStr = toYMD(new Date());

  // Summary stats
  const stats = React.useMemo(() => {
    if (!pnlDays || pnlDays.length === 0) return null;
    const values = pnlDays.map((d) => d.pnl);
    const totalPnl = values.reduce((a, b) => a + b, 0);
    const bestDay = Math.max(...values);
    const worstDay = Math.min(...values);
    const tradingDays = pnlDays.length;
    const greenDays = values.filter((v) => v > 0).length;
    return { totalPnl, bestDay, worstDay, tradingDays, greenDays };
  }, [pnlDays]);

  const handleMouseEnter = (
    e: React.MouseEvent<HTMLDivElement>,
    date: Date,
    entry: DailyPnl | undefined
  ) => {
    const rect = (e.target as HTMLElement).getBoundingClientRect();
    setTooltip({
      visible: true,
      x: rect.left + rect.width / 2,
      y: rect.top - 8,
      date: formatDateFull(date),
      pnl: entry?.pnl,
      tradeCount: entry?.trade_count,
    });
  };

  const handleMouseLeave = () => {
    setTooltip((prev) => ({ ...prev, visible: false }));
  };

  const DOW_LABELS = ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"];

  return (
    <section
      className="rounded-xl p-5"
      style={{ backgroundColor: "#0a0a0a", border: "1px solid #1a1a2e" }}
    >
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <h3
            className="font-mono text-sm font-bold tracking-[0.15em] uppercase"
            style={{ color: "#00ff88" }}
          >
            P&amp;L CALENDAR
          </h3>
          <span
            className="font-mono text-[9px] tracking-wider px-2 py-0.5 rounded"
            style={{ backgroundColor: "#00ff8810", border: "1px solid #00ff8820", color: "#00ff8880" }}
          >
            13 WEEKS
          </span>
        </div>

        {/* Legend */}
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-mono text-[9px] tracking-wider" style={{ color: "#444" }}>
            LEGEND:
          </span>
          <div className="flex items-center gap-1">
            <div className="h-3 w-3 rounded-sm" style={{ backgroundColor: COLORS.loss_lg }} />
            <span className="font-mono text-[9px]" style={{ color: "#888" }}>-$300+</span>
          </div>
          <div className="flex items-center gap-1">
            <div className="h-3 w-3 rounded-sm" style={{ backgroundColor: COLORS.loss_sm }} />
            <span className="font-mono text-[9px]" style={{ color: "#888" }}>-$50</span>
          </div>
          <div className="flex items-center gap-1">
            <div className="h-3 w-3 rounded-sm" style={{ backgroundColor: COLORS.none }} />
            <span className="font-mono text-[9px]" style={{ color: "#888" }}>$0</span>
          </div>
          <div className="flex items-center gap-1">
            <div className="h-3 w-3 rounded-sm" style={{ backgroundColor: COLORS.profit_sm }} />
            <span className="font-mono text-[9px]" style={{ color: "#888" }}>+$50</span>
          </div>
          <div className="flex items-center gap-1">
            <div className="h-3 w-3 rounded-sm" style={{ backgroundColor: COLORS.profit_lg }} />
            <span className="font-mono text-[9px]" style={{ color: "#888" }}>+$300+</span>
          </div>
        </div>
      </div>

      {/* Calendar */}
      {isLoading ? (
        <CalendarSkeleton />
      ) : error ? (
        <div
          className="flex items-center justify-center rounded-lg py-8"
          style={{ backgroundColor: "#0f0f0f", border: "1px solid #1a1a2e" }}
        >
          <span className="font-mono text-xs" style={{ color: "#444" }}>
            Calendar data unavailable
          </span>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <div style={{ minWidth: "560px" }}>
            {/* Month labels row */}
            <div className="flex gap-1 mb-1" style={{ paddingLeft: "24px" }}>
              {weeks.map((_, wi) => {
                const label = monthLabels.find((ml) => ml.colIndex === wi);
                return (
                  <div key={wi} className="flex-1">
                    {label ? (
                      <span
                        className="font-mono text-[9px] tracking-wider"
                        style={{ color: "#555" }}
                      >
                        {label.label}
                      </span>
                    ) : null}
                  </div>
                );
              })}
            </div>

            {/* Main grid: 7 rows (DOW) × WEEKS columns */}
            <div className="flex gap-1">
              {/* DOW labels column */}
              <div className="flex flex-col gap-1" style={{ width: "20px" }}>
                {DOW_LABELS.map((label, i) => (
                  <div
                    key={i}
                    className="flex items-center justify-end pr-1"
                    style={{ height: "12px", flexShrink: 0 }}
                  >
                    {/* Show only Mo, We, Fr to avoid crowding */}
                    {(i === 1 || i === 3 || i === 5) ? (
                      <span className="font-mono text-[8px]" style={{ color: "#444" }}>
                        {label}
                      </span>
                    ) : null}
                  </div>
                ))}
              </div>

              {/* Week columns */}
              {weeks.map((week, wi) => (
                <div key={wi} className="flex flex-col gap-1 flex-1">
                  {week.map((date, di) => {
                    if (date === null) {
                      // Future slot
                      return (
                        <div
                          key={di}
                          className="rounded-sm"
                          style={{
                            aspectRatio: "1",
                            backgroundColor: "#0d0d0d",
                            border: "1px solid #111",
                          }}
                        />
                      );
                    }

                    const ymd = toYMD(date);
                    const entry = pnlMap[ymd];
                    const isToday = ymd === todayStr;
                    const bg = pnlColor(entry?.pnl);
                    const borderColor = isToday ? "#00ff88" : pnlBorderColor(entry?.pnl);

                    return (
                      <div
                        key={di}
                        className="rounded-sm transition-all cursor-default"
                        style={{
                          aspectRatio: "1",
                          backgroundColor: bg,
                          border: `1px solid ${borderColor}`,
                          boxShadow: isToday ? "0 0 6px #00ff8840" : undefined,
                          outline: isToday ? "1px solid #00ff8860" : undefined,
                          outlineOffset: "1px",
                        }}
                        onMouseEnter={(e) => handleMouseEnter(e, date, entry)}
                        onMouseLeave={handleMouseLeave}
                      />
                    );
                  })}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Stats row */}
      {!isLoading && !error && stats && (
        <div
          className="grid grid-cols-5 gap-3 mt-4 pt-3"
          style={{ borderTop: "1px solid #1a1a2e" }}
        >
          <div className="flex flex-col items-center gap-0.5">
            <span className="font-mono text-[9px] uppercase tracking-wider" style={{ color: "#444" }}>
              Net P&amp;L
            </span>
            <span
              className="font-mono text-sm font-bold tabular-nums"
              style={{ color: stats.totalPnl >= 0 ? "#00ff88" : "#ff4444" }}
            >
              {formatPnl(stats.totalPnl)}
            </span>
          </div>
          <div className="flex flex-col items-center gap-0.5">
            <span className="font-mono text-[9px] uppercase tracking-wider" style={{ color: "#444" }}>
              Best Day
            </span>
            <span className="font-mono text-sm font-bold tabular-nums" style={{ color: "#00ff88" }}>
              {formatPnl(stats.bestDay)}
            </span>
          </div>
          <div className="flex flex-col items-center gap-0.5">
            <span className="font-mono text-[9px] uppercase tracking-wider" style={{ color: "#444" }}>
              Worst Day
            </span>
            <span className="font-mono text-sm font-bold tabular-nums" style={{ color: "#ff4444" }}>
              {formatPnl(stats.worstDay)}
            </span>
          </div>
          <div className="flex flex-col items-center gap-0.5">
            <span className="font-mono text-[9px] uppercase tracking-wider" style={{ color: "#444" }}>
              Trading Days
            </span>
            <span className="font-mono text-sm font-bold tabular-nums" style={{ color: "#e0e0e0" }}>
              {stats.tradingDays}
            </span>
          </div>
          <div className="flex flex-col items-center gap-0.5">
            <span className="font-mono text-[9px] uppercase tracking-wider" style={{ color: "#444" }}>
              Green Days
            </span>
            <span
              className="font-mono text-sm font-bold tabular-nums"
              style={{
                color:
                  stats.tradingDays > 0 && stats.greenDays / stats.tradingDays >= 0.5
                    ? "#00ff88"
                    : "#ffcc00",
              }}
            >
              {stats.greenDays}/{stats.tradingDays}
            </span>
          </div>
        </div>
      )}

      {!isLoading && !error && !stats && (
        <div className="mt-4 pt-3 text-center" style={{ borderTop: "1px solid #1a1a2e" }}>
          <span className="font-mono text-xs" style={{ color: "#333" }}>
            No trade data in the last 13 weeks
          </span>
        </div>
      )}

      {/* Tooltip (fixed position) */}
      {tooltip.visible && (
        <div
          className="fixed z-50 pointer-events-none"
          style={{
            left: tooltip.x,
            top: tooltip.y,
            transform: "translate(-50%, -100%)",
          }}
        >
          <div
            className="rounded-lg px-3 py-2 shadow-xl"
            style={{
              backgroundColor: "#111",
              border: "1px solid #2a2a2a",
              minWidth: "140px",
            }}
          >
            <div className="font-mono text-[10px] font-semibold mb-1" style={{ color: "#888" }}>
              {tooltip.date}
            </div>
            {tooltip.pnl !== undefined ? (
              <>
                <div
                  className="font-mono text-sm font-bold tabular-nums"
                  style={{ color: tooltip.pnl >= 0 ? "#00ff88" : "#ff4444" }}
                >
                  {formatPnl(tooltip.pnl)}
                </div>
                <div className="font-mono text-[9px] mt-0.5" style={{ color: "#555" }}>
                  {tooltip.tradeCount ?? 0} trade{(tooltip.tradeCount ?? 0) !== 1 ? "s" : ""}
                </div>
              </>
            ) : (
              <div className="font-mono text-[10px]" style={{ color: "#444" }}>
                No trades
              </div>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
