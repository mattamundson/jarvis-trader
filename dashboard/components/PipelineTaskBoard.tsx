"use client";

import useSWR from "swr";
import { fetchEngine } from "@/lib/api";

const STATUS_COLORS: Record<string, string> = {
  pending: "bg-zinc-700 text-zinc-400",
  running: "bg-blue-500/20 text-blue-400 animate-pulse",
  done: "bg-green-500/20 text-green-400",
  error: "bg-red-500/20 text-red-400",
  skipped: "bg-zinc-600 text-zinc-500",
};

interface BoardStage {
  stage: string;
  status: string;
  duration_ms?: number;
}

interface PipelineBoardData {
  run_id?: string;
  symbol?: string;
  interval?: string;
  stages?: Record<string, BoardStage>;
  done_count?: number;
  total_stages?: number;
  overall?: string;
}

export function PipelineTaskBoard() {
  const { data } = useSWR<PipelineBoardData>(
    "pipeline-board",
    () => fetchEngine<PipelineBoardData>("/pipeline/board"),
    { refreshInterval: 2000 }
  );

  if (!data?.run_id) {
    return (
      <div className="rounded-lg border border-zinc-800 p-4">
        <p className="text-sm text-zinc-500">No pipeline run in progress.</p>
      </div>
    );
  }

  const stages = Object.values(data.stages || {}) as BoardStage[];

  return (
    <div className="rounded-lg border border-zinc-800 p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-zinc-200">Pipeline Board</h3>
        <span className="text-xs text-zinc-500">
          {data.symbol} {data.interval}
        </span>
      </div>
      <div className="space-y-1">
        {stages.map((t) => (
          <div key={t.stage} className="flex items-center gap-2">
            <span
              className={`text-xs px-2 py-0.5 rounded font-mono ${STATUS_COLORS[t.status] ?? ""}`}
            >
              {t.status}
            </span>
            <span className="text-xs text-zinc-400">
              {t.stage} {t.duration_ms ? `(${t.duration_ms}ms)` : ""}
            </span>
          </div>
        ))}
      </div>
      {data.overall && (
        <div className="mt-2 pt-2 border-t border-zinc-800 text-xs text-zinc-400">
          Overall: {data.overall}
        </div>
      )}
    </div>
  );
}