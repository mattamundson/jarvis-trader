"use client";

import { useState } from "react";
import useSWR from "swr";
import { fetchEngine, type FullHealthResponse, type LLMSubsystemHealth } from "@/lib/api";
import { HEALTH_FULL_KEY, POLL_INTERVAL } from "@/lib/polling-config";

export interface LLMHealth {
  /** The leg actually serving (active_provider, or primary if nothing served yet). */
  provider: string | null;
  /** True when serving on a non-primary leg. */
  fallbackActive: boolean;
  /** ok | degraded | unknown — mirrors subsystems.llm.status. */
  status: string | null;
  healthy: boolean | null;
  singleLegWarning: boolean;
  lastChecked: Date | null;
  /** True only once we've parsed a response carrying the US-004 llm subsystem. */
  hasSignal: boolean;
}

const INITIAL: LLMHealth = {
  provider: null,
  fallbackActive: false,
  status: null,
  healthy: null,
  singleLegWarning: false,
  lastChecked: null,
  hasSignal: false,
};

/**
 * SWR-backed poll of `/health/full`, reading subsystems.llm (US-004) to report
 * which LLM provider is serving and whether the path is on a fallback leg.
 * Shares the `HEALTH_FULL_KEY` SWR cache key with useIBDataHealth so the two
 * hooks dedupe onto ONE polled request. Fully defensive: an engine without the
 * llm subsystem yields hasSignal=false (no badge), and a fetch error never
 * asserts a degrade.
 */
export function useLLMHealth(): LLMHealth {
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

  const llm: LLMSubsystemHealth | undefined = data?.subsystems?.llm;
  const hasNewFields =
    llm != null && (llm.provider !== undefined || llm.fallback_active !== undefined);

  if (!hasNewFields) {
    return { ...INITIAL, lastChecked };
  }

  return {
    provider: (llm!.provider ?? null) as string | null,
    fallbackActive: llm!.fallback_active === true,
    status: (llm!.status ?? null) as string | null,
    healthy: llm!.healthy ?? null,
    singleLegWarning: llm!.single_leg_warning === true,
    lastChecked,
    hasSignal: true,
  };
}
