"use client";

import { useEffect, useState } from "react";
import { useIBDataHealth } from "@/hooks/useIBDataHealth";
import { StalenessIndicator } from "@/components/ui/staleness-indicator";

const DISMISS_DURATION_MS = 60_000;

/**
 * Loud, top-fixed banner shown whenever the IB market-data leg is degraded —
 * disconnected, or serving a non-IBKR fallback tier (sqlite_cache / polygon /
 * csv_cache / none). Reads PR#68 /health/full ib_gateway fields via
 * useIBDataHealth. Distinct from EngineOfflineBanner (bottom, engine fully down):
 * this surfaces silent degrade while the engine itself is still up.
 */
export function IBDataDegradedBanner() {
  const { isDataDegraded, dataSource, consecutiveFailures, lastChecked, hasSignal } =
    useIBDataHealth();
  const [dismissedUntil, setDismissedUntil] = useState<number | null>(null);
  const [now, setNow] = useState<number>(Date.now());

  // Keep `now` fresh so the dismiss timer re-shows the banner automatically.
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 5_000);
    return () => clearInterval(id);
  }, []);

  // Clear the dismiss as soon as data recovers, so a later degrade shows immediately.
  useEffect(() => {
    if (!isDataDegraded) setDismissedUntil(null);
  }, [isDataDegraded]);

  const isDismissed = dismissedUntil !== null && now < dismissedUntil;

  // Render only with a definite degrade signal and not dismissed.
  if (!hasSignal || !isDataDegraded || isDismissed) return null;

  function handleDismiss() {
    setDismissedUntil(Date.now() + DISMISS_DURATION_MS);
  }

  const sourceLabel = (dataSource ?? "fallback").toUpperCase();
  const failuresLabel =
    consecutiveFailures && consecutiveFailures > 0
      ? `watchdog retrying (${consecutiveFailures} failed)`
      : "watchdog reconnecting";

  return (
    <div
      role="alert"
      aria-live="assertive"
      className="fixed top-0 left-0 right-0 z-[9998] flex items-center justify-between gap-4 px-4 py-2 bg-amber-500 border-b-2 border-b-amber-600"
    >
      <div className="flex items-center gap-3 min-w-0">
        <span
          className="shrink-0 inline-block w-2.5 h-2.5 rounded-full animate-pulse bg-[#7a3d00]"
        />
        <p
          className="font-mono text-xs font-semibold leading-snug truncate text-[#1a1000]"
        >
          IB MARKET DATA DEGRADED{" "}
          <span className="font-normal opacity-70">—</span>{" "}
          <span className="font-normal text-[#3d2800]">
            serving {sourceLabel} fallback; {failuresLabel}.
          </span>
        </p>
        {lastChecked && (
          <span className="shrink-0 hidden sm:inline">
            <StalenessIndicator lastUpdated={lastChecked} />
          </span>
        )}
      </div>

      <button
        onClick={handleDismiss}
        aria-label="Dismiss data degraded banner for 60 seconds"
        className="shrink-0 flex items-center justify-center w-6 h-6 rounded transition-opacity hover:opacity-70 text-[#1a1000]"
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 16 16"
          fill="currentColor"
          className="w-4 h-4"
          aria-hidden="true"
        >
          <path d="M3.22 3.22a.75.75 0 0 1 1.06 0L8 6.94l3.72-3.72a.75.75 0 1 1 1.06 1.06L9.06 8l3.72 3.72a.75.75 0 1 1-1.06 1.06L8 9.06l-3.72 3.72a.75.75 0 0 1-1.06-1.06L6.94 8 3.22 4.28a.75.75 0 0 1 0-1.06Z" />
        </svg>
      </button>
    </div>
  );
}
