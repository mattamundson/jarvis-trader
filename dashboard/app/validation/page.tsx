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
import {
  fetchHonestTrades,
  maxDrawdownPct,
  dedupCaveat,
} from "@/lib/honestTrades";
import { simulateTrade } from "@/lib/settings-api";
import type { SimulateTradePayload, SimulateTradeResult } from "@/lib/settings-api";
import { PipelineRunHistory } from "@/components/PipelineRunHistory";
import { PositionSizingCalculator } from "@/components/PositionSizingCalculator";
import { ReconciliationWidget } from "@/components/ReconciliationWidget";
import { ExportDataWidget } from "@/components/ExportDataWidget";
import { WFEMonitorWidget } from "@/components/WFEMonitorWidget";
import { TradingDaysCountdownCard } from "@/components/TradingDaysCountdownCard";
import { BacktestVsPaperWidget } from "@/components/BacktestVsPaperWidget";
import { WidgetErrorBoundary } from "@/components/WidgetErrorBoundary";
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

// ── Honest performance adapter ────────────────────────────────────────────────
// Replaces the former /analytics/performance fetcher that returned the inflated
// raw-engine counts (~29 rows → fabricated +$3,899 / PF 2.95 / 19 trades).
// Now sources everything from fetchHonestTrades() which applies the dedup
// (18 real trades, -$8,188, PF 0.66). Sharpe is NOT in the deduped record
// (only symbol/direction/entry_time/exit_time/pnl_usd/grade are available),
// so it is surfaced as null / "not computed" — no fabricated PASS.

async function honestPerformanceFetcher(): Promise<ValidationReport> {
  const set = await fetchHonestTrades();

  const pf = set.profitFactor;
  // sharpe_ratio is intentionally null — annualized Sharpe cannot be derived
  // from the deduped record (no timestamps granular enough, no risk-free rate).
  const sharpe: null = null;
  const winRate = set.winRate; // already 0..1
  // Shared single-source-of-truth DD (seeds peak at 0, denominates against the
  // real starting balance) — the former inline loop gated on peak>0, so a
  // net-negative account whose equity never rose above 0 reported 0% drawdown.
  const maxDd = maxDrawdownPct(set.trades); // fraction
  const trades = set.trades.length;

  // Avg win/loss from the deduped set
  const winners = set.trades.filter((t) => t.pnl > 0);
  const losers = set.trades.filter((t) => t.pnl < 0);
  const avgWin = winners.length > 0
    ? winners.reduce((s, t) => s + t.pnl, 0) / winners.length
    : 0;
  const avgLoss = losers.length > 0
    ? losers.reduce((s, t) => s + t.pnl, 0) / losers.length
    : 0;

  let status: ValidationReport["status"];
  let recommendation: string;
  if (trades < THRESHOLDS.minTrades) {
    status = "INSUFFICIENT_DATA";
    recommendation = `Collecting data — ${trades}/${THRESHOLDS.minTrades} trades before validation gates apply. ${dedupCaveat(set)}.`;
  } else {
    const pfPass = pf != null && pf >= THRESHOLDS.profitFactor;
    // Sharpe gate is SUSPENDED — cannot fabricate a PASS from the deduped record.
    const ddPass = maxDd < THRESHOLDS.maxDrawdown;
    const allPass = pfPass && ddPass; // sharpe intentionally excluded
    status = allPass ? "PASS" : "FAIL";
    recommendation = allPass
      ? `All computable validation gates passing. Sharpe not computed from deduped record. ${dedupCaveat(set)}.`
      : [
          !pfPass ? "profit factor" : null,
          !ddPass ? "max drawdown" : null,
          "Sharpe not computed from deduped record",
        ]
          .filter(Boolean)
          .join("; ")
          .replace(/^(.)/, (c) => c.toUpperCase()) + `. ${dedupCaveat(set)}.`;
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
      period_days: 0, // not in deduped record
      total_pnl: set.net,
      avg_win: avgWin,
      avg_loss: avgLoss,
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

// ── Live validation analytics (gate-v2 verdicts via /analytics/*) ─────────────
// These four cards replace the former hardcoded static blocks. All data is live
// from the engine's /analytics/{significance,sensitivity,monte-carlo} endpoints,
// which read the same gate-v2 verdict JSONs the strategy ledger uses.

interface SignificanceEntry {
  symbol: string | null;
  family: string | null;
  verdict: string | null;
  p_edge: number | null;
  dsr: number | null;
  pf_ci_lower: number | null;
  n_oos_trades: number | null;
  n_windows: number | null;
  mean_oos_pf: number | null;
  t_stat: number | null;
  significant: boolean;
  source_file: string | null;
}

interface SignificanceResponse {
  entries: SignificanceEntry[];
  total: number;
  n_significant: number;
  p_edge_threshold: number;
  generated_at: string;
}

interface SensitivityParam {
  parameter: string;
  pf_min: number;
  pf_max: number;
  pf_spread: number;
  half_spread: number;
  best_value: unknown;
  level: string;
}

interface SensitivityEntry {
  symbol: string | null;
  family: string | null;
  verdict: string | null;
  n_combos: number | null;
  fixed_params_min_pf: number | null;
  fixed_params_mean_pf: number | null;
  fixed_params_max_pf: number | null;
  params: SensitivityParam[];
  source_file: string | null;
}

interface SensitivityResponse {
  entries: SensitivityEntry[];
  total: number;
  generated_at: string;
}

interface MonteCarloEntry {
  symbol: string | null;
  family: string | null;
  timeframe: string | null;
  verdict: string | null;
  mc_95th_dd_pct: number | null;
  n_simulations: number | null;
  n_trades: number | null;
  return_p5: number | null;
  return_median: number | null;
  return_p95: number | null;
  capital_at_risk_95: number | null;
  artifact_verdict: string | null;
  degenerate: boolean | null;
  source: string;
  source_file: string | null;
}

interface MonteCarloResponse {
  entries: MonteCarloEntry[];
  total: number;
  n_with_artifact: number;
  generated_at: string;
}

const ANALYTICS_SWR = { refreshInterval: 60_000, revalidateOnFocus: false } as const;

const P_EDGE_FLOOR = 0.95; // gate-v2 edge threshold
const PF_CI_FLOOR = 1.1; // gate-v2 PF lower-CI floor
const DSR_FLOOR = 0.1; // gate-v2 deflated-Sharpe floor

function fmtNum(v: number | null | undefined, decimals = 2): string {
  return v != null && Number.isFinite(v) ? v.toFixed(decimals) : "—";
}

function verdictChipClasses(verdict: string | null | undefined): string {
  const v = (verdict ?? "").toUpperCase();
  if (v.includes("PASS") || v === "TRADE") return "bg-bull/10 border-bull/20 text-bull";
  if (
    v.includes("NEAR") ||
    v.includes("HOLD") ||
    v.includes("MARGINAL") ||
    v.includes("WEAK")
  )
    return "bg-warn/10 border-warn/20 text-warn";
  if (!v) return "bg-muted border-border text-muted-foreground";
  return "bg-bear/10 border-bear/20 text-bear";
}

function strategyLabel(symbol: string | null, family: string | null): string {
  const s = symbol ?? "—";
  return family ? `${s} · ${family}` : s;
}

/**
 * Honest placeholder shown while an analytics endpoint is unreachable (e.g. an
 * engine restart is pending to deploy the route) or has returned no rows. Never
 * fabricates data — the whole point of de-staticing these cards.
 */
function AwaitingAnalytics({ loading, message }: { loading: boolean; message: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-8 text-center">
      {loading ? (
        <div className="h-5 w-5 rounded-full border-2 border-accent border-t-transparent animate-spin" />
      ) : (
        <WifiOff className="h-5 w-5 text-muted-foreground" />
      )}
      <p className="max-w-md text-xs leading-relaxed text-muted-foreground font-mono">
        {message}
      </p>
    </div>
  );
}

// ── Section 1: Strategy Validation Scorecard (live gate-v2 verdicts) ──────────

function ValidationScorecardCard() {
  const { data, error, isLoading } = useSWR<SignificanceResponse>(
    "/analytics/significance",
    fetcher,
    ANALYTICS_SWR,
  );
  const entries = data?.entries ?? [];
  const nPass = entries.filter((e) =>
    (e.verdict ?? "").toUpperCase().includes("PASS"),
  ).length;

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
              Live gate-v2 verdicts — every evaluated strategy
            </p>
          </div>
          {entries.length > 0 && (
            <span className="ml-auto">
              <Badge variant={nPass > 0 ? "bull" : "bear"}>
                {nPass}/{entries.length} PASS
              </Badge>
            </span>
          )}
        </div>

        {entries.length === 0 ? (
          <AwaitingAnalytics
            loading={isLoading && !error}
            message={
              error
                ? "/analytics/significance unreachable — engine restart pending to deploy live validation analytics."
                : isLoading
                  ? "Loading gate-v2 verdicts…"
                  : "No gate-v2 verdicts on disk yet."
            }
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border">
                  <th className="pb-2 pr-4 text-left font-semibold text-muted-foreground uppercase tracking-wider">
                    Strategy
                  </th>
                  <th className="pb-2 pr-4 text-right font-semibold text-muted-foreground uppercase tracking-wider">
                    p_edge ≥ 0.95
                  </th>
                  <th className="pb-2 pr-4 text-right font-semibold text-muted-foreground uppercase tracking-wider">
                    PF-CI ≥ 1.10
                  </th>
                  <th className="pb-2 pr-4 text-right font-semibold text-muted-foreground uppercase tracking-wider">
                    DSR ≥ 0.10
                  </th>
                  <th className="pb-2 pr-4 text-right font-semibold text-muted-foreground uppercase tracking-wider">
                    OOS Trades
                  </th>
                  <th className="pb-2 text-center font-semibold text-muted-foreground uppercase tracking-wider">
                    Verdict
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/50">
                {entries.map((e) => {
                  const pEdgePass = e.p_edge != null && e.p_edge >= P_EDGE_FLOOR;
                  const pfPass = e.pf_ci_lower != null && e.pf_ci_lower >= PF_CI_FLOOR;
                  const dsrPass = e.dsr != null && e.dsr >= DSR_FLOOR;
                  return (
                    <tr
                      key={e.source_file ?? strategyLabel(e.symbol, e.family)}
                      className="hover:bg-muted/20 transition-colors"
                    >
                      <td className="py-2.5 pr-4 font-medium text-foreground whitespace-nowrap">
                        {strategyLabel(e.symbol, e.family)}
                      </td>
                      <td
                        className={`py-2.5 pr-4 text-right font-mono tabular-nums font-semibold ${pEdgePass ? "text-bull" : "text-bear"}`}
                      >
                        {fmtNum(e.p_edge)}
                      </td>
                      <td
                        className={`py-2.5 pr-4 text-right font-mono tabular-nums font-semibold ${pfPass ? "text-bull" : "text-bear"}`}
                      >
                        {fmtNum(e.pf_ci_lower)}
                      </td>
                      <td
                        className={`py-2.5 pr-4 text-right font-mono tabular-nums font-semibold ${dsrPass ? "text-bull" : "text-bear"}`}
                      >
                        {fmtNum(e.dsr)}
                      </td>
                      <td className="py-2.5 pr-4 text-right font-mono tabular-nums text-muted-foreground">
                        {e.n_oos_trades ?? "—"}
                      </td>
                      <td className="py-2.5 text-center">
                        <span
                          className={`inline-block rounded-full border px-2.5 py-0.5 text-[10px] font-bold tracking-wider ${verdictChipClasses(e.verdict)}`}
                        >
                          {e.verdict ?? "—"}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ── Section 2: Monte Carlo Risk (live) ───────────────────────────────────────

function signedPct(v: number | null): { text: string; cls: string } {
  if (v == null || !Number.isFinite(v))
    return { text: "—", cls: "text-muted-foreground" };
  return {
    text: `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`,
    cls: v >= 0 ? "text-bull" : "text-bear",
  };
}

function MonteCarloCard() {
  const { data, error, isLoading } = useSWR<MonteCarloResponse>(
    "/analytics/monte-carlo",
    fetcher,
    ANALYTICS_SWR,
  );
  const entries = data?.entries ?? [];

  return (
    <Card>
      <CardContent className="pt-5 pb-5">
        <div className="flex items-center gap-2 mb-4">
          <div className="flex h-7 w-7 items-center justify-center rounded-md bg-info/20">
            <BarChart3 className="h-4 w-4 text-info" />
          </div>
          <div>
            <p className="text-xs font-semibold uppercase tracking-widest text-info">
              Monte Carlo Risk
            </p>
            <p className="text-[10px] text-muted-foreground">
              Gate-v2 95th-pctile drawdown per strategy; return percentiles where a live sim exists
            </p>
          </div>
          {data && (
            <span className="ml-auto">
              <Badge variant="info">
                {data.n_with_artifact}/{data.total} with sim
              </Badge>
            </span>
          )}
        </div>

        {entries.length === 0 ? (
          <AwaitingAnalytics
            loading={isLoading && !error}
            message={
              error
                ? "/analytics/monte-carlo unreachable — engine restart pending to deploy live validation analytics."
                : isLoading
                  ? "Loading Monte Carlo risk…"
                  : "No gate-v2 verdicts on disk yet."
            }
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border">
                  <th className="pb-2 pr-4 text-left font-semibold text-muted-foreground uppercase tracking-wider">
                    Strategy
                  </th>
                  <th className="pb-2 pr-4 text-right font-semibold text-muted-foreground uppercase tracking-wider whitespace-nowrap">
                    MC 95th DD
                  </th>
                  <th className="pb-2 pr-4 text-right font-semibold text-muted-foreground uppercase tracking-wider">
                    P5
                  </th>
                  <th className="pb-2 pr-4 text-right font-semibold text-muted-foreground uppercase tracking-wider">
                    Median
                  </th>
                  <th className="pb-2 pr-4 text-right font-semibold text-muted-foreground uppercase tracking-wider">
                    P95
                  </th>
                  <th className="pb-2 text-right font-semibold text-muted-foreground uppercase tracking-wider whitespace-nowrap">
                    95% VaR
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/50">
                {entries.map((e) => {
                  const dd = e.mc_95th_dd_pct;
                  const ddCls =
                    dd == null
                      ? "text-muted-foreground"
                      : dd <= 5
                        ? "text-bull"
                        : dd <= 8
                          ? "text-warn"
                          : "text-bear";
                  const p5 = signedPct(e.return_p5);
                  const med = signedPct(e.return_median);
                  const p95 = signedPct(e.return_p95);
                  return (
                    <tr
                      key={e.source_file ?? strategyLabel(e.symbol, e.family)}
                      className="hover:bg-muted/20 transition-colors"
                    >
                      <td className="py-2.5 pr-4 whitespace-nowrap">
                        <span className="font-mono font-bold text-foreground">
                          {strategyLabel(e.symbol, e.family)}
                        </span>
                        {e.timeframe && (
                          <span className="ml-1.5 text-muted-foreground">{e.timeframe}</span>
                        )}
                        {e.degenerate && (
                          <span
                            className="ml-1.5 text-[9px] text-warn"
                            title="MC artifact percentiles collapsed — only the gate drawdown is trustworthy"
                          >
                            stale sim
                          </span>
                        )}
                      </td>
                      <td
                        className={`py-2.5 pr-4 text-right font-mono tabular-nums font-semibold ${ddCls}`}
                      >
                        {dd != null ? `${dd.toFixed(2)}%` : "—"}
                      </td>
                      <td
                        className={`py-2.5 pr-4 text-right font-mono tabular-nums font-semibold ${p5.cls}`}
                      >
                        {p5.text}
                      </td>
                      <td
                        className={`py-2.5 pr-4 text-right font-mono tabular-nums font-semibold ${med.cls}`}
                      >
                        {med.text}
                      </td>
                      <td
                        className={`py-2.5 pr-4 text-right font-mono tabular-nums font-semibold ${p95.cls}`}
                      >
                        {p95.text}
                      </td>
                      <td className="py-2.5 text-right font-mono tabular-nums text-foreground">
                        {e.capital_at_risk_95 != null
                          ? formatCurrency(e.capital_at_risk_95)
                          : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        <div className="mt-3 rounded-lg border border-info/20 bg-info/5 px-3 py-2 text-[11px] text-info leading-relaxed">
          MC 95th-percentile drawdown is the gate-v2 risk gate (PASS ≤ 5%, ALT routing ≤ 4%).
          Return percentiles appear only when a non-degenerate Monte Carlo artifact exists on
          disk; otherwise the gate drawdown is the canonical signal.
        </div>
      </CardContent>
    </Card>
  );
}

// ── Section 3: Parameter Sensitivity (live) ──────────────────────────────────

function sensLevelClasses(level: string): string {
  const l = level.toUpperCase();
  if (l === "LOW") return "bg-bull/10 border-bull/20 text-bull";
  if (l === "MEDIUM") return "bg-warn/10 border-warn/20 text-warn";
  return "bg-bear/10 border-bear/20 text-bear";
}

function ParameterSensitivityCard() {
  const { data, error, isLoading } = useSWR<SensitivityResponse>(
    "/analytics/sensitivity",
    fetcher,
    ANALYTICS_SWR,
  );
  const entries = data?.entries ?? [];
  const rows = entries.flatMap((e) =>
    e.params.map((p, i) => ({
      key: `${e.source_file ?? strategyLabel(e.symbol, e.family)}-${p.parameter}`,
      strategy: i === 0 ? strategyLabel(e.symbol, e.family) : "",
      param: p,
    })),
  );

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
              PF spread across each tunable parameter&apos;s grid. LOW = robust, HIGH = fragile.
            </p>
          </div>
        </div>

        {rows.length === 0 ? (
          <AwaitingAnalytics
            loading={isLoading && !error}
            message={
              error
                ? "/analytics/sensitivity unreachable — engine restart pending to deploy live validation analytics."
                : isLoading
                  ? "Loading parameter sensitivity…"
                  : "No tunable-parameter grids found in gate-v2 verdicts."
            }
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border">
                  <th className="pb-2 pr-4 text-left font-semibold text-muted-foreground uppercase tracking-wider">
                    Strategy
                  </th>
                  <th className="pb-2 pr-4 text-left font-semibold text-muted-foreground uppercase tracking-wider">
                    Parameter
                  </th>
                  <th className="pb-2 pr-4 text-right font-semibold text-muted-foreground uppercase tracking-wider whitespace-nowrap">
                    PF Range
                  </th>
                  <th className="pb-2 pr-4 text-right font-semibold text-muted-foreground uppercase tracking-wider">
                    ± Spread
                  </th>
                  <th className="pb-2 pr-4 text-right font-semibold text-muted-foreground uppercase tracking-wider">
                    Best
                  </th>
                  <th className="pb-2 text-center font-semibold text-muted-foreground uppercase tracking-wider">
                    Level
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/50">
                {rows.map((r) => (
                  <tr key={r.key} className="hover:bg-muted/20 transition-colors">
                    <td className="py-2.5 pr-4 font-medium text-foreground whitespace-nowrap">
                      {r.strategy}
                    </td>
                    <td className="py-2.5 pr-4 font-mono text-muted-foreground">
                      {r.param.parameter}
                    </td>
                    <td className="py-2.5 pr-4 text-right font-mono tabular-nums text-muted-foreground whitespace-nowrap">
                      {fmtNum(r.param.pf_min)} → {fmtNum(r.param.pf_max)}
                    </td>
                    <td className="py-2.5 pr-4 text-right font-mono tabular-nums text-foreground">
                      ±{fmtNum(r.param.half_spread)}
                    </td>
                    <td className="py-2.5 pr-4 text-right font-mono tabular-nums text-accent">
                      {r.param.best_value != null ? String(r.param.best_value) : "—"}
                    </td>
                    <td className="py-2.5 text-center">
                      <span
                        className={`inline-block rounded-full border px-2 py-0.5 text-[10px] font-bold tracking-wider ${sensLevelClasses(r.param.level)}`}
                      >
                        {r.param.level}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div className="mt-3 rounded-lg border border-border bg-muted/30 px-3 py-2 text-[11px] text-muted-foreground leading-relaxed">
          Spread is the PF range as each parameter is swept across the gate-v2 combo grid
          (others held). LOW (±&lt;0.15) = robust; MEDIUM (±&lt;0.30); HIGH = fragile to that knob.
        </div>
      </CardContent>
    </Card>
  );
}

// ── Section 4: Statistical Significance (live) ───────────────────────────────

function StatisticalSignificanceCard() {
  const { data, error, isLoading } = useSWR<SignificanceResponse>(
    "/analytics/significance",
    fetcher,
    ANALYTICS_SWR,
  );
  const entries = data?.entries ?? [];

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
              OOS profit-factor t-test + gate-v2 edge probability per strategy
            </p>
          </div>
          {entries.length > 0 && (
            <span className="ml-auto">
              <Badge variant={data && data.n_significant > 0 ? "bull" : "neutral"}>
                {data?.n_significant ?? 0} SIGNIFICANT
              </Badge>
            </span>
          )}
        </div>

        {entries.length === 0 ? (
          <AwaitingAnalytics
            loading={isLoading && !error}
            message={
              error
                ? "/analytics/significance unreachable — engine restart pending to deploy live validation analytics."
                : isLoading
                  ? "Loading statistical significance…"
                  : "No gate-v2 verdicts on disk yet."
            }
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border">
                  <th className="pb-2 pr-4 text-left font-semibold text-muted-foreground uppercase tracking-wider">
                    Strategy
                  </th>
                  <th className="pb-2 pr-4 text-right font-semibold text-muted-foreground uppercase tracking-wider whitespace-nowrap">
                    Mean OOS PF
                  </th>
                  <th className="pb-2 pr-4 text-right font-semibold text-muted-foreground uppercase tracking-wider">
                    t-Stat
                  </th>
                  <th className="pb-2 pr-4 text-right font-semibold text-muted-foreground uppercase tracking-wider">
                    p_edge
                  </th>
                  <th className="pb-2 pr-4 text-right font-semibold text-muted-foreground uppercase tracking-wider">
                    DSR
                  </th>
                  <th className="pb-2 pr-4 text-right font-semibold text-muted-foreground uppercase tracking-wider whitespace-nowrap">
                    Windows
                  </th>
                  <th className="pb-2 text-center font-semibold text-muted-foreground uppercase tracking-wider">
                    Result
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/50">
                {entries.map((e) => (
                  <tr
                    key={e.source_file ?? strategyLabel(e.symbol, e.family)}
                    className="hover:bg-muted/20 transition-colors"
                  >
                    <td className="py-2.5 pr-4 font-medium text-foreground whitespace-nowrap">
                      {strategyLabel(e.symbol, e.family)}
                    </td>
                    <td
                      className={`py-2.5 pr-4 text-right font-mono tabular-nums font-semibold ${e.mean_oos_pf != null && e.mean_oos_pf >= 1 ? "text-bull" : "text-bear"}`}
                    >
                      {fmtNum(e.mean_oos_pf)}
                    </td>
                    <td
                      className={`py-2.5 pr-4 text-right font-mono tabular-nums font-semibold ${e.t_stat != null && e.t_stat >= 2 ? "text-bull" : "text-muted-foreground"}`}
                    >
                      {fmtNum(e.t_stat, 2)}
                    </td>
                    <td
                      className={`py-2.5 pr-4 text-right font-mono tabular-nums font-semibold ${e.p_edge != null && e.p_edge >= P_EDGE_FLOOR ? "text-bull" : "text-muted-foreground"}`}
                    >
                      {fmtNum(e.p_edge)}
                    </td>
                    <td className="py-2.5 pr-4 text-right font-mono tabular-nums text-muted-foreground">
                      {fmtNum(e.dsr)}
                    </td>
                    <td className="py-2.5 pr-4 text-right font-mono tabular-nums text-muted-foreground">
                      {e.n_windows ?? "—"}
                    </td>
                    <td className="py-2.5 text-center">
                      {e.significant ? (
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
        )}

        <div className="mt-3 rounded-lg border border-border bg-muted/30 px-3 py-2 text-[11px] text-muted-foreground leading-relaxed">
          <span className="font-semibold text-foreground">Interpretation:</span>{" "}
          t-stat &gt; 2.0 marks OOS profit factor as distinguishable from break-even (PF = 1.0);
          p_edge ≥ 0.95 is the gate-v2 edge probability. A strategy is flagged SIGNIFICANT when its
          gate-v2 p_edge clears 0.95.
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
            <p className="tabular-nums text-lg font-bold font-mono text-muted-foreground">
              —
            </p>
            <p className="text-[10px] mt-0.5 text-muted-foreground leading-tight">
              not computed from deduped record
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
      // Sharpe is intentionally null in the honest deduped record — annualized
      // Sharpe cannot be derived from symbol/direction/entry_time/exit_time/pnl_usd.
      // pass=null prevents a fabricated PASS; the "—" label makes the gap visible.
      metric: "Sharpe Ratio",
      backtest: fmtBaselineNum(baseline?.sharpeRatio ?? null),
      live: "— (not computed from deduped record)",
      threshold: `> ${THRESHOLDS.sharpeRatio}`,
      pass: null,
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
    // Key is a stable string; honestPerformanceFetcher ignores the key and fetches
    // from fetchHonestTrades() which calls the deduped /master/trading/realized endpoint.
  } = useSWR<ValidationReport>("honest-performance", honestPerformanceFetcher, {
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
        <WidgetErrorBoundary name="Backtest vs Paper">
          <BacktestVsPaperWidget />
        </WidgetErrorBoundary>

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
              <p className="text-sm font-semibold text-bear">Engine offline or honest trade record unavailable</p>
              <p className="text-xs text-muted-foreground mt-0.5">
                Ensure the JARVIS engine is running and reachable through the dashboard proxy, and{" "}
                <code className="font-mono">/master/trading/realized</code> is responding (the deduped trade source).
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
          <WidgetErrorBoundary name="Export Data">
            <ExportDataWidget />
          </WidgetErrorBoundary>
        </section>

        {/* Section I: Position Reconciliation */}
        <section>
          <SectionLabel>I — Position Reconciliation</SectionLabel>
          <WidgetErrorBoundary name="Reconciliation">
            <ReconciliationWidget />
          </WidgetErrorBoundary>
        </section>

        {/* Section J: Go-Live Roadmap */}
        <section>
          <SectionLabel>J — Go-Live Roadmap</SectionLabel>
          <GoLivePlanCard />
        </section>

        {/* Section K: WFE Live Monitor */}
        <section>
          <SectionLabel>K — Walk-Forward Efficiency Monitor</SectionLabel>
          <WidgetErrorBoundary name="WFE Monitor">
            <WFEMonitorWidget />
          </WidgetErrorBoundary>
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
