"use client";

import { POLL_INTERVAL } from "@/lib/polling-config";

import useSWR from "swr";
import { BarChart2 } from "lucide-react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchEngine } from "@/lib/api";

// ── Types ─────────────────────────────────────────────────────────────────────

interface SignalStats {
  total_signals: number;
  by_action: Record<string, number>;
  by_symbol: Record<string, number>;
  by_status: Record<string, number>;
  last_signal_at: string | null;
  pipeline_success_rate: number;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fetcher<T>(path: string): Promise<T> {
  return fetchEngine<T>(path);
}

function formatRelativeTime(iso: string | null): string {
  if (!iso) return "—";
  const diffMs = Date.now() - new Date(iso).getTime();
  if (diffMs < 0) return "just now";
  const diffSec = Math.floor(diffMs / 1000);
  if (diffSec < 60) return `${diffSec}s ago`;
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

// ── SignalStatsCard ───────────────────────────────────────────────────────────

export function SignalStatsCard() {
  const { data: stats, isLoading, error } = useSWR<SignalStats>(
    "/signals/stats",
    fetcher,
    { refreshInterval: POLL_INTERVAL.MINUTE, shouldRetryOnError: false }
  );

  const successRate = stats ? Math.round(stats.pipeline_success_rate * 100) : null;
  const successVariant =
    successRate === null
      ? "neutral"
      : successRate >= 90
      ? "bull"
      : successRate >= 70
      ? "warn"
      : "bear";

  const longCount = stats?.by_action?.["LONG"] ?? 0;
  const shortCount = stats?.by_action?.["SHORT"] ?? 0;
  const closeCount = stats?.by_action?.["CLOSE"] ?? 0;

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2">
            <BarChart2 className="h-4 w-4 text-muted-foreground" />
            Signal Stats
          </CardTitle>
          {successRate !== null && (
            <Badge variant={successVariant} className="font-mono text-[11px]">
              {successRate}% success
            </Badge>
          )}
        </div>
      </CardHeader>

      <CardContent className="space-y-3">
        {isLoading && (
          <div className="flex items-center gap-2 py-4 justify-center">
            <div className="h-3.5 w-3.5 rounded-full border-2 border-accent border-t-transparent animate-spin" />
            <span className="text-xs text-muted-foreground">Loading…</span>
          </div>
        )}

        {error && !isLoading && (
          <p className="text-center text-xs text-bear py-4">
            Stats unavailable — engine offline
          </p>
        )}

        {!isLoading && !error && stats && (
          <>
            {/* Total + last signal */}
            <div className="flex items-center justify-between">
              <div>
                <p className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
                  Total Processed
                </p>
                <p className="font-mono text-2xl font-bold tabular-nums text-foreground leading-none mt-0.5">
                  {stats.total_signals.toLocaleString()}
                </p>
              </div>
              <div className="text-right">
                <p className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
                  Last Signal
                </p>
                <p className="font-mono text-xs text-foreground/80 mt-0.5">
                  {formatRelativeTime(stats.last_signal_at)}
                </p>
              </div>
            </div>

            {/* Divider */}
            <div className="h-px bg-border" />

            {/* Action breakdown */}
            <div>
              <p className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground mb-2">
                Action Breakdown
              </p>
              <div className="flex items-center gap-2 flex-wrap">
                <div className="flex items-center gap-1.5">
                  <Badge variant="bull" className="font-mono text-[10px] px-2">
                    LONG
                  </Badge>
                  <span className="font-mono text-xs tabular-nums font-semibold text-foreground">
                    {longCount}
                  </span>
                </div>
                <div className="flex items-center gap-1.5">
                  <Badge variant="bear" className="font-mono text-[10px] px-2">
                    SHORT
                  </Badge>
                  <span className="font-mono text-xs tabular-nums font-semibold text-foreground">
                    {shortCount}
                  </span>
                </div>
                <div className="flex items-center gap-1.5">
                  <Badge variant="neutral" className="font-mono text-[10px] px-2">
                    CLOSE
                  </Badge>
                  <span className="font-mono text-xs tabular-nums font-semibold text-foreground">
                    {closeCount}
                  </span>
                </div>
              </div>
            </div>

            {/* Status breakdown */}
            {stats.by_status && Object.keys(stats.by_status).length > 0 && (
              <>
                <div className="h-px bg-border" />
                <div className="grid grid-cols-3 gap-2">
                  {(["completed", "skipped", "error"] as const).map((key) => {
                    const count = stats.by_status?.[key] ?? 0;
                    const variant =
                      key === "completed" ? "bull" : key === "error" ? "bear" : "warn";
                    return (
                      <div key={key} className="text-center">
                        <p className="font-mono text-[9px] uppercase tracking-widest text-muted-foreground">
                          {key}
                        </p>
                        <p
                          className={`font-mono text-sm font-bold tabular-nums mt-0.5 ${
                            variant === "bull"
                              ? "text-bull"
                              : variant === "bear"
                              ? "text-bear"
                              : "text-warn"
                          }`}
                        >
                          {count}
                        </p>
                      </div>
                    );
                  })}
                </div>
              </>
            )}
          </>
        )}

        {!isLoading && !error && !stats && (
          <p className="text-center text-xs text-muted-foreground py-4">
            No signal data yet
          </p>
        )}
      </CardContent>
    </Card>
  );
}
