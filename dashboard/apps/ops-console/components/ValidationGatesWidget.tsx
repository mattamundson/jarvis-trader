"use client";

import React from "react";
import useSWR from "swr";
import { RefreshCw } from "lucide-react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchEngine, type ValidationGatesData } from "@/lib/api";

const POLLING_INTERVAL_MS = 30_000; // 30 seconds

const fetcher = (): Promise<ValidationGatesData> =>
  fetchEngine<ValidationGatesData>("/paper/validation/gates");

function getGateLabel(name: string): string {
  const labels: Record<string, string> = {
    profit_factor: "Profit Factor",
    sharpe_ratio: "Sharpe Ratio",
    win_rate: "Win Rate",
    total_trades: "Total Trades",
    days_active: "Days Active",
    max_drawdown: "Max Drawdown",
  };
  return labels[name] || name;
}

function getGateBadgeVariant(
  name: string,
  passes: boolean,
  current: number,
  target: number
): "bull" | "warn" | "bear" | "info" {
  if (passes) return "bull";

  // Within 20% of target = amber (warn)
  if (name === "max_drawdown") {
    // For drawdown, lower is better, so check if within 20% of target
    const diff = target - current;
    const threshold = target * 0.2;
    if (diff >= 0 && diff <= threshold) return "warn";
  } else {
    // For other metrics, higher is better
    const diff = target - current;
    const threshold = target * 0.2;
    if (diff >= 0 && diff <= threshold) return "warn";
  }

  return "bear";
}

function formatValue(name: string, value: number, unit: string): string {
  if (name === "sharpe_ratio" || name === "profit_factor") {
    return value.toFixed(2);
  }
  if (unit === "%") {
    return `${value.toFixed(2)}%`;
  }
  if (unit === "days") {
    return `${Math.floor(value)}`;
  }
  return Math.floor(value).toString();
}

export function ValidationGatesWidget() {
  const { data, error, isLoading, mutate } = useSWR<ValidationGatesData>(
    "validation-gates",
    fetcher,
    { refreshInterval: POLLING_INTERVAL_MS, shouldRetryOnError: false }
  );

  const gates = data?.gates ?? [];
  const daysElapsed = data?.days_elapsed ?? 0;
  const daysRemaining = data?.days_remaining ?? 0;
  const overallPass = data?.overall_pass ?? false;

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <CardTitle>VALIDATION GATES</CardTitle>
            <Badge variant={overallPass ? "bull" : "info"}>
              {overallPass ? "READY" : "IN PROGRESS"}
            </Badge>
          </div>
          <button
            onClick={() => mutate()}
            disabled={isLoading}
            className="flex items-center gap-1 rounded border border-border px-2 py-1 text-xs text-muted-foreground hover:text-foreground transition-colors disabled:opacity-40"
          >
            <RefreshCw className={`h-3 w-3 ${isLoading ? "animate-spin" : ""}`} />
            Refresh
          </button>
        </div>
        <p className="text-xs text-muted-foreground pt-0.5">
          Day {daysElapsed} / 30 — {daysRemaining} days remaining
        </p>
      </CardHeader>

      <CardContent className="space-y-3">
        {error ? (
          <p className="text-sm text-bear">Error loading validation gates</p>
        ) : isLoading ? (
          <div className="space-y-2 animate-pulse">
            {[...Array(6)].map((_, i) => (
              <div
                key={i}
                className="h-8 bg-muted rounded flex items-center justify-between px-2"
              />
            ))}
          </div>
        ) : gates.length === 0 ? (
          <p className="text-sm text-muted-foreground">No validation data yet</p>
        ) : (
          <>
            {/* Gate rows */}
            <div className="space-y-2">
              {gates.map((gate) => {
                const variant = getGateBadgeVariant(
                  gate.name,
                  gate.passes,
                  gate.current,
                  gate.target
                );

                return (
                  <div
                    key={gate.name}
                    className="flex items-center justify-between rounded-lg border border-border bg-muted/30 px-3 py-2"
                  >
                    <div className="flex items-center gap-2 flex-1">
                      <span className="text-xs font-semibold text-foreground min-w-24">
                        {getGateLabel(gate.name)}
                      </span>
                      <span className="text-xs text-muted-foreground">
                        {formatValue(gate.name, gate.current, gate.unit)}
                      </span>
                      <span className="text-xs text-muted-foreground">
                        / {formatValue(gate.name, gate.target, gate.unit)}
                      </span>
                    </div>
                    <Badge variant={variant}>
                      {gate.passes ? "PASS" : "PENDING"}
                    </Badge>
                  </div>
                );
              })}
            </div>

            {/* Overall status */}
            <div className="mt-3 pt-3 border-t border-border">
              <p className="text-[10px] uppercase tracking-widest text-muted-foreground mb-2">
                Status
              </p>
              <div className="grid grid-cols-2 gap-2 text-xs">
                <div className="bg-muted/50 rounded p-2">
                  <p className="text-muted-foreground text-[10px] mb-1">
                    Gates Passing
                  </p>
                  <p className="font-bold text-foreground">
                    {gates.filter((g) => g.passes).length} / {gates.length}
                  </p>
                </div>
                <div className="bg-muted/50 rounded p-2">
                  <p className="text-muted-foreground text-[10px] mb-1">
                    Days Elapsed
                  </p>
                  <p className="font-bold text-foreground">
                    {daysElapsed} / 30
                  </p>
                </div>
              </div>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
