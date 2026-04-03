"use client";

import React from "react";
import useSWR from "swr";
import { RefreshCw } from "lucide-react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchRollingWFE, type WFEResponse, type WFEInstrument } from "@/lib/api";

const POLLING_INTERVAL_MS = 60_000; // 60 seconds

const fetcher = (): Promise<WFEResponse> => fetchRollingWFE();

function getStatusColor(
  status: "healthy" | "warning" | "critical" | "insufficient_data"
): string {
  switch (status) {
    case "healthy":
      return "text-bull";
    case "warning":
      return "text-warn";
    case "critical":
      return "text-bear";
    case "insufficient_data":
      return "text-muted-foreground";
  }
}

function getStatusBadgeVariant(
  status: "healthy" | "warning" | "critical" | "insufficient_data"
): "bull" | "warn" | "bear" | "info" {
  switch (status) {
    case "healthy":
      return "bull";
    case "warning":
      return "warn";
    case "critical":
      return "bear";
    case "insufficient_data":
      return "info";
  }
}

function formatWFE(wfe: number | null): string {
  if (wfe === null) return "—";
  return (wfe * 100).toFixed(1);
}

function WFEBar({ instrument }: { instrument: WFEInstrument }) {
  const { symbol, current_wfe, kill_threshold, status, trades_in_window, current_pf } = instrument;

  const wfeValue = current_wfe ?? 0;
  const barPercentage = Math.min(100, wfeValue * 100);
  const thresholdPercentage = Math.min(100, kill_threshold * 100);

  // Color for the progress bar
  const barColor = status === "healthy" ? "bg-bull" : status === "warning" ? "bg-warn" : status === "critical" ? "bg-bear" : "bg-muted";

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="font-mono text-xs font-semibold text-foreground min-w-12">
            {symbol}
          </span>
          <span className="text-xs text-muted-foreground">
            {formatWFE(current_wfe)}%
          </span>
        </div>
        <Badge variant={getStatusBadgeVariant(status)}>
          {status === "insufficient_data"
            ? "INSUFFICIENT"
            : status.toUpperCase()}
        </Badge>
      </div>

      {/* Progress bar with threshold marker */}
      <div className="relative h-2 w-full bg-muted rounded overflow-hidden">
        <div
          className={`h-full ${barColor} transition-all`}
          style={{ width: `${barPercentage}%` }}
        />
        {/* Threshold marker line */}
        {status !== "insufficient_data" && (
          <div
            className="absolute top-0 bottom-0 w-0.5 bg-foreground/40"
            style={{ left: `${thresholdPercentage}%` }}
          />
        )}
      </div>

      {/* Stats row */}
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span>
          {trades_in_window} trades
          {current_pf !== null && ` | PF {current_pf.toFixed(2)}`}
        </span>
        <span>Threshold: {(kill_threshold * 100).toFixed(0)}%</span>
      </div>
    </div>
  );
}

export function RollingWFEWidget() {
  const { data, error, isLoading, mutate } = useSWR<WFEResponse>(
    "rolling-wfe",
    fetcher,
    { refreshInterval: POLLING_INTERVAL_MS, shouldRetryOnError: false }
  );

  const instruments = data?.instruments ?? [];

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle>ROLLING WFE</CardTitle>
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
          Walk-Forward Efficiency monitoring
        </p>
      </CardHeader>

      <CardContent className="space-y-4">
        {error ? (
          <p className="text-sm text-bear">Error loading WFE data</p>
        ) : isLoading ? (
          <div className="space-y-3 animate-pulse">
            {[...Array(2)].map((_, i) => (
              <div key={i} className="space-y-1">
                <div className="h-4 bg-muted rounded w-20" />
                <div className="h-2 bg-muted rounded w-full" />
                <div className="h-3 bg-muted rounded w-32" />
              </div>
            ))}
          </div>
        ) : instruments.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No instruments configured
          </p>
        ) : (
          <div className="space-y-4">
            {instruments.map((instrument) => (
              <WFEBar key={instrument.symbol} instrument={instrument} />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
