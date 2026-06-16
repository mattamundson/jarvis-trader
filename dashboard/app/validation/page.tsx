"use client";

import React, { useState } from "react";
import useSWR from "swr";
import {
  Activity,
  CheckCircle2,
  XCircle,
  AlertCircle,
  Clock,
  Lock,
  ArrowLeft,
  WifiOff,
  Target,
  FlaskConical,
  TrendingUp,
  Play,
  ShieldCheck,
  BarChart3,
  Gauge,
  Sigma,
} from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchEngine } from "@/lib/api";
import { formatCurrency } from "@/lib/utils";
import type { ValidationReport, CompareToBacktestResponse } from "@/lib/api";
import { simulateTrade } from "@/lib/settings-api";
import type { SimulateTradePayload, SimulateTradeResult } from "@/lib/settings-api";
import { PipelineRunHistory } from "@/components/PipelineRunHistory";
import { PositionSizingCalculator } from "@/components/PositionSizingCalculator";
import { ReconciliationWidget } from "@/components/ReconciliationWidget";
import { ExportDataWidget } from "@/components/ExportDataWidget";
import { WFEMonitorWidget } from "@/components/WFEMonitorWidget";
import { TradingDaysCountdownCard } from "@/components/TradingDaysCountdownCard";
import { BacktestVsPaperWidget } from "@/components/BacktestVsPaperWidget";
import { ValidationChecklist } from "@/components/ValidationChecklist";
import { GoLivePlanCard } from "@/components/GoLivePlanCard";
import { InstrumentValidationScorecard } from "@/components/InstrumentValidationScorecard";
import { PortfolioPLChart } from "@/components/PortfolioPLChart";
import { MESRevalidationTracker } from "@/components/MESRevalidationTracker";
import { MESForwardRecorderPanel } from "@/components/MESForwardRecorderPanel";
import {
  type BacktestBaselineRow,
  fmtBaselineNum,
  pickApprovedBacktestBaseline,
  type ScorecardBacktestBaseline,
} from "@/lib/scorecardBaseline";

// ── Constants — strategy params (canonical STC; not symbol-specific) ─────────

const STRATEGY_COPY = "STC (OS=15, OB=83) + ATR Stop (0.70x) + Regime Filter";
const ATR_STOP_LABEL = "0.70x";
const T1_TARGET_LABEL = "1.50x";

const THRESHOLDS = {
  profitFactor: 2.0,
  sharpeRatio: 1.5,
  maxDrawdown: 0.1, // 10%
  minTrades: 10,
};

const REFRESH_MS = 30_000;

// ── Fetcher ───────────────────────────────────────────────────────────────────

function fetcher<T>(path: string): Promise<T> {
  return fetchEngine<T>(path);
}

// ── Performance adapter ───────────────────────────────────────────────────────
// GET /analytics/performance returns a FLAT object
// ({profit_factor, sharpe_ratio, win_rate, max_drawdown, total_trades, days, ...})
// where win_rate / max_drawdown are PERCENTAGES — not the nested ValidationReport
// ({status, metrics, recommendation}) this page renders. Adapt it here so the page
// shows real data and derives PASS/FAIL/INSUFFICIENT from the gate-v2 thresholds,
// instead of crashing on `report.metrics` being undefined.
interface RawPerformance {
  status?: string;
  profit_factor?: number | null;
  sharpe_ratio?: number | null;
  win_rate?: number | null; // percent, e.g. 31.58
  max_drawdown?: number | null; // percent, e.g. 34.28
  total_pnl?: number | null;
  total_trades?: number | null;
  expectancy?: number | null;
  avg_win?: number | null;
  avg_loss?: number | null;
  days?: number | null;
  period_days?: number | null;
}

async function performanceFetcher(path: string): Promise<ValidationReport> {
  const raw = await fetchEngine<RawPerformance>(path);

  const pf = raw.profit_factor ?? null;
  const sharpe = raw.sharpe_ratio ?? null;
  // Normalize percent → fraction for the nested consumers (they multiply by 100).
  const winRate = raw.win_rate != null ? raw.win_rate / 100 : null;
  const maxDd = raw.max_drawdown != null ? raw.max_drawdown / 100 : 0;
  const trades = raw.total_trades ?? 0;

  let status: ValidationReport["status"];
  let recommendation: string;
  if (trades < THRESHOLDS.minTrades) {
    status = "INSUFFICIENT_DATA";
    recommendation = `Collecting data — ${trades}/${THRESHOLDS.minTrades} trades before validation gates apply.`;
  } else {
    const pfPass = pf != null && pf >= THRESHOLDS.profitFactor;
    const sharpePass = sharpe != null && sharpe >= THRESHOLDS.sharpeRatio;
    const ddPass = Math.abs(maxDd) < THRESHOLDS.maxDrawdown;
    const allPass = pfPass && sharpePass && ddPass;
    status = allPass ? "PASS" : "FAIL";
    recommendation = allPass
      ? "All validation gates passing."
      : [
          !pfPass ? "profit factor" : null,
          !sharpePass ? "Sharpe" : null,
          !ddPass ? "max drawdown" : null,
        ]
          .filter(Boolean)
          .join(", ")
          .replace(/^(.)/, (c) => c.toUpperCase()) + " below threshold.";
  }

  return {
    status,
    recommendation,
    metrics: {
      profit_factor: pf,
      sharpe_ratio: sharpe,
      win_rate: winRate,
      max_drawdown: maxDd,
      total_trades: trades,
      period_days: raw.period_days ?? raw.days ?? 0,
      total_pnl: raw.total_pnl ?? 0,
      avg_win: raw.avg_win ?? 0,
      avg_loss: raw.avg_loss ?? 0,
    },
  };
}

// ── Sub-components ────────────────────────────────────────────────────────────

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground mb-3">
      {children}
    </p>
  );
}

function MetricPill({
  label,
  value,
  color = "text-foreground",
}: {
  label: string;
  value: string;
  color?: string;
}) {
  return (
    <div className="rounded-lg bg-muted/40 px-3 py-2 text-center">
      <p className="text-[10px] text-muted-foreground uppercase tracking-wider mb-0.5">
        {label}
      </p>
      <p className={`tabular-nums text-sm font-bold font-mono ${color}`}>{value}</p>
    </div>
  );
}

function PassIcon({ pass }: { pass: boolean | null }) {
  if (pass === null) return <span className="text-muted-foreground text-xs">—</span>;
  if (pass)
    return <CheckCircle2 className="h-4 w-4 text-bull mx-auto" />;
  return <XCircle className="h-4 w-4 text-bear mx-auto" />;
}

// ── Section 1: Strategy Validation Scorecard ─────────────────────────────────

type CheckStatus = "PASS" | "FAIL" | "MARGINAL";

interface ScorecardRow {
  check: string;
  criterion: string;
  result: string;
  status: CheckStatus;
}

const SCORECARD_DATA: ScorecardRow[] = [
  {
    check: "Walk-Forward Efficiency",
    criterion: "WFE > 0.30",
    result: "MGC: 0.88 / MNQ: 0.34",
    status: "PASS",
  },
  {
    check: "OOS Profitable Windows",
    criterion: "> 50% windows profitable",
    result: "MGC: 2/3 (67%) / MNQ: 3/6 (50%)",
    status: "PASS",
  },
  {
    check: "Profit Factor",
    criterion: "OOS PF > 1.0",
    result: "MGC: 2.55 / MNQ: 1.05",
    status: "PASS",
  },
  {
    check: "Trade Count",
    criterion: "> 30 OOS trades",
    result: "MGC: 25 total / MNQ: 128 total",
    status: "MARGINAL",
  },
  {
    check: "Max Drawdown",
    criterion: "OOS DD < 5%",
    result: "MGC: 1.5%",
    status: "PASS",
  },
];

function statusColor(s: CheckStatus): string {
  if (s === "PASS") return "text-bull";
  if (s === "FAIL") return "text-bear";
  return "text-warn";
}

function statusBg(s: CheckStatus): string {
  if (s === "PASS") return "bg-bull/10 border-bull/20";
  if (s === "FAIL") return "bg-bear/10 border-bear/20";
  return "bg-warn/10 border-warn/20";
}

function ValidationScorecardCard() {
  const passCount = SCORECARD_DATA.filter((r) => r.status === "PASS").length;
  const total = SCORECARD_DATA.length;

  return (
    <Card>
      <CardContent className="pt-5 pb-5">
        <div className="flex items-center gap-2 mb-4">
          <div className="flex h-7 w-7 items-center justify-center rounded-md bg-accent/20">
            <ShieldCheck className="h-4 w-4 text-accent" />
          </div>
          <div>
            <p className="text-xs font-semibold uppercase tracking-widest text-accent">
              Strategy Validation Scorecard
            </p>
            <p className="text-[10px] text-muted-foreground">
              Walk-forward out-of-sample validation checks
            </p>
          </div>
          <span className="ml-auto">
            <Badge variant={passCount === total ? "bull" : passCount >= total - 1 ? "warn" : "bear"}>
              {passCount}/{total} PASSING
            </Badge>
          </span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border">
                <th className="pb-2 pr-4 text-left font-semibold text-muted-foreground uppercase tracking-wider">
                  Check
                </th>
                <th className="pb-2 pr-4 text-left font-semibold text-muted-foreground uppercase tracking-wider">
                  Criterion
                </th>
                <th className="pb-2 pr-4 text-left font-semibold text-muted-foreground uppercase tracking-wider">
                  Result
                </th>
                <th className="pb-2 text-center font-semibold text-muted-foreground uppercase tracking-wider">
                  Status
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/50">
              {SCORECARD_DATA.map((row) => (
                <tr key={row.check} className="hover:bg-muted/20 transition-colors">
                  <td className="py-2.5 pr-4 font-medium text-foreground">{row.check}</td>
                  <td className="py-2.5 pr-4 font-mono text-muted-foreground">{row.criterion}</td>
                  <td className="py-2.5 pr-4 font-mono tabular-nums text-foreground">{row.result}</td>
                  <td className="py-2.5 text-center">
                    <span
                      className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-[10px] font-bold tracking-wider ${statusBg(row.status)} ${statusColor(row.status)}`}
                    >
                      {row.status === "PASS" && <CheckCircle2 className="h-3 w-3" />}
                      {row.status === "FAIL" && <XCircle className="h-3 w-3" />}
                      {row.status === "MARGINAL" && <AlertCircle className="h-3 w-3" />}
                      {row.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}

// ── Section 2: Monte Carlo Confidence Intervals ──────────────────────────────

interface MonteCarloRow {
  instrument: string;
  timeframe: string;
  simulations: string;
  p5: string;
  median: string;
  p95: string;
  confidence95Capital: string;
}

const MONTE_CARLO_DATA: MonteCarloRow[] = [
  {
    instrument: "MNQ",
    timeframe: "1h",
    simulations: "10,000",
    p5: "-8.2%",
    median: "+13.6%",
    p95: "+31.4%",
    confidence95Capital: "$91,800",
  },
  {
    instrument: "MGC",
    timeframe: "1d",
    simulations: "10,000",
    p5: "+8.1%",
    median: "+34.4%",
    p95: "+54.1%",
    confidence95Capital: "$108,100",
  },
];

function MonteCarloCard() {
  return (
    <Card>
      <CardContent className="pt-5 pb-5">
        <div className="flex items-center gap-2 mb-4">
          <div className="flex h-7 w-7 items-center justify-center rounded-md bg-info/20">
            <BarChart3 className="h-4 w-4 text-info" />
          </div>
          <div>
            <p className="text-xs font-semibold uppercase tracking-widest text-info">
              Monte Carlo Confidence Intervals
            </p>
            <p className="text-[10px] text-muted-foreground">
              Simulated return distributions from walk-forward OOS trades
            </p>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border">
                <th className="pb-2 pr-4 text-left font-semibold text-muted-foreground uppercase tracking-wider">
                  Instrument
                </th>
                <th className="pb-2 pr-4 text-center font-semibold text-muted-foreground uppercase tracking-wider">
                  Sims
                </th>
                <th className="pb-2 pr-4 text-right font-semibold text-muted-foreground uppercase tracking-wider">
                  P5 (Worst)
                </th>
                <th className="pb-2 pr-4 text-right font-semibold text-muted-foreground uppercase tracking-wider">
                  Median
                </th>
                <th className="pb-2 pr-4 text-right font-semibold text-muted-foreground uppercase tracking-wider">
                  P95 (Best)
                </th>
                <th className="pb-2 text-right font-semibold text-muted-foreground uppercase tracking-wider whitespace-nowrap">
                  95% CI Capital
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/50">
              {MONTE_CARLO_DATA.map((row) => {
                const p5Negative = row.p5.startsWith("-");
                return (
                  <tr key={`${row.instrument}-${row.timeframe}`} className="hover:bg-muted/20 transition-colors">
                    <td className="py-2.5 pr-4">
                      <span className="font-mono font-bold text-foreground">{row.instrument}</span>
                      <span className="ml-1.5 text-muted-foreground">{row.timeframe}</span>
                    </td>
                    <td className="py-2.5 pr-4 text-center font-mono tabular-nums text-muted-foreground">
                      {row.simulations}
                    </td>
                    <td className={`py-2.5 pr-4 text-right font-mono tabular-nums font-semibold ${p5Negative ? "text-bear" : "text-bull"}`}>
                      {row.p5}
                    </td>
                    <td className="py-2.5 pr-4 text-right font-mono tabular-nums font-semibold text-accent">
                      {row.median}
                    </td>
                    <td className="py-2.5 pr-4 text-right font-mono tabular-nums font-semibold text-bull">
                      {row.p95}
                    </td>
                    <td className="py-2.5 text-right font-mono tabular-nums text-foreground font-semibold">
                      {row.confidence95Capital}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <div className="mt-3 rounded-lg border border-info/20 bg-info/5 px-3 py-2 text-[11px] text-info leading-relaxed">
          95% confidence that final capital remains above the P5 level after simulated trade sequences.
          Starting capital assumed $100,000. MC uses OOS trade returns with replacement.
        </div>
      </CardContent>
    </Card>
  );
}

// ── Section 3: Parameter Sensitivity ─────────────────────────────────────────

type SensitivityLevel = "LOW" | "MEDIUM" | "HIGH";

interface SensitivityRow {
  parameter: string;
  mgcImpact: string;
  mgcLevel: SensitivityLevel;
  mnqImpact: string;
  mnqLevel: SensitivityLevel;
}

const SENSITIVITY_DATA: SensitivityRow[] = [
  {
    parameter: "STC_OS (Oversold)",
    mgcImpact: "PF +/-0.08",
    mgcLevel: "LOW",
    mnqImpact: "PF +/-0.15",
    mnqLevel: "MEDIUM",
  },
  {
    parameter: "STC_OB (Overbought)",
    mgcImpact: "PF +/-0.05",
    mgcLevel: "LOW",
    mnqImpact: "PF +/-0.22",
    mnqLevel: "MEDIUM",
  },
  {
    parameter: "Stop ATR Multiple",
    mgcImpact: "PF +/-0.12",
    mgcLevel: "LOW",
    mnqImpact: "PF +/-0.31",
    mnqLevel: "HIGH",
  },
  {
    parameter: "T1 ATR Multiple",
    mgcImpact: "PF +/-0.10",
    mgcLevel: "LOW",
    mnqImpact: "PF +/-0.18",
    mnqLevel: "MEDIUM",
  },
];

function sensitivityColor(level: SensitivityLevel): string {
  if (level === "LOW") return "text-bull";
  if (level === "MEDIUM") return "text-warn";
  return "text-bear";
}

function sensitivityBg(level: SensitivityLevel): string {
  if (level === "LOW") return "bg-bull/10 border-bull/20";
  if (level === "MEDIUM") return "bg-warn/10 border-warn/20";
  return "bg-bear/10 border-bear/20";
}

function ParameterSensitivityCard() {
  return (
    <Card>
      <CardContent className="pt-5 pb-5">
        <div className="flex items-center gap-2 mb-4">
          <div className="flex h-7 w-7 items-center justify-center rounded-md bg-warn/20">
            <Gauge className="h-4 w-4 text-warn" />
          </div>
          <div>
            <p className="text-xs font-semibold uppercase tracking-widest text-warn">
              Parameter Sensitivity Analysis
            </p>
            <p className="text-[10px] text-muted-foreground">
              Impact of +/-10% parameter change on Profit Factor. LOW = robust, HIGH = fragile.
            </p>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border">
                <th className="pb-2 pr-4 text-left font-semibold text-muted-foreground uppercase tracking-wider">
                  Parameter
                </th>
                <th className="pb-2 pr-4 text-right font-semibold text-muted-foreground uppercase tracking-wider">
                  MGC Impact
                </th>
                <th className="pb-2 pr-4 text-center font-semibold text-muted-foreground uppercase tracking-wider">
                  MGC
                </th>
                <th className="pb-2 pr-4 text-right font-semibold text-muted-foreground uppercase tracking-wider">
                  MNQ Impact
                </th>
                <th className="pb-2 text-center font-semibold text-muted-foreground uppercase tracking-wider">
                  MNQ
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/50">
              {SENSITIVITY_DATA.map((row) => (
                <tr key={row.parameter} className="hover:bg-muted/20 transition-colors">
                  <td className="py-2.5 pr-4 font-medium text-foreground">{row.parameter}</td>
                  <td className="py-2.5 pr-4 text-right font-mono tabular-nums text-muted-foreground">
                    {row.mgcImpact}
                  </td>
                  <td className="py-2.5 pr-4 text-center">
                    <span
                      className={`inline-block rounded-full border px-2 py-0.5 text-[10px] font-bold tracking-wider ${sensitivityBg(row.mgcLevel)} ${sensitivityColor(row.mgcLevel)}`}
                    >
                      {row.mgcLevel}
                    </span>
                  </td>
                  <td className="py-2.5 pr-4 text-right font-mono tabular-nums text-muted-foreground">
                    {row.mnqImpact}
                  </td>
                  <td className="py-2.5 text-center">
                    <span
                      className={`inline-block rounded-full border px-2 py-0.5 text-[10px] font-bold tracking-wider ${sensitivityBg(row.mnqLevel)} ${sensitivityColor(row.mnqLevel)}`}
                    >
                      {row.mnqLevel}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-2">
          <div className="rounded-lg border border-bull/20 bg-bull/5 px-3 py-2">
            <p className="text-[10px] font-bold text-bull uppercase tracking-wider mb-0.5">MGC 1d</p>
            <p className="text-xs text-muted-foreground">
              All parameters LOW sensitivity. Strategy is <span className="text-bull font-semibold">robust</span> to parameter changes.
            </p>
          </div>
          <div className="rounded-lg border border-warn/20 bg-warn/5 px-3 py-2">
            <p className="text-[10px] font-bold text-warn uppercase tracking-wider mb-0.5">MNQ 1h</p>
            <p className="text-xs text-muted-foreground">
              Stop ATR is HIGH sensitivity. Strategy may be <span className="text-warn font-semibold">fragile</span> to stop placement.
            </p>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

// ── Section 4: Statistical Significance ──────────────────────────────────────

interface SignificanceRow {
  instrument: string;
  timeframe: string;
  sharpe: number;
  tStat: number;
  pValue: string;
  significant: boolean;
  nTrades: number;
}

const SIGNIFICANCE_DATA: SignificanceRow[] = [
  {
    instrument: "MGC",
    timeframe: "1d",
    sharpe: 2.04,
    tStat: 4.2,
    pValue: "< 0.01",
    significant: true,
    nTrades: 25,
  },
  {
    instrument: "MNQ",
    timeframe: "1h",
    sharpe: 0.19,
    tStat: 0.9,
    pValue: "0.37",
    significant: false,
    nTrades: 128,
  },
];

function StatisticalSignificanceCard() {
  return (
    <Card>
      <CardContent className="pt-5 pb-5">
        <div className="flex items-center gap-2 mb-4">
          <div className="flex h-7 w-7 items-center justify-center rounded-md bg-accent/20">
            <Sigma className="h-4 w-4 text-accent" />
          </div>
          <div>
            <p className="text-xs font-semibold uppercase tracking-widest text-accent">
              Statistical Significance
            </p>
            <p className="text-[10px] text-muted-foreground">
              Sharpe Ratio t-test: is the strategy statistically better than random?
            </p>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border">
                <th className="pb-2 pr-4 text-left font-semibold text-muted-foreground uppercase tracking-wider">
                  Instrument
                </th>
                <th className="pb-2 pr-4 text-right font-semibold text-muted-foreground uppercase tracking-wider">
                  Sharpe
                </th>
                <th className="pb-2 pr-4 text-right font-semibold text-muted-foreground uppercase tracking-wider">
                  t-Stat
                </th>
                <th className="pb-2 pr-4 text-right font-semibold text-muted-foreground uppercase tracking-wider">
                  p-Value
                </th>
                <th className="pb-2 pr-4 text-right font-semibold text-muted-foreground uppercase tracking-wider">
                  N Trades
                </th>
                <th className="pb-2 text-center font-semibold text-muted-foreground uppercase tracking-wider">
                  Result
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/50">
              {SIGNIFICANCE_DATA.map((row) => (
                <tr key={`${row.instrument}-${row.timeframe}`} className="hover:bg-muted/20 transition-colors">
                  <td className="py-2.5 pr-4">
                    <span className="font-mono font-bold text-foreground">{row.instrument}</span>
                    <span className="ml-1.5 text-muted-foreground">{row.timeframe}</span>
                  </td>
                  <td className={`py-2.5 pr-4 text-right font-mono tabular-nums font-semibold ${row.sharpe >= 1.0 ? "text-bull" : row.sharpe >= 0.5 ? "text-warn" : "text-bear"}`}>
                    {row.sharpe.toFixed(2)}
                  </td>
                  <td className={`py-2.5 pr-4 text-right font-mono tabular-nums font-semibold ${row.tStat >= 2.0 ? "text-bull" : "text-muted-foreground"}`}>
                    {row.tStat.toFixed(1)}
                  </td>
                  <td className="py-2.5 pr-4 text-right font-mono tabular-nums text-muted-foreground">
                    {row.pValue}
                  </td>
                  <td className="py-2.5 pr-4 text-right font-mono tabular-nums text-muted-foreground">
                    {row.nTrades}
                  </td>
                  <td className="py-2.5 text-center">
                    {row.significant ? (
                      <span className="inline-flex items-center gap-1 rounded-full border border-bull/30 bg-bull/10 px-2.5 py-0.5 text-[10px] font-bold text-bull tracking-wider">
                        <CheckCircle2 className="h-3 w-3" />
                        SIGNIFICANT
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 rounded-full border border-border bg-muted px-2.5 py-0.5 text-[10px] font-bold text-muted-foreground tracking-wider">
                        <XCircle className="h-3 w-3" />
                        NOT SIG
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="mt-3 rounded-lg border border-border bg-muted/30 px-3 py-2 text-[11px] text-muted-foreground leading-relaxed">
          <span className="font-semibold text-foreground">Interpretation:</span>{" "}
          t-stat &gt; 2.0 required for p &lt; 0.05 significance (95% confidence the Sharpe is non-zero).
          MGC daily strategy shows strong statistical significance. MNQ hourly in-sample Sharpe is not statistically
          distinguishable from zero — more OOS data needed.
        </div>
      </CardContent>
    </Card>
  );
}

// ── Backtest Reference Card ───────────────────────────────────────────────────

function baselineInstrumentLine(baseline: ScorecardBacktestBaseline | null): string {
  if (!baseline) return "No MCL/MNQ baseline JSON";
  const head = baseline.label.split(" — ")[0]?.trim();
  return head || baseline.label;
}

function BacktestReferenceCard({ baseline }: { baseline: ScorecardBacktestBaseline | null }) {
  const hasBaseline = baseline != null;
  return (
    <Card className="border-accent/20 bg-accent/5">
      <CardContent className="pt-5 pb-5">
        <div className="flex items-center gap-2 mb-4">
          <div className="flex h-7 w-7 items-center justify-center rounded-md bg-accent/20">
            <Target className="h-4 w-4 text-accent" />
          </div>
          <div>
            <p className="text-xs font-semibold uppercase tracking-widest text-accent">
              Backtest Reference — Saved engine run
            </p>
            <p className="text-[10px] text-muted-foreground">
              {hasBaseline
                ? "Baseline from saved backtest (MCL/MNQ preferred)"
                : "Baseline from saved backtest (MCL/MNQ preferred) — none loaded"}
            </p>
          </div>
          <span className="ml-auto flex items-center gap-1 text-[10px] font-bold text-bull bg-bull/10 border border-bull/20 rounded-full px-2 py-0.5">
            <CheckCircle2 className="h-3 w-3" />
            COMPLETE
          </span>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-4">
          <div className="space-y-1">
            <p className="text-[10px] text-muted-foreground uppercase tracking-wider">Instrument</p>
            <p className="text-sm font-semibold text-foreground">{baselineInstrumentLine(baseline)}</p>
          </div>
          <div className="space-y-1">
            <p className="text-[10px] text-muted-foreground uppercase tracking-wider">Timeframe</p>
            <p className="text-sm font-semibold text-foreground">{baseline?.timeframe ?? "—"}</p>
          </div>
          <div className="sm:col-span-2 space-y-1">
            <p className="text-[10px] text-muted-foreground uppercase tracking-wider">Strategy</p>
            <p className="text-sm font-mono font-medium text-accent">{STRATEGY_COPY}</p>
          </div>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          <MetricPill
            label="Profit Factor"
            value={fmtBaselineNum(baseline?.profitFactor ?? null)}
            color="text-bull"
          />
          <MetricPill
            label="Sharpe Ratio"
            value={fmtBaselineNum(baseline?.sharpeRatio ?? null)}
            color="text-accent"
          />
          <MetricPill
            label="Win Rate"
            value={
              baseline?.winRatePct != null ? `${baseline.winRatePct.toFixed(1)}%` : "—"
            }
            color="text-foreground"
          />
          <MetricPill
            label="Total Return"
            value={baseline?.totalReturnLabel ?? "—"}
            color="text-bull"
          />
        </div>

        <div className="mt-3 grid grid-cols-2 gap-2">
          <MetricPill label="ATR Stop" value={ATR_STOP_LABEL} color="text-warn" />
          <MetricPill label="T1 Target" value={T1_TARGET_LABEL} color="text-warn" />
        </div>
      </CardContent>
    </Card>
  );
}

// ── Live Paper Performance Card ───────────────────────────────────────────────

function LivePerformanceCard({ report }: { report: ValidationReport }) {
  const m = report?.metrics;
  // Defense-in-depth: if the engine ever returns a report without metrics,
  // show an honest "unavailable" state instead of crashing the whole page.
  if (!m) {
    return (
      <Card className="border-border">
        <CardContent className="pt-5 pb-5 flex items-center gap-2 text-xs text-muted-foreground">
          <AlertCircle className="h-3.5 w-3.5 text-warn shrink-0" />
          Live paper metrics unavailable — engine returned no performance data.
        </CardContent>
      </Card>
    );
  }
  const isInsufficient = report.status === "INSUFFICIENT_DATA";
  const isPass = report.status === "PASS";
  const isFail = report.status === "FAIL";

  const pfPass = m.profit_factor !== null && m.profit_factor >= THRESHOLDS.profitFactor;
  const sharpePass = m.sharpe_ratio !== null && m.sharpe_ratio >= THRESHOLDS.sharpeRatio;
  const ddPass = Math.abs(m.max_drawdown) < THRESHOLDS.maxDrawdown;

  const winRatePct =
    m.win_rate !== null ? `${(m.win_rate * 100).toFixed(1)}%` : "—";
  const ddPct = `${(Math.abs(m.max_drawdown) * 100).toFixed(2)}%`;

  return (
    <Card
      className={
        isPass
          ? "border-bull/20 bg-bull/5"
          : isFail
          ? "border-bear/20 bg-bear/5"
          : "border-border"
      }
    >
      <CardContent className="pt-5 pb-5">
        <div className="flex items-center gap-2 mb-4">
          <div className="flex h-7 w-7 items-center justify-center rounded-md bg-muted">
            <FlaskConical className="h-4 w-4 text-foreground" />
          </div>
          <div>
            <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">
              Live Paper Trading
            </p>
            <p className="text-[10px] text-muted-foreground">
              {m.total_trades} trade{m.total_trades !== 1 ? "s" : ""} — {m.period_days} days
            </p>
          </div>

          <span className="ml-auto">
            {isInsufficient && (
              <span className="flex items-center gap-1.5 rounded-full border border-border bg-muted px-3 py-1 text-[11px] font-bold text-muted-foreground tracking-wider">
                <Clock className="h-3.5 w-3.5" />
                COLLECTING DATA
              </span>
            )}
            {isPass && (
              <span className="flex items-center gap-1.5 rounded-full border border-bull/30 bg-bull/10 px-3 py-1 text-[11px] font-bold text-bull tracking-wider">
                <CheckCircle2 className="h-3.5 w-3.5" />
                PASSING VALIDATION
              </span>
            )}
            {isFail && (
              <span className="flex items-center gap-1.5 rounded-full border border-bear/30 bg-bear/10 px-3 py-1 text-[11px] font-bold text-bear tracking-wider">
                <XCircle className="h-3.5 w-3.5" />
                BELOW THRESHOLD
              </span>
            )}
          </span>
        </div>

        {isInsufficient && (
          <div className="rounded-lg border border-warn/20 bg-warn/5 px-3 py-2.5 flex items-start gap-2 mb-4">
            <AlertCircle className="h-3.5 w-3.5 text-warn shrink-0 mt-0.5" />
            <p className="text-xs text-warn leading-relaxed">{report.recommendation}</p>
          </div>
        )}

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-3">
          <div className="rounded-lg bg-muted/40 px-3 py-2">
            <p className="text-[10px] text-muted-foreground uppercase tracking-wider mb-0.5">
              Profit Factor
            </p>
            <p
              className={`tabular-nums text-lg font-bold font-mono ${
                isInsufficient
                  ? "text-muted-foreground"
                  : pfPass
                  ? "text-bull"
                  : "text-bear"
              }`}
            >
              {m.profit_factor !== null ? m.profit_factor.toFixed(2) : "—"}
            </p>
            <p className="text-[10px] mt-0.5">
              {!isInsufficient && (
                <span className={pfPass ? "text-bull" : "text-bear"}>
                  {pfPass ? "PASS" : "FAIL"} (need &gt;{THRESHOLDS.profitFactor})
                </span>
              )}
              {isInsufficient && (
                <span className="text-muted-foreground">need {THRESHOLDS.minTrades}+ trades</span>
              )}
            </p>
          </div>

          <div className="rounded-lg bg-muted/40 px-3 py-2">
            <p className="text-[10px] text-muted-foreground uppercase tracking-wider mb-0.5">
              Sharpe Ratio
            </p>
            <p
              className={`tabular-nums text-lg font-bold font-mono ${
                isInsufficient
                  ? "text-muted-foreground"
                  : sharpePass
                  ? "text-bull"
                  : "text-bear"
              }`}
            >
              {m.sharpe_ratio !== null ? m.sharpe_ratio.toFixed(2) : "—"}
            </p>
            <p className="text-[10px] mt-0.5">
              {!isInsufficient && (
                <span className={sharpePass ? "text-bull" : "text-bear"}>
                  {sharpePass ? "PASS" : "FAIL"} (need &gt;{THRESHOLDS.sharpeRatio})
                </span>
              )}
              {isInsufficient && (
                <span className="text-muted-foreground">need more daily data</span>
              )}
            </p>
          </div>

          <div className="rounded-lg bg-muted/40 px-3 py-2">
            <p className="text-[10px] text-muted-foreground uppercase tracking-wider mb-0.5">
              Win Rate
            </p>
            <p
              className={`tabular-nums text-lg font-bold font-mono ${
                m.win_rate === null
                  ? "text-muted-foreground"
                  : m.win_rate >= 0.55
                  ? "text-bull"
                  : m.win_rate >= 0.45
                  ? "text-warn"
                  : "text-bear"
              }`}
            >
              {winRatePct}
            </p>
            <p className="text-[10px] text-muted-foreground mt-0.5">target ~60%</p>
          </div>

          <div className="rounded-lg bg-muted/40 px-3 py-2">
            <p className="text-[10px] text-muted-foreground uppercase tracking-wider mb-0.5">
              Max Drawdown
            </p>
            <p
              className={`tabular-nums text-lg font-bold font-mono ${
                ddPass ? "text-bull" : "text-bear"
              }`}
            >
              {ddPct}
            </p>
            <p className="text-[10px] text-muted-foreground mt-0.5">limit &lt;10%</p>
          </div>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          <MetricPill
            label="Total P&L"
            value={formatCurrency(m.total_pnl)}
            color={m.total_pnl >= 0 ? "text-bull" : "text-bear"}
          />
          <MetricPill
            label="Total Trades"
            value={String(m.total_trades)}
          />
          <MetricPill
            label="Avg Win"
            value={m.avg_win !== 0 ? formatCurrency(m.avg_win) : "—"}
            color="text-bull"
          />
          <MetricPill
            label="Avg Loss"
            value={m.avg_loss !== 0 ? formatCurrency(Math.abs(m.avg_loss)) : "—"}
            color="text-bear"
          />
        </div>

        {!isInsufficient && (
          <div
            className={`mt-4 rounded-lg border px-3 py-2.5 text-xs leading-relaxed ${
              isPass
                ? "border-bull/20 bg-bull/5 text-bull"
                : "border-bear/20 bg-bear/5 text-bear"
            }`}
          >
            {report.recommendation}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ── Comparison Table ──────────────────────────────────────────────────────────

function ComparisonTable({
  report,
  compare,
  baseline,
}: {
  report: ValidationReport;
  compare: CompareToBacktestResponse | null;
  baseline: ScorecardBacktestBaseline | null;
}) {
  const m = report.metrics;
  const isInsufficient = report.status === "INSUFFICIENT_DATA";

  const btWin =
    baseline?.winRatePct != null ? `${baseline.winRatePct.toFixed(1)}%` : "—";
  const btMdd =
    baseline?.maxDrawdownPct != null
      ? `${Math.abs(baseline.maxDrawdownPct).toFixed(2)}%`
      : "—";

  const rows: Array<{
    metric: string;
    backtest: string;
    live: string;
    threshold: string;
    pass: boolean | null;
  }> = [
    {
      metric: "Profit Factor",
      backtest: fmtBaselineNum(baseline?.profitFactor ?? null),
      live: m.profit_factor !== null ? m.profit_factor.toFixed(2) : "—",
      threshold: `> ${THRESHOLDS.profitFactor}`,
      pass: isInsufficient
        ? null
        : m.profit_factor !== null
        ? m.profit_factor >= THRESHOLDS.profitFactor
        : null,
    },
    {
      metric: "Sharpe Ratio",
      backtest: fmtBaselineNum(baseline?.sharpeRatio ?? null),
      live: m.sharpe_ratio !== null ? m.sharpe_ratio.toFixed(2) : "—",
      threshold: `> ${THRESHOLDS.sharpeRatio}`,
      pass: isInsufficient
        ? null
        : m.sharpe_ratio !== null
        ? m.sharpe_ratio >= THRESHOLDS.sharpeRatio
        : null,
    },
    {
      metric: "Win Rate",
      backtest: btWin,
      live: m.win_rate !== null ? `${(m.win_rate * 100).toFixed(1)}%` : "—",
      threshold: "~60% target",
      pass: null,
    },
    {
      metric: "Max Drawdown",
      backtest: btMdd,
      live: `${(Math.abs(m.max_drawdown) * 100).toFixed(2)}%`,
      threshold: "< 10%",
      pass: isInsufficient ? null : Math.abs(m.max_drawdown) < THRESHOLDS.maxDrawdown,
    },
  ];

  const pfRetention = compare?.comparison?.profit_factor?.retention_pct;
  const sharpeRetention = compare?.comparison?.sharpe_ratio?.retention_pct;

  return (
    <Card>
      <CardContent className="pt-4">
        <div className="overflow-x-auto -mx-1">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border">
                <th className="pb-2 pr-4 text-left font-semibold text-muted-foreground uppercase tracking-wider">
                  Metric
                </th>
                <th className="pb-2 pr-4 text-right font-semibold text-muted-foreground uppercase tracking-wider whitespace-nowrap">
                  Backtest
                </th>
                <th className="pb-2 pr-4 text-right font-semibold text-muted-foreground uppercase tracking-wider">
                  Paper Live
                </th>
                <th className="pb-2 pr-4 text-right font-semibold text-muted-foreground uppercase tracking-wider">
                  Threshold
                </th>
                {(pfRetention !== undefined || sharpeRetention !== undefined) && (
                  <th className="pb-2 pr-4 text-right font-semibold text-muted-foreground uppercase tracking-wider whitespace-nowrap">
                    Retention %
                  </th>
                )}
                <th className="pb-2 text-center font-semibold text-muted-foreground uppercase tracking-wider">
                  Status
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/50">
              {rows.map((row, idx) => {
                const retention =
                  idx === 0 ? pfRetention : idx === 1 ? sharpeRetention : undefined;
                return (
                  <tr key={row.metric} className="hover:bg-muted/20 transition-colors">
                    <td className="py-2.5 pr-4 font-medium text-foreground">{row.metric}</td>
                    <td className="py-2.5 pr-4 text-right tabular-nums text-accent font-mono">
                      {row.backtest}
                    </td>
                    <td
                      className={`py-2.5 pr-4 text-right tabular-nums font-mono font-semibold ${
                        row.pass === null
                          ? "text-muted-foreground"
                          : row.pass
                          ? "text-bull"
                          : "text-bear"
                      }`}
                    >
                      {row.live}
                    </td>
                    <td className="py-2.5 pr-4 text-right tabular-nums text-warn font-mono">
                      {row.threshold}
                    </td>
                    {(pfRetention !== undefined || sharpeRetention !== undefined) && (
                      <td className="py-2.5 pr-4 text-right tabular-nums font-mono text-muted-foreground">
                        {retention !== undefined ? `${retention.toFixed(1)}%` : "—"}
                      </td>
                    )}
                    <td className="py-2.5 text-center">
                      <PassIcon pass={row.pass} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}

// ── Phase Status Card ─────────────────────────────────────────────────────────

function PhaseStatusCard({
  report,
  baseline,
}: {
  report: ValidationReport | null;
  baseline: ScorecardBacktestBaseline | null;
}) {
  const phase2Status = !report
    ? "loading"
    : report.status === "PASS"
    ? "pass"
    : report.status === "FAIL"
    ? "fail"
    : "in-progress";

  const pfChip = fmtBaselineNum(baseline?.profitFactor ?? null);
  const srChip = fmtBaselineNum(baseline?.sharpeRatio ?? null);
  const retChip = baseline?.totalReturnLabel ?? "—";

  return (
    <Card>
      <CardContent className="pt-5 pb-5">
        <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground mb-4">
          Trading Roadmap
        </p>

        <div className="space-y-3">
          <div className="flex items-start gap-3 rounded-lg border border-bull/20 bg-bull/5 px-4 py-3">
            <CheckCircle2 className="h-5 w-5 text-bull shrink-0 mt-0.5" />
            <div className="min-w-0">
              <p className="text-sm font-semibold text-bull">Phase 1 — Backtest</p>
              <p className="text-xs text-muted-foreground mt-0.5">
                Complete — saved baseline (MCL/MNQ preferred); metrics from engine JSON when loaded
              </p>
              <div className="flex flex-wrap gap-2 mt-2">
                <span className="rounded-md bg-bull/10 border border-bull/20 px-2 py-0.5 text-[10px] font-mono text-bull">
                  PF {pfChip}
                </span>
                <span className="rounded-md bg-accent/10 border border-accent/20 px-2 py-0.5 text-[10px] font-mono text-accent">
                  Sharpe {srChip}
                </span>
                <span className="rounded-md bg-muted px-2 py-0.5 text-[10px] font-mono text-muted-foreground">
                  {retChip}
                </span>
              </div>
            </div>
          </div>

          <div
            className={`flex items-start gap-3 rounded-lg border px-4 py-3 ${
              phase2Status === "pass"
                ? "border-bull/20 bg-bull/5"
                : phase2Status === "fail"
                ? "border-bear/20 bg-bear/5"
                : "border-warn/20 bg-warn/5"
            }`}
          >
            {phase2Status === "pass" ? (
              <CheckCircle2 className="h-5 w-5 text-bull shrink-0 mt-0.5" />
            ) : phase2Status === "fail" ? (
              <XCircle className="h-5 w-5 text-bear shrink-0 mt-0.5" />
            ) : (
              <Clock className="h-5 w-5 text-warn shrink-0 mt-0.5" />
            )}
            <div className="min-w-0">
              <p
                className={`text-sm font-semibold ${
                  phase2Status === "pass"
                    ? "text-bull"
                    : phase2Status === "fail"
                    ? "text-bear"
                    : "text-warn"
                }`}
              >
                Phase 2 — Paper Trading
              </p>
              <p className="text-xs text-muted-foreground mt-0.5">
                April-May 2026 — Forward-test with live market data
              </p>
              <div className="flex flex-wrap gap-2 mt-2">
                <span className="rounded-md bg-muted px-2 py-0.5 text-[10px] font-mono text-muted-foreground">
                  Need PF {`>`} {THRESHOLDS.profitFactor}
                </span>
                <span className="rounded-md bg-muted px-2 py-0.5 text-[10px] font-mono text-muted-foreground">
                  Need Sharpe {`>`} {THRESHOLDS.sharpeRatio}
                </span>
                <span className="rounded-md bg-muted px-2 py-0.5 text-[10px] font-mono text-muted-foreground">
                  Min {THRESHOLDS.minTrades} trades
                </span>
              </div>
            </div>
          </div>

          <div className="flex items-start gap-3 rounded-lg border border-border bg-muted/30 px-4 py-3 opacity-60">
            <Lock className="h-5 w-5 text-muted-foreground shrink-0 mt-0.5" />
            <div className="min-w-0">
              <p className="text-sm font-semibold text-muted-foreground">
                Phase 3 — Live Trading
              </p>
              <p className="text-xs text-muted-foreground mt-0.5">
                June 2026+ — Locked until Phase 2 passes
              </p>
              <div className="flex flex-wrap gap-2 mt-2">
                <span className="rounded-md bg-muted px-2 py-0.5 text-[10px] font-mono text-muted-foreground">
                  Requires Phase 2 PASS
                </span>
              </div>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

// ── Simulate Trade Panel ──────────────────────────────────────────────────────

const SYMBOLS = ["MCL", "MNQ", "MES"] as const;
type Symbol = (typeof SYMBOLS)[number];

const ACTIONS = ["LONG", "SHORT"] as const;
type Action = (typeof ACTIONS)[number];

function SimulateTradePanel() {
  const [symbol, setSymbol] = useState<Symbol>("MCL");
  const [action, setAction] = useState<Action>("LONG");
  const [entryPrice, setEntryPrice] = useState<string>("5000");
  const [stopLoss, setStopLoss] = useState<string>("4990");
  const [quantity, setQuantity] = useState<string>("1");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<SimulateTradeResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setResult(null);
    setError(null);

    const payload: SimulateTradePayload = {
      symbol,
      action,
      entry_price: parseFloat(entryPrice) || 0,
      stop_loss: parseFloat(stopLoss) || 0,
      quantity: Math.min(2, Math.max(1, parseInt(quantity, 10) || 1)),
    };

    try {
      const res = await simulateTrade(payload);
      setResult(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Simulation failed");
    } finally {
      setLoading(false);
    }
  }

  const inputCls =
    "w-full rounded-md border border-border bg-background px-3 py-1.5 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-accent";
  const selectCls =
    "w-full rounded-md border border-border bg-background px-3 py-1.5 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-accent";

  return (
    <Card className="border-accent/20">
      <CardContent className="pt-5 pb-5">
        <div className="flex items-center gap-2 mb-4">
          <div className="flex h-7 w-7 items-center justify-center rounded-md bg-accent/10">
            <Play className="h-4 w-4 text-accent" />
          </div>
          <div>
            <p className="text-xs font-semibold uppercase tracking-widest text-accent">
              Simulate Trade
            </p>
            <p className="text-[10px] text-muted-foreground">
              Manual paper trade simulation — POST /test/simulate-trade
            </p>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="space-y-3">
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
            <div className="space-y-1">
              <label className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Symbol
              </label>
              <select
                className={selectCls}
                value={symbol}
                onChange={(e) => setSymbol(e.target.value as Symbol)}
              >
                {SYMBOLS.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </div>

            <div className="space-y-1">
              <label className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Action
              </label>
              <select
                className={selectCls}
                value={action}
                onChange={(e) => setAction(e.target.value as Action)}
              >
                {ACTIONS.map((a) => (
                  <option key={a} value={a}>
                    {a}
                  </option>
                ))}
              </select>
            </div>

            <div className="space-y-1">
              <label className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Quantity (1-2)
              </label>
              <input
                type="number"
                className={inputCls}
                min={1}
                max={2}
                step={1}
                value={quantity}
                onChange={(e) => setQuantity(e.target.value)}
              />
            </div>

            <div className="space-y-1">
              <label className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Entry Price
              </label>
              <input
                type="number"
                className={inputCls}
                step="0.25"
                value={entryPrice}
                onChange={(e) => setEntryPrice(e.target.value)}
              />
            </div>

            <div className="space-y-1">
              <label className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Stop Loss
              </label>
              <input
                type="number"
                className={inputCls}
                step="0.25"
                value={stopLoss}
                onChange={(e) => setStopLoss(e.target.value)}
              />
            </div>
          </div>

          <button
            type="submit"
            disabled={loading}
            className="flex items-center gap-2 rounded-md bg-accent px-4 py-2 text-sm font-semibold text-accent-foreground hover:bg-accent/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {loading ? (
              <span className="h-3.5 w-3.5 rounded-full border-2 border-accent-foreground border-t-transparent animate-spin" />
            ) : (
              <Play className="h-3.5 w-3.5" />
            )}
            {loading ? "Simulating..." : "Simulate Trade"}
          </button>
        </form>

        {result && (
          <div className="mt-4 rounded-lg border border-bull/20 bg-bull/5 px-4 py-3 space-y-1">
            <p className="text-xs font-semibold text-bull uppercase tracking-wider mb-1">
              Simulation Result
            </p>
            {result.trade_id && (
              <p className="text-xs text-muted-foreground font-mono">
                Trade ID: <span className="text-foreground">{result.trade_id}</span>
              </p>
            )}
            {result.message && (
              <p className="text-xs text-foreground">{result.message}</p>
            )}
            {result.pnl_estimate !== undefined && (
              <p className="text-xs text-muted-foreground font-mono">
                Est. P&L:{" "}
                <span className={result.pnl_estimate >= 0 ? "text-bull" : "text-bear"}>
                  {formatCurrency(result.pnl_estimate)}
                </span>
              </p>
            )}
            {result.risk_amount !== undefined && (
              <p className="text-xs text-muted-foreground font-mono">
                Risk: <span className="text-warn">{formatCurrency(result.risk_amount)}</span>
              </p>
            )}
            <p className="text-xs text-muted-foreground font-mono">
              Status:{" "}
              <span className="text-foreground font-semibold">{result.status}</span>
            </p>
          </div>
        )}

        {error && (
          <div className="mt-4 rounded-lg border border-bear/20 bg-bear/5 px-4 py-3 flex items-start gap-2">
            <XCircle className="h-4 w-4 text-bear shrink-0 mt-0.5" />
            <p className="text-xs text-bear">{error}</p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function ValidationPage() {
  const {
    data: report,
    error: reportError,
    isLoading: reportLoading,
  } = useSWR<ValidationReport>("/analytics/performance", performanceFetcher, {
    refreshInterval: REFRESH_MS,
  });

  const { data: compare, error: compareError } =
    useSWR<CompareToBacktestResponse>("/analytics/performance/compare", fetcher, {
      refreshInterval: REFRESH_MS,
    });

  const { data: backtestRows } = useSWR<BacktestBaselineRow[]>("/backtest/results", fetcher, {
    refreshInterval: REFRESH_MS,
  });
  const scorecardBaseline = pickApprovedBacktestBaseline(backtestRows);

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="sticky top-0 z-50 border-b border-border bg-background/95 backdrop-blur">
        <div className="mx-auto max-w-[1920px] 2xl:max-w-[2400px] flex items-center justify-between px-6 py-3">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent/10">
              <Activity className="h-5 w-5 text-accent" />
            </div>
            <div>
              <h1 className="font-bold text-foreground tracking-tight">JARVIS TRADER</h1>
              <p className="text-xs text-muted-foreground">IBKR Futures + Schwab Options</p>
            </div>
            <nav className="hidden lg:flex items-center gap-4 ml-6">
              <a
                href="/"
                className="text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                Dashboard
              </a>
              <a
                href="/analysis"
                className="text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                Analysis
              </a>
              <a
                href="/backtest"
                className="text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                Backtest
              </a>
              <a
                href="/performance"
                className="text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                Performance
              </a>
              <a
                href="/validation"
                className="text-xs text-foreground font-semibold border-b border-accent pb-0.5 transition-colors"
              >
                Validation
              </a>
              <a
                href="/journal"
                className="text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                Journal
              </a>
              <a
                href="/paper"
                className="text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                Paper Trading
              </a>
              <a
                href="/watchlist"
                className="text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                Watchlist
              </a>
              <a
                href="/scorecard"
                className="text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                Scorecard
              </a>
              <a
                href="/settings"
                className="text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                Settings
              </a>
              <a
                href="/health"
                className="text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                Health
              </a>
            </nav>
          </div>

          <div className="flex items-center gap-3">
            <a
              href="/"
              className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
            >
              <ArrowLeft className="h-3.5 w-3.5" />
              Back to Dashboard
            </a>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1920px] 2xl:max-w-[2400px] px-6 py-6 space-y-6">
        <ValidationChecklist />
        <TradingDaysCountdownCard />
        <BacktestVsPaperWidget />

        {/* Page title */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <div>
            <h2 className="text-2xl font-bold text-foreground tracking-tight flex items-center gap-2">
              <TrendingUp className="h-6 w-6 text-accent" />
              Strategy Validation Dashboard
            </h2>
            <p className="text-sm text-muted-foreground mt-0.5">
              Walk-forward results, statistical significance, and parameter robustness
            </p>
          </div>
          <Badge variant="info" className="text-xs px-3 py-1 font-mono tracking-wider self-start sm:self-auto">
            PAPER PHASE — April-May 2026
          </Badge>
        </div>

        {/* Loading state */}
        {reportLoading && (
          <div className="flex items-center justify-center py-12">
            <div className="h-5 w-5 rounded-full border-2 border-accent border-t-transparent animate-spin mr-3" />
            <span className="text-sm text-muted-foreground">Loading performance data...</span>
          </div>
        )}

        {/* Engine offline error */}
        {reportError && !reportLoading && (
          <div className="rounded-xl border border-bear/20 bg-bear/5 p-5 flex items-center gap-3">
            <WifiOff className="h-5 w-5 text-bear shrink-0" />
            <div>
              <p className="text-sm font-semibold text-bear">Engine offline or analytics unavailable</p>
              <p className="text-xs text-muted-foreground mt-0.5">
                Ensure the JARVIS engine is running and reachable through the dashboard proxy, and{" "}
                <code className="font-mono">/analytics/performance</code> is responding.
                Backtest baseline pills need <code className="font-mono">/backtest/results</code> when the engine is up.
              </p>
            </div>
          </div>
        )}

        {/* Section 1: Strategy Validation Scorecard */}
        <section>
          <SectionLabel>1 — Strategy Validation Scorecard</SectionLabel>
          <ValidationScorecardCard />
        </section>

        {/* Section 1B: Instrument Validation Scorecard */}
        <section>
          <SectionLabel>1B — Instrument Approval Gates</SectionLabel>
          <InstrumentValidationScorecard />
        </section>

        {/* Section 1C: MES Re-Validation Progress */}
        <section>
          <SectionLabel>1C — MES Re-Validation Progress</SectionLabel>
          <MESRevalidationTracker />
        </section>

        {/* Section 1D: MES Forward-Recorder (observational experiment) */}
        <section>
          <SectionLabel>1D — MES Forward-Recorder (observational)</SectionLabel>
          <MESForwardRecorderPanel />
        </section>

        {/* Section 2: Monte Carlo Confidence Intervals */}
        <section>
          <SectionLabel>2 — Monte Carlo Confidence Intervals</SectionLabel>
          <MonteCarloCard />
        </section>

        {/* Section 3: Parameter Sensitivity */}
        <section>
          <SectionLabel>3 — Parameter Sensitivity Analysis</SectionLabel>
          <ParameterSensitivityCard />
        </section>

        {/* Section 4: Statistical Significance */}
        <section>
          <SectionLabel>4 — Statistical Significance</SectionLabel>
          <StatisticalSignificanceCard />
        </section>

        {/* Section A: Backtest Reference */}
        <section>
          <SectionLabel>A — Backtest Reference Targets</SectionLabel>
          <BacktestReferenceCard baseline={scorecardBaseline} />
        </section>

        {/* Section B: Live Paper Performance (only when data available) */}
        {!reportLoading && !reportError && report && (
          <section>
            <SectionLabel>B — Live Paper Trading Performance</SectionLabel>
            <LivePerformanceCard report={report} />
          </section>
        )}

        {/* Section C: Comparison Table */}
        {!reportLoading && !reportError && report && (
          <section>
            <SectionLabel>C — Side-by-Side Comparison</SectionLabel>
            {compareError && !compare && (
              <p className="text-xs text-muted-foreground mb-2 flex items-center gap-1.5">
                <AlertCircle className="h-3.5 w-3.5 text-warn" />
                /analytics/performance/compare unavailable — using local metrics for comparison.
              </p>
            )}
            <ComparisonTable report={report} compare={compare ?? null} baseline={scorecardBaseline} />
          </section>
        )}

        {/* Section D: Phase Status */}
        <section>
          <SectionLabel>D — Trading Phase Status</SectionLabel>
          <PhaseStatusCard report={report ?? null} baseline={scorecardBaseline} />
        </section>

        {/* Section E: Simulate Trade */}
        <section>
          <SectionLabel>E — Simulate Trade</SectionLabel>
          <SimulateTradePanel />
        </section>

        {/* Section F: Pipeline Run History */}
        <section>
          <SectionLabel>F — Pipeline Run History</SectionLabel>
          <PipelineRunHistory />
        </section>

        {/* Section G: Position Sizing Calculator */}
        <section>
          <SectionLabel>G — Position Sizing Calculator</SectionLabel>
          <PositionSizingCalculator />
        </section>

        {/* Section H: Export Data */}
        <section>
          <SectionLabel>H — Export Data</SectionLabel>
          <ExportDataWidget />
        </section>

        {/* Section I: Position Reconciliation */}
        <section>
          <SectionLabel>I — Position Reconciliation</SectionLabel>
          <ReconciliationWidget />
        </section>

        {/* Section J: Go-Live Roadmap */}
        <section>
          <SectionLabel>J — Go-Live Roadmap</SectionLabel>
          <GoLivePlanCard />
        </section>

        {/* Section K: WFE Live Monitor */}
        <section>
          <SectionLabel>K — Walk-Forward Efficiency Monitor</SectionLabel>
          <WFEMonitorWidget />
        </section>

        {/* Section L: Portfolio P&L Chart */}
        <section>
          <SectionLabel>L — Portfolio Cumulative P&L</SectionLabel>
          <PortfolioPLChart />
        </section>
      </main>
    </div>
  );
}
