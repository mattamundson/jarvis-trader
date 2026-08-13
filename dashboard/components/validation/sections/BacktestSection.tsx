"use client";

// Validation workspace — "backtest" (backtest reference + comparison) section.
// Extracted verbatim from the former app/validation/page.tsx Sections A and C
// (PRB dashboard-hardening Task 3) — no calculation, label, or error-handling
// behavior changed, only relocated.

import useSWR from "swr";
import { AlertCircle, CheckCircle2, Target, WifiOff } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import type { ValidationReport, CompareToBacktestResponse } from "@/lib/api";
import {
  type BacktestBaselineRow,
  fmtBaselineNum,
  pickApprovedBacktestBaseline,
  type ScorecardBacktestBaseline,
} from "@/lib/scorecardBaseline";
import { PREFERRED_BASELINE_LABEL } from "@/lib/approvedSymbols";
import {
  SectionLabel,
  MetricPill,
  PassIcon,
  STRATEGY_COPY,
  ATR_STOP_LABEL,
  T1_TARGET_LABEL,
  THRESHOLDS,
  REFRESH_MS,
  fetcher,
  honestPerformanceFetcher,
} from "@/components/validation/shared";

// ── Backtest Reference Card ───────────────────────────────────────────────────

function baselineInstrumentLine(baseline: ScorecardBacktestBaseline | null): string {
  if (!baseline) return `No ${PREFERRED_BASELINE_LABEL} baseline JSON`;
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
                ? `Baseline from saved backtest (${PREFERRED_BASELINE_LABEL} preferred)`
                : `Baseline from saved backtest (${PREFERRED_BASELINE_LABEL} preferred) — none loaded`}
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

// ── Section — top-level composition ───────────────────────────────────────────

export default function BacktestSection() {
  const {
    data: report,
    error: reportError,
    isLoading: reportLoading,
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
    <div className="space-y-6">
      {reportLoading && (
        <div className="flex items-center justify-center py-12">
          <div className="h-5 w-5 rounded-full border-2 border-accent border-t-transparent animate-spin mr-3" />
          <span className="text-sm text-muted-foreground">Loading performance data...</span>
        </div>
      )}

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

      {/* Section A: Backtest Reference */}
      <section>
        <SectionLabel>A — Backtest Reference Targets</SectionLabel>
        <BacktestReferenceCard baseline={scorecardBaseline} />
      </section>

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
    </div>
  );
}
