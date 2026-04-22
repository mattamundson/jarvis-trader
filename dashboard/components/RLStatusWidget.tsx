"use client";

import useSWR from "swr";
import { Brain, Cpu, TrendingUp, Activity } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { fetchEngine } from "@/lib/api";

// ── Types ─────────────────────────────────────────────────────────────────

interface RLRunEntry {
  run_id: string;
  symbol: string;
  status: string;
  started_at: string;
  completed_at?: string | null;
}

interface RLLastResult {
  sharpe?: number;
  win_rate?: number;
  total_trades?: number;
  pf?: number;
  symbol?: string;
  run_id?: string;
}

interface RLStatusResponse {
  training_active: boolean;
  current_symbol?: string | null;
  started_at?: string | null;
  progress_pct: number;
  last_result?: RLLastResult | null;
  error?: string | null;
  recent_runs: RLRunEntry[];
  walkforward_windows: unknown[];
  walkforward_n_windows: number;
  walkforward_complete: boolean;
}

// STC reference metrics for A/B comparison (static reference — not live)
const STC_REFERENCE = {
  sharpe: 0.87,
  win_rate: 0.58,
  symbol: "MCL",
};

// ── Helpers ───────────────────────────────────────────────────────────────

function fetcher<T = unknown>(path: string): Promise<T> {
  return fetchEngine<T>(path);
}

function trainingBadgeVariant(
  data: RLStatusResponse
): "bull" | "warn" | "bear" | "neutral" | "info" {
  if (data.training_active) return "info";
  if (data.error) return "bear";
  if (data.last_result) return "bull";
  return "neutral";
}

function trainingLabel(data: RLStatusResponse): string {
  if (data.training_active) return "TRAINING";
  if (data.error) return "ERROR";
  if (data.last_result) return "ACTIVE";
  return "IDLE";
}

function metricColor(value: number, good: number, warn: number): string {
  if (value >= good) return "text-bull";
  if (value >= warn) return "text-warn";
  return "text-bear";
}

function formatTimestamp(ts?: string | null): string {
  if (!ts) return "—";
  try {
    return new Date(ts).toLocaleString("en-US", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return ts;
  }
}

// ── Widget ────────────────────────────────────────────────────────────────

export function RLStatusWidget() {
  const { data, error } = useSWR<RLStatusResponse>(
    "/strategies/rl/status",
    fetcher,
    { refreshInterval: 30_000, shouldRetryOnError: false }
  );

  const loading = !data && !error;

  // ── Loading ──
  if (loading) {
    return (
      <div className="rounded-xl border border-zinc-800 bg-zinc-950 p-4">
        <div className="flex items-center gap-2 mb-4">
          <Brain className="h-4 w-4 text-cyan-400" />
          <span className="font-mono text-[11px] font-bold tracking-widest uppercase text-cyan-400">
            RL Strategy Status
          </span>
        </div>
        <div className="space-y-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-8 animate-pulse rounded bg-zinc-800/50" />
          ))}
        </div>
      </div>
    );
  }

  // ── Error / offline ──
  if (error || !data) {
    return (
      <div className="rounded-xl border border-zinc-800 bg-zinc-950 p-4">
        <div className="flex items-center gap-2 mb-3">
          <Brain className="h-4 w-4 text-zinc-500" />
          <span className="font-mono text-[11px] font-bold tracking-widest uppercase text-zinc-500">
            RL Strategy Status
          </span>
          <Badge variant="neutral" className="ml-auto">OFFLINE</Badge>
        </div>
        <p className="text-xs text-muted-foreground font-mono">Engine unavailable.</p>
      </div>
    );
  }

  const statusVariant = trainingBadgeVariant(data);
  const label = trainingLabel(data);
  const res = data.last_result;
  const latestRun = data.recent_runs?.[0];
  const hasComparison = res && typeof res.sharpe === "number";

  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-950 p-4 space-y-3">
      {/* Header */}
      <div className="flex items-center gap-2">
        <Brain className="h-4 w-4 text-cyan-400" />
        <span className="font-mono text-[11px] font-bold tracking-widest uppercase text-cyan-400">
          RL Strategy Status
        </span>
        <Badge variant={statusVariant} className="ml-auto">{label}</Badge>
      </div>

      <div className="h-px bg-zinc-800" />

      {/* Training progress bar */}
      {data.training_active && (
        <div className="space-y-1">
          <div className="flex items-center justify-between">
            <span className="font-mono text-[10px] text-zinc-400 uppercase tracking-wider">
              Training {data.current_symbol ?? "…"}
            </span>
            <span className="font-mono text-[10px] text-cyan-400 tabular-nums">
              {data.progress_pct.toFixed(0)}%
            </span>
          </div>
          <div className="h-1.5 w-full rounded-full bg-zinc-800 overflow-hidden">
            <div
              className="h-full rounded-full bg-cyan-500 transition-all"
              style={{ width: `${Math.min(data.progress_pct, 100)}%` }}
            />
          </div>
        </div>
      )}

      {/* Latest run info */}
      {latestRun && (
        <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-2.5 space-y-1">
          <div className="flex items-center gap-1.5">
            <Cpu className="h-3 w-3 text-zinc-500" />
            <span className="font-mono text-[10px] text-zinc-400 uppercase tracking-wider">
              Latest Run
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="font-mono text-[10px] text-zinc-500 truncate">{latestRun.run_id.slice(0, 12)}…</span>
            <span className="font-mono text-[10px] text-zinc-400">{latestRun.symbol}</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="font-mono text-[10px] text-zinc-500">{formatTimestamp(latestRun.started_at)}</span>
            <span className={`font-mono text-[10px] uppercase ${
              latestRun.status === "completed" ? "text-bull" :
              latestRun.status === "running" ? "text-cyan-400" : "text-zinc-500"
            }`}>{latestRun.status}</span>
          </div>
        </div>
      )}

      {/* Metrics grid */}
      {res && (
        <div className="space-y-1">
          <div className="flex items-center gap-1.5 mb-1">
            <Activity className="h-3 w-3 text-zinc-500" />
            <span className="font-mono text-[10px] text-zinc-400 uppercase tracking-wider">
              Last Evaluation Metrics
            </span>
          </div>
          <div className="grid grid-cols-3 gap-2">
            <MetricCell
              label="Sharpe"
              value={typeof res.sharpe === "number" ? res.sharpe.toFixed(2) : "—"}
              colorClass={typeof res.sharpe === "number" ? metricColor(res.sharpe, 1.5, 0.8) : "text-zinc-500"}
            />
            <MetricCell
              label="Win Rate"
              value={typeof res.win_rate === "number" ? `${(res.win_rate * 100).toFixed(1)}%` : "—"}
              colorClass={typeof res.win_rate === "number" ? metricColor(res.win_rate, 0.55, 0.45) : "text-zinc-500"}
            />
            <MetricCell
              label="Trades"
              value={typeof res.total_trades === "number" ? String(res.total_trades) : "—"}
              colorClass="text-zinc-300"
            />
          </div>
        </div>
      )}

      {/* A/B vs STC comparison */}
      {hasComparison && res && typeof res.sharpe === "number" && (
        <div className="rounded-lg border border-zinc-800 bg-zinc-900/60 p-2.5">
          <div className="flex items-center gap-1.5 mb-2">
            <TrendingUp className="h-3 w-3 text-zinc-500" />
            <span className="font-mono text-[10px] text-zinc-400 uppercase tracking-wider">A/B vs STC</span>
          </div>
          <div className="grid grid-cols-3 gap-1 text-center">
            <span className="font-mono text-[9px] text-zinc-500 uppercase">Metric</span>
            <span className="font-mono text-[9px] text-cyan-400 uppercase">RL</span>
            <span className="font-mono text-[9px] text-zinc-400 uppercase">STC</span>

            <span className="font-mono text-[10px] text-zinc-500">Sharpe</span>
            <span className={`font-mono text-[10px] tabular-nums font-bold ${
              res.sharpe >= STC_REFERENCE.sharpe ? "text-bull" : "text-bear"
            }`}>{res.sharpe.toFixed(2)}</span>
            <span className="font-mono text-[10px] tabular-nums text-zinc-400">{STC_REFERENCE.sharpe.toFixed(2)}</span>

            {typeof res.win_rate === "number" && (
              <>
                <span className="font-mono text-[10px] text-zinc-500">Win Rate</span>
                <span className={`font-mono text-[10px] tabular-nums font-bold ${
                  res.win_rate >= STC_REFERENCE.win_rate ? "text-bull" : "text-bear"
                }`}>{(res.win_rate * 100).toFixed(1)}%</span>
                <span className="font-mono text-[10px] tabular-nums text-zinc-400">
                  {(STC_REFERENCE.win_rate * 100).toFixed(1)}%
                </span>
              </>
            )}
          </div>
        </div>
      )}

      {/* WF windows badge */}
      {data.walkforward_n_windows > 0 && (
        <div className="flex items-center justify-between text-xs">
          <span className="font-mono text-[10px] text-zinc-500">
            WF windows: {data.walkforward_n_windows}
          </span>
          <Badge variant={data.walkforward_complete ? "bull" : "info"}>
            {data.walkforward_complete ? "WF COMPLETE" : "WF RUNNING"}
          </Badge>
        </div>
      )}

      {/* Error */}
      {data.error && (
        <div className="rounded-lg border border-bear/20 bg-bear/5 px-2.5 py-2">
          <p className="font-mono text-[10px] text-bear">{data.error}</p>
        </div>
      )}

      <p className="font-mono text-[9px] text-zinc-700 text-right">30s poll</p>
    </div>
  );
}

function MetricCell({
  label,
  value,
  colorClass,
}: {
  label: string;
  value: string;
  colorClass: string;
}) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-2 text-center">
      <p className="font-mono text-[9px] text-zinc-500 uppercase mb-0.5">{label}</p>
      <p className={`font-mono text-sm font-bold tabular-nums ${colorClass}`}>{value}</p>
    </div>
  );
}
