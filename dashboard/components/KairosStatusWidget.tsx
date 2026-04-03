"use client";

import useSWR from "swr";
import { useRouter } from "next/navigation";
import { Radio } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchEngine } from "@/lib/api";

// ── Types ─────────────────────────────────────────────────────────────────────

interface KairosStatus {
  enabled: boolean;
  running: boolean;
  tick_count: number;
  watcher_count: number;
  last_tick: string | null;
  uptime_seconds: number | null;
  error_count: number;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fetcher<T>(url: string): Promise<T> {
  return fetchEngine<T>(url);
}

function timeAgo(isoString: string | null): string {
  if (!isoString) return "never";
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
    return "unknown";
  }
}

// ── Component ─────────────────────────────────────────────────────────────────

export function KairosStatusWidget() {
  const router = useRouter();

  const { data, error } = useSWR<KairosStatus>("/kairos/status", fetcher, {
    refreshInterval: 30_000,
  });

  if (error || !data) {
    // Loading / error — show compact skeleton
    return (
      <Card
        className="cursor-pointer hover:border-accent/40 transition-colors"
        onClick={() => router.push("/kairos")}
      >
        <CardContent className="p-3">
          <div className="flex items-center gap-2">
            <div className="h-2 w-2 rounded-full bg-muted animate-pulse" />
            <span className="text-xs font-semibold text-muted-foreground tracking-wide">
              KAIROS
            </span>
          </div>
        </CardContent>
      </Card>
    );
  }

  const isRunning = data.running === true;
  const isEnabled = data.enabled !== false;

  return (
    <Card
      className="cursor-pointer hover:border-accent/40 transition-colors"
      onClick={() => router.push("/kairos")}
    >
      <CardContent className="p-3 space-y-2">
        {/* Header row */}
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            {/* Pulsing indicator */}
            <span className="relative flex h-2 w-2">
              {isRunning && isEnabled ? (
                <>
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-bull opacity-75" />
                  <span className="relative inline-flex h-2 w-2 rounded-full bg-bull" />
                </>
              ) : (
                <span className="relative inline-flex h-2 w-2 rounded-full bg-muted-foreground" />
              )}
            </span>
            <span className="text-xs font-semibold text-foreground tracking-wide">
              KAIROS
            </span>
          </div>
          <Badge variant={isRunning && isEnabled ? "bull" : isEnabled ? "warn" : "neutral"}>
            {!isEnabled ? "Disabled" : isRunning ? "Running" : "Stopped"}
          </Badge>
        </div>

        {/* Stats row */}
        <div className="flex items-center gap-3 text-[11px] text-muted-foreground">
          <div className="flex items-center gap-1">
            <Radio className="h-3 w-3" />
            <span>{data.tick_count ?? 0} ticks today</span>
          </div>
          <span className="text-border">·</span>
          <span>{data.watcher_count ?? 0} watchers</span>
          <span className="text-border">·</span>
          <span>{timeAgo(data.last_tick)}</span>
        </div>
      </CardContent>
    </Card>
  );
}
