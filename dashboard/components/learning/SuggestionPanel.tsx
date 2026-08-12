"use client";

import useSWR from "swr";
import { fetchEngine } from "@/lib/api";
import { Badge } from "@/components/ui/badge";

const REFRESH_MS = 60_000;

function fetcher<T = unknown>(url: string): Promise<T> {
  return fetchEngine<T>(url);
}

// ── Types ─────────────────────────────────────────────────────────────────────

interface ParamSuggestion {
  param_name: string;
  current_value: number | string | null;
  suggested_value: number | string | null;
  reason: string;
  confidence: number;
  impact: "high" | "medium" | "low";
  direction?: "increase" | "decrease" | "change" | null;
}

interface SuggestionsData {
  symbol: string;
  generated_at?: string | null;
  suggestions: ParamSuggestion[];
  summary?: string | null;
  data_quality?: string | null;
  trades_analyzed?: number | null;
}

// Engine wraps every /learning/* response in {status, data: {...}} — verified
// live against engine/routers/learning_router.py get_suggestions() 2026-08-12.
interface SuggestionsResponse {
  status: string;
  data: SuggestionsData;
  error?: string;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function impactBadgeVariant(impact: string): "bull" | "warn" | "info" | "neutral" {
  switch (impact) {
    case "high":   return "bull";
    case "medium": return "warn";
    case "low":    return "info";
    default:       return "neutral";
  }
}

function confidenceBar(confidence: number) {
  const pct = Math.min(100, Math.max(0, confidence * 100));
  const color = pct >= 70 ? "#00ff88" : pct >= 40 ? "#ffcc00" : "#888";
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 rounded-full bg-muted overflow-hidden">
        <div
          className="h-full rounded-full transition-all"
          style={{ width: `${pct}%`, backgroundColor: color }}
        />
      </div>
      <span className="font-mono text-[10px] tabular-nums" style={{ color }}>
        {pct.toFixed(0)}%
      </span>
    </div>
  );
}

function directionArrow(direction: string | null | undefined): string {
  switch (direction) {
    case "increase": return "↑";
    case "decrease": return "↓";
    case "change":   return "↔";
    default:         return "→";
  }
}

function directionColor(direction: string | null | undefined): string {
  switch (direction) {
    case "increase": return "#00ff88";
    case "decrease": return "#ff4444";
    default:         return "#ffcc00";
  }
}

// ── Component ─────────────────────────────────────────────────────────────────

interface SuggestionPanelProps {
  symbol: string;
}

export function SuggestionPanel({ symbol }: SuggestionPanelProps) {
  const { data: resp, isLoading, error } = useSWR<SuggestionsResponse>(
    `/learning/suggestions?symbol=${symbol}`,
    fetcher,
    { refreshInterval: REFRESH_MS }
  );

  const data = resp?.data;

  if (isLoading) {
    return (
      <div className="rounded-xl border border-border bg-card p-4">
        <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground mb-3">
          Strategy Tuning — {symbol}
        </p>
        <p className="font-mono text-xs text-muted-foreground/50 animate-pulse">
          Analyzing strategy parameters…
        </p>
      </div>
    );
  }

  if (error || resp?.error) {
    return (
      <div className="rounded-xl border border-border bg-card p-4 space-y-2">
        <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
          Strategy Tuning — {symbol}
        </p>
        <p className="font-mono text-xs text-red-400/70 italic">
          {resp?.error ?? "No suggestions available — the StrategyTuner needs more trade data"}
        </p>
        <p className="font-mono text-[10px] text-muted-foreground/40">
          Suggestions appear after 30+ completed trades with consistent market conditions.
        </p>
      </div>
    );
  }

  const suggestions = data?.suggestions ?? [];

  return (
    <div className="space-y-4">
      {/* Header summary */}
      <div className="rounded-xl border border-border bg-card p-4 space-y-3">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
              Strategy Tuning — {symbol}
            </p>
            {data?.generated_at && (
              <p className="font-mono text-[10px] text-muted-foreground/40 mt-0.5">
                Generated {new Date(data.generated_at).toLocaleString("en-US", {
                  month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
                })}
              </p>
            )}
          </div>
          <div className="text-right space-y-0.5">
            {data?.trades_analyzed != null && (
              <p className="font-mono text-[10px] text-muted-foreground/60">
                {data.trades_analyzed} trades analyzed
              </p>
            )}
            {data?.data_quality && (
              <Badge variant={
                data.data_quality === "good" ? "bull"
                : data.data_quality === "fair" ? "warn"
                : "neutral"
              }>
                {data.data_quality} data quality
              </Badge>
            )}
          </div>
        </div>

        {data?.summary && (
          <div className="rounded-lg border border-border/50 bg-muted/10 p-3">
            <p className="font-mono text-[11px] text-foreground/70 leading-relaxed">
              {data.summary}
            </p>
          </div>
        )}

        <div className="flex items-center gap-2">
          <span className="font-mono text-[10px] text-muted-foreground/60">
            {suggestions.length} suggestion{suggestions.length !== 1 ? "s" : ""}
          </span>
          {suggestions.filter((s) => s.impact === "high").length > 0 && (
            <Badge variant="bull">
              {suggestions.filter((s) => s.impact === "high").length} high impact
            </Badge>
          )}
        </div>
      </div>

      {/* Suggestion cards */}
      {suggestions.length === 0 ? (
        <div className="rounded-xl border border-border bg-card p-6 text-center">
          <p className="font-mono text-xs text-muted-foreground/50 italic">
            Strategy is performing well — no parameter changes suggested at this time.
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {suggestions.map((s, i) => (
            <div
              key={i}
              className="rounded-xl border border-border bg-card p-4 space-y-3"
            >
              {/* Param name + impact */}
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-center gap-2">
                  <span
                    className="font-mono text-sm font-bold"
                    style={{ color: directionColor(s.direction) }}
                  >
                    {directionArrow(s.direction)}
                  </span>
                  <span className="font-mono text-sm font-semibold text-foreground">
                    {s.param_name}
                  </span>
                </div>
                <Badge variant={impactBadgeVariant(s.impact)}>
                  {s.impact} impact
                </Badge>
              </div>

              {/* Current → Suggested */}
              <div className="flex items-center gap-3 font-mono text-xs">
                <div className="flex-1 rounded-lg bg-muted/20 border border-border/50 p-2.5 text-center">
                  <p className="text-[10px] uppercase tracking-wider text-muted-foreground/60 mb-1">
                    Current
                  </p>
                  <p className="text-base font-bold tabular-nums text-foreground/70">
                    {s.current_value != null ? String(s.current_value) : "—"}
                  </p>
                </div>

                <div className="flex flex-col items-center text-muted-foreground/40">
                  <span className="text-lg">→</span>
                </div>

                <div
                  className="flex-1 rounded-lg border p-2.5 text-center"
                  style={{
                    backgroundColor: `${directionColor(s.direction)}08`,
                    borderColor: `${directionColor(s.direction)}30`,
                  }}
                >
                  <p className="text-[10px] uppercase tracking-wider text-muted-foreground/60 mb-1">
                    Suggested
                  </p>
                  <p
                    className="text-base font-bold tabular-nums"
                    style={{ color: directionColor(s.direction) }}
                  >
                    {s.suggested_value != null ? String(s.suggested_value) : "—"}
                  </p>
                </div>
              </div>

              {/* Reason */}
              <p className="font-mono text-[11px] text-foreground/60 leading-relaxed">
                {s.reason}
              </p>

              {/* Confidence bar */}
              <div className="space-y-1">
                <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/50">
                  Confidence
                </p>
                {confidenceBar(s.confidence)}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
