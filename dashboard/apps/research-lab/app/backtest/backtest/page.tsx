"use client";

import React, { useMemo, useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import type { LucideIcon } from "lucide-react";
import { Activity, TrendingUp, Award, BarChart2, Percent } from "lucide-react";
import { fetchEngine } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { BacktestComparisonCard } from "@/components/BacktestComparisonCard";
import { StrategyParamsCard } from "@/components/StrategyParamsCard";
import { SignalAccuracyWidget } from "@/components/SignalAccuracyWidget";
import { LongShortBalanceWidget } from "@/components/LongShortBalanceWidget";
import { WidgetErrorBoundary } from "@/components/WidgetErrorBoundary";
import { DecisionBreakdownCard } from "@/components/DecisionBreakdownCard";
import { LightweightSeriesChart, type SeriesPoint } from "@/components/charts/LightweightSeriesChart";

// ── Types ───────────────────────────────────────────────────────────────────

interface TradeEntry {
  entry_date: string;
  exit_date: string;
  pnl: number;
}

interface FullMetrics {
  symbol?: string;
  start_date?: string;
  end_date?: string;
  initial_capital?: number;
  final_capital?: number;
  total_trades?: number;
  winning_trades?: number;
  losing_trades?: number;
  win_rate?: number;
  gross_profit?: number;
  gross_loss?: number;
  profit_factor?: number;
  total_pnl?: number;
  total_return_pct?: number;
  max_drawdown_pct?: number;
  max_drawdown_dollars?: number;
  avg_win?: number;
  avg_loss?: number;
  avg_win_loss_ratio?: number;
  sharpe_ratio?: number;
  sortino_ratio?: number;
  max_consecutive_losses?: number;
  max_consecutive_wins?: number;
  equity_curve?: number[];
  trades?: TradeEntry[];
}

interface TopParam {
  stc_oversold?: number;
  stc_overbought?: number;
  atr_stop_mult?: number;
  atr_target_mult?: number;
  regime_filter?: boolean;
  trades?: number;
  win_rate?: number;
  profit_factor?: number;
  sharpe?: number;
  total_return_pct?: number;
  max_dd_pct?: number;
  score?: number;
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
  // optimizer file shape
  top_params?: TopParam[];
  consensus?: Record<string, unknown>;
  _filename: string;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function fetcher<T>(url: string): Promise<T> {
  return fetchEngine<T>(url);
}

function pfColor(pf: number | undefined): string {
  if (pf === undefined) return "text-muted-foreground";
  if (pf >= 3.0) return "text-green-400";
  if (pf >= 2.0) return "text-yellow-400";
  return "text-red-400";
}

function pfBadgeVariant(pf: number | undefined): "bull" | "warn" | "bear" | "neutral" {
  if (pf === undefined) return "neutral";
  if (pf >= 3.0) return "bull";
  if (pf >= 2.0) return "warn";
  return "bear";
}

function pct(v: number | undefined, decimals = 1): string {
  if (v === undefined) return "—";
  return `${(v * 100).toFixed(decimals)}%`;
}

function fmt(v: number | undefined, decimals = 2): string {
  if (v === undefined) return "—";
  return v.toFixed(decimals);
}

function shortDate(iso: string | null | undefined): string {
  return iso != null ? iso.slice(0, 10) : "—";
}

// Build a downsample equity curve from the full_metrics or trades_list
function buildEquityCurve(result: BacktestResult): { idx: number; value: number }[] {
  const curve = result.full_metrics?.equity_curve;
  if (curve && curve.length > 1) {
    // Downsample to ~60 points for performance
    const step = Math.max(1, Math.floor(curve.length / 60));
    return curve
      .filter((_, i) => i % step === 0 || i === curve.length - 1)
      .map((v, i) => ({ idx: i, value: v }));
  }
  // Fallback: cumulative PnL from trades_list
  const trades = result.trades_list;
  if (trades && trades.length > 0) {
    const initial = 100000;
    let running = initial;
    const pts: { idx: number; value: number }[] = [{ idx: 0, value: initial }];
    trades.forEach((t, i) => {
      running += t.pnl;
      pts.push({ idx: i + 1, value: running });
    });
    return pts;
  }
  return [];
}

// ── Stat Card ────────────────────────────────────────────────────────────────

function StatCard({
  label,
  value,
  sub,
  icon: Icon,
  valueClass = "text-foreground",
}: {
  label: string;
  value: string;
  sub?: string;
  icon: LucideIcon;
  valueClass?: string;
}) {
  return (
    <div className="rounded-xl border border-border bg-card p-4 flex items-start gap-3">
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent/10">
        <Icon className="h-4 w-4 text-accent" />
      </div>
      <div className="min-w-0">
        <p className="text-xs text-muted-foreground uppercase tracking-wider">{label}</p>
        <p className={`text-xl font-bold font-mono tabular-nums mt-0.5 ${valueClass}`}>{value}</p>
        {sub && <p className="text-xs text-muted-foreground mt-0.5">{sub}</p>}
      </div>
    </div>
  );
}

// ── Equity Mini-Chart ─────────────────────────────────────────────────────────

function EquityMiniChart({ result }: { result: BacktestResult }) {
  const data = useMemo(() => buildEquityCurve(result), [result]);
  if (data.length < 2) {
    return (
      <div className="flex h-20 items-center justify-center text-xs text-muted-foreground">
        No curve data
      </div>
    );
  }

  const isPositive =
    (result.full_metrics?.total_return_pct ?? result.total_return ?? 0) >= 0;
  const strokeColor = isPositive ? "#22c55e" : "#ef4444";

  // Same equity values; idx → synthetic ascending daily timestamps so the
  // TradingView renderer accepts an index-based (non-dated) curve. Time axis
  // is hidden because the X axis is trade-index, not a calendar.
  const series: SeriesPoint[] = data.map((p) => ({
    time: (Date.UTC(2000, 0, 1) / 1000 + p.idx * 86400) as SeriesPoint["time"],
    value: p.value,
  }));

  return (
    <LightweightSeriesChart
      data={series}
      type="area"
      color={strokeColor}
      topColor={`${strokeColor}4D`}
      bottomColor={`${strokeColor}00`}
      height={80}
      valueFormat="dollar"
      hideTimeAxis
    />
  );
}

// ── Result Row Component ──────────────────────────────────────────────────────

function ResultRow({ result, isSelected, onSelect }: {
  result: BacktestResult;
  isSelected: boolean;
  onSelect: () => void;
}) {
  // Skip optimizer files (they have top_params, not trade metrics)
  if (result.top_params) return null;

  const pf = result.profit_factor ?? result.full_metrics?.profit_factor;
  const sharpe = result.sharpe ?? result.full_metrics?.sharpe_ratio;
  const winRate = result.win_rate ?? result.full_metrics?.win_rate;
  const totalReturn = result.total_return ?? result.full_metrics?.total_return_pct;
  const nTrades = result.n_trades ?? result.full_metrics?.total_trades;

  const returnClass =
    (totalReturn ?? 0) >= 0.05
      ? "text-green-400"
      : (totalReturn ?? 0) >= 0
      ? "text-green-300"
      : "text-red-400";

  return (
    <tr
      className={`border-b border-border transition-colors cursor-pointer hover:bg-white/[0.03] ${
        isSelected ? "bg-accent/5" : ""
      }`}
      onClick={onSelect}
    >
      <td className="px-4 py-3 font-mono font-bold text-sm text-foreground">
        {result.symbol}
      </td>
      <td className="px-4 py-3 text-xs text-muted-foreground font-mono">
        {result.interval}
      </td>
      <td className="px-4 py-3 text-xs text-muted-foreground">
        {shortDate(result.start)} — {shortDate(result.end)}
      </td>
      <td className="px-4 py-3 text-sm tabular-nums text-center text-muted-foreground">
        {nTrades ?? "—"}
      </td>
      <td className="px-4 py-3 text-sm tabular-nums text-center">
        {winRate !== undefined ? (
          <span className={winRate >= 0.5 ? "text-green-400" : winRate >= 0.3 ? "text-yellow-400" : "text-red-400"}>
            {pct(winRate, 0)}
          </span>
        ) : "—"}
      </td>
      <td className="px-4 py-3 text-sm tabular-nums text-center">
        {pf !== undefined ? (
          <span className={pfColor(pf)}>{fmt(pf)}</span>
        ) : "—"}
      </td>
      <td className="px-4 py-3 text-sm tabular-nums text-center text-muted-foreground">
        {fmt(sharpe)}
      </td>
      <td className="px-4 py-3 text-sm tabular-nums text-center">
        <span className={returnClass}>{pct(totalReturn)}</span>
      </td>
      <td className="px-4 py-3 text-center">
        <Badge variant={pfBadgeVariant(pf)}>
          {(pf ?? 0) >= 3.0 ? "STRONG" : (pf ?? 0) >= 2.0 ? "GOOD" : "WEAK"}
        </Badge>
      </td>
    </tr>
  );
}

// ── Detail Panel ──────────────────────────────────────────────────────────────

function DetailPanel({ result }: { result: BacktestResult }) {
  const m = result.full_metrics;
  if (!m) return null;

  const rows: { label: string; value: string }[] = [
    { label: "Initial Capital", value: m.initial_capital ? `$${m.initial_capital.toLocaleString()}` : "—" },
    { label: "Final Capital", value: m.final_capital ? `$${m.final_capital.toLocaleString(undefined, { maximumFractionDigits: 0 })}` : "—" },
    { label: "Total P&L", value: m.total_pnl ? `$${m.total_pnl.toLocaleString(undefined, { maximumFractionDigits: 0 })}` : "—" },
    { label: "Gross Profit", value: m.gross_profit ? `$${m.gross_profit.toLocaleString(undefined, { maximumFractionDigits: 0 })}` : "—" },
    { label: "Gross Loss", value: m.gross_loss ? `$${m.gross_loss.toLocaleString(undefined, { maximumFractionDigits: 0 })}` : "—" },
    { label: "Profit Factor", value: fmt(m.profit_factor) },
    { label: "Sharpe Ratio", value: fmt(m.sharpe_ratio) },
    { label: "Sortino Ratio", value: fmt(m.sortino_ratio) },
    { label: "Win Rate", value: pct(m.win_rate, 1) },
    { label: "Avg Win", value: m.avg_win ? `$${m.avg_win.toFixed(0)}` : "—" },
    { label: "Avg Loss", value: m.avg_loss ? `$${m.avg_loss.toFixed(0)}` : "—" },
    { label: "Win/Loss Ratio", value: fmt(m.avg_win_loss_ratio) },
    { label: "Max Drawdown %", value: pct(m.max_drawdown_pct) },
    { label: "Max Drawdown $", value: m.max_drawdown_dollars ? `$${m.max_drawdown_dollars.toFixed(0)}` : "—" },
    { label: "Max Consec. Losses", value: String(m.max_consecutive_losses ?? "—") },
    { label: "Max Consec. Wins", value: String(m.max_consecutive_wins ?? "—") },
    { label: "Winning Trades", value: String(m.winning_trades ?? "—") },
    { label: "Losing Trades", value: String(m.losing_trades ?? "—") },
  ];

  return (
    <div className="mt-4 rounded-xl border border-border bg-card p-5">
      <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-4">
        {result.symbol} {result.interval} — Full Metrics
      </p>

      {/* Equity Curve */}
      <div className="mb-5">
        <p className="text-xs text-muted-foreground mb-2">Equity Curve</p>
        <EquityMiniChart result={result} />
      </div>

      {/* Metrics grid */}
      <div className="grid grid-cols-2 gap-x-8 gap-y-1.5">
        {rows.map(({ label, value }) => (
          <div key={label} className="flex justify-between text-xs border-b border-border/40 pb-1">
            <span className="text-muted-foreground">{label}</span>
            <span className="tabular-nums font-medium text-foreground">{value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Optimizer Panel ───────────────────────────────────────────────────────────

function OptimizerPanel({ results }: { results: BacktestResult[] }) {
  const optFiles = results.filter((r) => r.top_params);
  if (optFiles.length === 0) return null;

  // Find daily optimal (from MEMORY: STC_OS=23, OB=83, stop=0.70 ATR)
  const dailyOptimal = {
    stc_oversold: 23,
    stc_overbought: 83,
    atr_stop_mult: 0.70,
    atr_target_mult: "—",
    regime_filter: "—",
  };

  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-4">
        Parameter Optimization — SPY
      </p>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* 1h Optimal */}
        {optFiles.map((opt) => {
          const best = opt.consensus ?? opt.top_params?.[0];
          if (!best) return null;
          return (
            <div key={opt._filename} className="rounded-lg border border-border bg-background p-4">
              <p className="text-xs font-semibold text-accent mb-3">
                {opt.symbol} {opt.interval} — 1H Optimal ({opt.start} → {opt.end})
              </p>
              <ParamTable params={best as Record<string, unknown>} />
              {opt.top_params && opt.top_params[0] && (
                <div className="mt-3 pt-3 border-t border-border/50 grid grid-cols-3 gap-2">
                  <Metric label="Best PF" value={fmt(opt.top_params[0].profit_factor)} color="text-green-400" />
                  <Metric label="Best Sharpe" value={fmt(opt.top_params[0].sharpe)} color="text-accent" />
                  <Metric label="Win Rate" value={pct(opt.top_params[0].win_rate, 0)} color="text-foreground" />
                </div>
              )}
            </div>
          );
        })}

        {/* Daily Optimal (from backtest memory) */}
        <div className="rounded-lg border border-border bg-background p-4">
          <p className="text-xs font-semibold text-yellow-400 mb-2">
            SPY 1D — Daily Optimal (from optimizer run)
          </p>
          <div className="mb-3 flex items-center gap-2 rounded px-2 py-1 font-mono text-[10px] uppercase tracking-wider"
            style={{ backgroundColor: "#2a1f0a", border: "1px solid #6b5414", color: "#e0b94a" }}>
            <span className="font-bold">Frozen snapshot</span>
            <span style={{ color: "#9a8030" }}>optimizer result — not live</span>
          </div>
          <ParamTable params={dailyOptimal as Record<string, unknown>} />
          <div className="mt-3 pt-3 border-t border-border/50 grid grid-cols-3 gap-2">
            <Metric label="PF" value="3.56" color="text-green-400" />
            <Metric label="Sharpe" value="3.69" color="text-accent" />
            <Metric label="Win Rate" value="10%" color="text-foreground" />
          </div>
        </div>
      </div>
    </div>
  );
}

function ParamTable({ params }: { params: Record<string, unknown> }) {
  const labels: Record<string, string> = {
    stc_oversold: "STC Oversold",
    stc_overbought: "STC Overbought",
    atr_stop_mult: "ATR Stop Mult",
    atr_target_mult: "ATR Target Mult",
    regime_filter: "Regime Filter",
  };

  return (
    <div className="space-y-1.5">
      {Object.entries(params).map(([k, v]) => (
        <div key={k} className="flex justify-between text-xs">
          <span className="text-muted-foreground">{labels[k] ?? k}</span>
          <span className="font-mono font-medium text-foreground">
            {typeof v === "boolean" ? (v ? "ON" : "OFF") : String(v ?? "—")}
          </span>
        </div>
      ))}
    </div>
  );
}

function Metric({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div className="text-center">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={`text-sm font-bold font-mono tabular-nums ${color}`}>{value}</p>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function BacktestPage() {
  const { data: results, isLoading, error } = useSWR<BacktestResult[]>(
    "/backtest/results",
    fetcher,
    { refreshInterval: 60_000 }
  );

  const [selectedFile, setSelectedFile] = useState<string | null>(null);

  // Filter to backtest results (not optimizer files)
  const backtestResults = useMemo(
    () => (results ?? []).filter((r) => !r.top_params),
    [results]
  );

  // Summary stats across all backtest results
  const summaryStats = useMemo(() => {
    if (!backtestResults.length) return null;

    const pfs = backtestResults.map((r) => r.profit_factor ?? r.full_metrics?.profit_factor ?? 0);
    const sharpes = backtestResults.map((r) => r.sharpe ?? r.full_metrics?.sharpe_ratio ?? 0);
    const winRates = backtestResults.map((r) => r.win_rate ?? r.full_metrics?.win_rate ?? 0);

    return {
      total: backtestResults.length,
      bestPF: Math.max(...pfs),
      bestSharpe: Math.max(...sharpes),
      bestWinRate: Math.max(...winRates),
    };
  }, [backtestResults]);

  const selectedResult = useMemo(
    () => results?.find((r) => r._filename === selectedFile) ?? null,
    [results, selectedFile]
  );

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="sticky top-0 z-50 border-b border-border bg-background/95 backdrop-blur">
        <div className="mx-auto max-w-[1920px] 2xl:max-w-[2400px] flex items-center gap-3 px-6 py-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent/10">
            <Activity className="h-5 w-5 text-accent" />
          </div>
          <div>
            <h1 className="font-bold text-foreground tracking-tight">JARVIS TRADER — Backtest Results</h1>
            <p className="text-xs text-muted-foreground">Historical strategy performance</p>
          </div>
          <nav className="hidden lg:flex items-center gap-4 ml-6">
            <Link href="/" className="text-xs text-muted-foreground hover:text-foreground transition-colors">
              Dashboard
            </Link>
            <Link href="/analysis" className="text-xs text-muted-foreground hover:text-foreground transition-colors">
              Analysis
            </Link>
            <Link href="/backtest" className="text-xs text-accent transition-colors font-medium">
              Backtest
            </Link>
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-[1920px] 2xl:max-w-[2400px] px-6 py-6 space-y-6">
        {/* Strategy Parameters reference card */}
        <StrategyParamsCard />

        {/* Loading / Error */}
        {isLoading && (
          <div className="flex items-center gap-2 text-xs text-muted-foreground animate-pulse p-4">
            <Activity className="h-3.5 w-3.5" />
            Loading backtest results from engine…
          </div>
        )}
        {error && (
          <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-400">
            Engine offline or no backtest results found. Start the FastAPI engine and verify the dashboard proxy is configured.
          </div>
        )}

        {/* Live vs. Backtest Comparison */}
        <BacktestComparisonCard />

        {/* Signal Accuracy by direction */}
        <WidgetErrorBoundary name="Signal Accuracy">
          <SignalAccuracyWidget />
        </WidgetErrorBoundary>

        {/* Long vs Short balance vs backtest benchmark */}
        <WidgetErrorBoundary name="Long/Short Balance">
          <LongShortBalanceWidget />
        </WidgetErrorBoundary>

        {/* Decision breakdown from pipeline history */}
        <DecisionBreakdownCard />

        {/* Summary stat cards */}
        {summaryStats && (
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <StatCard
              label="Total Backtests"
              value={String(summaryStats.total)}
              sub="result files loaded"
              icon={BarChart2}
            />
            <StatCard
              label="Best Profit Factor"
              value={summaryStats.bestPF.toFixed(2)}
              sub="higher is better (≥3 = strong)"
              icon={TrendingUp}
              valueClass={pfColor(summaryStats.bestPF)}
            />
            <StatCard
              label="Best Sharpe Ratio"
              value={summaryStats.bestSharpe.toFixed(2)}
              sub="risk-adjusted return"
              icon={Award}
              valueClass="text-accent"
            />
            <StatCard
              label="Best Win Rate"
              value={pct(summaryStats.bestWinRate, 0)}
              sub="across all backtests"
              icon={Percent}
            />
          </div>
        )}

        {/* Results table */}
        {backtestResults.length > 0 && (
          <div className="rounded-xl border border-border bg-card overflow-hidden">
            <div className="px-5 py-3.5 border-b border-border flex items-center justify-between">
              <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Backtest Results
              </p>
              <p className="text-xs text-muted-foreground">
                {backtestResults.length} result{backtestResults.length !== 1 ? "s" : ""} · click row to expand
              </p>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-left">
                <thead>
                  <tr className="border-b border-border bg-black/20">
                    {["Symbol", "Interval", "Period", "Trades", "Win%", "Prof. Factor", "Sharpe", "Return", "Status"].map(
                      (h) => (
                        <th
                          key={h}
                          className="px-4 py-2.5 text-xs font-medium uppercase tracking-wider text-muted-foreground text-left"
                        >
                          {h}
                        </th>
                      )
                    )}
                  </tr>
                </thead>
                <tbody>
                  {backtestResults.map((r) => (
                    <ResultRow
                      key={r._filename}
                      result={r}
                      isSelected={selectedFile === r._filename}
                      onSelect={() =>
                        setSelectedFile(selectedFile === r._filename ? null : r._filename)
                      }
                    />
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Detail panel for selected row */}
        {selectedResult && !selectedResult.top_params && (
          <DetailPanel result={selectedResult} />
        )}

        {/* Optimizer / Parameters section */}
        {(results?.length ?? 0) === 0 && (
          <div className="text-center text-muted-foreground py-12">
            <p>No backtest results yet. Run a backtest above to see results.</p>
          </div>
        )}
      </main>
    </div>
  );
}
