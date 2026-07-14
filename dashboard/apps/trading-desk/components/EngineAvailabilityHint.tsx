"use client";

import { useEngineStatus } from "@/hooks/useEngineStatus";

/**
 * P2.3 — Surface engine reachability (LLM/pipeline availability is separate).
 *
 * Uses the shared, POLLING `useEngineStatus` hook (SWR key "/health" on the
 * HEALTH cadence) rather than a one-shot per-navigation check. This is what
 * catches a MID-SESSION engine death: the old implementation only re-checked
 * on `pathname` change, so if the engine died while the user sat on one page,
 * this hint never re-fired and the (intentionally stale-sticky) LLM/IB health
 * badges kept showing their last-known-good green with nothing contradicting
 * them. Sharing the `/health` SWR key means this adds no extra request.
 */
export function EngineAvailabilityHint() {
  const { isOnline } = useEngineStatus();

  if (isOnline) return null;

  return (
    <div
      className="border-b border-amber-500/40 bg-amber-500/10 px-4 py-2 text-center font-mono text-xs text-amber-200"
      role="status"
    >
      Cannot reach the engine — confirm the FastAPI service is up and Next.js rewrites
      are configured. Health badges below may show stale last-known-good values.
    </div>
  );
}
