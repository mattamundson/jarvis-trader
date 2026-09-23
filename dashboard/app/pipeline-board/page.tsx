"use client";

import useSWR from "swr";
import { LayoutDashboard, RefreshCw } from "lucide-react";
import { fetchEngine } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";

// ── Types (mirror engine agents/task_board.py PipelineTaskBoard.get_status()) ─
// GET /pipeline/board — read-only stage-tracking snapshot for the pipeline's
// most recent (or in-progress) run. In-memory on the engine side, so it
// reflects only what happened since the process last started.
//
// NOTE: engine/routers/pipeline_board_router.py also exposes
// `POST /pipeline/board/reset`, which clears this state (forensic evidence of
// a bad run). That endpoint is intentionally NOT wired anywhere on this page
// or anywhere else in the dashboard — this route is read-only by design.

type StageStatus = "pending" | "running" | "done" | "error" | "skipped";

interface PipelineStage {
  stage: string;
  status: StageStatus;
  started_at: string | null;
  completed_at: string | null;
  duration_ms: number | null;
  result_summary: string | null;
  error: string | null;
}

interface PipelineBoardResponse {
  run_id: string | null;
  symbol: string | null;
  interval: string | null;
  run_started_at: string | null;
  stages: Record<string, PipelineStage>;
  overall: "pending" | "running" | "complete" | "error";
  total_stages: number;
  done_count: number;
  error_count: number;
}

const REFRESH_MS = 15_000;

async function fetchPipelineBoard(): Promise<PipelineBoardResponse> {
  return fetchEngine<PipelineBoardResponse>("/pipeline/board");
}

const OVERALL_META: Record<
  PipelineBoardResponse["overall"],
  { variant: "bull" | "bear" | "warn" | "neutral"; label: string }
> = {
  pending: { variant: "neutral", label: "Pending" },
  running: { variant: "warn", label: "Running" },
  complete: { variant: "bull", label: "Complete" },
  error: { variant: "bear", label: "Error" },
};

const STAGE_META: Record<StageStatus, { variant: "bull" | "bear" | "warn" | "info" | "neutral"; label: string }> = {
  pending: { variant: "neutral", label: "Pending" },
  running: { variant: "warn", label: "Running" },
  done: { variant: "bull", label: "Done" },
  error: { variant: "bear", label: "Error" },
  skipped: { variant: "info", label: "Skipped" },
};

function fmtDuration(ms: number | null): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function fmtTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : `${iso}Z`);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
}

function StageStatusBadge({ status }: { status: StageStatus }) {
  const meta = STAGE_META[status] ?? STAGE_META.pending;
  return <Badge variant={meta.variant}>{meta.label}</Badge>;
}

export default function PipelineBoardPage() {
  const { data, error, isLoading, isValidating, mutate } = useSWR<PipelineBoardResponse>(
    "/pipeline/board",
    fetchPipelineBoard,
    { refreshInterval: REFRESH_MS, revalidateOnFocus: false, shouldRetryOnError: false }
  );

  const stages = data ? Object.values(data.stages) : [];
  const hasRun = !!data?.run_id;
  const overallMeta = data ? OVERALL_META[data.overall] ?? OVERALL_META.pending : null;

  return (
    <div className="space-y-5 p-4 md:p-6">
      {/* Header */}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-xl font-bold tracking-tight text-foreground">
            <LayoutDashboard className="h-5 w-5 text-accent" />
            Pipeline Board
          </h1>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Live per-stage execution status for the most recent pipeline run — technical / news /
            social / fundamental analysts through debate, trader, risk, and fund-manager stages.
            In-memory on the engine, so it only reflects activity since the engine last started.
            Read-only — this page never resets or mutates run state.
          </p>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <button
            type="button"
            onClick={() => mutate()}
            disabled={isValidating}
            className="flex items-center gap-1.5 rounded-md border border-border bg-card px-2.5 py-1 font-semibold text-foreground hover:bg-muted disabled:opacity-50"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${isValidating ? "animate-spin" : ""}`} />
            Refresh
          </button>
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-bear/30 bg-bear/10 px-4 py-2.5 text-xs text-bear">
          Pipeline board unreachable: {error instanceof Error ? error.message : "engine offline"}
        </div>
      )}

      {isLoading && !error && (
        <div className="rounded-lg border border-border bg-card px-4 py-6 text-center text-xs text-muted-foreground">
          <RefreshCw className="mr-2 inline h-4 w-4 animate-spin" />
          Loading pipeline board…
        </div>
      )}

      {!isLoading && !error && data && !hasRun && (
        <div className="rounded-lg border border-border bg-card px-4 py-6 text-center text-xs text-muted-foreground">
          No pipeline run recorded yet since the engine last started.
        </div>
      )}

      {!isLoading && !error && data && hasRun && (
        <>
          {/* Run summary */}
          <div className="flex flex-wrap items-center gap-2 text-xs">
            {overallMeta && <Badge variant={overallMeta.variant}>{overallMeta.label}</Badge>}
            <span className="rounded-md border border-border bg-card px-2.5 py-1 font-mono text-muted-foreground">
              {data.symbol ?? "—"} · {data.interval ?? "—"}
            </span>
            <span className="rounded-md border border-border bg-card px-2.5 py-1 font-mono text-muted-foreground">
              run {data.run_id}
            </span>
            <span className="rounded-md border border-bull/30 bg-bull/10 px-2.5 py-1 font-mono text-bull">
              {data.done_count}/{data.total_stages} done
            </span>
            {data.error_count > 0 && (
              <span className="rounded-md border border-bear/30 bg-bear/10 px-2.5 py-1 font-mono text-bear">
                {data.error_count} error{data.error_count === 1 ? "" : "s"}
              </span>
            )}
            <span className="ml-auto font-mono text-muted-foreground/70">
              started {fmtTime(data.run_started_at)} · auto 15s
            </span>
          </div>

          {/* Stage table */}
          <Card>
            <CardContent className="p-0">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border bg-muted/40 text-left">
                      {["Stage", "Status", "Started", "Completed", "Duration", "Result / error"].map((h) => (
                        <th
                          key={h}
                          className="px-3 py-2.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground whitespace-nowrap"
                        >
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border/60">
                    {stages.map((s) => (
                      <tr key={s.stage} className="hover:bg-muted/30">
                        <td className="px-3 py-2.5 font-mono text-xs font-semibold text-foreground whitespace-nowrap">
                          {s.stage}
                        </td>
                        <td className="px-3 py-2.5">
                          <StageStatusBadge status={s.status} />
                        </td>
                        <td className="px-3 py-2.5 font-mono text-xs text-muted-foreground whitespace-nowrap">
                          {fmtTime(s.started_at)}
                        </td>
                        <td className="px-3 py-2.5 font-mono text-xs text-muted-foreground whitespace-nowrap">
                          {fmtTime(s.completed_at)}
                        </td>
                        <td className="px-3 py-2.5 font-mono text-xs tabular-nums text-muted-foreground whitespace-nowrap">
                          {fmtDuration(s.duration_ms)}
                        </td>
                        <td className="px-3 py-2.5 text-xs text-muted-foreground max-w-md truncate">
                          {s.status === "error" ? (
                            <span className="text-bear">{s.error ?? "unspecified error"}</span>
                          ) : (
                            s.result_summary ?? "—"
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        </>
      )}

      <p className="pb-4 text-center text-[11px] text-muted-foreground">
        Pipeline Board mirrors engine <span className="font-mono">GET /pipeline/board</span> — display
        only, never routes or gates a trade. State is in-memory and reset by the engine on restart.
      </p>
    </div>
  );
}
