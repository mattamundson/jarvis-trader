"use client";

import { useEffect, useRef, useState } from "react";
import { fetchEngine, type FullHealthResponse, type LLMSubsystemHealth } from "@/lib/api";

const POLL_INTERVAL_MS = 15_000;

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
 * Polls /health/full every 15s and reads subsystems.llm (US-004) to report which
 * LLM provider is serving and whether the path is on a fallback leg. Mirrors the
 * abort/cleanup discipline of useIBDataHealth. Fully defensive: an engine without
 * the llm subsystem yields hasSignal=false (no badge), and a fetch error never
 * asserts a degrade.
 */
export function useLLMHealth(): LLMHealth {
  const [state, setState] = useState<LLMHealth>(INITIAL);
  const activeController = useRef<AbortController | null>(null);
  const intervalId = useRef<ReturnType<typeof setInterval> | null>(null);

  async function check(): Promise<void> {
    activeController.current?.abort();
    const controller = new AbortController();
    activeController.current = controller;

    try {
      const full = await fetchEngine<FullHealthResponse>("/health/full");
      if (controller.signal.aborted) return;

      const llm: LLMSubsystemHealth | undefined = full?.subsystems?.llm;
      const hasNewFields =
        llm != null && (llm.provider !== undefined || llm.fallback_active !== undefined);

      if (!hasNewFields) {
        setState((s) => ({ ...s, lastChecked: new Date(), hasSignal: false }));
        return;
      }

      setState({
        provider: (llm!.provider ?? null) as string | null,
        fallbackActive: llm!.fallback_active === true,
        status: (llm!.status ?? null) as string | null,
        healthy: llm!.healthy ?? null,
        singleLegWarning: llm!.single_leg_warning === true,
        lastChecked: new Date(),
        hasSignal: true,
      });
    } catch (err) {
      if (err instanceof Error && err.name === "AbortError") return;
      if (controller.signal.aborted) return;
      // Engine unreachable is the offline banner's job — don't assert a degrade.
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
