"use client";

import useSWR from "swr";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchLlmDailyStats } from "@/lib/api";

const REFRESH_MS = 60_000;

// Reference target from the JARVIS Master Battle Plan (P6). This is NOT an
// enforced cap in the engine — cost_tracker.py only tracks/reports spend,
// nothing blocks a call once this is exceeded. Shown as a reference line only.
const DAILY_COST_TARGET_USD = 50;

function fmtUsd(v: number): string {
  return `$${v.toFixed(2)}`;
}

function barVariant(pct: number): "bull" | "warn" | "bear" {
  if (pct < 0.7) return "bull";
  if (pct < 1.0) return "warn";
  return "bear";
}

export function LlmCostWidget() {
  const { data, isLoading, error } = useSWR(
    ["llm-daily-stats", 0],
    () => fetchLlmDailyStats(0),
    { refreshInterval: REFRESH_MS }
  );

  const pct = data ? data.total_cost_usd / DAILY_COST_TARGET_USD : 0;
  const variant = barVariant(pct);

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>LLM Cost Today</CardTitle>
          <Badge variant={error ? "static" : "live"}>{error ? "static" : "live"}</Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {isLoading ? (
          <p className="text-xs text-muted-foreground/50 animate-pulse">Loading…</p>
        ) : error ? (
          <p className="text-xs text-red-400/70 italic">
            LLM cost stats unavailable — engine may be unreachable
          </p>
        ) : (
          <>
            <div className="flex items-end justify-between">
              <div>
                <p className="text-2xl font-bold text-foreground tabular-nums">
                  {fmtUsd(data!.total_cost_usd)}
                </p>
                <p className="text-[11px] text-muted-foreground">
                  {data!.total_calls} calls &middot; {(data!.success_rate * 100).toFixed(0)}% success
                  &middot; {Math.round(data!.avg_latency_ms)}ms avg
                </p>
              </div>
              <Badge variant={variant}>
                {(pct * 100).toFixed(0)}% of ${DAILY_COST_TARGET_USD}/day reference
              </Badge>
            </div>

            <div className="h-1.5 rounded-full bg-muted overflow-hidden">
              <div
                className={`h-full rounded-full ${
                  variant === "bull" ? "bg-bull" : variant === "warn" ? "bg-warn" : "bg-bear"
                }`}
                style={{ width: `${Math.min(100, pct * 100)}%` }}
              />
            </div>

            <p className="text-[10px] text-muted-foreground/40">
              Reference only — not an enforced cap. No code path currently blocks
              LLM calls once this target is exceeded.
            </p>

            {Object.keys(data!.per_model).length > 0 && (
              <div className="space-y-1 pt-1">
                {Object.entries(data!.per_model)
                  .sort((a, b) => b[1].cost_usd - a[1].cost_usd)
                  .map(([model, stats]) => (
                    <div
                      key={model}
                      className="flex items-center justify-between text-[11px]"
                    >
                      <span className="text-muted-foreground truncate">{model}</span>
                      <span className="text-foreground/80 tabular-nums shrink-0 ml-2">
                        {fmtUsd(stats.cost_usd)} &middot; {stats.calls} calls
                      </span>
                    </div>
                  ))}
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
