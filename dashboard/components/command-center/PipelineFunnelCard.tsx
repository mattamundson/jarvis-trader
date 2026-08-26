"use client";

import React from "react";
import useSWR from "swr";
import { Filter, RefreshCw } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchEngine } from "@/lib/api";

/**
 * Pipeline Funnel card (T9) — trade-conversion visibility.
 *
 * Shows the runs -> signals -> approved -> executed -> filled conversion for
 * the last 30 and 90 days so "not enough trades" becomes an inspectable
 * funnel instead of a vague complaint. Data comes from the engine's
 * /analytics/pipeline-funnel endpoint (read-only, 300s TTL cache).
 */

interface FunnelConversion {
  signal_rate_pct: number | null;
  approval_rate_pct: number | null;
  execution_rate_pct: number | null;
  fill_rate_pct: number | null;
  overall_fill_rate_pct: number | null;
}

interface FunnelWindow {
  days: number;
  cutoff_utc: string;
  runs: number;
  signals: number;
  auto_signals: number;
  human_signals: number;
  queue_approved_raw: number;
  approved: number;
  executed: number;
  filled: number;
  conversion: FunnelConversion;
  notes: string[];
}

interface FunnelResponse {
  generated_at: string;
  cache_ttl_seconds: number;
  windows: Record<"30" | "90", FunnelWindow>;
}

type FunnelCountKey = "runs" | "signals" | "approved" | "executed" | "filled";

const STAGE_ROWS: {
  key: FunnelCountKey;
  label: string;
  convKey: keyof FunnelConversion;
  bar: string;
  text: string;
}[] = [
  { key: "runs", label: "RUNS", convKey: "signal_rate_pct", bar: "bg-slate-600", text: "text-slate-300" },
  { key: "signals", label: "SIGNALS", convKey: "signal_rate_pct", bar: "bg-cyan-500", text: "text-cyan-300" },
  { key: "approved", label: "APPROVED", convKey: "approval_rate_pct", bar: "bg-blue-500", text: "text-blue-300" },
  { key: "executed", label: "EXECUTED", convKey: "execution_rate_pct", bar: "bg-amber-500", text: "text-amber-300" },
  { key: "filled", label: "FILLED", convKey: "fill_rate_pct", bar: "bg-green-500", text: "text-green-300" },
];

function fmtPct(pct: number | null | undefined): string {
  if (pct == null || isNaN(pct)) return "—";
  return pct.toFixed(1) + "%";
}

function convColor(pct: number | null | undefined): string {
  if (pct == null || isNaN(pct)) return "text-slate-600";
  if (pct >= 50) return "text-green-400";
  if (pct >= 25) return "text-amber-400";
  return "text-red-400";
}

function FunnelColumn({ window, title }: { window: FunnelWindow; title: string }) {
  const max = Math.max(window.runs, 1);
  return (
    <div data-testid={`pipeline-funnel-${window.days}d`} className="space-y-1.5">
      <div className="flex items-center justify-between mb-1">
        <span className="font-mono text-[10px] tracking-widest text-slate-500">
          {title}
        </span>
        <span className="font-mono text-[10px] text-slate-600">
          since {window.cutoff_utc.slice(0, 10)} UTC
        </span>
      </div>
      {STAGE_ROWS.map((row, i) => {
        const count = window[row.key];
        const widthPct = Math.max((count / max) * 100, count > 0 ? 4 : 0);
        // Conversion shown on the row that measures FROM the previous stage:
        // signals/runs on SIGNALS, approved/signals on APPROVED, etc.
        const conv = i === 0 ? null : (window.conversion[row.convKey] ?? null);
        return (
          <div key={row.key} className="flex items-center gap-2">
            <span className={`font-mono text-[10px] w-[74px] flex-shrink-0 ${row.text}`}>
              {row.label}
            </span>
            <div className="relative flex-1 h-5 bg-slate-950/60 rounded overflow-hidden border border-slate-800/60">
              <div
                className={`absolute inset-y-0 left-0 ${row.bar} opacity-80`}
                style={{ width: `${widthPct}%` }}
              />
              <span className="absolute inset-y-0 left-2 flex items-center font-mono text-[11px] font-bold text-white">
                {count.toLocaleString()}
              </span>
            </div>
            <span className={`font-mono text-[10px] w-[52px] text-right flex-shrink-0 ${convColor(conv)}`}>
              {conv == null ? "—" : fmtPct(conv)}
            </span>
          </div>
        );
      })}
      <div className="flex items-center justify-between mt-2 pt-1.5 border-t border-slate-800/60">
        <span className="font-mono text-[10px] tracking-widest text-slate-400">
          OVERALL CONVERSION
        </span>
        <span
          className={`font-mono text-sm font-bold ${convColor(window.conversion.overall_fill_rate_pct)}`}
        >
          {fmtPct(window.conversion.overall_fill_rate_pct)}
        </span>
      </div>
      <div className="text-[10px] font-mono text-slate-600">
        {window.filled.toLocaleString()} filled of {window.runs.toLocaleString()} runs
        <span className="ml-1 text-slate-700">
          · {window.approved.toLocaleString()} approved ({window.auto_signals.toLocaleString()} auto +{" "}
          {window.human_signals.toLocaleString()} human)
        </span>
      </div>
      {window.notes.length > 0 && (
        <div className="mt-1 space-y-0.5">
          {window.notes.map((n, i) => (
            <p key={i} className="text-[10px] font-mono text-amber-500/80 leading-tight">
              ⚠ {n}
            </p>
          ))}
        </div>
      )}
    </div>
  );
}

export default function PipelineFunnelCard() {
  const { data, error, isLoading, mutate } = useSWR<FunnelResponse>(
    "pipeline-funnel",
    () => fetchEngine<FunnelResponse>("/analytics/pipeline-funnel"),
    { refreshInterval: 60_000, revalidateOnFocus: false, shouldRetryOnError: false }
  );

  return (
    <Card data-testid="pipeline-funnel-card" className="bg-slate-900/60 border border-cyan-900/50">
      <CardHeader className="pb-2 pt-3 px-4">
        <CardTitle className="text-xs font-mono text-cyan-400 tracking-widest flex items-center justify-between gap-1.5">
          <span className="flex items-center gap-1.5">
            <Filter className="w-3 h-3" />
            PIPELINE FUNNEL
          </span>
          <span className="flex items-center gap-2">
            {data && (
              <span className="text-[10px] text-slate-600 font-mono">
                cache {data.cache_ttl_seconds}s · {data.generated_at.slice(11, 19)}Z
              </span>
            )}
            <button
              onClick={() => mutate()}
              className="p-1 rounded hover:bg-slate-800 text-slate-500 hover:text-slate-300 transition-colors"
              aria-label="Refresh pipeline funnel"
              data-testid="pipeline-funnel-refresh"
            >
              <RefreshCw className="w-3.5 h-3.5" />
            </button>
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="px-4 pb-3">
        {isLoading && !data ? (
          <div className="space-y-2 py-2">
            {[0, 1, 2, 3, 4].map((i) => (
              <div key={i} className="h-5 animate-pulse rounded bg-slate-800/60" />
            ))}
          </div>
        ) : error || !data ? (
          <div className="text-xs text-slate-500 font-mono py-4 text-center">
            Pipeline funnel unavailable — engine endpoint /analytics/pipeline-funnel
            {error ? ` (${error instanceof Error ? error.message : "error"})` : ""}
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <FunnelColumn window={data.windows["30"]} title="LAST 30 DAYS" />
            <FunnelColumn window={data.windows["90"]} title="LAST 90 DAYS" />
          </div>
        )}
      </CardContent>
    </Card>
  );
}
