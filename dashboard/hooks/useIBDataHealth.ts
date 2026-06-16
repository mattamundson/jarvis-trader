"use client";

import { useEffect, useRef, useState } from "react";
import { fetchEngine, type FullHealthResponse, type IBGatewayHealth } from "@/lib/api";

const POLL_INTERVAL_MS = 10_000;

export interface IBDataHealth {
  /** True only when there's a definite signal the data leg is degraded. */
  isDataDegraded: boolean;
  dataSource: string | null;
  ibkrDataConnected: boolean | null;
  consecutiveFailures: number | null;
  lastChecked: Date | null;
  /** True only once we've parsed a response that actually carries the PR#68 fields. */
  hasSignal: boolean;
}

const INITIAL: IBDataHealth = {
  isDataDegraded: false,
  dataSource: null,
  ibkrDataConnected: null,
  consecutiveFailures: null,
  lastChecked: null,
  hasSignal: false,
};

/**
 * Polls /health/full every 10s and derives whether the IB market-data leg is
 * degraded — i.e. disconnected, or serving a non-IBKR fallback tier. Mirrors the
 * abort/cleanup discipline of useEngineStatus. Fully defensive: an engine build
 * without the PR#68 ib_gateway fields yields hasSignal=false (no false banner),
 * and a fetch error never asserts degrade (EngineOfflineBanner owns "offline").
 */
export function useIBDataHealth(): IBDataHealth {
  const [state, setState] = useState<IBDataHealth>(INITIAL);
  const activeController = useRef<AbortController | null>(null);
  const intervalId = useRef<ReturnType<typeof setInterval> | null>(null);

  async function check(): Promise<void> {
    activeController.current?.abort();
    const controller = new AbortController();
    activeController.current = controller;

    try {
      const full = await fetchEngine<FullHealthResponse>("/health/full");
      if (controller.signal.aborted) return;

      const ib: IBGatewayHealth | undefined = full?.subsystems?.ib_gateway;
      const hasNewFields =
        ib != null && (ib.data_source !== undefined || ib.data_connected !== undefined);

      if (!hasNewFields) {
        // Older engine — surface no banner.
        setState((s) => ({ ...s, lastChecked: new Date(), hasSignal: false }));
        return;
      }

      const dataSource = (ib!.data_source ?? null) as string | null;
      const connected = ib!.data_connected ?? null;
      // Degraded when explicitly disconnected OR serving a non-IBKR tier.
      // dataSource === null means nothing has been fetched yet → not degraded.
      const degraded =
        connected === false || (dataSource != null && dataSource !== "ibkr");

      setState({
        isDataDegraded: degraded,
        dataSource,
        ibkrDataConnected: connected,
        consecutiveFailures: ib!.watchdog?.consecutive_failures ?? null,
        lastChecked: new Date(),
        hasSignal: true,
      });
    } catch (err) {
      if (err instanceof Error && err.name === "AbortError") return;
      if (controller.signal.aborted) return;
      // Engine unreachable is the offline banner's job — don't assert degrade.
      setState((s) => ({ ...s, lastChecked: new Date() }));
    }
  }

  useEffect(() => {
    check();
    intervalId.current = setInterval(check, POLL_INTERVAL_MS);
    return () => {
      activeController.current?.abort();
      if (intervalId.current !== null) clearInterval(intervalId.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return state;
}
