"use client";

import React, { useEffect, useState } from "react";
import type { LucideIcon } from "lucide-react";
import {
  TrendingUp,
  BarChart2,
  Percent,
  AlertTriangle,
  RefreshCw,
  Activity,
} from "lucide-react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchEngine } from "@/lib/api";


// ── Types ─────────────────────────────────────────────────────────────────────

interface TradeEntry {
  entry_date: string;
  exit_date: string;
  pnl: number;
}

interface FullMetrics {
  symbol?: string;
  start_date?: string;
  end_date?: string;
  total_trades?: number;
  winning_trades?: number;
  losing_trades?: number;
  win_rate?: number;
  profit_factor?: number;
  total_return_pct?: number;
  max_drawdown_pct?: number;
  sharpe_ratio?: number;
  sortino_ratio?: number;
}

interface BacktestResult {
  symbol: string;
  interval: string;
  start: string;
  end: string;
  n_trades?: number;
  win_rate?: number;
  profit_factor?: number;
  sharpe?: number;
  total_return?: number;
  trades_list?: TradeEntry[];
  full_metrics?: FullMetrics;
  top_params?: unknown[];
  _filename: string;
}

// ── Derived aggregate metrics ─────────────────────────────────────────────────

interface AggregateMetrics {
  profitFactor: number;
  sharpe: number;
  winRate: number;
  maxDrawdown: number;
  totalTrades: number;
  totalReturn: number;
  symbol: string;
  period: string;
}

function computeAggregate(results: BacktestResult[]): AggregateMetrics | null {
  const backtests = results.filter((r) => !r.top_params);
  if (!backtests.length) return null;

  // Find the "best" result by profit factor to display as the primary metrics
  const scored = backtests.map((r) => {
    const pf = r.profit_factor ?? r.full_metrics?.profit_factor ?? 0;
    const sharpe = r.sharpe ?? r.full_metrics?.sharpe_ratio ?? 0;
    const winRate = r.win_rate ?? r.full_metrics?.win_rate ?? 0;
    const totalReturn = r.total_return ?? r.full_metrics?.total_return_pct ?? 0;
    const maxDrawdown = r.full_metrics?.max_drawdown_pct ?? 0;
    const totalTrades = r.n_trades ?? r.full_metrics?.total_trades ?? 0;
    return { r, pf, sharpe, winRate, totalReturn, maxDrawdown, totalTrades };
  });

  // Sort by profit factor descending — display the best result
  scored.sort((a, b) => b.pf - a.pf);
  const best = scored[0];

  return {
    profitFactor: best.pf,
    sharpe: best.sharpe,
    winRate: best.winRate,
    maxDrawdown: Math.abs(best.maxDrawdown),
    totalTrades: best.totalTrades,
    totalReturn: best.totalReturn,
    symbol: best.r.symbol,
    period: `${best.r.start.slice(0, 10)} — ${best.r.end.slice(0, 10)}`,
  };
}

// ── Badge helpers ─────────────────────────────────────────────────────────────

type BV = "bull" | "bear" | "warn" | "info" | "neutral";

function pfVariant(v: number): BV {
  if (v >= 2.0) return "bull";
  if (v >= 1.5) return "warn";
  return "bear";
}

function sharpeVariant(v: number): BV {
  if (v >= 1.5) return "bull";
  if (v >= 1.0) return "warn";
  return "bear";
}

function winRateVariant(v: number): BV {
  // win_rate is 0–1 decimal
  const pct = v > 1 ? v : v * 100;
  if (pct >= 55) return "bull";
  if (pct >= 45) return "warn";
  return "bear";
}

function drawdownVariant(v: number): BV {
  // v is absolute drawdown as decimal (e.g. 0.12 = 12%)
  const pct = v > 1 ? v : v * 100;
  if (pct <= 10) return "bull";
  if (pct <= 20) return "warn";
  return "bear";
}

function overallVariant(m: AggregateMetrics): BV {
  const scores = [
    pfVariant(m.profitFactor),
    sharpeVariant(m.sharpe),
    winRateVariant(m.winRate),
    drawdownVariant(m.maxDrawdown),
  ];
  const bulls = scores.filter((s) => s === "bull").length;
  const bears = scores.filter((s) => s === "bear").length;
  if (bears >= 2) return "bear";
  if (bulls >= 3) return "bull";
  return "warn";
}

// ── Formatting helpers ────────────────────────────────────────────────────────

function fmtPct(v: number, decimals = 1): string {
  const pct = v > 1 ? v : v * 100;
  return `${pct.toFixed(decimals)}%`;
}

function fmtNum(v: number, decimals = 2): string {
  return v.toFixed(decimals);
}

// ── Metric Card ───────────────────────────────────────────────────────────────

function MetricTile({
  label,
  value,
  variant,
  icon: Icon,
  sub,
}: {
  label: string;
  value: string;
  variant: BV;
  icon: LucideIcon;
  sub?: string;
}) {
  const valueColors: Record<BV, string> = {
    bull: "text-green-400",
    bear: "text-red-400",
    warn: "text-yellow-400",
    info: "text-blue-400",
    neutral: "text-foreground",
  };

  return (
    <div className="rounded-lg border border-border bg-background p-4 flex flex-col gap-1.5">
      <div className="flex items-center gap-2">
        <Icon className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="text-xs text-muted-foreground uppercase tracking-wider">{label}</span>
      </div>
      <p className={`text-2xl font-bold font-mono tabular-nums ${valueColors[variant]}`}>{value}</p>
      {sub && <p className="text-xs text-muted-foreground">{sub}</p>}
    </div>
  );
}

// ── Secondary stat row ────────────────────────────────────────────────────────

function StatPill({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col items-center gap-0.5 px-3 py-2 rounded-lg bg-background border border-border min-w-[90px]">
      <span className="text-xs text-muted-foreground uppercase tracking-wider">{label}</span>
      <span className="text-sm font-bold font-mono tabular-nums text-foreground">{value}</span>
    </div>
  );
}

// ── Main Widget ───────────────────────────────────────────────────────────────

export function BacktestMetricsWidget() {
  const [metrics, setMetrics] = useState<AggregateMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  async function load() {
    try {
      const results = await fetchEngine<BacktestResult[]>("/backtest/results");
      const agg = computeAggregate(results);
      setMetrics(agg);
      setError(null);
      setLastUpdated(new Date());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load backtest results");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    const timer = setInterval(load, 60_000);
    return () => clearInterval(timer);
  }, []);

  const overall = metrics ? overallVariant(metrics) : "neutral";
  const overallLabel =
    overall === "bull" ? "STRONG" : overall === "bear" ? "WEAK" : "MODERATE";

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-3">
        <div className="flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-accent/10">
            <Activity className="h-4 w-4 text-accent" />
          </div>
          <CardTitle>Backtest Metrics</CardTitle>
        </div>
        <div className="flex items-center gap-2">
          {metrics && <Badge variant={overall}>{overallLabel}</Badge>}
          {loading && (
            <RefreshCw className="h-3.5 w-3.5 text-muted-foreground animate-spin" />
          )}
          {lastUpdated && !loading && (
            <span className="text-xs text-muted-foreground">
              {lastUpdated.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
            </span>
          )}
        </div>
      </CardHeader>

      <CardContent>
        {/* Error state */}
        {error && (
          <div className="flex items-start gap-3 rounded-lg border border-red-500/30 bg-red-500/10 p-4">
            <AlertTriangle className="h-4 w-4 text-red-400 mt-0.5 shrink-0" />
            <div>
              <p className="text-sm font-medium text-red-400">Engine offline</p>
              <p className="text-xs text-muted-foreground mt-0.5">
                Start the FastAPI engine to see backtest metrics.
              </p>
            </div>
          </div>
        )}

        {/* Loading skeleton */}
        {loading && !error && (
          <div className="grid grid-cols-2 gap-3">
            {[1, 2, 3, 4].map((i) => (
              <div
                key={i}
                className="h-24 rounded-lg border border-border bg-background animate-pulse"
              />
            ))}
          </div>
        )}

        {/* No data state */}
        {!loading && !error && !metrics && (
          <div className="rounded-lg border border-border bg-background p-8 text-center">
            <BarChart2 className="h-8 w-8 text-muted-foreground mx-auto mb-3" />
            <p className="text-sm font-medium text-muted-foreground">
              No backtest data available
            </p>
            <p className="text-xs text-muted-foreground mt-2 max-w-xs mx-auto">
              Run a backtest from the engine CLI to populate results here:
            </p>
            <code className="mt-2 inline-block text-xs bg-muted/30 border border-border rounded px-2 py-1 font-mono text-muted-foreground">
              POST /backtest/run &#123; symbol, start, end &#125;
            </code>
          </div>
        )}

        {/* Main metrics grid */}
        {!loading && !error && metrics && (
          <div className="space-y-4">
            {/* Symbol / context line */}
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <span className="font-mono font-semibold text-foreground">{metrics.symbol}</span>
              <span>·</span>
              <span>{metrics.period}</span>
              <span>·</span>
              <span>Best result by profit factor</span>
            </div>

            {/* 2×2 primary metric tiles */}
            <div className="grid grid-cols-2 gap-3">
              <MetricTile
                label="Profit Factor"
                value={fmtNum(metrics.profitFactor)}
                variant={pfVariant(metrics.profitFactor)}
                icon={TrendingUp}
                sub={
                  metrics.profitFactor >= 2.0
                    ? "≥2.0 — excellent"
                    : metrics.profitFactor >= 1.5
                    ? "1.5–2.0 — acceptable"
                    : "<1.5 — needs work"
                }
              />
              <MetricTile
                label="Sharpe Ratio"
                value={fmtNum(metrics.sharpe)}
                variant={sharpeVariant(metrics.sharpe)}
                icon={BarChart2}
                sub={
                  metrics.sharpe >= 1.5
                    ? "≥1.5 — strong risk-adj."
                    : metrics.sharpe >= 1.0
                    ? "1.0–1.5 — acceptable"
                    : "<1.0 — low risk-adj."
                }
              />
              <MetricTile
                label="Win Rate"
                value={fmtPct(metrics.winRate, 1)}
                variant={winRateVariant(metrics.winRate)}
                icon={Percent}
                sub={
                  (metrics.winRate > 1 ? metrics.winRate : metrics.winRate * 100) >= 55
                    ? "≥55% — above average"
                    : (metrics.winRate > 1 ? metrics.winRate : metrics.winRate * 100) >= 45
                    ? "45–55% — neutral"
                    : "<45% — below average"
                }
              />
              <MetricTile
                label="Max Drawdown"
                value={fmtPct(metrics.maxDrawdown, 1)}
                variant={drawdownVariant(metrics.maxDrawdown)}
                icon={AlertTriangle}
                sub={
                  (metrics.maxDrawdown > 1 ? metrics.maxDrawdown : metrics.maxDrawdown * 100) <=
                  10
                    ? "≤10% — low risk"
                    : (metrics.maxDrawdown > 1
                        ? metrics.maxDrawdown
                        : metrics.maxDrawdown * 100) <= 20
                    ? "10–20% — moderate"
                    : ">20% — high risk"
                }
              />
            </div>

            {/* Secondary row */}
            <div className="flex flex-wrap gap-2">
              <StatPill label="Total Trades" value={String(metrics.totalTrades)} />
              <StatPill
                label="Total Return"
                value={fmtPct(metrics.totalReturn, 1)}
              />
              <StatPill label="Period" value={metrics.period.slice(0, 10)} />
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
