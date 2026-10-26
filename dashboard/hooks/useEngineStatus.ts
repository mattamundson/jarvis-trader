"use client";

import { useEffect, useState } from "react";
import useSWR from "swr";
import { fetchEngineNoRetry } from "@/lib/api";
import { POLL_INTERVAL } from "@/lib/polling-config";

export interface EngineStatus {
  isOnline: boolean;
  lastChecked: Date | null;
}

/**
 * SWR-backed poll of the engine health endpoint on the shared HEALTH cadence.
 * Several components share the "/health" key. SWR delivers `data` / `error` to
 * every subscriber, but `onSuccess` / `onError` run only for the subscriber
 * that started the request. Stamp `lastChecked` from the shared result so a
 * later subscriber, such as the freshness strip, does not stay on "No data".
 */
export function useEngineStatus(): EngineStatus {
  const [lastChecked, setLastChecked] = useState<Date | null>(null);

  const { data, error } = useSWR("/health", () => fetchEngineNoRetry("/health"), {
    refreshInterval: POLL_INTERVAL.HEALTH,
    shouldRetryOnError: false,
    errorRetryCount: 0,
  });

  useEffect(() => {
    if (data === undefined && error == null) return;
    setLastChecked(new Date());
  }, [data, error]);

  return { isOnline: !error, lastChecked };
}
