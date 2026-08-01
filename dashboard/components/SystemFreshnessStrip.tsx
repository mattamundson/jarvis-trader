"use client";

import { Wifi, WifiOff, Activity, Clock } from "lucide-react";
import { useEngineStatus } from "@/hooks/useEngineStatus";
import { useEngineWebSocketContext } from "@/lib/engine-websocket-context";
import { StalenessIndicator } from "@/components/ui/staleness-indicator";
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
    </div>
  );
}
