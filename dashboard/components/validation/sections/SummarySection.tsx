"use client";

// Validation workspace — "summary" section (default view).
//
// Holds the strategy-readiness verdict evidence: live gate-v2 scorecards,
// instrument approval gates, MES re-validation/forward-recorder progress,
// Monte Carlo / parameter-sensitivity / statistical-significance analytics,
// trading-phase status, and the operator tools (simulate trade, position
// sizing, go-live roadmap) that don't belong to a specific drill-down.
// Extracted verbatim from the former app/validation/page.tsx Sections
// 1, 1B, 1C, 1D, 2, 3, 4, D, E, G, J (PRB dashboard-hardening Task 3) — no
// calculation, label, or error-handling behavior changed, only relocated.
// Also renders the summary-card links into the paper/backtest/wfe/
// reconciliation/audit drill-down sections (Step 4 of the task brief).

import React, { useState } from "react";
import useSWR from "swr";
import Link from "next/link";
import {
  ShieldCheck,
  WifiOff,
  BarChart3,
  Gauge,
  Sigma,
  CheckCircle2,
  XCircle,
  Clock,
  Lock,
  Play,
} from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ResultLabel } from "@/components/ResultLabel";
import { fetchApprovedPaperGates } from "@/lib/api";
import { formatCurrency } from "@/lib/utils";
import type { ValidationReport, ApprovedPaperGatesResponse } from "@/lib/api";
import { eligibilityRows, eligibleCount } from "@/lib/tradingEligibility";
import { simulateTrade } from "@/lib/settings-api";
import type { SimulateTradePayload, SimulateTradeResult } from "@/lib/settings-api";
import { PositionSizingCalculator } from "@/components/PositionSizingCalculator";
import { GoLivePlanCard } from "@/components/GoLivePlanCard";
import { InstrumentEligibilityCard } from "@/components/InstrumentEligibilityCard";
import { MESRevalidationTracker } from "@/components/MESRevalidationTracker";
import { MESForwardRecorderPanel } from "@/components/MESForwardRecorderPanel";
import {
  type BacktestBaselineRow,
  fmtBaselineNum,
  pickApprovedBacktestBaseline,
  type ScorecardBacktestBaseline,
} from "@/lib/scorecardBaseline";
import {
  DEFAULT_BRIEFING_SYMBOLS,
  ALL_TRACKED_SYMBOLS,
  PREFERRED_BASELINE_LABEL,
} from "@/lib/approvedSymbols";
import { VALIDATION_SECTIONS } from "@/components/validation/validationSections";
import {
  SectionLabel,
  fetcher,
  honestPerformanceFetcher,
  THRESHOLDS,
  REFRESH_MS,
  ANALYTICS_SWR,
  P_EDGE_FLOOR,
  PF_CI_FLOOR,
  DSR_FLOOR,
  fmtNum,
  verdictChipClasses,
  strategyLabel,
  AwaitingAnalytics,
  type SignificanceResponse,
  type SensitivityResponse,
  type MonteCarloResponse,
} from "@/components/validation/shared";

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

// ── Section 1B: Instrument Approval Gates (live, PRB-36) ─────────────────────
// Was InstrumentValidationScorecard.tsx: a static per-symbol WFE/status
// override table (INSTRUMENT_STATUS in lib/approvedSymbols.ts) that hardcoded
// MES/MGC=APPROVED WFE 1.00 and MCL/MNQ=HALTED WFE 0.00 regardless of live
// data, with a fabricated "APPROVED" fallback for any symbol the live gates
// endpoint didn't return a row for -- a fail-open default in the one place
// that should never have one. Replaced with the live-sourced pattern PRB-25
// already built for /trading-eligibility: every row read straight off
// GET /paper/validation/approved-paper-gates via eligibilityRows(), zero
// hardcoded symbol table, rendered with the same InstrumentEligibilityCard
// this section now shares with /trading-eligibility (no reinvented UI).

function InstrumentEligibilityGatesCard() {
  const { data, error, isLoading } = useSWR<ApprovedPaperGatesResponse>(
    "/paper/validation/approved-paper-gates",
    () => fetchApprovedPaperGates(),
    { refreshInterval: REFRESH_MS, revalidateOnFocus: false },
  );
  const rows = eligibilityRows(data);
  const nEligible = eligibleCount(rows);

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <p className="text-[11px] text-muted-foreground">
          Live from{" "}
          <code className="font-mono">GET /paper/validation/approved-paper-gates</code>{" "}
          — no hardcoded per-symbol overrides.{" "}
          <a href="/trading-eligibility" className="text-accent hover:underline">
            Full eligibility view →
          </a>
        </p>
        {data && (
          <Badge variant={nEligible > 0 ? "bull" : "neutral"}>
            {nEligible}/{rows.length} eligible
          </Badge>
        )}
      </div>

      {error && (
        <div className="flex items-center gap-2 p-3 bg-bear/10 border border-bear/20 text-bear rounded-lg text-xs">
          <WifiOff className="h-3.5 w-3.5 shrink-0" />
          /paper/validation/approved-paper-gates unreachable — engine may be down
          or restarting. Not showing stale data.
        </div>
      )}

      {isLoading && !data && !error && (
        <p className="text-xs text-muted-foreground py-4 text-center">
          Loading live eligibility gates…
        </p>
      )}

      {data && rows.length === 0 && !error && (
        <div className="p-4 border border-border rounded-xl text-center text-xs text-muted-foreground">
          The engine returned no instruments. Nothing is currently tracked by
          this endpoint.
        </div>
      )}

      {rows.length > 0 && (
        <div className="grid gap-4 md:grid-cols-2">
          {rows.map((row) => (
            <InstrumentEligibilityCard key={row.symbol} row={row} />
          ))}
        </div>
      )}
    </div>
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
            <p className="text-xs font-semibold uppercase tracking-widest text-info flex items-center gap-2">
              Monte Carlo Risk
              <ResultLabel kind="simulated" />
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
                Complete — saved baseline ({PREFERRED_BASELINE_LABEL} preferred); metrics from engine JSON when loaded
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
                Ongoing — Forward-test with live market data
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
                TBD, pending Amo decision — Locked until Phase 2 passes
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

// Derived from the shared instrument constants (D2-03-v2, 2026-07-24) so this
// selector's default can't drift back to a halted symbol — was hardcoded
// ["MCL","MNQ","MES"] defaulting to MCL, which is DO_NOT_TRADE. All four
// symbols stay selectable (this panel is a manual-simulation tool, so
// testing a halted symbol's behavior is still a valid use case); only the
// default changes to the actively-traded pair.
const SYMBOLS = ALL_TRACKED_SYMBOLS;
type Symbol = (typeof SYMBOLS)[number];

const ACTIONS = ["LONG", "SHORT"] as const;
type Action = (typeof ACTIONS)[number];

function SimulateTradePanel() {
  const [symbol, setSymbol] = useState<Symbol>(DEFAULT_BRIEFING_SYMBOLS[0]);
  const [action, setAction] = useState<Action>("LONG");
  const [entryPrice, setEntryPrice] = useState<string>("5000");
  const [stopLoss, setStopLoss] = useState<string>("4990");
  const [quantity, setQuantity] = useState<string>("1");
  const [result, setResult] = useState<SimulateTradeResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  // GT-41: submission is disabled below (button `disabled`) because no backend
  // endpoint implements a non-persisting trade simulation -- see simulateTrade()
  // in settings-api.ts for the full explanation. handleSubmit is kept functional
  // (rather than deleted) purely as a defensive fallback: if the button's
  // `disabled` attribute is ever bypassed, simulateTrade() throws a clear
  // "not yet implemented" error that lands in the existing error UI below
  // instead of silently 404ing or touching live portfolio state.
  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
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
              Manual paper trade simulation — not yet implemented (GT-41)
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
            disabled
            title="Disabled (GT-41): the backend endpoint this panel depended on (/test/simulate-trade) was never registered on the engine, and no equivalent non-persisting simulate endpoint exists. Repointing to the real manual-trade route would open an actual paper position instead of a dry-run estimate."
            className="flex items-center gap-2 rounded-md bg-accent px-4 py-2 text-sm font-semibold text-accent-foreground hover:bg-accent/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            <Play className="h-3.5 w-3.5" />
            Simulate Trade (not yet implemented)
          </button>
          <p className="text-[10px] text-muted-foreground">
            Disabled — GT-41: no backend endpoint implements a non-persisting trade
            simulation. See settings-api.ts simulateTrade() for details.
          </p>
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

// ── Drill-down links (Step 4: summary cards link to each section) ────────────

function DrillDownLinks() {
  const links = VALIDATION_SECTIONS.filter((s) => s.id !== "summary");
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
      {links.map((s) => (
        <Link
          key={s.id}
          href={`/validation?section=${s.id}`}
          data-testid={`validation-summary-card-${s.id}`}
          className="rounded-xl border border-border bg-muted/20 p-4 flex flex-col gap-1 hover:border-accent/40 hover:bg-muted/30 transition-colors"
        >
          <span className="text-xs font-semibold uppercase tracking-widest text-foreground">
            {s.label}
          </span>
          <span className="text-[11px] text-muted-foreground leading-snug">{s.summary}</span>
        </Link>
      ))}
    </div>
  );
}

// ── Section — top-level composition ───────────────────────────────────────────

export default function SummarySection() {
  const {
    data: report,
  } = useSWR<ValidationReport>("honest-performance", honestPerformanceFetcher, {
    refreshInterval: REFRESH_MS,
  });

  const { data: backtestRows } = useSWR<BacktestBaselineRow[]>("/backtest/results", fetcher, {
    refreshInterval: REFRESH_MS,
  });
  const scorecardBaseline = pickApprovedBacktestBaseline(backtestRows);

  return (
    <div className="space-y-6">
      <DrillDownLinks />

      {/* Section 1: Strategy Validation Scorecard */}
      <section>
        <SectionLabel>1 — Strategy Validation Scorecard</SectionLabel>
        <ValidationScorecardCard />
      </section>

      {/* Section 1B: Instrument Approval Gates (live, PRB-36) */}
      <section>
        <SectionLabel>1B — Instrument Approval Gates</SectionLabel>
        <InstrumentEligibilityGatesCard />
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

      {/* Section G: Position Sizing Calculator */}
      <section>
        <SectionLabel>G — Position Sizing Calculator</SectionLabel>
        <PositionSizingCalculator />
      </section>

      {/* Section J: Go-Live Roadmap */}
      <section>
        <SectionLabel>J — Go-Live Roadmap</SectionLabel>
        <GoLivePlanCard />
      </section>
    </div>
  );
}
