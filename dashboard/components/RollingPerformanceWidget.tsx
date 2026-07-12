"use client";

import React from "react";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { type HonestTradeSet } from "@/lib/honestTrades";
import { useHonestTrades } from "@/lib/useHonestTrades";
import { deriveRollingWindowMetrics } from "@/lib/rolling-performance";


// ── Types ────────────────────────────────────────────────────────────────────

interface RollingWindow {
  window: string;
  days: number;
  trade_count: number;
  profit_factor: number | null;
  /** null — not derivable from deduped daily P&L (no per-trade std) */
  sharpe_ratio: null;
  win_rate: number | null;
  gross_pnl: number;
}

// ── Thresholds ───────────────────────────────────────────────────────────────

const TARGETS = {
  profit_factor: { pass: 2.0, warn: 1.5 },
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

function wrVariant(val: number | null): MetricBadgeVariant {
  if (val === null) return "neutral";
  // win_rate may come as 0-1; normalise to percent
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

// ── Derivation from honest trades ──────────────────────────────────────────────
// Delegates to the shared lib/rolling-performance.ts module (also used by
// RollingPerformanceCard on /readiness) so both surfaces agree on window
// filtering instead of computing gross_pnl and trade_count from two
// different filters. Sharpe is available from the shared derivation but
// intentionally not surfaced by this table (see the Sharpe-widget pointer
// in the footnote below); RollingPerformanceCard renders it.

function buildWindows(set: HonestTradeSet): RollingWindow[] {
  const dayParams = [7, 14, 30];

  return dayParams.map((d) => {
    const m = deriveRollingWindowMetrics(set.trades, d);
    return {
      window: m.window,
      days: m.days,
      trade_count: m.tradeCount,
      profit_factor: m.profitFactor,
      sharpe_ratio: null,
      win_rate: m.winRate,
      gross_pnl: m.grossPnl,
    } satisfies RollingWindow;
  });
}

// ── Loading skeleton ──────────────────────────────────────────────────────────

function SkeletonRow() {
  return (
    <tr>
      {Array.from({ length: 5 }).map((_, i) => (
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
  const { honest: set, isLoading: loading, error: loadError } = useHonestTrades(5 * 60 * 1000);
  const error = loadError ? (loadError instanceof Error ? loadError.message : String(loadError)) : null;
  const windows = set ? buildWindows(set) : null;

  const hasData = windows && windows.some((w) => w.trade_count > 0);

  return (
    <Card>
      <CardHeader className={cn("flex flex-row items-center justify-between space-y-0 pb-2")}>
        <CardTitle>Rolling Performance Windows</CardTitle>
        <Badge variant="neutral">Deduped · Auto-refresh 5m</Badge>
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
          Rolling windows vs validation targets (PF&ge;2.0, WR&ge;55%) &mdash; derived from deduped trade record. Sharpe omitted (requires per-trade std; see Sharpe widget).
        </p>
      </CardContent>
    </Card>
  );
}
