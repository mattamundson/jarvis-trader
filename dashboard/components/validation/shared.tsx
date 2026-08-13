"use client";

// Shared fetchers, formatting helpers, and small UI atoms used by more than one
// /validation workspace section. Extracted verbatim from the former monolithic
// app/validation/page.tsx (PRB dashboard-hardening Task 3) -- no calculation,
// endpoint, label, or error-handling behavior changed, only relocated.

import React from "react";
import { CheckCircle2, XCircle, WifiOff } from "lucide-react";
import { fetchEngine } from "@/lib/api";
import type { ValidationReport } from "@/lib/api";
import {
  fetchHonestTrades,
  maxDrawdownPct,
  dedupCaveat,
} from "@/lib/honestTrades";

// ── Constants — strategy params (canonical STC; not symbol-specific) ─────────

export const STRATEGY_COPY = "STC (OS=15, OB=83) + ATR Stop (0.70x) + Regime Filter";
export const ATR_STOP_LABEL = "0.70x";
export const T1_TARGET_LABEL = "1.50x";

export const THRESHOLDS = {
  profitFactor: 2.0,
  sharpeRatio: 1.5,
  maxDrawdown: 0.1, // 10%
  minTrades: 10,
};

export const REFRESH_MS = 30_000;

// ── Fetcher ───────────────────────────────────────────────────────────────────

export function fetcher<T>(path: string): Promise<T> {
  return fetchEngine<T>(path);
}

// ── Honest performance adapter ────────────────────────────────────────────────
// Replaces the former /analytics/performance fetcher that returned the inflated
// raw-engine counts (~29 rows → fabricated +$3,899 / PF 2.95 / 19 trades).
// Now sources everything from fetchHonestTrades() which applies the dedup
// (18 real trades, -$8,188, PF 0.66). Sharpe is NOT in the deduped record
// (only symbol/direction/entry_time/exit_time/pnl_usd/grade are available),
// so it is surfaced as null / "not computed" — no fabricated PASS.

export async function honestPerformanceFetcher(): Promise<ValidationReport> {
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

export function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground mb-3">
      {children}
    </p>
  );
}

export function MetricPill({
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

export function PassIcon({ pass }: { pass: boolean | null }) {
  if (pass === null) return <span className="text-muted-foreground text-xs">—</span>;
  if (pass)
    return <CheckCircle2 className="h-4 w-4 text-bull mx-auto" />;
  return <XCircle className="h-4 w-4 text-bear mx-auto" />;
}

// ── Live validation analytics (gate-v2 verdicts via /analytics/*) ─────────────
// These four cards replace the former hardcoded static blocks. All data is live
// from the engine's /analytics/{significance,sensitivity,monte-carlo} endpoints,
// which read the same gate-v2 verdict JSONs the strategy ledger uses.

export interface SignificanceEntry {
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

export interface SignificanceResponse {
  entries: SignificanceEntry[];
  total: number;
  n_significant: number;
  p_edge_threshold: number;
  generated_at: string;
}

export interface SensitivityParam {
  parameter: string;
  pf_min: number;
  pf_max: number;
  pf_spread: number;
  half_spread: number;
  best_value: unknown;
  level: string;
}

export interface SensitivityEntry {
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

export interface SensitivityResponse {
  entries: SensitivityEntry[];
  total: number;
  generated_at: string;
}

export interface MonteCarloEntry {
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

export interface MonteCarloResponse {
  entries: MonteCarloEntry[];
  total: number;
  n_with_artifact: number;
  generated_at: string;
}

export const ANALYTICS_SWR = { refreshInterval: 60_000, revalidateOnFocus: false } as const;

export const P_EDGE_FLOOR = 0.95; // gate-v2 edge threshold
export const PF_CI_FLOOR = 1.1; // gate-v2 PF lower-CI floor
export const DSR_FLOOR = 0.1; // gate-v2 deflated-Sharpe floor

export function fmtNum(v: number | null | undefined, decimals = 2): string {
  return v != null && Number.isFinite(v) ? v.toFixed(decimals) : "—";
}

export function verdictChipClasses(verdict: string | null | undefined): string {
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

export function strategyLabel(symbol: string | null, family: string | null): string {
  const s = symbol ?? "—";
  return family ? `${s} · ${family}` : s;
}

/**
 * Honest placeholder shown while an analytics endpoint is unreachable (e.g. an
 * engine restart is pending to deploy the route) or has returned no rows. Never
 * fabricates data — the whole point of de-staticing these cards.
 */
export function AwaitingAnalytics({ loading, message }: { loading: boolean; message: string }) {
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
