"use client";

import { useEffect, useState } from "react";
import { useEngineStatus } from "@/hooks/useEngineStatus";
import { StalenessIndicator } from "@/components/ui/staleness-indicator";

const DISMISS_DURATION_MS = 60_000;

export function EngineOfflineBanner() {
  const { isOnline, lastChecked } = useEngineStatus();
  const [dismissedUntil, setDismissedUntil] = useState<number | null>(null);
  const [now, setNow] = useState<number>(Date.now());

  // Keep `now` fresh so the dismiss timer re-shows the banner automatically
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 5_000);
    return () => clearInterval(id);
  }, []);

  // If the engine comes back online, clear any active dismiss so the banner
  // disappears immediately (it won't be rendered anyway, but this keeps state clean).
  useEffect(() => {
    if (isOnline) setDismissedUntil(null);
  }, [isOnline]);

  const isDismissed = dismissedUntil !== null && now < dismissedUntil;

  // Only render when the engine is offline AND the user hasn't dismissed
  if (isOnline || isDismissed) return null;

  function handleDismiss() {
    setDismissedUntil(Date.now() + DISMISS_DURATION_MS);
  }

  return (
    <div
      role="alert"
      aria-live="assertive"
      className="fixed bottom-0 left-0 right-0 z-[9999] flex items-center justify-between gap-4 px-4 py-3"
      style={{
        backgroundColor: "#ffcc00",
        borderTop: "2px solid #e6b800",
      }}
    >
      {/* Left: icon + message */}
      <div className="flex items-center gap-3 min-w-0">
        {/* Pulsing dot */}
        <span
          className="shrink-0 inline-block w-2.5 h-2.5 rounded-full animate-pulse"
          style={{ backgroundColor: "#7a5c00" }}
        />

        <p
          className="font-mono text-xs font-semibold leading-snug truncate"
          style={{ color: "#1a1000" }}
        >
          ENGINE OFFLINE{" "}
          <span className="font-normal opacity-70">—</span>{" "}
          <span className="font-normal" style={{ color: "#3d2800" }}>
            Engine API not responding (dashboard uses the /api/engine proxy). Start the FastAPI engine and see docs/troubleshooting.md.
          </span>
        </p>

        {lastChecked && (
          <span className="shrink-0 hidden sm:inline">
            <StalenessIndicator lastUpdated={lastChecked} />
          </span>
        )}
      </div>

      {/* Right: dismiss button */}
      <button
        onClick={handleDismiss}
        aria-label="Dismiss engine offline banner for 60 seconds"
        className="shrink-0 flex items-center justify-center w-6 h-6 rounded transition-opacity hover:opacity-70"
        style={{ color: "#1a1000" }}
      >
        {/* Simple X — no external icon dependency */}
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
