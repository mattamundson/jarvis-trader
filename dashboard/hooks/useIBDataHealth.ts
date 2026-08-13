"use client";

import { useState } from "react";
import useSWR from "swr";
import { fetchEngine, type FullHealthResponse, type IBGatewayHealth } from "@/lib/api";
import { HEALTH_FULL_KEY, POLL_INTERVAL } from "@/lib/polling-config";

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
 * SWR-backed poll of `/health/full`, deriving whether the IB market-data leg
 * is degraded — i.e. disconnected, or serving a non-IBKR fallback tier. Shares
 * the `HEALTH_FULL_KEY` SWR cache key with useLLMHealth so the two hooks
 * dedupe onto ONE polled request. Fully defensive: an engine build without the
 * PR#68 ib_gateway fields yields hasSignal=false (no false banner), and a
 * fetch error never asserts degrade (EngineOfflineBanner owns "offline").
 */
export function useIBDataHealth(): IBDataHealth {
  const [lastChecked, setLastChecked] = useState<Date | null>(null);

  const { data } = useSWR<FullHealthResponse>(
    HEALTH_FULL_KEY,
    () => fetchEngine<FullHealthResponse>(HEALTH_FULL_KEY),
    {
      refreshInterval: POLL_INTERVAL.HEALTH,
      shouldRetryOnError: false,
      errorRetryCount: 0,
      onSuccess: () => setLastChecked(new Date()),
      onError: () => setLastChecked(new Date()),
    },
  );

  const ib: IBGatewayHealth | undefined = data?.subsystems?.ib_gateway;
  const hasNewFields =
    ib != null && (ib.data_source !== undefined || ib.data_connected !== undefined);

  if (!hasNewFields) {
    return { ...INITIAL, lastChecked };
  }

  const dataSource = (ib!.data_source ?? null) as string | null;
  const connected = ib!.data_connected ?? null;
  // Degraded when explicitly disconnected OR serving a non-IBKR tier.
  // dataSource === null means nothing has been fetched yet → not degraded.
  const degraded = connected === false || (dataSource != null && dataSource !== "ibkr");

  return {
    isDataDegraded: degraded,
    dataSource,
    ibkrDataConnected: connected,
    consecutiveFailures: ib!.watchdog?.consecutive_failures ?? null,
    lastChecked,
    hasSignal: true,
  };
}
