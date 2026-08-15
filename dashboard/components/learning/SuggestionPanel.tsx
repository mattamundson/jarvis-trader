"use client";

import useSWR from "swr";
import { fetchEngine } from "@/lib/api";
import { Badge } from "@/components/ui/badge";

const REFRESH_MS = 60_000;

function fetcher<T = unknown>(url: string): Promise<T> {
  return fetchEngine<T>(url);
}

// ── Types ─────────────────────────────────────────────────────────────────────
// Mirrors the ACTUAL engine response — GET /learning/suggestions in
// engine/routers/learning_router.py wraps everything as {status, data}, and
// each Suggestion (engine/learning/_experimental/strategy_tuner.py) only ever
// carries param_name/current_value/suggested_value/confidence/reason. There is
// no `impact` tier or `direction` field on the wire — both are derived below.

interface ParamSuggestion {
  param_name: string;
  current_value: number | string | null;
  suggested_value: number | string | null;
  confidence: number;
  reason: string;
}

interface SuggestionsData {
  symbol: string | null;
  trades_analyzed: number;
  current_params: Record<string, number | string>;
  suggestions: ParamSuggestion[];
  suggestion_count: number;
}

interface SuggestionsEnvelope {
  status: string;
  data: SuggestionsData;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

type Impact = "high" | "medium" | "low";
type Direction = "increase" | "decrease" | "change";

// The backend does not return an impact tier — derive one from confidence
// using the same 70%/40% thresholds the confidence bar below already uses.
function impactFromConfidence(confidence: number): Impact {
  if (confidence >= 0.7) return "high";
  if (confidence >= 0.4) return "medium";
  return "low";
}

function impactBadgeVariant(impact: Impact): "bull" | "warn" | "info" {
  switch (impact) {
    case "high":   return "bull";
    case "medium": return "warn";
    case "low":    return "info";
  }
}

// The backend does not return a direction either — derive it by comparing
// current_value vs suggested_value (both may be numeric or numeric strings).
function directionFromValues(
  current: number | string | null,
  suggested: number | string | null
): Direction {
  const c = typeof current === "number" ? current : Number(current);
  const s = typeof suggested === "number" ? suggested : Number(suggested);
  if (!Number.isFinite(c) || !Number.isFinite(s)) return "change";
  if (s > c) return "increase";
  if (s < c) return "decrease";
  return "change";
}

function directionArrow(direction: Direction): string {
  switch (direction) {
    case "increase": return "↑";
    case "decrease": return "↓";
    case "change":    return "↔";
  }
}

function directionColor(direction: Direction): string {
  switch (direction) {
    case "increase": return "#00ff88";
    case "decrease": return "#ff4444";
    case "change":    return "#ffcc00";
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

// ── Component ─────────────────────────────────────────────────────────────────

interface SuggestionPanelProps {
  symbol: string;
}

export function SuggestionPanel({ symbol }: SuggestionPanelProps) {
  const { data: envelope, isLoading, error } = useSWR<SuggestionsEnvelope>(
    `/learning/suggestions?symbol=${symbol}`,
    fetcher,
    { refreshInterval: REFRESH_MS }
  );

  const data = envelope?.data;

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

  if (error) {
    return (
      <div className="rounded-xl border border-border bg-card p-4 space-y-2">
        <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
          Strategy Tuning — {symbol}
        </p>
        <p className="font-mono text-xs text-red-400/70 italic">
          {error instanceof Error ? error.message : "No suggestions available — the StrategyTuner needs more trade data"}
        </p>
        <p className="font-mono text-[10px] text-muted-foreground/40">
          Suggestions appear after 5+ completed trades with consistent market conditions.
        </p>
      </div>
    );
  }

  const suggestions = data?.suggestions ?? [];
  const highImpactCount = suggestions.filter(
    (s) => impactFromConfidence(s.confidence) === "high"
  ).length;

  return (
    <div className="space-y-4">
      {/* Header summary */}
      <div className="rounded-xl border border-border bg-card p-4 space-y-3">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
              Strategy Tuning — {symbol}
            </p>
          </div>
          {data?.trades_analyzed != null && (
            <p className="font-mono text-[10px] text-muted-foreground/60">
              {data.trades_analyzed} trades analyzed
            </p>
          )}
        </div>

        <div className="flex items-center gap-2">
          <span className="font-mono text-[10px] text-muted-foreground/60">
            {suggestions.length} suggestion{suggestions.length !== 1 ? "s" : ""}
          </span>
          {highImpactCount > 0 && (
            <Badge variant="bull">{highImpactCount} high impact</Badge>
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
          {suggestions.map((s, i) => {
            const direction = directionFromValues(s.current_value, s.suggested_value);
            const impact = impactFromConfidence(s.confidence);
            return (
              <div
                key={`${s.param_name}-${i}`}
                className="rounded-xl border border-border bg-card p-4 space-y-3"
              >
                {/* Param name + impact */}
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-center gap-2">
                    <span
                      className="font-mono text-sm font-bold"
                      style={{ color: directionColor(direction) }}
                    >
                      {directionArrow(direction)}
                    </span>
                    <span className="font-mono text-sm font-semibold text-foreground">
                      {s.param_name}
                    </span>
                  </div>
                  <Badge variant={impactBadgeVariant(impact)}>
                    {impact} impact
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
                      backgroundColor: `${directionColor(direction)}08`,
                      borderColor: `${directionColor(direction)}30`,
                    }}
                  >
                    <p className="text-[10px] uppercase tracking-wider text-muted-foreground/60 mb-1">
                      Suggested
                    </p>
                    <p
                      className="text-base font-bold tabular-nums"
                      style={{ color: directionColor(direction) }}
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
            );
          })}
        </div>
      )}
    </div>
  );
}
