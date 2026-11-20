"use client";

import { Clock } from "lucide-react";
import { StalenessIndicator } from "@/components/ui/staleness-indicator";
import { cn } from "@/lib/utils";
import {
  DEFAULT_FRESH_MS,
  DEFAULT_STALE_MS,
  formatPullTimeCt,
  staleWarning,
  toDate,
} from "@/lib/panelFreshness";

export interface PanelPullTimeProps {
  /** When this panel's data was last pulled/fetched. */
  pulledAt: Date | string | number | null | undefined;
  freshMs?: number;
  staleMs?: number;
  className?: string;
  /** Hide the absolute CT clock (badge only). */
  hideClock?: boolean;
}

/**
 * Addition-only per-panel freshness: absolute America/Chicago pull clock +
 * existing StalenessIndicator + a text warning when stale/missing.
 * Wire via CardHeader `pulledAt` or drop in beside a panel title.
 */
export function PanelPullTime({
  pulledAt,
  freshMs = DEFAULT_FRESH_MS,
  staleMs = DEFAULT_STALE_MS,
  className,
  hideClock = false,
}: PanelPullTimeProps) {
  const date = toDate(pulledAt);
  const warn = staleWarning(pulledAt, { freshMs, staleMs });

  return (
    <div
      role="status"
      aria-live="polite"
      className={cn("flex flex-wrap items-center gap-2 font-mono text-[10px] text-muted-foreground", className)}
    >
      {!hideClock && (
        <span className="inline-flex items-center gap-1" title="Panel pull time (America/Chicago)">
          <Clock className="h-3 w-3" />
          Pulled {formatPullTimeCt(date)}
        </span>
      )}
      <StalenessIndicator
        lastUpdated={date}
        freshMs={freshMs}
        staleMs={staleMs}
        className="h-5 px-1.5 text-[10px]"
      />
      {warn && (
        <span className="text-warn" data-testid="panel-stale-warning">
          {warn}
        </span>
      )}
    </div>
  );
}
