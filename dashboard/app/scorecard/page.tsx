"use client";

import Link from "next/link";
import React from "react";
import useSWR from "swr";
import type { LucideIcon } from "lucide-react";
import {
  Activity,
  AlertTriangle,
  BarChart3,
  CheckCircle2,
  Clock,
  FileDown,
  RefreshCw,
  Target,
  TrendingDown,
  TrendingUp,
  XCircle,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { fetchEngine } from "@/lib/api";
import {
  type BacktestBaselineRow,
  fmtBaselineNum,
  pickApprovedBacktestBaseline,
  type ScorecardBacktestBaseline,
} from "@/lib/scorecardBaseline";
import { formatCurrency } from "@/lib/utils";
import { ReadinessCheckWidget } from "@/components/ReadinessCheckWidget";
import { StreakBadge } from "@/components/StreakBadge";
import { RollingPerformanceCard } from "@/components/RollingPerformanceCard";
import { CalendarHeatmap } from "@/components/CalendarHeatmap";
import { EquityCurveWidget } from "@/components/EquityCurveWidget";
import { PaperBalanceWidget } from "@/components/PaperBalanceWidget";
import { DailyPnLCalendarWidget } from "@/components/DailyPnLCalendarWidget";
import { MonthlyTargetCard } from "@/components/MonthlyTargetCard";
import { PnLStreakWidget } from "@/components/PnLStreakWidget";
import { MaxDrawdownTrackerWidget } from "@/components/MaxDrawdownTrackerWidget";
import { DrawdownChartWidget } from "@/components/DrawdownChartWidget";
import { BacktestCompareWidget } from "@/components/BacktestCompareWidget";

// ── Constants ─────────────────────────────────────────────────────────────────

const TARGETS = {
  profitFactor: 2.0,  // v2.7 live gate (paper gate: 1.5)
  sharpeRatio: 1.5,   // v2.7 live gate (paper gate: 1.0)
  winRate: 50,        // percent — v2.7 live gate (paper gate: 45%)
  maxDrawdown: 8,     // percent (positive = limit) — v2.7 live gate
  daysActive: 60,     // min 60+ days with 60+ trades — v2.7 graduation rule
};

const REFRESH_MS = 60_000;

// ── API types ─────────────────────────────────────────────────────────────────

interface PortfolioStatsSummary {
  total_trades: number;
  winning: number;
  losing: number;
  total_pnl: number;
  best_day: number;
  worst_day: number;
  days_active?: number;
  start_date?: string;
}

interface AnalyticsPerformance {
  profit_factor: number;
  sharpe_ratio: number;
  win_rate: number;   // 0–1 decimal
  avg_win: number;
  avg_loss: number;
}

interface DrawdownStats {
  current_drawdown: number;       // decimal, negative = loss
  peak_balance: number;
  max_historical_drawdown: number; // decimal, negative = loss
}

// ── Fetchers ─────────────────────────────────────────────────────────────────

const fetchSummary = () =>
  fetchEngine<PortfolioStatsSummary>("/portfolio/stats/summary");
const fetchPerformance = () =>
  fetchEngine<AnalyticsPerformance>("/analytics/performance");
const fetchDrawdown = () =>
  fetchEngine<DrawdownStats>("/portfolio/stats/drawdown");
const fetchBacktestResults = () =>
  fetchEngine<BacktestBaselineRow[]>("/backtest/results");

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmt2(n: number): string {
  return n.toFixed(2);
}

function fmtPct(n: number): string {
  return `${n.toFixed(1)}%`;
}

/** Clamp a ratio to [0, 100] for progress bars */
function progressPct(value: number, target: number): number {
  return Math.min(100, Math.max(0, (value / target) * 100));
}

type ColorLevel = "red" | "yellow" | "green";

function pfLevel(pf: number): ColorLevel {
  if (pf >= TARGETS.profitFactor) return "green";
  if (pf >= 1.3) return "yellow";
  return "red";
}

function sharpeLevel(sr: number): ColorLevel {
  if (sr >= TARGETS.sharpeRatio) return "green";
  if (sr >= 0.8) return "yellow";
  return "red";
}

function daysLevel(days: number): ColorLevel {
  if (days >= TARGETS.daysActive) return "green";
  if (days >= 15) return "yellow";
  return "red";
}

function colorClass(level: ColorLevel): string {
  if (level === "green") return "text-bull";
  if (level === "yellow") return "text-warn";
  return "text-bear";
}

function barColor(level: ColorLevel): string {
  if (level === "green") return "bg-bull";
  if (level === "yellow") return "bg-warn";
  return "bg-bear";
}

// ── Sub-components ────────────────────────────────────────────────────────────

function SectionHeader({ title }: { title: string }) {
  return (
    <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3">
      {title}
    </p>
  );
}

function MetricCard({
  label,
  value,
  sub,
  level,
  icon: Icon,
}: {
  label: string;
  value: string;
  sub?: string;
  level: ColorLevel;
  icon: LucideIcon;
}) {
  return (
    <div className="rounded-xl border border-border bg-card p-5 flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <span className="text-xs text-muted-foreground font-medium">{label}</span>
        <Icon className={`h-4 w-4 ${colorClass(level)}`} />
      </div>
      <p className={`text-3xl font-bold font-mono ${colorClass(level)}`}>{value}</p>
      {sub && <p className="text-xs text-muted-foreground">{sub}</p>}
    </div>
  );
}

function ProgressBar({
  label,
  value,
  target,
  unit,
  level,
  currentLabel,
  targetLabel,
}: {
  label: string;
  value: number;
  target: number;
  unit?: string;
  level: ColorLevel;
  currentLabel: string;
  targetLabel: string;
}) {
  const pct = progressPct(value, target);

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-foreground">{label}</span>
        <div className="flex items-center gap-2">
          <span className={`text-xs font-mono font-bold ${colorClass(level)}`}>
            {currentLabel}
          </span>
          <span className="text-xs text-muted-foreground">/ {targetLabel}</span>
        </div>
      </div>
      <div className="h-2.5 w-full rounded-full bg-muted overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-500 ${barColor(level)}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="flex justify-between">
        <span className="text-[10px] text-muted-foreground">0{unit}</span>
        <span className="text-[10px] text-muted-foreground">
          Target: {targetLabel}
        </span>
      </div>
    </div>
  );
}

function StatusCheck({
  label,
  pass,
}: {
  label: string;
  pass: boolean | null;
}) {
  if (pass === null) {
    return (
      <div className="flex items-center gap-2">
        <div className="h-4 w-4 rounded-full bg-muted animate-pulse" />
        <span className="text-xs text-muted-foreground">{label}</span>
      </div>
    );
  }
  return (
    <div className="flex items-center gap-2">
      {pass ? (
        <CheckCircle2 className="h-4 w-4 text-bull flex-shrink-0" />
      ) : (
        <XCircle className="h-4 w-4 text-bear flex-shrink-0" />
      )}
      <span className={`text-xs font-medium ${pass ? "text-bull" : "text-bear"}`}>
        {label}
      </span>
    </div>
  );
}

function SkeletonCard() {
  return (
    <div className="rounded-xl border border-border bg-card p-5 animate-pulse">
      <div className="h-3 w-24 bg-muted rounded mb-4" />
      <div className="h-8 w-20 bg-muted rounded mb-2" />
      <div className="h-3 w-32 bg-muted rounded" />
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function ScorecardPage() {
  const {
    data: summary,
    isLoading: loadingSummary,
    mutate: mutateSummary,
  } = useSWR<PortfolioStatsSummary>("scorecard/summary", fetchSummary, {
    refreshInterval: REFRESH_MS,
  });

  const {
    data: perf,
    isLoading: loadingPerf,
    mutate: mutatePerf,
  } = useSWR<AnalyticsPerformance>("scorecard/performance", fetchPerformance, {
    refreshInterval: REFRESH_MS,
  });

  const {
    data: drawdown,
    isLoading: loadingDrawdown,
    mutate: mutateDrawdown,
  } = useSWR<DrawdownStats>("scorecard/drawdown", fetchDrawdown, {
    refreshInterval: REFRESH_MS,
  });

  const { data: backtestRows, mutate: mutateBacktest } = useSWR<BacktestBaselineRow[]>(
    "scorecard/backtest-results",
    fetchBacktestResults,
    { refreshInterval: REFRESH_MS }
  );
  const baseline: ScorecardBacktestBaseline | null =
    pickApprovedBacktestBaseline(backtestRows);

  const isLoading = loadingSummary || loadingPerf || loadingDrawdown;

  function refreshAll() {
    mutateSummary();
    mutatePerf();
    mutateDrawdown();
    mutateBacktest();
  }

  // Derived values
  const pf = perf?.profit_factor ?? 0;
  const sr = perf?.sharpe_ratio ?? 0;
  const wr = (perf?.win_rate ?? 0) * 100; // convert 0–1 → percent
  const days = summary?.days_active ?? 0;
  const maxDD = Math.abs((drawdown?.max_historical_drawdown ?? 0) * 100);
  const totalPnl = summary?.total_pnl ?? 0;

  const pfLvl = pfLevel(pf);
  const srLvl = sharpeLevel(sr);
  const daysLvl = daysLevel(days);

  const pfPass = pf >= TARGETS.profitFactor;
  const srPass = sr >= TARGETS.sharpeRatio;
  const daysPass = days >= TARGETS.daysActive;
  const allPass = pfPass && srPass && daysPass;
  const anyPass = pfPass || srPass || daysPass;

  type Verdict = "NOT READY" | "APPROACHING" | "READY FOR LIVE";
  let verdict: Verdict = "NOT READY";
  let verdictColor = "text-bear";
  let verdictBg = "border-bear/40 bg-bear/5";
  if (allPass) {
    verdict = "READY FOR LIVE";
    verdictColor = "text-bull";
    verdictBg = "border-bull/40 bg-bull/5";
  } else if (anyPass || pfLvl === "yellow" || srLvl === "yellow") {
    verdict = "APPROACHING";
    verdictColor = "text-warn";
    verdictBg = "border-warn/40 bg-warn/5";
  }

  const wrPass = wr >= TARGETS.winRate;
  const ddPass = maxDD < TARGETS.maxDrawdown;

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="sticky top-0 z-50 border-b border-border bg-background/95 backdrop-blur">
        <div className="mx-auto max-w-[1600px] 2xl:max-w-[2000px] flex items-center justify-between px-6 py-3">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent/10">
              <Activity className="h-5 w-5 text-accent" />
            </div>
            <div>
              <h1 className="font-bold text-foreground tracking-tight">
                JARVIS TRADER
              </h1>
              <p className="text-xs text-muted-foreground">
                IBKR Futures + Schwab Options
              </p>
            </div>
            <nav className="hidden lg:flex items-center gap-4 ml-6">
              <Link
                href="/"
                className="text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                Dashboard
              </Link>
              <Link
                href="/analysis"
                className="text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                Analysis
              </Link>
              <Link
                href="/backtest"
                className="text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                Backtest
              </Link>
              <Link
                href="/performance"
                className="text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                Performance
              </Link>
              <Link
                href="/validation"
                className="text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                Validation
              </Link>
              <Link
                href="/scorecard"
                className="text-xs text-foreground font-semibold border-b border-accent pb-0.5"
              >
                Scorecard
              </Link>
              <Link
                href="/journal"
                className="text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                Journal
              </Link>
              <Link
                href="/watchlist"
                className="text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                Watchlist
              </Link>
              <Link
                href="/settings"
                className="text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                Settings
              </Link>
              <Link
                href="/health"
                className="text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                Health
              </Link>
            </nav>
          </div>

          <div className="flex items-center gap-3">
            <span className="text-[10px] text-muted-foreground hidden sm:block">
              Auto-refresh 60s
            </span>
            <Link
              href="/api/engine/reports/performance?format=download"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-2 rounded-md border border-border bg-background px-3 py-1.5 text-sm hover:bg-accent"
            >
              <FileDown className="h-4 w-4" />
              Download Report
            </Link>
            <button
              onClick={refreshAll}
              disabled={isLoading}
              className="flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1 text-xs text-muted-foreground hover:text-foreground transition-colors disabled:opacity-40"
            >
              <RefreshCw className={`h-3 w-3 ${isLoading ? "animate-spin" : ""}`} />
              Refresh
            </button>
          </div>
        </div>
      </header>

      {/* Page content */}
      <main className="mx-auto max-w-[1600px] 2xl:max-w-[2000px] px-6 py-6 space-y-6">

        {/* Page title */}
        <div className="flex items-center gap-3">
          <Target className="h-5 w-5 text-muted-foreground" />
          <div>
            <h2 className="text-lg font-bold text-foreground">
              Paper Trading Scorecard
            </h2>
            <p className="text-xs text-muted-foreground">
              {baseline
                ? `${baseline.label} — ${baseline.timeframe} — Validation targets for live trading promotion`
                : "No MCL/MNQ baseline JSON — Validation targets for live trading promotion"}
            </p>
          </div>
        </div>

        {/* ── Paper Account Balance ───────────────────────────────────────── */}
        <PaperBalanceWidget />

        {/* ── Monthly P&L Target ──────────────────────────────────────────── */}
        <MonthlyTargetCard />

        {/* ── P&L Streak ──────────────────────────────────────────────────── */}
        <PnLStreakWidget />

        {/* ── Validation Progress ─────────────────────────────────────────── */}
        <div className={`rounded-xl border p-6 space-y-6 ${verdictBg}`}>
          <div className="flex items-center justify-between">
            <SectionHeader title="Validation Progress" />
            <div
              className={`flex items-center gap-2 rounded-full px-3 py-1.5 text-xs font-bold border ${
                allPass
                  ? "border-bull/50 bg-bull/10 text-bull"
                  : verdict === "APPROACHING"
                  ? "border-warn/50 bg-warn/10 text-warn"
                  : "border-bear/50 bg-bear/10 text-bear"
              }`}
            >
              {allPass ? (
                <CheckCircle2 className="h-3.5 w-3.5" />
              ) : verdict === "APPROACHING" ? (
                <AlertTriangle className="h-3.5 w-3.5" />
              ) : (
                <XCircle className="h-3.5 w-3.5" />
              )}
              {verdict}
            </div>
          </div>

          <p className="text-xs text-muted-foreground -mt-2">
            All three criteria must be met to advance to live trading.
          </p>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <ProgressBar
              label="Profit Factor"
              value={pf}
              target={TARGETS.profitFactor}
              level={pfLvl}
              currentLabel={isLoading ? "—" : fmt2(pf)}
              targetLabel={`${TARGETS.profitFactor}`}
            />
            <ProgressBar
              label="Sharpe Ratio"
              value={sr}
              target={TARGETS.sharpeRatio}
              level={srLvl}
              currentLabel={isLoading ? "—" : fmt2(sr)}
              targetLabel={`${TARGETS.sharpeRatio}`}
            />
            <ProgressBar
              label="Days Active"
              value={days}
              target={TARGETS.daysActive}
              unit=" days"
              level={daysLvl}
              currentLabel={isLoading ? "—" : `${days}d`}
              targetLabel={`${TARGETS.daysActive}d`}
            />
          </div>

          <div className="flex items-center gap-6 pt-1">
            <StatusCheck
              label={`PF > ${TARGETS.profitFactor} (currently ${isLoading ? "…" : fmt2(pf)})`}
              pass={isLoading ? null : pfPass}
            />
            <StatusCheck
              label={`Sharpe > ${TARGETS.sharpeRatio} (currently ${isLoading ? "…" : fmt2(sr)})`}
              pass={isLoading ? null : srPass}
            />
            <StatusCheck
              label={`${TARGETS.daysActive}+ trading days (currently ${isLoading ? "…" : days})`}
              pass={isLoading ? null : daysPass}
            />
          </div>
        </div>

        {/* ── Live vs Backtest Comparison ─────────────────────────────────── */}
        <BacktestCompareWidget />

        {/* ── Rolling Performance Windows ─────────────────────────────────── */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <RollingPerformanceCard />
        </div>

        {/* ── Pre-Live Readiness Check ────────────────────────────────────── */}
        <ReadinessCheckWidget />

        {/* ── Key Metrics Grid ────────────────────────────────────────────── */}
        <div>
          <SectionHeader title="Key Metrics" />
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            {isLoading ? (
              <>
                <SkeletonCard />
                <SkeletonCard />
                <SkeletonCard />
                <SkeletonCard />
              </>
            ) : (
              <>
                <MetricCard
                  label="Profit Factor"
                  value={fmt2(pf)}
                  sub={`Target: > ${TARGETS.profitFactor}`}
                  level={pfLvl}
                  icon={BarChart3}
                />
                <MetricCard
                  label="Sharpe Ratio"
                  value={fmt2(sr)}
                  sub={`Target: > ${TARGETS.sharpeRatio}`}
                  level={srLvl}
                  icon={TrendingUp}
                />
                <MetricCard
                  label="Win Rate"
                  value={fmtPct(wr)}
                  sub={`Target: > ${TARGETS.winRate}%`}
                  level={wr >= TARGETS.winRate ? "green" : wr >= 40 ? "yellow" : "red"}
                  icon={Target}
                />
                <MetricCard
                  label="Total P&L"
                  value={formatCurrency(totalPnl)}
                  sub={totalPnl >= 0 ? "Net profit" : "Net loss"}
                  level={totalPnl > 0 ? "green" : totalPnl === 0 ? "yellow" : "red"}
                  icon={totalPnl >= 0 ? TrendingUp : TrendingDown}
                />
              </>
            )}
          </div>
        </div>

        {/* ── Backtest Comparison Table ───────────────────────────────────── */}
        <div className="rounded-xl border border-border bg-card overflow-hidden">
          <div className="px-5 py-4 border-b border-border">
            <SectionHeader title="Backtest vs Live Paper" />
            <p className="text-xs text-muted-foreground -mt-1">
              Comparing live paper results against strategy backtest baseline
            </p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border bg-muted/30">
                  <th className="text-left px-5 py-3 text-muted-foreground font-semibold uppercase tracking-wide">
                    Metric
                  </th>
                  <th className="text-right px-4 py-3 text-muted-foreground font-semibold uppercase tracking-wide">
                    Backtest
                  </th>
                  <th className="text-right px-4 py-3 text-muted-foreground font-semibold uppercase tracking-wide">
                    Live Paper
                  </th>
                  <th className="text-right px-4 py-3 text-muted-foreground font-semibold uppercase tracking-wide">
                    Target
                  </th>
                  <th className="text-center px-5 py-3 text-muted-foreground font-semibold uppercase tracking-wide">
                    Status
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {/* Profit Factor */}
                <tr className="hover:bg-muted/20 transition-colors">
                  <td className="px-5 py-3.5 font-medium text-foreground">
                    Profit Factor
                  </td>
                  <td className="px-4 py-3.5 text-right font-mono text-muted-foreground">
                    {fmtBaselineNum(baseline?.profitFactor ?? null)}
                  </td>
                  <td
                    className={`px-4 py-3.5 text-right font-mono font-bold ${
                      isLoading ? "text-muted-foreground" : colorClass(pfLvl)
                    }`}
                  >
                    {isLoading ? "…" : fmt2(pf)}
                  </td>
                  <td className="px-4 py-3.5 text-right text-muted-foreground">
                    &gt; {TARGETS.profitFactor}
                  </td>
                  <td className="px-5 py-3.5 text-center">
                    {isLoading ? (
                      <span className="text-muted-foreground">—</span>
                    ) : pfPass ? (
                      <CheckCircle2 className="h-4 w-4 text-bull mx-auto" />
                    ) : (
                      <XCircle className="h-4 w-4 text-bear mx-auto" />
                    )}
                  </td>
                </tr>
                {/* Sharpe Ratio */}
                <tr className="hover:bg-muted/20 transition-colors">
                  <td className="px-5 py-3.5 font-medium text-foreground">
                    Sharpe Ratio
                  </td>
                  <td className="px-4 py-3.5 text-right font-mono text-muted-foreground">
                    {fmtBaselineNum(baseline?.sharpeRatio ?? null)}
                  </td>
                  <td
                    className={`px-4 py-3.5 text-right font-mono font-bold ${
                      isLoading ? "text-muted-foreground" : colorClass(srLvl)
                    }`}
                  >
                    {isLoading ? "…" : fmt2(sr)}
                  </td>
                  <td className="px-4 py-3.5 text-right text-muted-foreground">
                    &gt; {TARGETS.sharpeRatio}
                  </td>
                  <td className="px-5 py-3.5 text-center">
                    {isLoading ? (
                      <span className="text-muted-foreground">—</span>
                    ) : srPass ? (
                      <CheckCircle2 className="h-4 w-4 text-bull mx-auto" />
                    ) : (
                      <XCircle className="h-4 w-4 text-bear mx-auto" />
                    )}
                  </td>
                </tr>
                {/* Win Rate */}
                <tr className="hover:bg-muted/20 transition-colors">
                  <td className="px-5 py-3.5 font-medium text-foreground">
                    Win Rate
                  </td>
                  <td className="px-4 py-3.5 text-right font-mono text-muted-foreground">
                    {baseline?.winRatePct != null
                      ? `${baseline.winRatePct.toFixed(1)}%`
                      : "—"}
                  </td>
                  <td
                    className={`px-4 py-3.5 text-right font-mono font-bold ${
                      isLoading
                        ? "text-muted-foreground"
                        : wrPass
                        ? "text-bull"
                        : "text-bear"
                    }`}
                  >
                    {isLoading ? "…" : fmtPct(wr)}
                  </td>
                  <td className="px-4 py-3.5 text-right text-muted-foreground">
                    &gt; {TARGETS.winRate}%
                  </td>
                  <td className="px-5 py-3.5 text-center">
                    {isLoading ? (
                      <span className="text-muted-foreground">—</span>
                    ) : wrPass ? (
                      <CheckCircle2 className="h-4 w-4 text-bull mx-auto" />
                    ) : (
                      <XCircle className="h-4 w-4 text-bear mx-auto" />
                    )}
                  </td>
                </tr>
                {/* Max Drawdown */}
                <tr className="hover:bg-muted/20 transition-colors">
                  <td className="px-5 py-3.5 font-medium text-foreground">
                    Max Drawdown
                  </td>
                  <td className="px-4 py-3.5 text-right font-mono text-muted-foreground">
                    {baseline?.maxDrawdownPct != null
                      ? `-${Math.abs(baseline.maxDrawdownPct).toFixed(1)}%`
                      : "—"}
                  </td>
                  <td
                    className={`px-4 py-3.5 text-right font-mono font-bold ${
                      isLoading
                        ? "text-muted-foreground"
                        : ddPass
                        ? "text-bull"
                        : "text-bear"
                    }`}
                  >
                    {isLoading ? "…" : `-${fmtPct(maxDD)}`}
                  </td>
                  <td className="px-4 py-3.5 text-right text-muted-foreground">
                    &lt; -{TARGETS.maxDrawdown}%
                  </td>
                  <td className="px-5 py-3.5 text-center">
                    {isLoading ? (
                      <span className="text-muted-foreground">—</span>
                    ) : ddPass ? (
                      <CheckCircle2 className="h-4 w-4 text-bull mx-auto" />
                    ) : (
                      <XCircle className="h-4 w-4 text-bear mx-auto" />
                    )}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        {/* ── Equity Curve ────────────────────────────────────────────────── */}
        <EquityCurveWidget />

        {/* ── Drawdown Chart ──────────────────────────────────────────────── */}
        <DrawdownChartWidget />

        {/* ── Daily P&L Calendar ──────────────────────────────────────────── */}
        <DailyPnLCalendarWidget />

        {/* ── Trade Summary ───────────────────────────────────────────────── */}
        <div className="rounded-xl border border-border bg-card p-5">
          <SectionHeader title="Trade Summary" />
          <div className="mb-4">
            <StreakBadge />
          </div>
          {isLoading ? (
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4 animate-pulse">
              {Array.from({ length: 6 }).map((_, i) => (
                <div key={i} className="space-y-2">
                  <div className="h-3 w-20 bg-muted rounded" />
                  <div className="h-5 w-14 bg-muted rounded" />
                </div>
              ))}
            </div>
          ) : (
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
              <TradeStat
                label="Total Trades"
                value={String(summary?.total_trades ?? 0)}
              />
              <TradeStat
                label="Winning"
                value={String(summary?.winning ?? 0)}
                valueClass="text-bull"
              />
              <TradeStat
                label="Losing"
                value={String(summary?.losing ?? 0)}
                valueClass="text-bear"
              />
              <TradeStat
                label="Avg Win"
                value={formatCurrency(perf?.avg_win ?? 0)}
                valueClass="text-bull"
              />
              <TradeStat
                label="Avg Loss"
                value={formatCurrency(perf?.avg_loss ?? 0)}
                valueClass="text-bear"
              />
              <div />

              <TradeStat
                label="Best Day"
                value={formatCurrency(summary?.best_day ?? 0)}
                valueClass="text-bull"
              />
              <TradeStat
                label="Worst Day"
                value={formatCurrency(summary?.worst_day ?? 0)}
                valueClass="text-bear"
              />
              <TradeStat
                label="Peak Balance"
                value={formatCurrency(drawdown?.peak_balance ?? 0)}
              />
              <TradeStat
                label="Current Drawdown"
                value={`-${fmtPct(Math.abs((drawdown?.current_drawdown ?? 0) * 100))}`}
                valueClass={
                  Math.abs((drawdown?.current_drawdown ?? 0) * 100) > 5
                    ? "text-bear"
                    : "text-warn"
                }
              />
              <TradeStat
                label="Max Drawdown"
                value={`-${fmtPct(maxDD)}`}
                valueClass={ddPass ? "text-bull" : "text-bear"}
              />
              <TradeStat
                label="Days Active"
                value={`${days}d`}
                valueClass={colorClass(daysLvl)}
              />
            </div>
          )}
        </div>

        {/* ── P&L Calendar ────────────────────────────────────────────── */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <CalendarHeatmap />
        </div>

        {/* Footer note */}
        <p className="text-[11px] text-muted-foreground text-center pb-4">
          {baseline ? (
            <>
              Backtest baseline: {baseline.label} &mdash; PF{" "}
              {fmtBaselineNum(baseline.profitFactor)}, Sharpe{" "}
              {fmtBaselineNum(baseline.sharpeRatio)}, {baseline.totalReturnLabel ?? "—"}, Win Rate{" "}
              {baseline.winRatePct != null ? `${baseline.winRatePct.toFixed(1)}%` : "—"} &mdash;
              Auto-refresh every 60s
            </>
          ) : (
            <>
              Baseline from saved backtest (MCL/MNQ preferred) &mdash; none loaded &mdash;
              Auto-refresh every 60s
            </>
          )}
        </p>
      </main>
    </div>
  );
}

function TradeStat({
  label,
  value,
  valueClass = "text-foreground",
}: {
  label: string;
  value: string;
  valueClass?: string;
}) {
  return (
    <div className="space-y-0.5">
      <p className="text-[10px] text-muted-foreground uppercase tracking-wide font-medium">
        {label}
      </p>
      <p className={`text-lg font-bold tabular-nums ${valueClass}`}>
        {value}
      </p>
    </div>
  );
}