"use client";

import React, { useEffect, useState, useCallback } from "react";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { fetchEngine } from "@/lib/api";


// ── Types ────────────────────────────────────────────────────────────────────

interface RollingWindow {
  window: string;
  days: number;
  trade_count: number;
  profit_factor: number | null;
  sharpe_ratio: number | null;
  win_rate: number | null;
  gross_pnl: number;
  max_drawdown: number;
  avg_pnl_per_trade: number | null;
  best_trade: number | null;
  worst_trade: number | null;
  window_start: string;
  window_end: string;
}

// ── Thresholds ───────────────────────────────────────────────────────────────

const TARGETS = {
  profit_factor: { pass: 2.0, warn: 1.5 },
  sharpe_ratio: { pass: 1.5, warn: 1.0 },
  win_rate_pct: { pass: 55, warn: 45 },
};

// ── Badge helpers ─────────────────────────────────────────────────────────────

type MetricBadgeVariant = "bull" | "bear" | "warn" | "neutral";

function pfVariant(val: number | null): MetricBadgeVariant {
  if (val === null) return "neutral";
  if (val >= TARGETS.profit_factor.pass) return "bull";
  if (val >= TARGETS.profit_factor.warn) return "warn";
  return "bear";
}

function sharpeVariant(val: number | null): MetricBadgeVariant {
  if (val === null) return "neutral";
  if (val >= TARGETS.sharpe_ratio.pass) return "bull";
  if (val >= TARGETS.sharpe_ratio.warn) return "warn";
  return "bear";
}

function wrVariant(val: number | null): MetricBadgeVariant {
  if (val === null) return "neutral";
  // win_rate may come as 0-1 or 0-100; normalise to percent
  const pct = val > 1 ? val : val * 100;
  if (pct >= TARGETS.win_rate_pct.pass) return "bull";
  if (pct >= TARGETS.win_rate_pct.warn) return "warn";
  return "bear";
}

function badgeLabel(variant: MetricBadgeVariant): string {
  if (variant === "bull") return "PASS";
  if (variant === "bear") return "FAIL";
  if (variant === "warn") return "WARN";
  return "N/A";
}

// ── Formatters ────────────────────────────────────────────────────────────────

function fmtNum(val: number | null, decimals = 2): string {
  if (val === null || isNaN(val)) return "—";
  return val.toFixed(decimals);
}

function fmtWinRate(val: number | null): string {
  if (val === null || isNaN(val)) return "—";
  const pct = val > 1 ? val : val * 100;
  return `${pct.toFixed(1)}%`;
}

function fmtPnl(val: number): string {
  const sign = val >= 0 ? "+" : "";
  return `${sign}$${Math.abs(val).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

// ── Loading skeleton ──────────────────────────────────────────────────────────

function SkeletonRow() {
  return (
    <tr>
      {Array.from({ length: 6 }).map((_, i) => (
        <td key={i} className="px-3 py-3">
          <div className="h-4 rounded bg-muted/40 animate-pulse" style={{ width: i === 0 ? 40 : 80 }} />
        </td>
      ))}
    </tr>
  );
}

// ── Metric cell ───────────────────────────────────────────────────────────────

interface MetricCellProps {
  value: string;
  variant: MetricBadgeVariant;
}

function MetricCell({ value, variant }: MetricCellProps) {
  return (
    <td className="px-3 py-3 text-right">
      <div className="flex items-center justify-end gap-1.5">
        <span className="font-mono tabular-nums text-foreground">{value}</span>
        <Badge variant={variant}>{badgeLabel(variant)}</Badge>
      </div>
    </td>
  );
}

// ── Main widget ───────────────────────────────────────────────────────────────

export function RollingPerformanceWidget() {
  const [windows, setWindows] = useState<RollingWindow[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchWindows = useCallback(async () => {
    try {
      const dayParams = [7, 14, 30];
      const results = await Promise.all(
        dayParams.map((d) =>
          fetchEngine(`/analytics/performance/rolling?days=${d}`)
            .then((r) => {
              if (!r.ok) throw new Error(`HTTP ${r.status}`);
              return r.json();
            })
            .then((data) => ({
              ...data,
              window: `${d}d`,
              days: d,
            }))
        )
      );
      setWindows(results as RollingWindow[]);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load rolling performance");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchWindows();
    const id = setInterval(fetchWindows, 5 * 60 * 1000); // refresh every 5 minutes
    return () => clearInterval(id);
  }, [fetchWindows]);

  const hasData = windows && windows.some((w) => w.trade_count > 0);

  return (
    <Card>
      <CardHeader className={cn("flex flex-row items-center justify-between space-y-0 pb-2")}>
        <CardTitle>Rolling Performance Windows</CardTitle>
        <Badge variant="neutral">Auto-refresh 5m</Badge>
      </CardHeader>

      <CardContent>
        {/* Error state */}
        {error && !loading && (
          <p className="text-xs text-bear py-4">
            Unable to load rolling performance data. Engine may be offline.
          </p>
        )}

        {/* No data state */}
        {!loading && !error && !hasData && (
          <p className="text-xs text-muted-foreground py-4">
            No trades found in any rolling window. Data will appear once trades close.
          </p>
        )}

        {/* Table */}
        {(!error || loading) && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border">
                  <th className="px-3 py-2 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground">
                    Window
                  </th>
                  <th className="px-3 py-2 text-right text-xs font-medium uppercase tracking-wider text-muted-foreground">
                    Trades
                  </th>
                  <th className="px-3 py-2 text-right text-xs font-medium uppercase tracking-wider text-muted-foreground">
                    Profit Factor
                  </th>
                  <th className="px-3 py-2 text-right text-xs font-medium uppercase tracking-wider text-muted-foreground">
                    Sharpe
                  </th>
                  <th className="px-3 py-2 text-right text-xs font-medium uppercase tracking-wider text-muted-foreground">
                    Win Rate
                  </th>
                  <th className="px-3 py-2 text-right text-xs font-medium uppercase tracking-wider text-muted-foreground">
                    P&amp;L
                  </th>
                </tr>
              </thead>
              <tbody>
                {loading
                  ? Array.from({ length: 3 }).map((_, i) => <SkeletonRow key={i} />)
                  : windows?.map((w, idx) => {
                      const pfV = pfVariant(w.profit_factor);
                      const shV = sharpeVariant(w.sharpe_ratio);
                      const wrV = wrVariant(w.win_rate);
                      const pnlPositive = w.gross_pnl >= 0;

                      return (
                        <tr
                          key={w.window}
                          className={cn(
                            "border-b border-border/50 transition-colors hover:bg-white/[0.03]",
                            idx % 2 === 1 && "bg-muted/5"
                          )}
                        >
                          {/* Window label */}
                          <td className="px-3 py-3">
                            <span className="font-mono font-bold text-foreground">{w.window}</span>
                          </td>

                          {/* Trades */}
                          <td className="px-3 py-3 text-right font-mono tabular-nums text-muted-foreground">
                            {w.trade_count}
                          </td>

                          {/* Profit Factor */}
                          <MetricCell
                            value={w.profit_factor === null ? "—" : fmtNum(w.profit_factor)}
                            variant={w.trade_count === 0 ? "neutral" : pfV}
                          />

                          {/* Sharpe */}
                          <MetricCell
                            value={w.sharpe_ratio === null ? "—" : fmtNum(w.sharpe_ratio)}
                            variant={w.trade_count === 0 ? "neutral" : shV}
                          />

                          {/* Win Rate */}
                          <MetricCell
                            value={fmtWinRate(w.win_rate)}
                            variant={w.trade_count === 0 ? "neutral" : wrV}
                          />

                          {/* P&L */}
                          <td
                            className={cn(
                              "px-3 py-3 text-right font-mono tabular-nums font-semibold",
                              pnlPositive ? "text-bull" : "text-bear"
                            )}
                          >
                            {fmtPnl(w.gross_pnl)}
                          </td>
                        </tr>
                      );
                    })}
              </tbody>
            </table>
          </div>
        )}

        <p className="text-xs text-muted-foreground mt-2">
          Rolling windows vs validation targets (PF&ge;2.0, Sharpe&ge;1.5, WR&ge;55%)
        </p>
      </CardContent>
    </Card>
  );
}
