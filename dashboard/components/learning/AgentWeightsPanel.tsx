"use client";

import useSWR from "swr";
import { fetchAgentWeights, type AgentWeightEntry } from "@/lib/api";
import { Badge } from "@/components/ui/badge";

const REFRESH_MS = 30_000;

function fmtPct(v: number): string {
  return `${(v * 100).toFixed(0)}%`;
}

function fmtTimestamp(ts: string | null | undefined): string {
  if (!ts) return "never";
  try {
    return new Date(ts).toLocaleString("en-US", {
      month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
    });
  } catch {
    return ts;
  }
}

function weightBadgeVariant(weight: number, defaultWeight: number): "bull" | "bear" | "neutral" {
  if (weight > defaultWeight + 0.01) return "bull";
  if (weight < defaultWeight - 0.01) return "bear";
  return "neutral";
}

function AgentWeightRow({
  agent,
  entry,
  minWeight,
  maxWeight,
  defaultWeight,
}: {
  agent: string;
  entry: AgentWeightEntry;
  minWeight: number;
  maxWeight: number;
  defaultWeight: number;
}) {
  const span = maxWeight - minWeight;
  const barPct = span > 0 ? ((entry.weight - minWeight) / span) * 100 : 50;

  return (
    <div className="rounded-xl border border-border bg-card p-4 space-y-2 hover:border-border/80 transition-colors">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="font-mono text-xs font-semibold text-foreground capitalize">
            {agent}
          </span>
          <Badge variant={weightBadgeVariant(entry.weight, defaultWeight)}>
            {entry.weight.toFixed(2)}x
          </Badge>
          {!entry.ready && <Badge variant="warn">warming up</Badge>}
        </div>
        <span className="font-mono text-[10px] text-muted-foreground/50">
          {entry.sample_count_30d} trades / 30d
        </span>
      </div>

      <div className="h-1.5 rounded-full bg-muted overflow-hidden">
        <div
          className="h-full rounded-full bg-accent"
          style={{ width: `${Math.min(100, Math.max(0, barPct))}%` }}
        />
      </div>

      <div className="flex items-center gap-4">
        <span className="font-mono text-[10px] text-muted-foreground/60">
          30d accuracy <span className="text-foreground/80">{fmtPct(entry.accuracy_30d)}</span>
        </span>
        <span className="font-mono text-[10px] text-muted-foreground/60">
          90d accuracy <span className="text-foreground/80">{fmtPct(entry.accuracy_90d)}</span>
        </span>
      </div>
    </div>
  );
}

export function AgentWeightsPanel() {
  const { data, isLoading, error } = useSWR(
    "/analytics/agent-weights",
    fetchAgentWeights,
    { refreshInterval: REFRESH_MS }
  );

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-border bg-card p-4 space-y-1">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div>
            <div className="flex items-center gap-2">
              <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
                Agent Debate Weights
              </p>
              <Badge variant={error ? "static" : "live"}>
                {error ? "static" : "live"}
              </Badge>
            </div>
            <p className="font-mono text-[10px] text-muted-foreground/40 mt-0.5">
              P&amp;L-correlation weight applied to each Stage-1 analyst signal in debate.py
              (AgentFeedbackTracker, {data ? `${data.min_weight.toFixed(2)}x–${data.max_weight.toFixed(2)}x` : "0.70x–1.30x"} range)
            </p>
          </div>
          {data && (
            <span className="font-mono text-[10px] text-muted-foreground/50">
              saved weights updated {fmtTimestamp(data.saved_weights_updated_at)}
            </span>
          )}
        </div>
      </div>

      {isLoading ? (
        <div className="rounded-xl border border-border bg-card p-4">
          <p className="font-mono text-xs text-muted-foreground/50 animate-pulse">
            Loading agent weights…
          </p>
        </div>
      ) : error ? (
        <div className="rounded-xl border border-border bg-card p-4">
          <p className="font-mono text-xs text-red-400/70 italic">
            Agent weights unavailable — engine may be unreachable
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {data?.agents.map((agent) => {
            const entry = data.per_agent[agent];
            if (!entry) return null;
            return (
              <AgentWeightRow
                key={agent}
                agent={agent}
                entry={entry}
                minWeight={data.min_weight}
                maxWeight={data.max_weight}
                defaultWeight={data.default_weight}
              />
            );
          })}
        </div>
      )}
    </div>
  );
}
