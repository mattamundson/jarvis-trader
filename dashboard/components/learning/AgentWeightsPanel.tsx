"use client";

import { useState } from "react";
import useSWR from "swr";
import { fetchAgentWeights, type AgentWeightEntry } from "@/lib/api";
import { Badge } from "@/components/ui/badge";

const REFRESH_MS = 30_000;

// Mirrors agents/debate.py's REGIME_DEBATE_THRESHOLDS keys.
const REGIMES = [
  "COMPRESSION", "TRENDING_BULL", "TRENDING_BEAR", "RANGE_BOUND", "EXHAUSTED", "RANGING", "CAUTION",
] as const;

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
  const barPct = span > 0 ? ((entry.live_weight - minWeight) / span) * 100 : 50;
  const diverges = Math.abs(entry.live_weight - entry.recomputed_weight) > 0.01;

  return (
    <div className="rounded-xl border border-border bg-card p-4 space-y-2 hover:border-border/80 transition-colors">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="font-mono text-xs font-semibold text-foreground capitalize">
            {agent}
          </span>
          <Badge variant={weightBadgeVariant(entry.live_weight, defaultWeight)}>
            {entry.live_weight.toFixed(2)}x live
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

      <div className="flex items-center gap-4 flex-wrap">
        <span className="font-mono text-[10px] text-muted-foreground/60">
          30d accuracy <span className="text-foreground/80">{fmtPct(entry.accuracy_30d)}</span>
        </span>
        <span className="font-mono text-[10px] text-muted-foreground/60">
          90d accuracy <span className="text-foreground/80">{fmtPct(entry.accuracy_90d)}</span>
        </span>
        <span
          className="font-mono text-[10px] text-muted-foreground/40"
          title="Freshly recomputed all-regime weight -- a diagnostic view, not necessarily what's live-applied"
        >
          recomputed {entry.recomputed_weight.toFixed(2)}x
          {diverges && <span className="text-warn ml-1">(differs from live)</span>}
        </span>
      </div>
    </div>
  );
}

export function AgentWeightsPanel() {
  const [regime, setRegime] = useState<string>("");

  const { data, isLoading, error } = useSWR(
    ["/analytics/agent-weights", regime],
    () => fetchAgentWeights(regime || undefined),
    { refreshInterval: REFRESH_MS }
  );

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-border bg-card p-4 space-y-2">
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
          <div className="flex items-center gap-2">
            <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
              Regime
            </span>
            <select
              value={regime}
              onChange={(e) => setRegime(e.target.value)}
              className="font-mono text-[11px] rounded border border-border bg-background px-2 py-1 text-foreground"
            >
              <option value="">no regime (load_weights)</option>
              {REGIMES.map((r) => (
                <option key={r} value={r}>{r}</option>
              ))}
            </select>
          </div>
        </div>

        {data && (
          <div className="flex items-center justify-between gap-3 flex-wrap pt-1 border-t border-border/40">
            <span className="font-mono text-[10px] text-muted-foreground/60">
              live_weight source: <span className="text-foreground/70">{data.weights_source}</span>
            </span>
            <span className="font-mono text-[10px] text-muted-foreground/50">
              saved weights file {data.weights_file_exists ? "exists" : "does not exist"}, updated {fmtTimestamp(data.saved_weights_updated_at)}
            </span>
          </div>
        )}

        {data && !data.regime && !data.weights_file_exists && (
          <div className="rounded-md border border-warn/30 bg-warn/5 px-3 py-2">
            <p className="text-[11px] text-warn">
              agent_weights.json does not exist, so the no-regime live_weight is
              stuck at the {data.default_weight.toFixed(2)}x default for every
              agent — nothing in the codebase currently calls
              AgentFeedbackTracker.save_weights() to write it. Select a regime
              above to see the real, live-computed regime-conditional weight instead.
            </p>
          </div>
        )}
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
