"use client";

import { useEffect, useState } from "react";
import { CalendarDays } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

const ENGINE_URL = process.env.NEXT_PUBLIC_ENGINE_URL || "http://localhost:8010";

// ── Types ─────────────────────────────────────────────────────────────────────

interface DailyPnlRecord {
  date: string;
  realized_pnl: number;
  cumulative_pnl: number;
  num_trades: number;
}

interface MonthBucket {
  key: string; // "YYYY-MM"
  label: string; // "Mar 2026"
  total_pnl: number;
  trading_days: number;
  total_trades: number;
  win_days: number;
  loss_days: number;
  best_day: number;
  worst_day: number;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatMonthLabel(key: string): string {
  // key = "YYYY-MM"
  const [year, month] = key.split("-");
  const date = new Date(Number(year), Number(month) - 1, 1);
  return date.toLocaleDateString("en-US", { month: "short", year: "numeric" });
}

function formatPnl(value: number): string {
  const sign = value >= 0 ? "+" : "";
  return `${sign}$${Math.abs(value).toFixed(2)}`;
}

function pnlVariant(value: number): "bull" | "bear" | "neutral" {
  if (value > 0) return "bull";
  if (value < 0) return "bear";
  return "neutral";
}

function groupByMonth(records: DailyPnlRecord[]): MonthBucket[] {
  const map = new Map<string, MonthBucket>();

  for (const rec of records) {
    // date is an ISO string like "2026-03-15" or "2026-03-15T00:00:00"
    const key = rec.date.slice(0, 7); // "YYYY-MM"

    if (!map.has(key)) {
      map.set(key, {
        key,
        label: formatMonthLabel(key),
        total_pnl: 0,
        trading_days: 0,
        total_trades: 0,
        win_days: 0,
        loss_days: 0,
        best_day: -Infinity,
        worst_day: Infinity,
      });
    }

    const bucket = map.get(key)!;
    bucket.total_pnl += rec.realized_pnl;
    bucket.total_trades += rec.num_trades;

    if (rec.num_trades > 0) {
      bucket.trading_days += 1;
    }
    if (rec.realized_pnl > 0) {
      bucket.win_days += 1;
    } else if (rec.realized_pnl < 0) {
      bucket.loss_days += 1;
    }
    if (rec.realized_pnl > bucket.best_day) {
      bucket.best_day = rec.realized_pnl;
    }
    if (rec.realized_pnl < bucket.worst_day) {
      bucket.worst_day = rec.realized_pnl;
    }
  }

  // Fix up buckets with no trading data (best_day/worst_day still at sentinel values)
  for (const bucket of map.values()) {
    if (bucket.best_day === -Infinity) bucket.best_day = 0;
    if (bucket.worst_day === Infinity) bucket.worst_day = 0;
  }

  // Sort descending by key (most recent first), cap at 12
  return [...map.values()]
    .sort((a, b) => b.key.localeCompare(a.key))
    .slice(0, 12);
}

// ── Skeleton ──────────────────────────────────────────────────────────────────

function Skeleton() {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm flex items-center gap-2">
          <CalendarDays className="h-4 w-4" />
          Monthly Breakdown
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-2">
          {[1, 2, 3].map((i) => (
            <div key={i} className="animate-pulse h-8 bg-muted rounded" />
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

// ── Widget ────────────────────────────────────────────────────────────────────

export function MonthlyBreakdownWidget() {
  const [months, setMonths] = useState<MonthBucket[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      try {
        const res = await fetch(
          `${ENGINE_URL}/portfolio/history/daily-pnl?limit=365`
        );
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const records: DailyPnlRecord[] = await res.json();
        if (!cancelled) {
          setMonths(groupByMonth(records));
          setError(false);
        }
      } catch {
        if (!cancelled) setError(true);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    load();
    const id = setInterval(load, 5 * 60 * 1000); // refresh every 5 minutes
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  if (loading) return <Skeleton />;

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm flex items-center gap-2">
          <CalendarDays className="h-4 w-4" />
          Monthly Breakdown
        </CardTitle>
      </CardHeader>
      <CardContent>
        {error && (
          <p className="text-sm text-muted-foreground">
            Unable to load monthly data
          </p>
        )}

        {!error && months.length === 0 && (
          <p className="text-sm text-muted-foreground">No monthly data yet</p>
        )}

        {!error && months.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full font-mono text-xs">
              <thead>
                <tr
                  style={{ borderBottom: "1px solid hsl(var(--border))" }}
                >
                  {[
                    { label: "Month", align: "text-left" },
                    { label: "Trading Days", align: "text-right" },
                    { label: "Total P&L", align: "text-right" },
                    { label: "Best Day", align: "text-right" },
                    { label: "Worst Day", align: "text-right" },
                    { label: "Win Days", align: "text-right" },
                  ].map(({ label, align }) => (
                    <th
                      key={label}
                      className={`pb-2 px-2 font-semibold uppercase tracking-wider ${align}`}
                      style={{
                        color: "hsl(var(--muted-foreground))",
                        fontSize: "10px",
                      }}
                    >
                      {label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {months.map((m) => (
                  <tr
                    key={m.key}
                    className="hover:bg-muted/20 transition-colors"
                    style={{
                      borderBottom: "1px solid hsl(var(--border) / 0.5)",
                    }}
                  >
                    {/* Month */}
                    <td className="py-2 px-2 font-semibold tabular-nums">
                      {m.label}
                    </td>

                    {/* Trading Days */}
                    <td className="py-2 px-2 text-right tabular-nums text-muted-foreground">
                      {m.trading_days}
                    </td>

                    {/* Total P&L */}
                    <td className="py-2 px-2 text-right">
                      <Badge variant={pnlVariant(m.total_pnl)}>
                        {formatPnl(m.total_pnl)}
                      </Badge>
                    </td>

                    {/* Best Day */}
                    <td className="py-2 px-2 text-right">
                      <Badge variant={pnlVariant(m.best_day)}>
                        {formatPnl(m.best_day)}
                      </Badge>
                    </td>

                    {/* Worst Day */}
                    <td className="py-2 px-2 text-right">
                      <Badge variant={pnlVariant(m.worst_day)}>
                        {formatPnl(m.worst_day)}
                      </Badge>
                    </td>

                    {/* Win Days */}
                    <td className="py-2 px-2 text-right tabular-nums">
                      <span
                        style={{
                          color:
                            m.win_days > m.loss_days
                              ? "hsl(var(--bull))"
                              : m.loss_days > m.win_days
                              ? "hsl(var(--bear))"
                              : "hsl(var(--muted-foreground))",
                        }}
                      >
                        {m.win_days}
                        <span
                          className="text-muted-foreground"
                          style={{ fontSize: "9px" }}
                        >
                          /{m.trading_days}
                        </span>
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
