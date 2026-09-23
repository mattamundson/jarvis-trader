"use client";

import { useState } from "react";
import useSWR from "swr";
<<<<<<< HEAD
import { fetchEngine } from "@/lib/api";
=======
import { fetchEngineNoRetry } from "@/lib/api";
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
import { POLL_INTERVAL } from "@/lib/polling-config";

export interface EngineStatus {
  isOnline: boolean;
  lastChecked: Date | null;
}

/**
 * SWR-backed poll of the engine health endpoint on the shared HEALTH cadence.
 * SWR owns dedup/interval/stale-request handling; `lastChecked` is stamped on
 * every settle (success or error) via onSuccess/onError, mirroring the old
 * hand-rolled useEffect+setInterval+AbortController implementation.
 */
export function useEngineStatus(): EngineStatus {
  const [lastChecked, setLastChecked] = useState<Date | null>(null);

<<<<<<< HEAD
  const { error } = useSWR("/health", () => fetchEngine("/health"), {
=======
  const { error } = useSWR("/health", () => fetchEngineNoRetry("/health"), {
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
    refreshInterval: POLL_INTERVAL.HEALTH,
    shouldRetryOnError: false,
    errorRetryCount: 0,
    onSuccess: () => setLastChecked(new Date()),
    onError: () => setLastChecked(new Date()),
  });

  return { isOnline: !error, lastChecked };
}
