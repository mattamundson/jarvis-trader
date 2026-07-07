"use client";

import { useEffect, useMemo, useState } from "react";
import {
  classifyProvenance,
  type DataEnvelope,
  type ProvenanceView,
} from "@/lib/provenance";

/**
 * React hook wrapping `classifyProvenance` with a live client clock.
 *
 * On the server and the very first client render `nowMs` is null, so the result
 * exactly matches `classifyProvenance(env)` (server verdict, no clock) — this
 * keeps SSR/hydration in sync. After mount it ticks once per second, letting a
 * value that ages past its `stale_after_s` window downgrade LIVE -> STALE on
 * screen without a refetch. It can never promote to LIVE.
 */
export function useProvenance<T>(
  env: DataEnvelope<T> | null | undefined,
): ProvenanceView {
  const [nowMs, setNowMs] = useState<number | null>(null);

  useEffect(() => {
    setNowMs(Date.now());
    const id = setInterval(() => setNowMs(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  return useMemo(() => classifyProvenance(env, nowMs), [env, nowMs]);
}
