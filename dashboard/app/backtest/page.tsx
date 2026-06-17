"use client";

import React, { useMemo, useState, useEffect, useCallback } from "react";
import Link from "next/link";
import useSWR from "swr";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import type { LucideIcon } from "lucide-react";
import { Activity, TrendingUp, Award, BarChart2, Percent, AlertCircle } from "lucide-react";
import { fetchEngine } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { GitCompare } from "lucide-react";
import { StrategyParamsCard } from "@/components/StrategyParamsCard";

// ── Local fetch with 10s timeout (avoids 30s+ hang from fetchEngine's retry cycle) ──
const PANEL_TIMEOUT_MS = 10_000;

async function fetchPanel<T>(path: string): Promise<T> {
  const controller = new AbortController();
  const tid = setTimeout(() => controller.abort(), PANEL_TIMEOUT_MS);
  try {
    const res = await fetch(`/api/engine${path}`, {
      cache: "no-store",
      signal: controller.signal,
      headers: {
        "X-API-Key": process.env.NEXT_PUBLIC_ENGINE_API_KEY ?? "jarvis-dev-key-change-me",
      },
    });
    if (!res.ok) throw new Error(`${res.status} ${path}`);
    return res.json() as Promise<T>;
  } finally {
    clearTimeout(tid);
  }
}

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
  const fillColor = isPositive ? "#22c55e" : "#ef4444";

  return (
    <ResponsiveContainer width="100%" height={80}>
      <AreaChart data={data} margin={{ top: 4, right: 2, bottom: 0, left: 2 }}>
        <defs>
          <linearGradient id={`grad-${result._filename}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor={fillColor} stopOpacity={0.3} />
            <stop offset="95%" stopColor={fillColor} stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
        <XAxis dataKey="idx" hide />
        <YAxis domain={["auto", "auto"]} hide />
        <Tooltip
          contentStyle={{
            background: "hsl(var(--card))",
            border: "1px solid hsl(var(--border))",
            borderRadius: "8px",
            fontSize: "11px",
            color: "hsl(var(--foreground))",
          }}
          formatter={(v: number) => [`$${v.toLocaleString(undefined, { maximumFractionDigits: 0 })}`, "Equity"]}
          labelFormatter={() => ""}
        />
        <Area
          type="monotone"
          dataKey="value"
          stroke={strokeColor}
          strokeWidth={1.5}
          fill={`url(#grad-${result._filename})`}
          dot={false}
          isAnimationActive={false}
        />
      </AreaChart>
    </ResponsiveContainer>
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

// ── Inline panel: Backtest vs Paper Trading ───────────────────────────────────

interface PaperTrading {
  profit_factor: number;
  sharpe_ratio: number;
  win_rate: number;
  total_trades: number;
  total_pnl: number;
}
interface Backtested { profit_factor: number; sharpe_ratio: number; win_rate: number; }
interface ValidationThresholds { min_profit_factor: number; min_sharpe: number; min_win_rate: number; min_trades: number; }
interface CompareResponse { paper_trading: PaperTrading; backtested: Backtested; degradation_factor: number; validation_thresholds: ValidationThresholds; }

function fmtN(v: number | null | undefined, d = 2): string { return v != null ? v.toFixed(d) : "—"; }

function BacktestComparisonCard() {
  const [data, setData] = useState<CompareResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [errMsg, setErrMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setErrMsg(null);
    try {
      const json = await fetchPanel<CompareResponse>("/analytics/performance/compare");
      setData(json);
    } catch (e) {
      setErrMsg(e instanceof Error ? e.message : "Unavailable");
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); const iv = setInterval(load, 120_000); return () => clearInterval(iv); }, [load]);

  const paper = data?.paper_trading;
  const thresholds = data?.validation_thresholds;
  const pfPass = paper != null && thresholds != null && paper.profit_factor >= thresholds.min_profit_factor;
  const sharpePass = paper != null && thresholds != null && paper.sharpe_ratio >= thresholds.min_sharpe;
  const winRatePass = paper != null && thresholds != null && paper.win_rate >= thresholds.min_win_rate;
  const tradesPass = paper != null && thresholds != null && paper.total_trades >= thresholds.min_trades;
  const allPass = pfPass && sharpePass && winRatePass && tradesPass;
  const degradationPct = data && Number.isFinite(data.degradation_factor) ? (data.degradation_factor * 100).toFixed(1) : null;

  type MetricRowDef = { label: string; paperValue: string; targetValue: string; badgeVariant: "bull" | "bear" | "warn" | "info" | "neutral"; badgeLabel: string; };
  const metricRows: MetricRowDef[] = paper != null && thresholds != null ? [
    { label: "Profit Factor", paperValue: fmtN(paper.profit_factor), targetValue: `≥ ${fmtN(thresholds.min_profit_factor)}`, badgeVariant: pfPass ? "bull" : "bear", badgeLabel: pfPass ? "PASS" : "FAIL" },
    { label: "Sharpe Ratio", paperValue: fmtN(paper.sharpe_ratio), targetValue: `≥ ${fmtN(thresholds.min_sharpe)}`, badgeVariant: sharpePass ? "bull" : "bear", badgeLabel: sharpePass ? "PASS" : "FAIL" },
    { label: "Win Rate %", paperValue: `${fmtN(paper.win_rate, 1)}%`, targetValue: `≥ ${fmtN(thresholds.min_win_rate, 1)}%`, badgeVariant: winRatePass ? "bull" : "bear", badgeLabel: winRatePass ? "PASS" : "FAIL" },
    { label: "Total Trades", paperValue: String(paper.total_trades ?? "—"), targetValue: `≥ ${thresholds.min_trades ?? "—"}`, badgeVariant: tradesPass ? "bull" : "warn", badgeLabel: tradesPass ? "PASS" : "IN PROGRESS" },
  ] : [];

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2 text-sm">
            <GitCompare className="h-4 w-4" />
            Backtest vs. Paper Trading
          </CardTitle>
          {!loading && data && <Badge variant={allPass ? "bull" : "neutral"}>{allPass ? "VALIDATION PASS" : "NOT YET"}</Badge>}
        </div>
      </CardHeader>
      <CardContent>
        {errMsg && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground mb-3 rounded-lg border border-border bg-muted px-3 py-2">
            <AlertCircle className="h-4 w-4 shrink-0" />
            <span>Backtest vs paper unavailable — <code className="text-xs">/analytics/performance/compare</code>: {errMsg}</span>
          </div>
        )}
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border">
                <th className="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground">Metric</th>
                <th className="px-4 py-2 text-center text-xs font-medium uppercase tracking-wider text-muted-foreground">Paper Trading</th>
                <th className="px-4 py-2 text-center text-xs font-medium uppercase tracking-wider text-muted-foreground">Target</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <>{[0,1,2,3].map(i => (
                  <tr key={i} className="border-b border-border">
                    {[0,1,2].map(j => <td key={j} className="px-4 py-3"><div className="h-4 rounded bg-muted animate-pulse" /></td>)}
                  </tr>
                ))}</>
              ) : !data ? (
                <tr><td colSpan={3} className="px-4 py-6 text-center text-sm text-muted-foreground">No comparison data available — engine may be offline or endpoint missing</td></tr>
              ) : (
                metricRows.map(row => (
                  <tr key={row.label} className="border-b border-border last:border-0">
                    <td className="px-4 py-3 text-muted-foreground">{row.label}</td>
                    <td className="px-4 py-3 text-center font-mono font-medium tabular-nums text-foreground">{row.paperValue}</td>
                    <td className="px-4 py-3 text-center">
                      <div className="flex flex-col items-center gap-1">
                        <span className="font-mono text-xs text-muted-foreground">{row.targetValue}</span>
                        <Badge variant={row.badgeVariant}>{row.badgeLabel}</Badge>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
        {!loading && data && (
          <div className="mt-3 pt-3 border-t border-border flex items-center justify-between gap-2 flex-wrap">
            <p className="text-xs text-muted-foreground">Degradation factor: <span className="font-mono font-medium text-foreground">{degradationPct ?? "—"}{degradationPct != null ? "%" : ""}</span> of backtest performance achieved in live paper trading</p>
            <Badge variant={allPass ? "bull" : "neutral"}>{allPass ? "VALIDATION PASS" : "NOT YET"}</Badge>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ── Inline panel: Signal Accuracy / Long vs Short ─────────────────────────────

interface ClosedTradeLocal {
  id: string; symbol: string; action: string; entry_price: number; exit_price: number;
  quantity: number; entry_time: string; exit_time: string; pnl: number; commission: number; status: string;
}

function calcStats(trades: ClosedTradeLocal[]) {
  const wins = trades.filter(t => t.pnl > 0);
  const losses = trades.filter(t => t.pnl <= 0);
  const total = trades.length;
  const winRate = total > 0 ? (wins.length / total) * 100 : 0;
  const avgWin = wins.length > 0 ? wins.reduce((s, t) => s + t.pnl, 0) / wins.length : 0;
  const avgLoss = losses.length > 0 ? losses.reduce((s, t) => s + t.pnl, 0) / losses.length : 0;
  return { total, wins: wins.length, losses: losses.length, winRate, avgWin, avgLoss };
}

function useTrades() {
  const [trades, setTrades] = useState<ClosedTradeLocal[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const raw: unknown = await fetchPanel("/portfolio/history/trades?limit=500&status=CLOSED");
      const rows: ClosedTradeLocal[] = Array.isArray(raw) ? raw as ClosedTradeLocal[] : ((raw as { trades?: ClosedTradeLocal[] }).trades ?? []);
      setTrades(rows.filter(t => t.status === "CLOSED" && t.pnl != null));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unavailable");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); const iv = setInterval(load, 300_000); return () => clearInterval(iv); }, [load]);
  return { trades, loading, error };
}

function SignalAccuracyWidget() {
  const { trades, loading, error } = useTrades();
  const longTrades = trades.filter(t => t.action === "BUY" || t.action === "LONG");
  const shortTrades = trades.filter(t => t.action === "SELL" || t.action === "SHORT");
  const long = calcStats(longTrades);
  const short = calcStats(shortTrades);
  const totalAll = long.total + short.total;
  const overallWinRate = totalAll > 0 ? ((long.wins + short.wins) / totalAll) * 100 : 0;
  const overallVariant: "bull" | "warn" | "bear" = overallWinRate >= 55 ? "bull" : overallWinRate >= 45 ? "warn" : "bear";

  return (
    <Card>
      <CardHeader className="flex flex-row justify-between items-center">
        <CardTitle>Signal Accuracy</CardTitle>
        <Badge variant={overallVariant}>{overallWinRate.toFixed(1)}% Overall</Badge>
      </CardHeader>
      <CardContent>
        {loading ? (
          <div className="h-4 rounded bg-muted animate-pulse my-6" />
        ) : error ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground rounded-lg border border-border bg-muted px-3 py-4">
            <AlertCircle className="h-4 w-4 shrink-0" />
            <span>Trade data unavailable — <code className="text-xs">/portfolio/history/trades</code>: {error}</span>
          </div>
        ) : totalAll < 5 ? (
          <p className="text-sm text-muted-foreground text-center py-6">Need more trade data (min 5 trades)</p>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-4">
              <div className="rounded bg-muted p-3">
                <div className="flex justify-between items-center mb-2"><Badge variant="bull">LONG</Badge><span className="text-xs text-muted-foreground">{long.total} trades</span></div>
                <div className="space-y-1 text-xs">
                  <div className="flex justify-between"><span className="text-muted-foreground">Win Rate</span><span className={`font-mono ${long.winRate >= 55 ? "text-green-400" : long.winRate < 45 ? "text-red-400" : ""}`}>{long.winRate.toFixed(1)}%</span></div>
                  <div className="flex justify-between"><span className="text-muted-foreground">Wins / Losses</span><span className="font-mono">{long.wins} / {long.losses}</span></div>
                  <div className="flex justify-between"><span className="text-muted-foreground">Avg Win</span><span className="font-mono text-green-400">+${long.avgWin.toFixed(2)}</span></div>
                  <div className="flex justify-between"><span className="text-muted-foreground">Avg Loss</span><span className="font-mono text-red-400">-${Math.abs(long.avgLoss).toFixed(2)}</span></div>
                </div>
              </div>
              <div className="rounded bg-muted p-3">
                <div className="flex justify-between items-center mb-2"><Badge variant="bear">SHORT</Badge><span className="text-xs text-muted-foreground">{short.total} trades</span></div>
                <div className="space-y-1 text-xs">
                  <div className="flex justify-between"><span className="text-muted-foreground">Win Rate</span><span className={`font-mono ${short.winRate >= 55 ? "text-green-400" : short.winRate < 45 ? "text-red-400" : ""}`}>{short.total > 0 ? short.winRate.toFixed(1) + "%" : "N/A"}</span></div>
                  <div className="flex justify-between"><span className="text-muted-foreground">Wins / Losses</span><span className="font-mono">{short.wins} / {short.losses}</span></div>
                  <div className="flex justify-between"><span className="text-muted-foreground">Avg Win</span><span className="font-mono text-green-400">{short.total > 0 ? `+$${short.avgWin.toFixed(2)}` : "—"}</span></div>
                  <div className="flex justify-between"><span className="text-muted-foreground">Avg Loss</span><span className="font-mono text-red-400">{short.total > 0 ? `-$${Math.abs(short.avgLoss).toFixed(2)}` : "—"}</span></div>
                </div>
              </div>
            </div>
            <p className="text-xs text-muted-foreground mt-3">From last 500 closed trades · Refreshes every 5m</p>
          </>
        )}
      </CardContent>
    </Card>
  );
}

// ── Inline panel: Long vs Short Balance ───────────────────────────────────────

const BENCHMARK_LONG_PCT = 58;
const BENCHMARK_SHORT_PCT = 42;

function fmtPnl(val: number): string { const s = val >= 0 ? "+" : "-"; return `${s}$${Math.abs(val).toFixed(2)}`; }
function pnlClass(val: number): string { return val >= 0 ? "text-green-400" : "text-red-400"; }

function calcGroupStats(trades: ClosedTradeLocal[]) {
  const count = trades.length;
  if (count === 0) return { count: 0, win_rate: 0, avg_pnl: 0, total_pnl: 0 };
  const wins = trades.filter(t => t.pnl > 0).length;
  const total_pnl = trades.reduce((s, t) => s + t.pnl, 0);
  return { count, win_rate: (wins / count) * 100, avg_pnl: total_pnl / count, total_pnl };
}

function LongShortBalanceWidget() {
  const { trades, loading, error } = useTrades();
  const longTrades = trades.filter(t => t.action === "BUY" || t.action === "LONG" || t.action === "BUY_LONG");
  const shortTrades = trades.filter(t => t.action === "SELL" || t.action === "SHORT" || t.action === "SELL_SHORT");
  const total = trades.length;
  const longPct = total > 0 ? (longTrades.length / total) * 100 : 0;
  const shortPct = total > 0 ? (shortTrades.length / total) * 100 : 0;
  const longStats = calcGroupStats(longTrades);
  const shortStats = calcGroupStats(shortTrades);
  const badgeVariant: "bull" | "warn" | "neutral" = total === 0 ? "neutral" : (longPct >= 48 && longPct <= 68) ? "bull" : (longPct > 80 || shortPct > 80) ? "warn" : "neutral";
  const badgeLabel = badgeVariant === "bull" ? "Balanced" : badgeVariant === "warn" ? "Skewed" : "Neutral";

  const tableRows = [
    { label: "Count", longVal: String(longStats.count), shortVal: String(shortStats.count) },
    { label: "Win Rate", longVal: longStats.count > 0 ? `${longStats.win_rate.toFixed(1)}%` : "—", shortVal: shortStats.count > 0 ? `${shortStats.win_rate.toFixed(1)}%` : "—", longClass: longStats.count > 0 ? (longStats.win_rate >= 55 ? "text-green-400" : longStats.win_rate < 45 ? "text-red-400" : "") : "", shortClass: shortStats.count > 0 ? (shortStats.win_rate >= 55 ? "text-green-400" : shortStats.win_rate < 45 ? "text-red-400" : "") : "" },
    { label: "Avg P&L", longVal: longStats.count > 0 ? fmtPnl(longStats.avg_pnl) : "—", shortVal: shortStats.count > 0 ? fmtPnl(shortStats.avg_pnl) : "—", longClass: longStats.count > 0 ? pnlClass(longStats.avg_pnl) : "", shortClass: shortStats.count > 0 ? pnlClass(shortStats.avg_pnl) : "" },
    { label: "Total P&L", longVal: longStats.count > 0 ? fmtPnl(longStats.total_pnl) : "—", shortVal: shortStats.count > 0 ? fmtPnl(shortStats.total_pnl) : "—", longClass: longStats.count > 0 ? pnlClass(longStats.total_pnl) : "", shortClass: shortStats.count > 0 ? pnlClass(shortStats.total_pnl) : "" },
  ];

  return (
    <Card>
      <CardHeader className="flex flex-row justify-between items-center">
        <div>
          <CardTitle>Long vs Short Balance</CardTitle>
          <p className="text-xs text-muted-foreground mt-0.5">Paper vs Backtest Benchmark</p>
        </div>
        <Badge variant={badgeVariant}>{badgeLabel}</Badge>
      </CardHeader>
      <CardContent>
        {loading ? (
          <div className="h-4 rounded bg-muted animate-pulse my-6" />
        ) : error ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground rounded-lg border border-border bg-muted px-3 py-4">
            <AlertCircle className="h-4 w-4 shrink-0" />
            <span>Trade data unavailable — <code className="text-xs">/portfolio/history/trades</code>: {error}</span>
          </div>
        ) : total === 0 ? (
          <p className="text-sm text-muted-foreground text-center py-6">No closed trades found yet.</p>
        ) : (
          <>
            <div className="mb-4">
              <div className="flex rounded-full overflow-hidden h-6 w-full">
                <div className="flex items-center justify-center bg-green-500/80 text-xs font-bold text-white transition-all duration-500" style={{ width: `${longPct}%` }}>{longPct >= 12 && `${longPct.toFixed(1)}%`}</div>
                <div className="flex items-center justify-center bg-red-500/80 text-xs font-bold text-white transition-all duration-500" style={{ width: `${shortPct}%` }}>{shortPct >= 12 && `${shortPct.toFixed(1)}%`}</div>
              </div>
              <div className="flex justify-between mt-1 text-xs text-muted-foreground">
                <span className="text-green-400 font-medium">LONG {longPct.toFixed(1)}%</span>
                <span className="text-red-400 font-medium">SHORT {shortPct.toFixed(1)}%</span>
              </div>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead><tr className="border-b border-border"><th className="py-1.5 text-left font-medium text-muted-foreground w-1/3" /><th className="py-1.5 text-center font-semibold text-green-400">LONG</th><th className="py-1.5 text-center font-semibold text-red-400">SHORT</th></tr></thead>
                <tbody>
                  {tableRows.map(row => (
                    <tr key={row.label} className="border-b border-border/40 last:border-0">
                      <td className="py-1.5 text-muted-foreground">{row.label}</td>
                      <td className={`py-1.5 text-center font-mono tabular-nums ${row.longClass ?? ""}`}>{row.longVal}</td>
                      <td className={`py-1.5 text-center font-mono tabular-nums ${row.shortClass ?? ""}`}>{row.shortVal}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="mt-3 pt-3 border-t border-border/50 flex items-center justify-between text-xs">
              <span className="text-muted-foreground">Backtest Benchmark</span>
              <span className="font-mono text-muted-foreground"><span className="text-green-400/80">{BENCHMARK_LONG_PCT}% Long</span>{" / "}<span className="text-red-400/80">{BENCHMARK_SHORT_PCT}% Short</span></span>
            </div>
            <p className="text-xs text-muted-foreground mt-2">From last 500 closed trades · Refreshes every 5m</p>
          </>
        )}
      </CardContent>
    </Card>
  );
}

// ── Inline panel: Pipeline Decision Breakdown ─────────────────────────────────

interface DecisionRecord { action?: string; confidence?: number | null; }

function countDecisions(records: DecisionRecord[]) {
  let longCount = 0, shortCount = 0, holdCount = 0, exitCount = 0, otherCount = 0;
  const confidenceValues: number[] = [];
  for (const rec of records) {
    const a = (rec.action ?? "").toUpperCase().trim();
    if (a === "BUY_LONG" || a === "BUY") longCount++;
    else if (a === "SELL_SHORT" || a === "SELL") shortCount++;
    else if (a === "HOLD") holdCount++;
    else if (a === "EXIT_LONG" || a === "EXIT_SHORT" || a === "CLOSE") exitCount++;
    else otherCount++;
    if (rec.confidence != null) confidenceValues.push(rec.confidence);
  }
  const totalDecisions = longCount + shortCount + holdCount + exitCount + otherCount;
  const signalRate = totalDecisions > 0 ? ((longCount + shortCount) / totalDecisions) * 100 : 0;
  const holdRate = totalDecisions > 0 ? (holdCount / totalDecisions) * 100 : 0;
  const avgConfidence = confidenceValues.length > 0 ? confidenceValues.reduce((a, b) => a + b, 0) / confidenceValues.length : null;
  return { longCount, shortCount, holdCount, exitCount, otherCount, totalDecisions, signalRate, holdRate, avgConfidence };
}

function DecisionBreakdownCard() {
  const [records, setRecords] = useState<DecisionRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [errMsg, setErrMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const payload = await fetchPanel<unknown>("/portfolio/history/decisions?limit=500");
      const list: DecisionRecord[] = Array.isArray(payload) ? payload as DecisionRecord[] : ((payload as { decisions?: DecisionRecord[] }).decisions ?? []);
      setRecords(list);
      setErrMsg(null);
    } catch (e) {
      setErrMsg(e instanceof Error ? e.message : "Unavailable");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); const iv = setInterval(load, 300_000); return () => clearInterval(iv); }, [load]);

  const { longCount, shortCount, holdCount, exitCount, otherCount, totalDecisions, signalRate, holdRate, avgConfidence } = countDecisions(records);
  const badgeVariant: "bull" | "info" | "neutral" = signalRate >= 15 ? "bull" : signalRate >= 5 ? "info" : "neutral";
  const badgeLabel = badgeVariant === "bull" ? "Active" : badgeVariant === "info" ? "Moderate" : "Conservative";

  const segments = [
    { label: "BUY", count: longCount, colorClass: "bg-green-500/80", textColor: "text-green-400" },
    { label: "SELL", count: shortCount, colorClass: "bg-red-500/80", textColor: "text-red-400" },
    { label: "HOLD", count: holdCount, colorClass: "bg-zinc-500/70", textColor: "text-zinc-400" },
    { label: "EXIT", count: exitCount, colorClass: "bg-blue-500/80", textColor: "text-blue-400" },
    { label: "OTHER", count: otherCount, colorClass: "bg-zinc-700/70", textColor: "text-muted-foreground" },
  ];

  const statsRows = [
    { label: "Signal Rate", value: totalDecisions > 0 ? `${signalRate.toFixed(1)}%` : "—", valueClass: signalRate >= 15 ? "text-green-400" : signalRate >= 5 ? "text-blue-400" : "text-muted-foreground" },
    { label: "Hold Rate", value: totalDecisions > 0 ? `${holdRate.toFixed(1)}%` : "—" },
    { label: "Avg Confidence", value: avgConfidence != null ? `${(avgConfidence * 100).toFixed(1)}%` : "—" },
    { label: "Exits", value: totalDecisions > 0 ? String(exitCount) : "—" },
  ];

  return (
    <Card>
      <CardHeader className="flex flex-row justify-between items-center">
        <div>
          <CardTitle>Pipeline Decision Breakdown</CardTitle>
          <p className="text-xs text-muted-foreground mt-0.5">{totalDecisions > 0 ? `${totalDecisions.toLocaleString()} total decisions analyzed` : "No decisions loaded"}</p>
        </div>
        <Badge variant={badgeVariant}>{badgeLabel}</Badge>
      </CardHeader>
      <CardContent>
        {loading ? (
          <div className="h-4 rounded bg-muted animate-pulse my-6" />
        ) : errMsg ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground rounded-lg border border-border bg-muted px-3 py-4">
            <AlertCircle className="h-4 w-4 shrink-0" />
            <span>Decision history unavailable — <code className="text-xs">/portfolio/history/decisions</code>: {errMsg}</span>
          </div>
        ) : totalDecisions === 0 ? (
          <p className="text-sm text-muted-foreground text-center py-6">No decision records found yet.</p>
        ) : (
          <>
            <div className="mb-4">
              <div className="flex rounded-full overflow-hidden h-6 w-full">
                {segments.map(seg => { const w = totalDecisions > 0 ? (seg.count / totalDecisions) * 100 : 0; if (w === 0) return null; return <div key={seg.label} className={`flex items-center justify-center ${seg.colorClass} text-xs font-bold text-white transition-all duration-500`} style={{ width: `${w}%` }}>{w >= 8 && seg.count}</div>; })}
              </div>
              <div className="flex flex-wrap gap-x-4 gap-y-1 mt-2">
                {segments.map(seg => { const w = totalDecisions > 0 ? (seg.count / totalDecisions) * 100 : 0; if (seg.count === 0) return null; return <span key={seg.label} className={`text-xs font-medium ${seg.textColor}`}>{seg.label} {w.toFixed(1)}%</span>; })}
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3 mb-4">
              {statsRows.map(row => (
                <div key={row.label} className="rounded-lg border border-border bg-background p-3">
                  <p className="text-xs text-muted-foreground uppercase tracking-wider">{row.label}</p>
                  <p className={`text-lg font-bold font-mono tabular-nums mt-0.5 ${row.valueClass ?? "text-foreground"}`}>{row.value}</p>
                </div>
              ))}
            </div>
            <p className="text-xs text-muted-foreground">Higher signal rate = more trading opportunities | Lower = more selective</p>
            <p className="text-xs text-muted-foreground mt-1">From last 500 decisions · Refreshes every 5m</p>
          </>
        )}
      </CardContent>
    </Card>
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
        <SignalAccuracyWidget />

        {/* Long vs Short balance vs backtest benchmark */}
        <LongShortBalanceWidget />

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
