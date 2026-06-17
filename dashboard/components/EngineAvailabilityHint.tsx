"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { X } from "lucide-react";

import { fetchEngine } from "@/lib/api";

/**
 * Engine reachability hint — shown when the local FastAPI engine is unreachable.
 * Auto-dismisses after 12s; user can also dismiss manually.
 * Uses operator-friendly language (no references to FastAPI / Next.js rewrites).
 */
export function EngineAvailabilityHint() {
  const pathname = usePathname();
  const [visible, setVisible] = useState(false);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    // Reset dismiss on route change so the hint can reappear if still offline
    setDismissed(false);
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    (async () => {
      try {
        await fetchEngine("/health");
        if (!cancelled) setVisible(false);
      } catch {
        if (!cancelled) {
          setVisible(true);
          // Auto-dismiss after 12 seconds
          timer = setTimeout(() => {
            if (!cancelled) setVisible(false);
          }, 12000);
        }
      }
    })();

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [pathname]);

  if (!visible || dismissed) return null;

  return (
    <div
      className="flex items-center justify-between border-b px-4 py-2 font-mono text-xs"
      style={{
        backgroundColor: "rgba(255, 170, 0, 0.08)",
        borderColor: "rgba(255, 170, 0, 0.25)",
        color: "#ffaa00",
      }}
      role="status"
    >
      <span>Engine offline — trading suspended. Start the Jarvis engine on your local machine to enable live data.</span>
      <button
        onClick={() => setDismissed(true)}
        className="ml-4 flex-shrink-0 opacity-60 hover:opacity-100 transition-opacity"
        aria-label="Dismiss"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}
