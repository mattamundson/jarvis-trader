"use client";

import { useState } from "react";
import useSWR from "swr";
import { ChevronDown, ChevronRight, GitBranch, RefreshCw, AlertTriangle } from "lucide-react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchEngine } from "@/lib/api";

const REFRESH_MS = 30_000;

// ── Types ─────────────────────────────────────────────────────────────────────

interface PipelineRun {
  id: number;
  run_id: string;
  symbol: string;
  webhook_action: string | null;   // LONG / SHORT / CLOSE
  source: string;                  // tradingview / manual
  final_action: string | null;     // what pipeline decided
  final_quantity: number | null;
  requires_human: boolean;
  summary: string | null;
  status: string;                  // completed / error / skipped
  error_message: string | null;
  duration_ms: number | null;
  created_at: string;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fetcher<T>(path: string): Promise<T> {
  return fetchEngine<T>(path);
}

function formatDateTime(iso: string | undefined | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  const date = d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  const time = d.toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
  return `${date} ${time}`;
}

function formatDuration(ms: number | null): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

/**
 * Maps webhook_action → final_action into a human-readable arrow string.
 * Examples: "LONG → BUY", "SHORT → SELL", "CLOSE → CLOSE", "LONG → HOLD"
 */
function formatActionArrow(
  webhookAction: string | null,
  finalAction: string | null
): string {
  const from = webhookAction ?? "—";
  const to = finalAction ?? "HOLD";
  if (!webhookAction && !finalAction) return "—";
  return `${from} → ${to}`;
}

function statusBadgeVariant(status: string): "bull" | "bear" | "neutral" {
  if (status === "completed") return "bull";
  if (status === "error") return "bear";
  return "neutral";
}

function sourceBadgeVariant(source: string): "info" | "neutral" {
  if (source === "tradingview") return "info";
  return "neutral";
}

function finalActionColorClass(action: string | null): string {
  if (!action) return "text-muted-foreground";
  const upper = action.toUpperCase();
  if (upper === "BUY" || upper === "LONG") return "text-bull";
  if (upper === "SELL" || upper === "SHORT" || upper === "CLOSE") return "text-bear";
  return "text-muted-foreground";
}

// ── Row component ─────────────────────────────────────────────────────────────

function PipelineRunRow({ run }: { run: PipelineRun }) {
  const [expanded, setExpanded] = useState(false);
  const actionArrow = formatActionArrow(run.webhook_action, run.final_action);

  return (
    <div className="border-b border-border/50 last:border-0">
      {/* Main row — always visible */}
      <button
        className="w-full flex items-center gap-2 py-2 text-left hover:bg-muted/20 transition-colors rounded px-1 group"
        onClick={() => setExpanded((prev) => !prev)}
        aria-expanded={expanded}
      >
        {/* Expand chevron */}
        <span className="text-muted-foreground/50 shrink-0">
          {expanded ? (
            <ChevronDown className="h-3 w-3" />
          ) : (
            <ChevronRight className="h-3 w-3" />
          )}
        </span>

        {/* Timestamp */}
        <span className="font-mono text-[10px] text-muted-foreground whitespace-nowrap w-[80px] shrink-0">
          {formatDateTime(run.created_at)}
        </span>

        {/* Symbol */}
        <span className="font-mono text-xs font-semibold text-foreground w-[48px] shrink-0">
          {run.symbol ?? "—"}
        </span>

        {/* Source badge */}
        <Badge
          variant={sourceBadgeVariant(run.source)}
          className="text-[9px] px-1.5 py-0 shrink-0 font-mono tracking-wider"
        >
          {(run.source ?? "—").toUpperCase()}
        </Badge>

        {/* Action arrow */}
        <span
          className={`font-mono text-[10px] font-semibold whitespace-nowrap shrink-0 ${finalActionColorClass(run.final_action)}`}
        >
          {actionArrow}
        </span>

        {/* Requires human warning */}
        {run.requires_human && (
          <span title="Requires human approval">
            <AlertTriangle className="h-3 w-3 text-warn shrink-0" />
          </span>
        )}

        {/* Spacer */}
        <span className="flex-1" />

        {/* Duration */}
        <span className="font-mono text-[10px] text-muted-foreground tabular-nums w-[36px] text-right shrink-0">
          {formatDuration(run.duration_ms)}
        </span>

        {/* Status badge */}
        <Badge
          variant={statusBadgeVariant(run.status)}
          className="text-[9px] px-1.5 py-0 shrink-0 font-mono tracking-wider"
        >
          {(run.status ?? "—").toUpperCase()}
        </Badge>
      </button>

      {/* Expanded summary */}
      {expanded && (
        <div className="px-6 pb-2">
          <div className="rounded-lg bg-muted/40 border border-border p-2.5 space-y-2">
            {/* Run ID */}
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground mb-0.5">
                Run ID
              </p>
              <p className="text-[10px] font-mono text-foreground/70 break-all">
                {run.run_id}
              </p>
            </div>

            {/* Summary */}
            {run.summary && (
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground mb-0.5">
                  Summary
                </p>
                <p className="text-xs text-foreground/80 leading-relaxed whitespace-pre-wrap">
                  {run.summary}
                </p>
              </div>
            )}

            {/* Error message */}
            {run.error_message && (
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-widest text-bear mb-0.5">
                  Error
                </p>
                <p className="text-xs text-bear/80 leading-relaxed whitespace-pre-wrap font-mono">
                  {run.error_message}
                </p>
              </div>
            )}

            {/* Additional details row */}
            <div className="flex flex-wrap gap-4 pt-1">
              {run.final_quantity != null && (
                <div>
                  <p className="text-[10px] text-muted-foreground uppercase tracking-wider">Qty</p>
                  <p className="font-mono text-xs text-foreground">{run.final_quantity}</p>
                </div>
              )}
              {run.requires_human && (
                <div className="flex items-center gap-1">
                  <AlertTriangle className="h-3 w-3 text-warn" />
                  <p className="text-[10px] text-warn font-semibold uppercase tracking-wider">
                    Requires Human Approval
                  </p>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── PipelineRunHistory component ──────────────────────────────────────────────

export function PipelineRunHistory() {
  const {
    data: runs,
    isLoading,
    error,
    mutate,
  } = useSWR<PipelineRun[]>(
    "/pipeline/history?limit=20",
    fetcher,
    { refreshInterval: REFRESH_MS }
  );

  const rows = runs ?? [];

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2">
            <GitBranch className="h-4 w-4 text-muted-foreground" />
            Pipeline Run History
          </CardTitle>
          <div className="flex items-center gap-2">
            {rows.length > 0 && (
              <span className="text-xs text-muted-foreground tabular-nums">
                last {rows.length}
              </span>
            )}
            <button
              onClick={() => mutate()}
              className="flex items-center gap-1 rounded-md border border-border px-2 py-1 text-[10px] font-semibold text-muted-foreground hover:text-foreground hover:bg-muted/30 transition-colors"
              title="Refresh pipeline history"
            >
              <RefreshCw className="h-3 w-3" />
              Refresh
            </button>
          </div>
        </div>
      </CardHeader>

      <CardContent>
        {/* Loading state */}
        {isLoading && (
          <div className="flex items-center justify-center py-8">
            <div className="h-4 w-4 rounded-full border-2 border-accent border-t-transparent animate-spin mr-2" />
            <span className="text-xs text-muted-foreground">Loading pipeline runs…</span>
          </div>
        )}

        {/* Error state */}
        {error && !isLoading && (
          <p className="text-center text-xs text-bear py-6">
            Failed to load pipeline history — engine may be offline.
          </p>
        )}

        {/* Empty state */}
        {!isLoading && !error && rows.length === 0 && (
          <p className="text-center text-sm text-muted-foreground py-8">
            No pipeline runs yet. Send a TradingView alert or use the Simulate Trade panel.
          </p>
        )}

        {/* Rows */}
        {!isLoading && !error && rows.length > 0 && (
          <div>
            {/* Column headers */}
            <div className="flex items-center gap-2 pb-1.5 mb-1 border-b border-border px-1">
              <span className="w-3 shrink-0" />
              <span className="font-mono text-[9px] font-bold uppercase tracking-widest text-muted-foreground w-[80px] shrink-0">
                Time
              </span>
              <span className="font-mono text-[9px] font-bold uppercase tracking-widest text-muted-foreground w-[48px] shrink-0">
                Symbol
              </span>
              <span className="font-mono text-[9px] font-bold uppercase tracking-widest text-muted-foreground shrink-0 w-[72px]">
                Source
              </span>
              <span className="font-mono text-[9px] font-bold uppercase tracking-widest text-muted-foreground shrink-0">
                Action
              </span>
              <span className="flex-1" />
              <span className="font-mono text-[9px] font-bold uppercase tracking-widest text-muted-foreground w-[36px] text-right shrink-0">
                Dur
              </span>
              <span className="font-mono text-[9px] font-bold uppercase tracking-widest text-muted-foreground shrink-0 w-[72px] text-right">
                Status
              </span>
            </div>

            {/* Run rows */}
            <div>
              {rows.map((run) => (
                <PipelineRunRow key={run.id} run={run} />
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
