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
//
// The analytics (gate-v2/Monte Carlo/sensitivity/significance) and operator
// (phase status/simulate-trade/position-sizing/go-live) clusters live in
// their own files under sections/ (task-3 review Finding 2, fix round) so
// this file stays a thin composition rather than absorbing all 11 sections
// itself. This is purely internal file organization — the 6 top-level
// section ids/URL contract (summary/paper/backtest/wfe/reconciliation/audit)
// is unchanged.

import useSWR from "swr";
import Link from "next/link";
import { WifiOff } from "lucide-react";
import type { ValidationReport } from "@/lib/api";
import {
  type BacktestBaselineRow,
  pickApprovedBacktestBaseline,
} from "@/lib/scorecardBaseline";
import { VALIDATION_SECTIONS } from "@/components/validation/validationSections";
import { fetcher, honestPerformanceFetcher, REFRESH_MS } from "@/components/validation/shared";
import AnalyticsClusterSection from "@/components/validation/sections/AnalyticsClusterSection";
import OperatorToolsSection from "@/components/validation/sections/OperatorToolsSection";

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
    error: reportError,
    isLoading: reportLoading,
  } = useSWR<ValidationReport>("honest-performance", honestPerformanceFetcher, {
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

      <DrillDownLinks />

      <AnalyticsClusterSection />

      <OperatorToolsSection report={report ?? null} baseline={scorecardBaseline} />
    </div>
  );
}
