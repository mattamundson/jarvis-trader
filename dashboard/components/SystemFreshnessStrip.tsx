"use client";

import useSWR from "swr";
import { Wifi, WifiOff, Activity, Clock } from "lucide-react";
import { useEngineStatus } from "@/hooks/useEngineStatus";
import { useEngineWebSocketContext } from "@/lib/engine-websocket-context";
import { StalenessIndicator } from "@/components/ui/staleness-indicator";
import { Badge } from "@/components/ui/badge";
import { fetchMasterStatus, aggregationBannerState } from "@/lib/masterApi";
import { POLL_INTERVAL } from "@/lib/polling-config";
import { cn } from "@/lib/utils";

function fmtEventType(type: string | undefined): string {
  if (!type) return "none";
  return type.replaceAll("_", " ").toUpperCase();
}

function fmtEventTime(timestamp: string | undefined): Date | null {
  if (!timestamp) return null;
  const d = new Date(timestamp);
  return Number.isNaN(d.getTime()) ? null : d;
}

function eventTimestamp(event: ReturnType<typeof useEngineWebSocketContext>["lastEvent"]): string | undefined {
  return event && "timestamp" in event ? event.timestamp : undefined;
}

/**
 * Phase 4 operator observability: compact always-on freshness strip.
 *
 * This is intentionally read-only: it surfaces engine reachability and shared
 * WebSocket state but does not change any trading/risk config or execution
 * behavior. The engine-offline banner remains the loud failure mode; this strip
 * is the quiet at-a-glance status line for normal operation and review.
 */
export function SystemFreshnessStrip() {
  const { isOnline, lastChecked } = useEngineStatus();
  const { isConnected, lastEvent } = useEngineWebSocketContext();
  const lastEventTime = fmtEventTime(eventTimestamp(lastEvent));

  // Master-API reachability (Phase 10.1). Shares the "master-status" SWR key
  // with app/master/page.tsx so both consumers dedupe onto one poll.
  // aggregationBannerState() (lib/masterApi.ts) already distinguishes
  // unreachable (fetch failed / no body) from degraded-with-named-stale-
  // domains from healthy -- reused as-is rather than re-deriving the logic.
  const { data: masterStatus, error: masterError, isLoading: masterLoading } = useSWR(
    "master-status",
    fetchMasterStatus,
    { refreshInterval: POLL_INTERVAL.HEALTH },
  );
  const masterBanner = masterLoading
    ? null
    : aggregationBannerState(masterStatus ?? null, !!masterError);
  const masterUnreachable = !masterLoading && (!!masterError || masterStatus == null);

  return (
    <div
      role="status"
      aria-live="polite"
      className="sticky top-0 z-30 flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-border/70 bg-background/95 px-4 py-1.5 font-mono text-[10px] text-muted-foreground backdrop-blur"
    >
      <span className="flex items-center gap-1.5 font-bold uppercase tracking-widest text-foreground/80">
        <Activity className="h-3 w-3 text-accent" />
        System Freshness
      </span>

      <span className="flex items-center gap-1.5">
        <span
          className={cn(
            "h-1.5 w-1.5 rounded-full",
            isOnline ? "bg-bull animate-pulse" : "bg-bear animate-pulse",
          )}
        />
        Engine {isOnline ? "online" : "offline"}
      </span>

      <span className="flex items-center gap-1.5">
        {isConnected ? (
          <Wifi className="h-3 w-3 text-bull" />
        ) : (
          <WifiOff className="h-3 w-3 text-warn" />
        )}
        WS {isConnected ? "connected" : "disconnected"}
      </span>

      <span className="flex items-center gap-1.5">
        <Clock className="h-3 w-3 text-muted-foreground" />
        Health
        <StalenessIndicator
          lastUpdated={lastChecked}
          freshMs={30_000}
          staleMs={2 * 60_000}
          className="h-5 px-1.5 text-[10px]"
        />
      </span>

      <span className="flex items-center gap-1.5">
        Last event:
        <span className="text-foreground/80">{fmtEventType(lastEvent?.type)}</span>
        {lastEventTime && (
          <StalenessIndicator
            lastUpdated={lastEventTime}
            freshMs={30_000}
            staleMs={5 * 60_000}
            className="h-5 px-1.5 text-[10px]"
          />
        )}
      </span>

      <span className="flex items-center gap-1.5">
        {masterLoading ? (
          <span className="h-1.5 w-1.5 rounded-full bg-muted-foreground/50" />
        ) : masterBanner?.degraded ? (
          <WifiOff className="h-3 w-3 text-warn" />
        ) : (
          <Wifi className="h-3 w-3 text-bull" />
        )}
        Master API{" "}
        {masterLoading ? (
          "checking…"
        ) : masterBanner?.degraded ? (
          <Badge
            variant="warn"
            className="h-5 px-1.5 text-[10px] font-normal"
            title={masterBanner.reason}
          >
            {masterUnreachable ? "unreachable" : "degraded"}
          </Badge>
        ) : (
          "reachable"
        )}
      </span>
    </div>
  );
}
