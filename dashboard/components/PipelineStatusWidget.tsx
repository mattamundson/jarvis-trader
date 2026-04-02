"use client";

import { useState, useEffect } from "react";
import { Activity, CheckCircle, XCircle, AlertCircle, RefreshCw } from "lucide-react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchEngine } from "@/lib/api";

interface PipelineStatusResponse {
  available: boolean;
  last_run: Record<string, unknown> | null;
  decision_count: number;
}

interface AgentStage {
  stage: number;
  name: string;
}

const PIPELINE_STAGES: AgentStage[] = [
  { stage: 1, name: "Regime Detection Agent" },
  { stage: 2, name: "Momentum Analysis Agent" },
  { stage: 3, name: "Entry Signal Agent" },
  { stage: 4, name: "Risk Management Agent" },
  { stage: 5, name: "Execution Agent" },
];

type AgentStatus = "running" | "stopped" | "error";

function getAgentStatus(available: boolean | null, index: number): AgentStatus {
  if (available === null) return "stopped";
  if (!available) return "stopped";
  // When pipeline is available, all stages are considered running.
  // Stage 5 (Execution) is only "running" if decisions have been made.
  void index;
  return "running";
}

function StatusDot({ status }: { status: AgentStatus }) {
  if (status === "running") {
    return <span className="w-2 h-2 rounded-full bg-bull inline-block" />;
  }
  if (status === "error") {
    return <span className="w-2 h-2 rounded-full bg-bear inline-block" />;
  }
  return <span className="w-2 h-2 rounded-full bg-warn inline-block" />;
}

function StatusIcon({ status }: { status: AgentStatus }) {
  if (status === "running") {
    return <CheckCircle className="h-3.5 w-3.5 text-bull" />;
  }
  if (status === "error") {
    return <XCircle className="h-3.5 w-3.5 text-bear" />;
  }
  return <AlertCircle className="h-3.5 w-3.5 text-warn" />;
}

function healthBadgeVariant(
  available: boolean | null,
  errorOccurred: boolean
): "bull" | "bear" | "warn" | "neutral" {
  if (errorOccurred) return "bear";
  if (available === null) return "neutral";
  if (!available) return "warn";
  return "bull";
}

function healthLabel(
  available: boolean | null,
  errorOccurred: boolean
): string {
  if (errorOccurred) return "Error";
  if (available === null) return "Loading";
  if (!available) return "Offline";
  return "Healthy";
}

export function PipelineStatusWidget() {
  const [status, setStatus] = useState<PipelineStatusResponse | null>(null);
  const [fetchError, setFetchError] = useState(false);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);
  const [loading, setLoading] = useState(true);

  async function fetchStatus() {
    try {
      const data = await fetchEngine<PipelineStatusResponse>("/pipeline/status");
      setStatus(data);
      setFetchError(false);
    } catch {
      setFetchError(true);
      setStatus(null);
    } finally {
      setLoading(false);
      setLastRefresh(new Date());
    }
  }

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 15_000);
    return () => clearInterval(interval);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const available = fetchError ? null : (status?.available ?? null);

  const agentStatuses: AgentStatus[] = PIPELINE_STAGES.map((_, i) =>
    fetchError ? "error" : getAgentStatus(available, i)
  );

  const activeCount = agentStatuses.filter((s) => s === "running").length;

  const overallVariant = healthBadgeVariant(available, fetchError);
  const overallLabel = healthLabel(available, fetchError);

  function formatLastActive(): string {
    if (!status?.last_run) return "—";
    const ts =
      (status.last_run as Record<string, unknown>).timestamp ??
      (status.last_run as Record<string, unknown>).ts ??
      (status.last_run as Record<string, unknown>).time;
    if (typeof ts === "string" || typeof ts === "number") {
      const d = new Date(ts);
      if (!isNaN(d.getTime())) {
        return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
      }
    }
    return "recent";
  }

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Activity className="h-4 w-4 text-accent" />
            <CardTitle>Pipeline Status</CardTitle>
          </div>
          <Badge variant={overallVariant}>{overallLabel}</Badge>
        </div>
      </CardHeader>

      <CardContent className="space-y-3">
        {/* Loading skeleton */}
        {loading && (
          <div className="space-y-2 animate-pulse">
            {PIPELINE_STAGES.map((s) => (
              <div key={s.stage} className="h-8 w-full bg-muted rounded-lg" />
            ))}
          </div>
        )}

        {/* Agent rows */}
        {!loading && (
          <div className="space-y-1.5">
            {PIPELINE_STAGES.map((stage, i) => {
              const agentStatus = agentStatuses[i];
              return (
                <div
                  key={stage.stage}
                  className="flex items-center gap-3 rounded-lg px-3 py-2 bg-muted/30 border border-border/50"
                >
                  {/* Stage number badge */}
                  <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-accent/10 text-[10px] font-bold text-accent">
                    {stage.stage}
                  </span>

                  {/* Agent name */}
                  <span className="flex-1 text-xs font-medium text-foreground">
                    {stage.name}
                  </span>

                  {/* Last active — show for all stages when a last_run exists */}
                  {status?.last_run && agentStatus === "running" && (
                    <span className="text-[10px] text-muted-foreground font-mono">
                      {formatLastActive()}
                    </span>
                  )}

                  {/* Status icon + dot */}
                  <div className="flex items-center gap-1.5">
                    <StatusIcon status={agentStatus} />
                    <StatusDot status={agentStatus} />
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* Summary footer */}
        {!loading && (
          <div className="flex items-center justify-between pt-1 border-t border-border/50">
            <span className="text-xs text-muted-foreground">
              <span
                className={
                  activeCount === 5
                    ? "text-bull font-semibold"
                    : activeCount === 0
                    ? "text-bear font-semibold"
                    : "text-warn font-semibold"
                }
              >
                {activeCount}/5
              </span>{" "}
              agents active
              {status?.decision_count !== undefined && (
                <> &middot; {status.decision_count} decisions</>
              )}
            </span>

            <div className="flex items-center gap-1 text-[10px] text-muted-foreground">
              <RefreshCw className="h-3 w-3" />
              {lastRefresh
                ? lastRefresh.toLocaleTimeString([], {
                    hour: "2-digit",
                    minute: "2-digit",
                    second: "2-digit",
                  })
                : "—"}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
