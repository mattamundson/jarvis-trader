"use client";

import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

interface StalenessIndicatorProps {
  /** When the data was last fetched/checked. `null`/`undefined` renders "No data". */
  lastUpdated: Date | string | number | null | undefined;
  /** Age (ms) below which data counts as fresh/live. Default 60s. */
  freshMs?: number;
  /** Age (ms) above which data counts as stale/unreliable. Default 5min. */
  staleMs?: number;
  className?: string;
}

function formatAge(ms: number): string {
  const seconds = Math.max(0, Math.floor(ms / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ago`;
}

/**
 * Consistent freshness badge for live-data widgets — replaces the ad-hoc
 * "Last checked HH:MM:SS" text each widget previously rolled on its own.
 * Reuses the canonical `live`/`static` Badge provenance variants (Trust Pane,
 * 2026-07-02) plus `warn` for the in-between "getting old" state.
 */
export function StalenessIndicator({
  lastUpdated,
  freshMs = 60_000,
  staleMs = 300_000,
  className,
}: StalenessIndicatorProps) {
  // Ticker so the "Xs ago" text keeps advancing without a new fetch.
  const [, setTick] = useState(0);

  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(id);
  }, []);

  if (lastUpdated === null || lastUpdated === undefined) {
    return (
      <Badge variant="static" className={cn("gap-1.5 font-normal", className)}>
        No data
      </Badge>
    );
  }

  const date = lastUpdated instanceof Date ? lastUpdated : new Date(lastUpdated);
  if (Number.isNaN(date.getTime())) {
    return (
      <Badge variant="static" className={cn("gap-1.5 font-normal", className)}>
        No data
      </Badge>
    );
  }

  const ageMs = Date.now() - date.getTime();
  const variant = ageMs < freshMs ? "live" : ageMs < staleMs ? "warn" : "static";
  const label = ageMs < freshMs ? "Live" : ageMs < staleMs ? "Delayed" : "Stale";
  const dotClass =
    variant === "live" ? "bg-bull animate-pulse" : variant === "warn" ? "bg-warn" : "bg-muted-foreground/50";

  return (
    <Badge variant={variant} className={cn("gap-1.5 font-normal", className)}>
      <span className={cn("h-1.5 w-1.5 rounded-full shrink-0", dotClass)} />
      {label} &middot; {formatAge(ageMs)}
    </Badge>
  );
}
