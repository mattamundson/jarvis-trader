"use client";

import useSWR from "swr";
import { fetchEngine } from "@/lib/api";
import { useMarketSession } from "./useMarketSession";
import type {
  HealthResponse,
  SafetyStatus,
  PortfolioSnapshot,
  AgentDecision,
  MacroSnapshot,
  TradeRecord,
} from "@/lib/api";

// ── Scheduler types (local — mirrors engine Pydantic model) ─────────────────

interface SchedulerJob {
  name: string;
  last_run: string | null;
  next_run: string | null;
  running: boolean;
}

export interface SchedulerData {
  running: boolean;
  jobs?: SchedulerJob[];
  total_decisions_logged: number;
  last_scan?: string;
  next_scan?: string;
}

// ── Return type ──────────────────────────────────────────────────────────────

export interface CommandCenterData {
  session: ReturnType<typeof useMarketSession>;
  health: ReturnType<typeof useSWR<HealthResponse>>;
  safety: ReturnType<typeof useSWR<SafetyStatus>>;
  portfolio: ReturnType<typeof useSWR<PortfolioSnapshot>>;
  decisions: ReturnType<typeof useSWR<AgentDecision[]>>;
  scheduler: ReturnType<typeof useSWR<SchedulerData>>;
  macro: ReturnType<typeof useSWR<MacroSnapshot>>;
  trades: ReturnType<typeof useSWR<TradeRecord[]>>;
  refreshInterval: number;
}

// ── Hook ─────────────────────────────────────────────────────────────────────

export function useCommandCenterData(): CommandCenterData {
  const session = useMarketSession();

  // Adaptive refresh: 30s during active market sessions, 5 minutes otherwise
  const refreshInterval = session.isActive ? 30_000 : 300_000;

  const swrOptions = { refreshInterval };

  const health = useSWR<HealthResponse>(
    "/health",
    (path: string) => fetchEngine<HealthResponse>(path),
    swrOptions
  );

  const safety = useSWR<SafetyStatus>(
    "/safety/status",
    (path: string) => fetchEngine<SafetyStatus>(path),
    swrOptions
  );

  const portfolio = useSWR<PortfolioSnapshot>(
    "/portfolio",
    (path: string) => fetchEngine<PortfolioSnapshot>(path),
    swrOptions
  );

  const decisions = useSWR<AgentDecision[]>(
    "/decisions/recent?limit=5",
    (path: string) => fetchEngine<AgentDecision[]>(path),
    swrOptions
  );

  const scheduler = useSWR<SchedulerData>(
    "/scheduler/status",
    (path: string) => fetchEngine<SchedulerData>(path),
    swrOptions
  );

  const macro = useSWR<MacroSnapshot>(
    "/macro/snapshot",
    (path: string) => fetchEngine<MacroSnapshot>(path),
    { refreshInterval: 120_000, shouldRetryOnError: false }
  );

  const trades = useSWR<TradeRecord[]>(
    "/portfolio/history/trades",
    (path: string) => fetchEngine<TradeRecord[]>(path),
    swrOptions
  );

  return {
    session,
    health,
    safety,
    portfolio,
    decisions,
    scheduler,
    macro,
    trades,
    refreshInterval,
  };
}
