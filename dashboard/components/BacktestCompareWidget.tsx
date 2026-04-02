"use client";

import React, { useState, useEffect } from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchEngine } from "@/lib/api";


// ── Backtest benchmarks ────────────────────────────────────────────────────────

const BACKTEST = {
  profit_factor: 5.27,
  sharpe_ratio: 4.16,
  win_rate: 0.72,
  total_trades: 312,
  max_drawdown: -0.031,
  total_pnl: 47200.0,
  avg_trade_pnl: 151.28,
  label: "MES 1h Backtest (Best)",
  period: "Historical",
};

// ── Types ─────────────────────────────────────────────────────────────────────

interface PerformanceData {
  profit_factor: number;
  sharpe_ratio: number;
  win_rate: number;
  total_trades: number;
  trading_days: number;
  max_drawdown: number;
  total_pnl: number;
  avg_trade_pnl: number;
}

type RowColor = "green" | "orange" | "red" | "neutral";

// ── Helpers ───────────────────────────────────────────────────────────────────

function colorClass(c: RowColor): string {
  if (c === "green") return "text-bull";
  if (c === "orange") return "text-warn";
  if (c === "red") return "text-bear";
  return "text-muted-foreground";
}

/** For positive metrics (higher = better): green >= 70%, orange >= 40%, red < 40% */
function positiveColor(live: number, backtest: number): RowColor {
  if (backtest === 0) return "neutral";
  const ratio = live / backtest;
  if (ratio >= 0.7) return "green";
  if (ratio >= 0.4) return "orange";
  return "red";
}

/** For drawdown (lower abs = better) */
function drawdownColor(liveDD: number, backtestDD: number): RowColor {
  const liveAbs = Math.abs(liveDD);
  const btAbs = Math.abs(backtestDD);
  if (btAbs === 0) return "neutral";
  const ratio = liveAbs / btAbs;
  if (ratio <= 1.5) return "green";
  if (ratio <= 3) return "orange";
  return "red";
}

function fmtPct(n: number): string {
  return `${(n * 100).toFixed(1)}%`;
}

function fmtCurrency(n: number): string {
  return n.toLocaleString("en-US", { style: "currency", currency: "USD" });
}

function fmtDD(n: number): string {
  return `${(Math.abs(n) * 100).toFixed(1)}%`;
}

function isAllZeros(data: PerformanceData): boolean {
  return (
    data.profit_factor === 0 &&
    data.sharpe_ratio === 0 &&
    data.win_rate === 0 &&
    data.total_trades === 0 &&
    data.total_pnl === 0
  );
}

// ── Skeleton ──────────────────────────────────────────────────────────────────

function Skeleton() {
  return (
    <div className="animate-pulse space-y-3 p-4">
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="flex items-center justify-between">
          <div className="h-3 w-28 bg-muted rounded" />
          <div className="h-3 w-16 bg-muted rounded" />
          <div className="h-3 w-16 bg-muted rounded" />
        </div>
      ))}
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export function BacktestCompareWidget() {
  const [data, setData] = useState<PerformanceData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  function fetchData() {
    fetchEngine(`/analytics/performance`)
      .then((res) => {
        return res.json();
      })
      .then((json: Partial<PerformanceData>) => {
        setData({
          profit_factor: json.profit_factor ?? 0,
          sharpe_ratio: json.sharpe_ratio ?? 0,
          win_rate: json.win_rate ?? 0,
          total_trades: json.total_trades ?? 0,
          trading_days: json.trading_days ?? 0,
          max_drawdown: json.max_drawdown ?? 0,
          total_pnl: json.total_pnl ?? 0,
          avg_trade_pnl: json.avg_trade_pnl ?? 0,
        });
        setError(false);
        setLoading(false);
      })
      .catch(() => {
        setError(true);
        setLoading(false);
      });
  }

  useEffect(() => {
    fetchData();
    const id = setInterval(fetchData, 60_000);
    return () => clearInterval(id);
  }, []);

  // ── Overall badge ──────────────────────────────────────────────────────────

  type BadgeVariant = "bull" | "bear" | "warn" | "info" | "neutral";

  function overallBadge(): { variant: BadgeVariant; label: string } {
    if (!data || isAllZeros(data)) return { variant: "neutral", label: "NO DATA" };
    const pf = data.profit_factor;
    const sr = data.sharpe_ratio;
    if (pf >= 2.0 && sr >= 1.5) return { variant: "bull", label: "ON TARGET" };
    if (pf >= 1.5 || sr >= 1.2) return { variant: "info", label: "PROGRESSING" };
    return { variant: "warn", label: "BELOW TARGET" };
  }

  const badge = overallBadge();

  // ── Row data ───────────────────────────────────────────────────────────────

  type Row = {
    metric: string;
    live: string;
    backtest: string;
    color: RowColor;
  };

  function buildRows(): Row[] {
    if (!data) return [];
    return [
      {
        metric: "Profit Factor",
        live: data.profit_factor.toFixed(2),
        backtest: BACKTEST.profit_factor.toFixed(2),
        color: positiveColor(data.profit_factor, BACKTEST.profit_factor),
      },
      {
        metric: "Sharpe Ratio",
        live: data.sharpe_ratio.toFixed(2),
        backtest: BACKTEST.sharpe_ratio.toFixed(2),
        color: positiveColor(data.sharpe_ratio, BACKTEST.sharpe_ratio),
      },
      {
        metric: "Win Rate",
        live: fmtPct(data.win_rate),
        backtest: fmtPct(BACKTEST.win_rate),
        color: positiveColor(data.win_rate, BACKTEST.win_rate),
      },
      {
        metric: "Max Drawdown",
        live: fmtDD(data.max_drawdown),
        backtest: fmtDD(BACKTEST.max_drawdown),
        color: drawdownColor(data.max_drawdown, BACKTEST.max_drawdown),
      },
      {
        metric: "Avg Trade P&L",
        live: fmtCurrency(data.avg_trade_pnl),
        backtest: fmtCurrency(BACKTEST.avg_trade_pnl),
        color: positiveColor(data.avg_trade_pnl, BACKTEST.avg_trade_pnl),
      },
      {
        metric: "Total P&L",
        live: fmtCurrency(data.total_pnl),
        backtest: fmtCurrency(BACKTEST.total_pnl),
        color: "neutral",
      },
    ];
  }

  const rows = buildRows();

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle>Live vs Backtest Comparison</CardTitle>
            <p className="text-xs text-muted-foreground mt-1">
              Best backtest: MES 1h &nbsp;|&nbsp; PF 5.27 &nbsp;|&nbsp; Sharpe 4.16 &nbsp;|&nbsp; +47.2%
            </p>
          </div>
          <Badge variant={badge.variant}>{badge.label}</Badge>
        </div>
      </CardHeader>

      <CardContent>
        {loading ? (
          <Skeleton />
        ) : error ? (
          <div className="py-6 text-center text-sm text-muted-foreground">
            Performance data unavailable
          </div>
        ) : data && isAllZeros(data) ? (
          <div className="py-6 text-center text-sm text-muted-foreground">
            Accumulating live data...
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border bg-muted/30">
                  <th className="text-left px-4 py-2.5 text-muted-foreground font-semibold uppercase tracking-wide">
                    Metric
                  </th>
                  <th className="text-right px-4 py-2.5 text-muted-foreground font-semibold uppercase tracking-wide">
                    Live Paper
                  </th>
                  <th className="text-right px-4 py-2.5 text-muted-foreground font-semibold uppercase tracking-wide">
                    Backtest
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {rows.map((row) => (
                  <tr key={row.metric} className="hover:bg-muted/20 transition-colors">
                    <td className="px-4 py-3 font-medium text-foreground">
                      {row.metric}
                    </td>
                    <td
                      className={`px-4 py-3 text-right font-mono font-bold ${colorClass(row.color)}`}
                    >
                      {row.live}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-muted-foreground">
                      {row.backtest}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            <p className="mt-4 text-[11px] text-muted-foreground leading-relaxed border-t border-border pt-3">
              Note: Live paper trading expected to underperform backtests. Targets: PF &ge; 2.0, Sharpe &ge; 1.5
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
