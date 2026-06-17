"use client";

import { useState, useEffect } from "react";
import { X } from "lucide-react";
import { useEngineHealth } from "@/lib/engine-context";

/**
 * Engine reachability hint — shown when the local engine is unreachable.
 * Reads from the centralized EngineDataContext (no independent polling).
 * Auto-dismisses after 12s; user can dismiss manually.
 * Uses operator-friendly language (no FastAPI/Next.js references).
 */
export function EngineAvailabilityHint() {
  const { isOffline } = useEngineHealth();
  const [dismissed, setDismissed] = useState(false);
  const [visible, setVisible] = useState(false);
  const timerRef = { current: null as ReturnType<typeof setTimeout> | null };

  useEffect(() => {
    if (isOffline && !dismissed) {
      setVisible(true);
      // Auto-dismiss after 12s
      timerRef.current = setTimeout(() => setVisible(false), 12000);
    } else if (!isOffline) {
      setVisible(false);
      setDismissed(false); // reset so it shows again if engine goes offline again
      if (timerRef.current) clearTimeout(timerRef.current);
    }
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOffline]);

  if (!visible || dismissed) return null;

  return (
    <div
      className="flex items-center justify-between border-b px-4 py-2 font-mono text-xs animate-fade-in"
      style={{
        backgroundColor: "rgba(255, 170, 0, 0.06)",
        borderColor: "rgba(255, 170, 0, 0.20)",
        color: "#ffaa00",
      }}
      role="status"
    >
      <span>
        Engine offline — trading suspended. Start the Jarvis engine on your local machine to enable live data.
      </span>
      <button
        onClick={() => { setDismissed(true); setVisible(false); }}
        className="ml-4 flex-shrink-0 opacity-50 hover:opacity-100 transition-opacity"
        aria-label="Dismiss"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}
