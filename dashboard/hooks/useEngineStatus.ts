"use client";

import { useEffect, useRef, useState } from "react";
import { fetchEngine } from "@/lib/api";

const POLL_INTERVAL_MS = 10_000;

export interface EngineStatus {
  isOnline: boolean;
  lastChecked: Date | null;
}

/**
 * Polls the engine health endpoint every 10 seconds.
 * Uses AbortController on each request to prevent stale responses updating
 * state after unmount. Both the initial fetch and each interval tick are
 * individually abortable. Everything is cleaned up on unmount.
 */
export function useEngineStatus(): EngineStatus {
  const [isOnline, setIsOnline] = useState<boolean>(true);
  const [lastChecked, setLastChecked] = useState<Date | null>(null);

  // Holds the AbortController for the most recent in-flight fetch
  const activeController = useRef<AbortController | null>(null);
  const intervalId = useRef<ReturnType<typeof setInterval> | null>(null);

  async function checkHealth(): Promise<void> {
    // Abort any previous in-flight request before starting a new one
    activeController.current?.abort();
    const controller = new AbortController();
    activeController.current = controller;

    try {
      await fetchEngine("/health");
      if (!controller.signal.aborted) {
        setIsOnline(true);
        setLastChecked(new Date());
      }
    } catch (err) {
      if (err instanceof Error && err.name === "AbortError") {
        // Intentional abort — do not update state
        return;
      }
      if (!controller.signal.aborted) {
        setIsOnline(false);
        setLastChecked(new Date());
      }
    }
  }

  useEffect(() => {
    // Fire immediately on mount
    checkHealth();

    // Then poll on interval
    intervalId.current = setInterval(checkHealth, POLL_INTERVAL_MS);

    return () => {
      // Abort the most recent in-flight request
      activeController.current?.abort();
      // Cancel the interval
      if (intervalId.current !== null) {
        clearInterval(intervalId.current);
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return { isOnline, lastChecked };
}
