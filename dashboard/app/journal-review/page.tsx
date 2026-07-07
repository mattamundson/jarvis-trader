"use client";

import React, { useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import {
  ArrowLeft,
  BarChart2,
  Brain,
  ChevronDown,
  ChevronUp,
  Loader2,
  RefreshCw,
  Sparkles,
  TrendingDown,
  TrendingUp,
} from "lucide-react";
import {
  analyzeJournalPatterns,
  fetchJournalBreakdown,
  fetchJournalStats,
  formalizeInsight,
  type JournalBreakdownRow,
  type JournalFormalizeResult,
  type JournalTradeStats,
} from "@/lib/api";
import {
  fetchHonestTrades,
  dedupCaveat,
  type HonestTradeSet,
} from "@/lib/honestTrades";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function pct(n: number) {
  return `${(n * 100).toFixed(1)}%`;
}

function usd(n: number) {
  return `$${n >= 0 ? "+" : ""}${n.toFixed(2)}`;
}

type DiagnosisLevel = "win_rate" | "avg_loss" | "avg_win" | "solid" | "insufficient_data";

const DIAGNOSIS_STYLES: Record<DiagnosisLevel, string> = {
  win_rate: "text-red-400 border-red-500/30 bg-red-500/10",
  avg_loss: "text-orange-400 border-orange-500/30 bg-orange-500/10",
  avg_win: "text-yellow-400 border-yellow-500/30 bg-yellow-500/10",
  solid: "text-emerald-400 border-emerald-500/30 bg-emerald-500/10",
  insufficient_data: "text-neutral-400 border-neutral-500/30 bg-neutral-500/10",
};

const DIAGNOSIS_LABELS: Record<DiagnosisLevel, string> = {
  win_rate: "Bottleneck: win rate",
  avg_loss: "Bottleneck: avg loss too large",
  avg_win: "Bottleneck: avg win too small",
  solid: "Edge confirmed",
  insufficient_data: "Need more trades",
};

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function StatCard({
  label,
  value,
  sub,
  trend,
}: {
  label: string;
  value: string;
  sub?: string;
  trend?: "up" | "down" | "neutral";
}) {
  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
      <div className="text-xs text-neutral-500 mb-1">{label}</div>
      <div className="flex items-end gap-2">
        <span className="text-2xl font-mono font-semibold text-neutral-100">
          {value}
        </span>
        {trend === "up" && <TrendingUp className="h-4 w-4 text-emerald-400 mb-1" />}
        {trend === "down" && <TrendingDown className="h-4 w-4 text-red-400 mb-1" />}
      </div>
      {sub && <div className="text-xs text-neutral-500 mt-1">{sub}</div>}
    </div>
  );
}

function BreakdownTable({
  title,
  rows,
}: {
  title: string;
  rows: JournalBreakdownRow[];
}) {
  if (!rows.length) return null;
  return (
    <div>
      <h3 className="text-sm font-medium text-neutral-400 mb-2">{title}</h3>
      <div className="overflow-x-auto rounded-lg border border-neutral-800">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-neutral-800 text-neutral-500 text-xs">
              <th className="text-left px-3 py-2">Group</th>
              <th className="text-right px-3 py-2">N</th>
              <th className="text-right px-3 py-2">Win %</th>
              <th className="text-right px-3 py-2">Net P&L</th>
              <th className="text-right px-3 py-2">Avg</th>
              <th className="px-3 py-2"></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr
                key={r.group_value}
                className="border-b border-neutral-800/50 last:border-0 hover:bg-neutral-800/30"
              >
                <td className="px-3 py-2 font-mono text-neutral-200">{r.group_value}</td>
                <td className="px-3 py-2 text-right text-neutral-400">{r.count}</td>
                <td
                  className={`px-3 py-2 text-right font-mono ${
                    r.win_rate >= 0.55
                      ? "text-emerald-400"
                      : r.win_rate < 0.4
                      ? "text-red-400"
                      : "text-neutral-300"
                  }`}
                >
                  {pct(r.win_rate)}
                </td>
                <td
                  className={`px-3 py-2 text-right font-mono ${
                    r.net_pnl >= 0 ? "text-emerald-400" : "text-red-400"
                  }`}
                >
                  {usd(r.net_pnl)}
                </td>
                <td
                  className={`px-3 py-2 text-right font-mono ${
                    r.avg_pnl >= 0 ? "text-emerald-400" : "text-red-400"
                  }`}
                >
                  {usd(r.avg_pnl)}
                </td>
                <td className="px-3 py-2">
                  {r.flagged && (
                    <span className="text-xs px-1.5 py-0.5 rounded border border-yellow-500/30 bg-yellow-500/10 text-yellow-400">
                      {r.win_rate > 0.55 ? "edge" : "weak"}
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function AnalysisMarkdown({ text }: { text: string }) {
  const sections = text.split(/^## /m).filter(Boolean);
  return (
    <div className="space-y-4">
      {sections.map((section, i) => {
        const [heading, ...body] = section.split("\n");
        return (
          <div key={i} className="border-l-2 border-neutral-700 pl-3">
            <div className="text-sm font-semibold text-neutral-200 mb-1">
              {heading.trim()}
            </div>
            <div className="text-sm text-neutral-400 whitespace-pre-wrap">
              {body.join("\n").trim()}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function JournalReviewPage() {
  const [limit, setLimit] = useState(30);
  const [analysisText, setAnalysisText] = useState<string | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [analyzeError, setAnalyzeError] = useState<string | null>(null);

  const [observation, setObservation] = useState("");
  const [formalized, setFormalized] = useState<JournalFormalizeResult | null>(null);
  const [formalizing, setFormalizing] = useState(false);
  const [formalizeError, setFormalizeError] = useState<string | null>(null);

  const [showBreakdown, setShowBreakdown] = useState(false);

  const {
    data: stats,
    error: statsError,
    isLoading: statsLoading,
    mutate: mutateStats,
  } = useSWR<JournalTradeStats>(
    `journal-stats-${limit}`,
    () => fetchJournalStats(limit),
    { shouldRetryOnError: false, errorRetryCount: 0 }
  );

  const {
    data: breakdown,
    isLoading: bdLoading,
  } = useSWR(
    showBreakdown ? `journal-breakdown-${limit}` : null,
    () => fetchJournalBreakdown(limit),
    { shouldRetryOnError: false }
  );

  // Honest deduped aggregates — source of truth for all P&L-derived numbers.
  const { data: honestSet } = useSWR<HonestTradeSet>(
    "honest-trades",
    fetchHonestTrades,
    { shouldRetryOnError: false, errorRetryCount: 0 },
  );

  // Derived honest metrics (undefined while loading, shown as "—" in the UI).
  const honestWinRate: number | undefined =
    honestSet ? honestSet.winRate * 100 : undefined;
  const honestEV: number | undefined =
    honestSet && honestSet.trades.length > 0
      ? honestSet.net / honestSet.trades.length
      : undefined;
  const honestNet: number | undefined = honestSet?.net;
  const honestAvgWin: number | undefined =
    honestSet && honestSet.wins > 0
      ? honestSet.grossWin / honestSet.wins
      : undefined;
  const honestAvgLoss: number | undefined =
    honestSet && honestSet.losses > 0
      ? honestSet.grossLoss / honestSet.losses
      : undefined;
  const honestRR: number | undefined =
    honestAvgWin !== undefined && honestAvgLoss !== undefined && honestAvgLoss > 0
      ? honestAvgWin / honestAvgLoss
      : undefined;

  async function runAnalysis() {
    setAnalyzing(true);
    setAnalyzeError(null);
    setAnalysisText(null);
    try {
      const result = await analyzeJournalPatterns(limit);
      setAnalysisText(result.analysis);
    } catch (e) {
      setAnalyzeError(e instanceof Error ? e.message : "Analysis failed");
    } finally {
      setAnalyzing(false);
    }
  }

  async function runFormalize() {
    if (!observation.trim()) return;
    setFormalizing(true);
    setFormalizeError(null);
    setFormalized(null);
    try {
      const result = await formalizeInsight(observation);
      setFormalized(result);
    } catch (e) {
      setFormalizeError(e instanceof Error ? e.message : "Formalize failed");
    } finally {
      setFormalizing(false);
    }
  }

  const diagKey = (stats?.diagnosis ?? "insufficient_data") as DiagnosisLevel;

  return (
    <div className="min-h-screen bg-neutral-950 text-neutral-100">
      <div className="max-w-5xl mx-auto px-4 py-6 space-y-6">
        {/* Header */}
        <div className="flex items-center gap-3">
          <Link
            href="/journal"
            className="text-neutral-500 hover:text-neutral-300 transition-colors"
          >
            <ArrowLeft className="h-4 w-4" />
          </Link>
          <div>
            <h1 className="text-xl font-semibold text-neutral-100 flex items-center gap-2">
              <Brain className="h-5 w-5 text-violet-400" />
              Journal Review
            </h1>
            <p className="text-xs text-neutral-500 mt-0.5">
              Koroush AK framework — EV, patterns, rules
            </p>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <select
              value={limit}
              onChange={(e) => setLimit(Number(e.target.value))}
              className="text-xs bg-neutral-800 border border-neutral-700 rounded px-2 py-1 text-neutral-300"
            >
              <option value={20}>Last 20 trades</option>
              <option value={30}>Last 30 trades</option>
              <option value={50}>Last 50 trades</option>
              <option value={100}>Last 100 trades</option>
            </select>
            <button
              onClick={() => mutateStats()}
              className="p-1.5 rounded text-neutral-500 hover:text-neutral-300 hover:bg-neutral-800 transition-colors"
            >
              <RefreshCw className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* Stats cards */}
        {statsLoading && (
          <div className="flex items-center gap-2 text-neutral-500 text-sm">
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading stats…
          </div>
        )}

        {!statsLoading && (statsError || !stats) && (
          <div className="rounded border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">
            {statsError
              ? `Failed to load stats — ${statsError instanceof Error ? statsError.message : String(statsError)}`
              : "No stats returned — /api/engine/journal/review/stats may not be available yet."}
          </div>
        )}

        {stats && (
          <>
            {/* Diagnosis banner */}
            <div
              className={`rounded-lg border px-4 py-2.5 text-sm font-medium ${DIAGNOSIS_STYLES[diagKey]}`}
            >
              {DIAGNOSIS_LABELS[diagKey]}
              {honestSet
                ? ` — ${honestSet.trades.length} real trades (${honestSet.rawRows} rows)`
                : ` — ${stats.total_trades} trades analysed`}
            </div>

            {/* Dedup caveat */}
            {honestSet && (
              <div className="text-xs text-neutral-500 -mt-3">
                {dedupCaveat(honestSet)}
                {honestSet.relogged > 0 && (
                  <span className="ml-1 text-amber-500/70">
                    · raw endpoint over-counts re-logged winners
                  </span>
                )}
                {honestNet !== undefined && (
                  <span className={`ml-1 font-mono ${honestNet >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                    · net {usd(honestNet)}
                  </span>
                )}
              </div>
            )}

            {/* Stat grid */}
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
              <StatCard
                label="Win Rate"
                value={honestWinRate !== undefined ? `${honestWinRate.toFixed(1)}%` : "—"}
                trend={
                  honestWinRate !== undefined
                    ? honestWinRate >= 50 ? "up" : "down"
                    : "neutral"
                }
              />
              <StatCard
                label="Avg Win"
                value={honestAvgWin !== undefined ? `$${honestAvgWin.toFixed(0)}` : "—"}
                trend="up"
              />
              <StatCard
                label="Avg Loss"
                value={honestAvgLoss !== undefined ? `$${honestAvgLoss.toFixed(0)}` : "—"}
                trend="down"
              />
              <StatCard
                label="R:R Ratio"
                value={honestRR !== undefined ? honestRR.toFixed(2) : "—"}
                sub="win / loss"
                trend={honestRR !== undefined ? (honestRR >= 1.5 ? "up" : "neutral") : "neutral"}
              />
              <StatCard
                label="EV / Trade"
                value={honestEV !== undefined ? usd(honestEV) : "—"}
                trend={honestEV !== undefined ? (honestEV >= 0 ? "up" : "down") : "neutral"}
              />
              <StatCard
                label="Trades / Wk"
                value={stats.trades_per_week !== undefined ? stats.trades_per_week.toFixed(1) : "—"}
                sub="journal cadence"
              />
            </div>
          </>
        )}

        {/* Breakdown section */}
        <div className="rounded-lg border border-neutral-800 bg-neutral-900">
          <button
            className="w-full flex items-center justify-between px-4 py-3 text-sm font-medium text-neutral-300 hover:text-neutral-100 transition-colors"
            onClick={() => setShowBreakdown(!showBreakdown)}
          >
            <span className="flex items-center gap-2">
              <BarChart2 className="h-4 w-4 text-blue-400" />
              Performance Breakdown
            </span>
            {showBreakdown ? (
              <ChevronUp className="h-4 w-4 text-neutral-500" />
            ) : (
              <ChevronDown className="h-4 w-4 text-neutral-500" />
            )}
          </button>

          {showBreakdown && (
            <div className="px-4 pb-4 space-y-5 border-t border-neutral-800 pt-4">
              {bdLoading && (
                <div className="flex items-center gap-2 text-neutral-500 text-sm">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Loading breakdown…
                </div>
              )}
              {breakdown && (
                <>
                  {breakdown.flags.length > 0 && (
                    <div className="rounded border border-yellow-500/30 bg-yellow-500/10 p-3 text-sm">
                      <span className="text-yellow-400 font-medium">Flags: </span>
                      <span className="text-yellow-300/80">
                        {breakdown.flags
                          .map((f) => `${f.group_value} (${f.flag_reason})`)
                          .join(" · ")}
                      </span>
                    </div>
                  )}
                  <div className="grid md:grid-cols-2 gap-5">
                    <BreakdownTable title="By Symbol" rows={breakdown.by_symbol} />
                    <BreakdownTable title="By Side" rows={breakdown.by_side} />
                    <BreakdownTable title="By Regime" rows={breakdown.by_regime} />
                    <BreakdownTable title="By Bias" rows={breakdown.by_bias} />
                  </div>
                </>
              )}
            </div>
          )}
        </div>

        {/* LLM Analysis */}
        <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-4 space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-medium text-neutral-300 flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-violet-400" />
              Behavioral Pattern Analysis
            </h2>
            <button
              onClick={runAnalysis}
              disabled={analyzing}
              className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded bg-violet-600 hover:bg-violet-500 disabled:opacity-50 disabled:cursor-not-allowed text-white transition-colors"
            >
              {analyzing ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <Brain className="h-3 w-3" />
              )}
              {analyzing ? "Analyzing…" : "Run Analysis"}
            </button>
          </div>

          {analyzeError && (
            <div className="text-sm text-red-400 border border-red-500/30 bg-red-500/10 rounded p-2">
              {analyzeError}
            </div>
          )}

          {!analysisText && !analyzing && !analyzeError && (
            <p className="text-xs text-neutral-600">
              Click Run Analysis to surface emotional patterns, trade duration stats, and one
              concrete rule from your last {limit} trades.
            </p>
          )}

          {analysisText && <AnalysisMarkdown text={analysisText} />}
        </div>

        {/* Formalize */}
        <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-4 space-y-3">
          <h2 className="text-sm font-medium text-neutral-300 flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-cyan-400" />
            Formalize an Observation
          </h2>
          <p className="text-xs text-neutral-600">
            Turn a fuzzy pattern into a falsifiable rule with pass/fail thresholds.
          </p>
          <div className="flex gap-2">
            <input
              value={observation}
              onChange={(e) => setObservation(e.target.value)}
              placeholder="e.g. I win more on MES longs in bullish regimes"
              className="flex-1 text-sm bg-neutral-800 border border-neutral-700 rounded px-3 py-2 text-neutral-200 placeholder:text-neutral-600 focus:outline-none focus:border-cyan-500/50"
            />
            <button
              onClick={runFormalize}
              disabled={formalizing || !observation.trim()}
              className="flex items-center gap-1.5 text-xs px-3 py-2 rounded bg-cyan-700 hover:bg-cyan-600 disabled:opacity-50 disabled:cursor-not-allowed text-white transition-colors whitespace-nowrap"
            >
              {formalizing ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <Sparkles className="h-3 w-3" />
              )}
              {formalizing ? "Formalizing…" : "Formalize"}
            </button>
          </div>

          {formalizeError && (
            <div className="text-sm text-red-400 border border-red-500/30 bg-red-500/10 rounded p-2">
              {formalizeError}
            </div>
          )}

          {formalized && (
            <div className="space-y-3 pt-1">
              <div className="rounded border border-neutral-700 bg-neutral-800/50 p-3 space-y-2 text-sm">
                <div>
                  <span className="text-neutral-500 text-xs uppercase tracking-wide">
                    Pressure test
                  </span>
                  <p className="text-neutral-300 mt-0.5">{formalized.pressure_tested}</p>
                </div>
                <div>
                  <span className="text-neutral-500 text-xs uppercase tracking-wide">Rule</span>
                  <p className="text-cyan-300 font-medium mt-0.5">{formalized.falsifiable_rule}</p>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <span className="text-neutral-500 text-xs uppercase tracking-wide">Pass</span>
                    <p className="text-emerald-400 mt-0.5 text-xs">{formalized.pass_threshold}</p>
                  </div>
                  <div>
                    <span className="text-neutral-500 text-xs uppercase tracking-wide">Fail</span>
                    <p className="text-red-400 mt-0.5 text-xs">{formalized.fail_threshold}</p>
                  </div>
                </div>
                {formalized.abandonment_criteria && (
                  <div>
                    <span className="text-neutral-500 text-xs uppercase tracking-wide">
                      Abandon when
                    </span>
                    <p className="text-orange-300/80 mt-0.5 text-xs">
                      {formalized.abandonment_criteria}
                    </p>
                  </div>
                )}
                {formalized.journal_columns.length > 0 && (
                  <div>
                    <span className="text-neutral-500 text-xs uppercase tracking-wide">
                      Track columns
                    </span>
                    <div className="flex gap-1 flex-wrap mt-1">
                      {formalized.journal_columns.map((c) => (
                        <span
                          key={c}
                          className="text-xs px-1.5 py-0.5 rounded border border-neutral-600 bg-neutral-800 text-neutral-300"
                        >
                          {c}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
                <div className="text-xs text-neutral-600">
                  Sample size target: {formalized.sample_size} trades
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
