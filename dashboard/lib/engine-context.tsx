"use client";

/**
 * JARVIS ENGINE DATA CONTEXT
 * Single source of truth for all engine state across the dashboard.
 * Replaces 40+ scattered useSWR calls with one centralized, adaptive data layer.
 *
 * Architecture:
 * - One context provider in layout.tsx wraps the entire app
 * - Adaptive refresh: 15s during RTH, 60s extended session, 5min closed
 * - Health always polls at 10s regardless of session
 * - Per-domain error tracking (domain error ≠ global offline)
 * - lastUpdated timestamps persisted to localStorage
 * - WebSocket events trigger immediate domain refreshes
 */

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { SWRConfig } from "swr";
import useSWR from "swr";
import { fetchEngine } from "@/lib/api";
import { useMarketSession } from "@/hooks/useMarketSession";
import { useEngineWebSocketContext } from "@/lib/engine-websocket-context";
import type {
  HealthResponse,
  SafetyStatus,
  PortfolioSnapshot,
  AgentDecision,
  MacroSnapshot,
  TradeRecord,
  PendingApprovalsResponse,
} from "@/lib/api";

// ── Domain types ──────────────────────────────────────────────────────────────

export interface SchedulerData {
  running: boolean;
  jobs?: Array<{
    name: string;
    last_run: string | null;
    next_run: string | null;
    running: boolean;
  }>;
  total_decisions_logged: number;
  last_scan?: string;
  next_scan?: string;
}

export interface System2Status {
  running: boolean;
  pid: number | null;
  port: number | null;
  last_heartbeat: string | null;
  last_signal: {
    symbol: string;
    direction: string;
    timestamp: string;
  } | null;
  recent_events: Array<{
    ts: string;
    type: string;
    symbol?: string;
    direction?: string;
    price?: number;
  }>;
}

export interface StrategyCSignal {
  combined_scale: number;
  pre_mtf_scale: number;
  holdings: Record<string, number>;
  layers: {
    momentum_signal: { risk_regime: string };
    vix_composite: { vix: number };
    vol_targeting: { vol_regime: string; realized_vol_pct: number };
    mtf_signal?: {
      votes_bull: number;
      mtf_scale: number;
      weekly_momentum: string;
      monthly_momentum: string;
      daily_confirmation: string;
      breadth: string;
      confidence: string;
    };
  };
  generated_at?: string;
}

// ── Domain keys for error/lastUpdated tracking ────────────────────────────────

export type EngineDomain =
  | "health"
  | "safety"
  | "portfolio"
  | "decisions"
  | "macro"
  | "trades"
  | "pendingApprovals"
  | "scheduler"
  | "system2"
  | "strategyC";

// ── Context value shape ───────────────────────────────────────────────────────

export interface EngineContextValue {
  // Domain data
  health: HealthResponse | null;
  safety: SafetyStatus | null;
  portfolio: PortfolioSnapshot | null;
  decisions: AgentDecision[] | null;
  macro: MacroSnapshot | null;
  trades: TradeRecord[] | null;
  pendingApprovals: PendingApprovalsResponse | null;
  scheduler: SchedulerData | null;
  system2: System2Status | null;
  strategyC: StrategyCSignal | null;

  // Cross-cutting state
  isOffline: boolean; // true only when /health itself fails
  errors: Partial<Record<EngineDomain, string | null>>;
  lastUpdated: Partial<Record<EngineDomain, Date | null>>;

  // Refresh rate info
  refreshInterval: number; // ms — current adaptive interval

  // Manual refresh
  mutate: (domain?: EngineDomain) => void;
}

// ── localStorage helpers ──────────────────────────────────────────────────────

const LS_PREFIX = "jarvis:engine:lastUpdated:";

function readTimestamp(domain: EngineDomain): Date | null {
  try {
    const raw = localStorage.getItem(LS_PREFIX + domain);
    return raw ? new Date(raw) : null;
  } catch {
    return null;
  }
}

function writeTimestamp(domain: EngineDomain, d: Date): void {
  try {
    localStorage.setItem(LS_PREFIX + domain, d.toISOString());
  } catch {
    /* storage unavailable */
  }
}

function buildInitialTimestamps(): Partial<Record<EngineDomain, Date | null>> {
  const domains: EngineDomain[] = [
    "health","safety","portfolio","decisions","macro",
    "trades","pendingApprovals","scheduler","system2","strategyC",
  ];
  const result: Partial<Record<EngineDomain, Date | null>> = {};
  for (const d of domains) result[d] = readTimestamp(d);
  return result;
}

// ── Context ───────────────────────────────────────────────────────────────────

const EngineContext = createContext<EngineContextValue | null>(null);

// ── Fetcher with token ────────────────────────────────────────────────────────

function ef<T>(path: string): Promise<T> {
  return fetchEngine<T>(path);
}

// ── Provider ──────────────────────────────────────────────────────────────────

export function EngineDataProvider({ children }: { children: React.ReactNode }) {
  const session = useMarketSession();

  // Adaptive refresh based on market session
  const refreshInterval = useMemo(() => {
    if (session.isActive) return 15_000;       // RTH: 15s
    if (session.label.includes("CLOSED") || session.label.includes("WEEKEND")) {
      return 300_000;                           // Market closed: 5min
    }
    return 60_000;                              // Extended/pre-market: 60s
  }, [session.isActive, session.label]);

  // Track offline state and timestamps
  const [isOffline, setIsOffline] = useState(false);
  const [errors, setErrors] = useState<Partial<Record<EngineDomain, string | null>>>({});
  const [lastUpdated, setLastUpdated] = useState<Partial<Record<EngineDomain, Date | null>>>(
    buildInitialTimestamps
  );

  // ── SWR fetches ────────────────────────────────────────────────────────────

  const swrOpts = useMemo(() => ({ refreshInterval }), [refreshInterval]);
  const healthOpts = useMemo(() => ({ refreshInterval: 10_000 }), []);
  const approvalOpts = useMemo(() => ({ refreshInterval: 5_000 }), []);

  const { data: health, error: healthError, mutate: mutateHealth } =
    useSWR<HealthResponse>("/health", ef, healthOpts);

  const { data: safety, error: safetyError, mutate: mutateSafety } =
    useSWR<SafetyStatus>("/safety/status", ef, swrOpts);

  const { data: portfolio, error: portfolioError, mutate: mutatePortfolio } =
    useSWR<PortfolioSnapshot>("/portfolio", ef, swrOpts);

  const { data: decisions, error: decisionsError, mutate: mutateDecisions } =
    useSWR<AgentDecision[]>("/decisions/recent?limit=10", ef, swrOpts);

  const { data: macro, error: macroError, mutate: mutateMacro } =
    useSWR<MacroSnapshot>("/macro/snapshot", ef, swrOpts);

  const { data: trades, error: tradesError, mutate: mutateTrades } =
    useSWR<TradeRecord[]>("/portfolio/history/trades?limit=20&status=CLOSED", ef, swrOpts);

  const { data: pendingApprovals, error: approvalsError, mutate: mutateApprovals } =
    useSWR<PendingApprovalsResponse>("/pipeline/pending-approvals?limit=50", ef, approvalOpts);

  const { data: scheduler, error: schedulerError, mutate: mutateScheduler } =
    useSWR<SchedulerData>("/scheduler/status", ef, swrOpts);

  const { data: system2, error: system2Error, mutate: mutateSystem2 } =
    useSWR<System2Status>("/engine/system2/status", ef, swrOpts);

  const { data: strategyC, error: strategyCError, mutate: mutateStrategyC } =
    useSWR<StrategyCSignal>("/engine/v1/strategy_c/signal", ef, swrOpts);

  // ── Derive isOffline from health ───────────────────────────────────────────

  useEffect(() => {
    const offline = !!healthError;
    setIsOffline(offline);
    if (!offline && health) {
      const now = new Date();
      writeTimestamp("health", now);
      setLastUpdated(prev => ({ ...prev, health: now }));
    }
  }, [health, healthError]);

  // ── Track per-domain errors and timestamps ─────────────────────────────────

  type DomainWatch = {
    domain: EngineDomain;
    data: unknown;
    error: unknown;
  };

  const domainWatches: DomainWatch[] = [
    { domain: "safety", data: safety, error: safetyError },
    { domain: "portfolio", data: portfolio, error: portfolioError },
    { domain: "decisions", data: decisions, error: decisionsError },
    { domain: "macro", data: macro, error: macroError },
    { domain: "trades", data: trades, error: tradesError },
    { domain: "pendingApprovals", data: pendingApprovals, error: approvalsError },
    { domain: "scheduler", data: scheduler, error: schedulerError },
    { domain: "system2", data: system2, error: system2Error },
    { domain: "strategyC", data: strategyC, error: strategyCError },
  ];

  useEffect(() => {
    const newErrors: Partial<Record<EngineDomain, string | null>> = {};
    const newTimestamps: Partial<Record<EngineDomain, Date | null>> = {};

    for (const { domain, data, error } of domainWatches) {
      if (error) {
        const msg = error instanceof Error ? error.message : String(error);
        // Strip raw API paths for cleaner error messages
        newErrors[domain] = msg.replace(/:\s*\/api\/engine[^\s]*/g, "").trim() || "Unavailable";
      } else {
        newErrors[domain] = null;
      }
      if (data) {
        const now = new Date();
        writeTimestamp(domain, now);
        newTimestamps[domain] = now;
      }
    }

    setErrors(prev => ({ ...prev, ...newErrors }));
    setLastUpdated(prev => ({ ...prev, ...newTimestamps }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [safety, safetyError, portfolio, portfolioError, decisions, decisionsError,
      macro, macroError, trades, tradesError, pendingApprovals, approvalsError,
      scheduler, schedulerError, system2, system2Error, strategyC, strategyCError]);

  // ── WebSocket event → domain invalidation ─────────────────────────────────

  const wsCtx = useEngineWebSocketContext();

  useEffect(() => {
    return wsCtx.subscribe((event) => {
      switch (event.type) {
        case "kill_switch":
        case "safety_event":
          mutateSafety();
          mutateHealth();
          break;
        case "order_fill":
          mutatePortfolio();
          mutateTrades();
          break;
        case "position_opened":
        case "position_closed":
          mutatePortfolio();
          mutateDecisions();
          break;
        case "pipeline_complete":
          mutateDecisions();
          break;
        case "pending_approval_created":
          mutateApprovals();
          break;
        case "circuit_breaker":
          mutateSafety();
          break;
      }
    });
  }, [wsCtx, mutateSafety, mutateHealth, mutatePortfolio, mutateTrades,
      mutateDecisions, mutateApprovals]);

  // ── Manual mutate ──────────────────────────────────────────────────────────

  const mutate = useCallback((domain?: EngineDomain) => {
    if (!domain) {
      mutateHealth(); mutateSafety(); mutatePortfolio(); mutateDecisions();
      mutateMacro(); mutateTrades(); mutateApprovals(); mutateScheduler();
      mutateSystem2(); mutateStrategyC();
      return;
    }
    const map: Record<EngineDomain, () => void> = {
      health: mutateHealth,
      safety: mutateSafety,
      portfolio: mutatePortfolio,
      decisions: mutateDecisions,
      macro: mutateMacro,
      trades: mutateTrades,
      pendingApprovals: mutateApprovals,
      scheduler: mutateScheduler,
      system2: mutateSystem2,
      strategyC: mutateStrategyC,
    };
    map[domain]?.();
  }, [mutateHealth, mutateSafety, mutatePortfolio, mutateDecisions,
      mutateMacro, mutateTrades, mutateApprovals, mutateScheduler,
      mutateSystem2, mutateStrategyC]);

  // ── Context value ──────────────────────────────────────────────────────────

  const value = useMemo<EngineContextValue>(() => ({
    health: health ?? null,
    safety: safety ?? null,
    portfolio: portfolio ?? null,
    decisions: decisions ?? null,
    macro: macro ?? null,
    trades: trades ?? null,
    pendingApprovals: pendingApprovals ?? null,
    scheduler: scheduler ?? null,
    system2: system2 ?? null,
    strategyC: strategyC ?? null,
    isOffline,
    errors,
    lastUpdated,
    refreshInterval,
    mutate,
  }), [health, safety, portfolio, decisions, macro, trades, pendingApprovals,
      scheduler, system2, strategyC, isOffline, errors, lastUpdated,
      refreshInterval, mutate]);

  return (
    <EngineContext.Provider value={value}>
      {children}
    </EngineContext.Provider>
  );
}

// ── Consumer hook ─────────────────────────────────────────────────────────────

export function useEngineData(): EngineContextValue {
  const ctx = useContext(EngineContext);
  if (!ctx) {
    throw new Error("useEngineData must be used within <EngineDataProvider>");
  }
  return ctx;
}

// ── Convenience selectors (avoid re-renders on unrelated domains) ─────────────

export function useEngineHealth() {
  const { health, isOffline, errors, lastUpdated } = useEngineData();
  return { health, isOffline, error: errors.health, lastUpdated: lastUpdated.health };
}

export function useEngineSafety() {
  const { safety, isOffline, errors, mutate } = useEngineData();
  return { safety, isOffline, error: errors.safety, mutate: () => mutate("safety") };
}

export function useEnginePortfolio() {
  const { portfolio, isOffline, errors, lastUpdated, mutate } = useEngineData();
  return { portfolio, isOffline, error: errors.portfolio, lastUpdated: lastUpdated.portfolio, mutate: () => mutate("portfolio") };
}

export function useEngineDecisions() {
  const { decisions, isOffline, errors } = useEngineData();
  return { decisions, isOffline, error: errors.decisions };
}

export function useEnginePendingApprovals() {
  const { pendingApprovals, isOffline, errors, mutate } = useEngineData();
  return { pendingApprovals, isOffline, error: errors.pendingApprovals, mutate: () => mutate("pendingApprovals") };
}

export function useEngineSystem2() {
  const { system2, isOffline, errors } = useEngineData();
  return { system2, isOffline, error: errors.system2 };
}

export function useEngineStrategyC() {
  const { strategyC, isOffline, errors } = useEngineData();
  return { strategyC, isOffline, error: errors.strategyC };
}
