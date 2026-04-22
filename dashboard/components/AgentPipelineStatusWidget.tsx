"use client";

import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchEngine } from "@/lib/api";

// ── Types ────────────────────────────────────────────────────────────────────

interface PipelineAgent {
  name: string;
  stage: number;
  status: "active" | "idle" | "error" | string;
  last_run: string | null;
  runs_today: number;
}

interface PipelineStatusResponse {
  agents: PipelineAgent[];
  pipeline_healthy: boolean;
  last_cycle: string | null;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function relativeTime(iso: string | null): string {
  if (!iso) return "Never";
  try {
    const diffMs = Date.now() - new Date(iso).getTime();
    const diffSec = Math.floor(diffMs / 1000);
    if (diffSec < 5) return "Just now";
    if (diffSec < 60) return `${diffSec}s ago`;
    const diffMin = Math.floor(diffSec / 60);
    if (diffMin < 60) return `${diffMin}m ago`;
    const diffHr = Math.floor(diffMin / 60);
    return `${diffHr}h ago`;
  } catch {
    return "Unknown";
  }
}

// Stage label map: strip "Agent" suffix for display
const STAGE_LABELS: Record<number, string> = {
  1: "Regime",
  2: "Momentum",
  3: "Entry",
  4: "Risk",
  5: "Execution",
};

// ── Status Dot ───────────────────────────────────────────────────────────────

function StatusDot({ status }: { status: string }) {
  if (status === "active") {
    return (
      <span className="relative flex h-2.5 w-2.5">
        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-bull opacity-75" />
        <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-bull" />
      </span>
    );
  }
  if (status === "error") {
    return <span className="inline-flex rounded-full h-2.5 w-2.5 bg-bear" />;
  }
  // idle or unknown
  return <span className="inline-flex rounded-full h-2.5 w-2.5 bg-muted-foreground/40" />;
}

// ── Flow Diagram ─────────────────────────────────────────────────────────────

function PipelineFlowDiagram({ agents }: { agents: PipelineAgent[] }) {
  // Build a status map by stage number for quick lookup
  const stageStatusMap: Record<number, string> = {};
  for (const agent of agents) {
    if (agent.stage >= 1 && agent.stage <= 5) {
      stageStatusMap[agent.stage] = agent.status;
    }
  }

  return (
    <div className="flex items-center gap-1 flex-wrap">
      {[1, 2, 3, 4, 5].map((stage) => {
        const status = stageStatusMap[stage] ?? "idle";
        const bgClass =
          status === "active"
            ? "bg-bull/20 border-bull/40 text-bull"
            : status === "error"
            ? "bg-bear/20 border-bear/40 text-bear"
            : "bg-muted border-border text-muted-foreground";

        return (
          <div key={stage} className="flex items-center gap-1">
            <div
              className={`flex flex-col items-center justify-center rounded-lg border px-3 py-1.5 min-w-[72px] ${bgClass}`}
            >
              <span className="text-[10px] font-bold opacity-60">STAGE {stage}</span>
              <span className="text-xs font-semibold">{STAGE_LABELS[stage] ?? `S${stage}`}</span>
            </div>
            {stage < 5 && (
              <span className="text-muted-foreground text-sm select-none">→</span>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ── Agent Row ─────────────────────────────────────────────────────────────────

function AgentRow({ agent }: { agent: PipelineAgent }) {
  const statusVariant: "bull" | "bear" | "neutral" =
    agent.status === "active" ? "bull" : agent.status === "error" ? "bear" : "neutral";
  const statusLabel =
    agent.status === "active" ? "ACTIVE" : agent.status === "error" ? "ERROR" : "IDLE";

  return (
    <div className="flex items-center gap-3 rounded-lg border border-border bg-card/50 px-4 py-2.5">
      {/* Stage circle */}
      <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-muted border border-border">
        <span className="text-[11px] font-bold text-muted-foreground">{agent.stage}</span>
      </div>

      {/* Name */}
      <div className="flex-1 min-w-0">
        <p className="text-sm font-semibold text-foreground truncate">
          {STAGE_LABELS[agent.stage] ?? agent.name}
        </p>
        <p className="text-[11px] text-muted-foreground truncate">{agent.name}</p>
      </div>

      {/* Status dot + badge */}
      <div className="flex items-center gap-2">
        <StatusDot status={agent.status} />
        <Badge variant={statusVariant}>{statusLabel}</Badge>
      </div>

      {/* Runs today */}
      <div className="text-right shrink-0 hidden sm:block">
        <p className="text-[11px] text-muted-foreground">Runs today</p>
        <p className="text-xs font-semibold text-foreground">{agent.runs_today ?? 0}</p>
      </div>

      {/* Last run */}
      <div className="text-right shrink-0">
        <p className="text-[11px] text-muted-foreground">Last run</p>
        <p className="text-xs font-mono text-foreground">{relativeTime(agent.last_run)}</p>
      </div>
    </div>
  );
}

// ── Skeleton ──────────────────────────────────────────────────────────────────

function PipelineSkeleton() {
  return (
    <div className="space-y-2 animate-pulse">
      {/* Flow diagram skeleton */}
      <div className="flex items-center gap-1 mb-4">
        {[1, 2, 3, 4, 5].map((s) => (
          <div key={s} className="flex items-center gap-1">
            <div className="rounded-lg bg-muted h-10 w-[72px]" />
            {s < 5 && <span className="text-muted text-sm">→</span>}
          </div>
        ))}
      </div>
      {Array.from({ length: 5 }).map((_, i) => (
        <div key={i} className="flex items-center gap-3 rounded-lg border border-border bg-card/50 px-4 py-2.5">
          <div className="h-7 w-7 rounded-full bg-muted" />
          <div className="flex-1 space-y-1.5">
            <div className="h-3.5 w-28 rounded bg-muted" />
            <div className="h-3 w-20 rounded bg-muted" />
          </div>
          <div className="h-5 w-14 rounded-full bg-muted" />
          <div className="h-8 w-16 rounded bg-muted hidden sm:block" />
          <div className="h-8 w-16 rounded bg-muted" />
        </div>
      ))}
    </div>
  );
}

// ── Overall Summary Badge ─────────────────────────────────────────────────────

function OverallPipelineBadge({ agents }: { agents: PipelineAgent[] }) {
  const hasError = agents.some((a) => a.status === "error");
  const hasIdle = agents.some((a) => a.status === "idle");

  if (hasError) {
    return <Badge variant="bear">Pipeline Error</Badge>;
  }
  if (hasIdle) {
    return <Badge variant="warn">Partial Active</Badge>;
  }
  return <Badge variant="bull">All Systems Go</Badge>;
}

// ── Main Widget ───────────────────────────────────────────────────────────────

export function AgentPipelineStatusWidget() {
  const [data, setData] = useState<PipelineStatusResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);

  async function fetchStatus() {
    try {
      const json = await fetchEngine<PipelineStatusResponse>("/pipeline/status");
      setData(json);
      setError(null);
      setLastRefresh(new Date());
    } catch (err) {
      // Fallback: try /health and extract agent info if present
      try {
        const health = await fetchEngine<Record<string, unknown>>("/health");
        const fallbackAgents: PipelineAgent[] = (health.agents as PipelineAgent[]) ?? [];
        setData({
          agents: fallbackAgents,
          pipeline_healthy: health.overall === "healthy" || health.status === "ok",
          last_cycle: (health.timestamp as string) ?? null,
        });
        setError(null);
        setLastRefresh(new Date());
      } catch {
        setError(err instanceof Error ? err.message : "Unknown error");
      }
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 15_000);
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Normalise agents — sort by stage, fill in missing stages with idle placeholders
  const agents: PipelineAgent[] = (() => {
    if (!data?.agents?.length) {
      // Return 5 placeholder idle agents
      return [1, 2, 3, 4, 5].map((stage) => ({
        name: `${STAGE_LABELS[stage] ?? `Stage${stage}`}Agent`,
        stage,
        status: "idle",
        last_run: null,
        runs_today: 0,
      }));
    }
    // Sort by stage
    return [...data.agents].sort((a, b) => a.stage - b.stage);
  })();

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div>
            <CardTitle>10-Agent Pipeline Status</CardTitle>
            <p className="text-xs text-muted-foreground mt-1">
              Auto-refreshes every 15 seconds
              {lastRefresh && (
                <span className="ml-2 opacity-60">— last at {lastRefresh.toLocaleTimeString()}</span>
              )}
            </p>
          </div>
          {!loading && !error && data && (
            <OverallPipelineBadge agents={agents} />
          )}
        </div>
      </CardHeader>

      <CardContent>
        {/* Loading skeleton */}
        {loading && <PipelineSkeleton />}

        {/* Error state */}
        {!loading && error && (
          <div className="rounded-lg border border-bear/30 bg-bear/5 px-4 py-5 text-center space-y-1">
            <p className="text-sm font-semibold text-bear">Pipeline status unavailable</p>
            <p className="text-xs text-muted-foreground">{error}</p>
          </div>
        )}

        {/* Data */}
        {!loading && !error && data && (
          <div className="space-y-4">
            {/* Horizontal flow diagram */}
            <PipelineFlowDiagram agents={agents} />

            {/* Divider */}
            <div className="border-t border-border" />

            {/* Agent rows */}
            <div className="space-y-2">
              {agents.map((agent) => (
                <AgentRow key={agent.name} agent={agent} />
              ))}
            </div>

            {/* Last cycle */}
            {data.last_cycle && (
              <p className="text-[11px] text-muted-foreground text-right">
                Last pipeline cycle: {relativeTime(data.last_cycle)}
              </p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
