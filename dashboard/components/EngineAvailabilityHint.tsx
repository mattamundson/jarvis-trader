"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";

import { fetchEngine } from "@/lib/api";

/**
 * P2.3 — Surface engine reachability (LLM/pipeline availability is separate).
 * /health is auth-exempt on the engine; uses Next rewrite /api/engine/health.
 */
export function EngineAvailabilityHint() {
  const pathname = usePathname();
  const [hint, setHint] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        await fetchEngine("/health");
        if (cancelled) return;
        setHint(null);
      } catch {
        if (!cancelled) {
          setHint("Cannot reach the engine — confirm the FastAPI service is up and Next.js rewrites are configured.");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [pathname]);

  if (!hint) return null;

  return (
    <div
      className="border-b border-amber-500/40 bg-amber-500/10 px-4 py-2 text-center font-mono text-xs text-amber-200"
      role="status"
    >
      {hint}
    </div>
  );
}
