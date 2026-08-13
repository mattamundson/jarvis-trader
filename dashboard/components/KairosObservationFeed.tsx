"use client";

import { POLL_INTERVAL } from "@/lib/polling-config";

import { useState } from "react";
import useSWR from "swr";
import { AlertTriangle, Info, XCircle, Inbox } from "lucide-react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchEngine } from "@/lib/api";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface Observation {
  timestamp: string;
  watcher: string;
  severity: "info" | "warning" | "critical";
  message: string;
  symbol?: string;
  notify: boolean;
}

interface ObservationsResponse {
  observations: Observation[];
  total: number;
}

type SeverityFilter = "all" | "warning+" | "critical";

// ── Helpers ───────────────────────────────────────────────────────────────────

function fetcher<T>(url: string): Promise<T> {
  return fetchEngine<T>(url);
}

function timeAgo(isoString: string): string {
  try {
    const diffMs = Date.now() - new Date(isoString).getTime();
    const diffSec = Math.floor(diffMs / 1000);
    if (diffSec < 60) return `${diffSec}s ago`;
    const diffMin = Math.floor(diffSec / 60);
    if (diffMin < 60) return `${diffMin}m ago`;
    const diffHr = Math.floor(diffMin / 60);
    if (diffHr < 24) return `${diffHr}h ago`;
    return `${Math.floor(diffHr / 24)}d ago`;
  } catch {
    return "";
  }
}

function severityBadgeVariant(severity: Observation["severity"]): "info" | "warn" | "bear" {
  switch (severity) {
    case "info":
      return "info";
    case "warning":
      return "warn";
    case "critical":
      return "bear";
  }
}

function SeverityIcon({ severity }: { severity: Observation["severity"] }) {
  switch (severity) {
    case "info":
      return <Info className="h-3.5 w-3.5" />;
    case "warning":
      return <AlertTriangle className="h-3.5 w-3.5" />;
    case "critical":
      return <XCircle className="h-3.5 w-3.5" />;
  }
}

function passesFilter(obs: Observation, filter: SeverityFilter): boolean {
  if (filter === "all") return true;
  if (filter === "warning+") return obs.severity === "warning" || obs.severity === "critical";
  if (filter === "critical") return obs.severity === "critical";
  return true;
}

// ── Component ─────────────────────────────────────────────────────────────────

interface KairosObservationFeedProps {
  /** Minutes of history to show. Defaults to 60. */
  minutes?: number;
}

export function KairosObservationFeed({ minutes = 60 }: KairosObservationFeedProps) {
  const [filter, setFilter] = useState<SeverityFilter>("all");

  const { data, error, isLoading } = useSWR<ObservationsResponse>(
    `/kairos/observations?minutes=${minutes}`,
    fetcher,
    { refreshInterval: POLL_INTERVAL.STATUS }
  );

  const allObservations = data?.observations ?? [];
  const filtered = allObservations.filter((o) => passesFilter(o, filter)).slice(0, 50);

  return (
    <Card className="flex flex-col h-full">
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle>Observation Feed</CardTitle>
        <div className="flex items-center gap-1.5">
          {(["all", "warning+", "critical"] as SeverityFilter[]).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`rounded-full px-2.5 py-0.5 text-[11px] font-medium border transition-colors ${
                filter === f
                  ? f === "critical"
                    ? "bg-bear/15 text-bear border-bear/20"
                    : f === "warning+"
                    ? "bg-warn/15 text-warn border-warn/20"
                    : "bg-accent/15 text-accent border-accent/20"
                  : "bg-muted text-muted-foreground border-border hover:text-foreground"
              }`}
            >
              {f === "all" ? "All" : f === "warning+" ? "Warning+" : "Critical"}
            </button>
          ))}
        </div>
      </CardHeader>

      <CardContent className="flex-1 overflow-hidden p-0">
        {/* Loading skeleton */}
        {isLoading && allObservations.length === 0 && (
          <div className="px-4 py-3 space-y-2">
            {Array.from({ length: 5 }).map((_, i) => (
              <div
                key={i}
                className="h-10 rounded-lg bg-muted animate-pulse"
              />
            ))}
          </div>
        )}

        {/* Error state */}
        {error && (
          <div className="flex flex-col items-center justify-center py-8 gap-2 text-center px-4">
            <XCircle className="h-6 w-6 text-bear" />
            <p className="text-sm font-medium text-bear">Failed to load observations</p>
            <p className="text-xs text-muted-foreground">Check that KAIROS is running</p>
          </div>
        )}

        {/* Empty state */}
        {!isLoading && !error && filtered.length === 0 && (
          <div className="flex flex-col items-center justify-center py-10 gap-2 text-center px-4">
            <Inbox className="h-6 w-6 text-muted-foreground" />
            <p className="text-sm text-muted-foreground">
              {allObservations.length === 0
                ? `No observations in last ${minutes} minutes`
                : "No observations match the current filter"}
            </p>
          </div>
        )}

        {/* Feed rows */}
        {filtered.length > 0 && (
          <div className="overflow-y-auto max-h-[480px] divide-y divide-border/50">
            {filtered.map((obs, idx) => (
              <div
                key={`${obs.timestamp}-${obs.watcher}-${idx}`}
                className="flex items-start gap-3 px-4 py-2.5 hover:bg-muted/20 transition-colors"
              >
                {/* Severity icon */}
                <span
                  className={`mt-0.5 shrink-0 ${
                    obs.severity === "critical"
                      ? "text-bear"
                      : obs.severity === "warning"
                      ? "text-warn"
                      : "text-info"
                  }`}
                >
                  <SeverityIcon severity={obs.severity} />
                </span>

                {/* Main content */}
                <div className="flex-1 min-w-0 space-y-0.5">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-xs font-semibold text-foreground">
                      {obs.watcher}
                    </span>
                    {obs.symbol && (
                      <span className="font-mono text-xs text-muted-foreground">
                        {obs.symbol}
                      </span>
                    )}
                    <Badge variant={severityBadgeVariant(obs.severity)}>
                      <span className="flex items-center gap-1">
                        <SeverityIcon severity={obs.severity} />
                        {obs.severity}
                      </span>
                    </Badge>
                    {obs.notify && (
                      <Badge variant="info">notified</Badge>
                    )}
                  </div>
                  <p className="text-xs text-muted-foreground leading-relaxed">
                    {obs.message}
                  </p>
                </div>

                {/* Timestamp */}
                <span className="shrink-0 text-[11px] text-muted-foreground whitespace-nowrap mt-0.5">
                  {timeAgo(obs.timestamp)}
                </span>
              </div>
            ))}
          </div>
        )}

        {/* Footer */}
        <div className="px-4 py-2 border-t border-border/50">
          <p className="text-[11px] text-muted-foreground">
            Showing last {minutes}min · {filtered.length} of {allObservations.length} observations · auto-refreshes every 15s
          </p>
        </div>
      </CardContent>
    </Card>
  );
}
