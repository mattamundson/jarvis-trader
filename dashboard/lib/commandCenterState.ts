import type {
  CommandCenterDataIntegrityResponse,
  CommandCenterHealthData,
  CommandCenterSafetyData,
} from "@/lib/commandCenterApi";
import type { ExecutionStatus } from "@/lib/executionPath";

export type CommandCenterShellTone = "live" | "warn" | "offline" | "static";
export type CommandCenterStatusTone = "ok" | "warn" | "bad" | "unknown";

export interface CommandCenterStatusCell {
  label: string;
  detail: string;
  tone: CommandCenterStatusTone;
}

export interface CommandCenterStatusStripState {
  engine: CommandCenterStatusCell;
  broker: CommandCenterStatusCell;
  safety: CommandCenterStatusCell;
  data: CommandCenterStatusCell;
}

export type CommandCenterShellRegionKey =
  | "systemStatus"
  | "tradeQueue"
  | "eligibility"
  | "strategyLedger"
  | "dataIntegrity"
  | "researchIntake";

export interface CommandCenterShellRegionState {
  key: CommandCenterShellRegionKey;
  label: string;
  href: string;
  status: string;
  metric: string;
  detail: string;
  tone: CommandCenterShellTone;
}

export function compactCount(value: number | undefined | null): string {
  return typeof value === "number" && Number.isFinite(value) ? String(value) : "—";
}

export function deriveCommandCenterStatusStripState({
  health,
  healthErr,
  safety,
  safetyErr,
  killSwitchActive,
  execution,
  integrity,
  integrityErr,
  integrityReady,
  staleFeeds,
}: {
  health: CommandCenterHealthData | undefined;
  healthErr: boolean;
  safety: CommandCenterSafetyData | undefined;
  safetyErr: boolean;
  killSwitchActive: boolean;
  execution: Pick<ExecutionStatus, "tone" | "detail">;
  integrity: CommandCenterDataIntegrityResponse | undefined;
  integrityErr: boolean;
  integrityReady: boolean;
  staleFeeds: number;
}): CommandCenterStatusStripState {
  const statusOrdersPerMin = safety?.orders_last_minute ?? 0;
  const statusOrdersLimit = safety?.orders_per_minute_limit ?? 10;
  const engine = !health && !healthErr
    ? { label: "unknown", detail: "health probe pending", tone: "unknown" as const }
    : healthErr || !health
      ? { label: "offline", detail: "health endpoint unreachable", tone: "bad" as const }
      : health.status === "ok" || health.status === "healthy"
        ? { label: "online", detail: `version ${health.version ?? "unknown"}`, tone: "ok" as const }
        : { label: "degraded", detail: `status ${health.status ?? "unknown"}`, tone: "warn" as const };
  const broker = !health && !healthErr
    ? { label: "unknown", detail: "execution path pending", tone: "unknown" as const }
    : healthErr || !health
      ? { label: "unknown", detail: "engine offline; broker unprobed", tone: "unknown" as const }
      : execution.tone === "bull"
        ? { label: "verified", detail: execution.detail, tone: "ok" as const }
        : execution.tone === "warn"
          ? { label: "degraded", detail: execution.detail, tone: "warn" as const }
          : { label: "offline", detail: execution.detail, tone: "bad" as const };
  const safetyStatus = !safety && !safetyErr
    ? { label: "unknown", detail: "safety probe pending", tone: "unknown" as const }
    : safetyErr || !safety
      ? { label: "unknown", detail: "safety endpoint unavailable", tone: "unknown" as const }
      : killSwitchActive
        ? { label: "halted", detail: "kill switch active", tone: "bad" as const }
        : { label: "armed", detail: `${statusOrdersPerMin}/${statusOrdersLimit} orders per minute`, tone: "ok" as const };
  const data = integrityErr || !integrityReady
    ? { label: "unknown", detail: "data-integrity endpoint unavailable", tone: "unknown" as const }
    : staleFeeds > 0
      ? { label: "stale", detail: `${staleFeeds} stale feed${staleFeeds === 1 ? "" : "s"}`, tone: "warn" as const }
      : { label: "current", detail: `${compactCount(integrity?.count ?? integrity?.sources?.length)} streams`, tone: "ok" as const };

  return {
    engine,
    broker,
    safety: safetyStatus,
    data,
  };
}

export function deriveCommandCenterShellRegions({
  engineOnline,
  killSwitchActive,
  paperTrading,
  executionLabel,
  decisionsCount,
  decisionsErr,
  tradesCount,
  tradesErr,
  hasPaperStatus,
  approvedInstruments,
  totalInstruments,
  haltedInstruments,
  ledgerReady,
  ledgerErr,
  ledgerPassCount,
  ledgerFailCount,
  ledgerTotal,
  integrityReady,
  integrityErr,
  integrityCount,
  staleFeeds,
}: {
  engineOnline: boolean;
  killSwitchActive: boolean;
  paperTrading: boolean | undefined;
  executionLabel: string;
  decisionsCount: number | undefined;
  decisionsErr: boolean;
  tradesCount: number | undefined;
  tradesErr: boolean;
  hasPaperStatus: boolean;
  approvedInstruments: number;
  totalInstruments: number;
  haltedInstruments: number;
  ledgerReady: boolean;
  ledgerErr: boolean;
  ledgerPassCount: number | undefined;
  ledgerFailCount: number | undefined;
  ledgerTotal: number | undefined;
  integrityReady: boolean;
  integrityErr: boolean;
  integrityCount: number | undefined;
  staleFeeds: number;
}): CommandCenterShellRegionState[] {
  return [
    {
      key: "systemStatus",
      label: "SYSTEM STATUS",
      href: "/health",
      status: engineOnline ? (killSwitchActive ? "halted" : "online") : "offline",
      metric: engineOnline ? (killSwitchActive ? "HALT" : "OK") : "DOWN",
      detail: `${paperTrading === false ? "live flag observed" : "paper mode"} · ${executionLabel}`,
      tone: engineOnline ? (killSwitchActive ? "warn" : "live") : "offline",
    },
    {
      key: "tradeQueue",
      label: "TRADE QUEUE",
      href: "/trades/pending-approvals",
      status: decisionsErr ? "degraded" : "mounted",
      metric: `${compactCount(decisionsCount)} recent`,
      detail: tradesErr ? "fills unavailable" : `${compactCount(tradesCount)} fill rows visible`,
      tone: decisionsErr || tradesErr ? "warn" : "live",
    },
    {
      key: "eligibility",
      label: "ELIGIBILITY",
      href: "/trading-eligibility",
      status: hasPaperStatus ? "policy" : "fallback",
      metric: `${approvedInstruments}/${totalInstruments}`,
      detail: `${haltedInstruments} halted · gate-v2 authorization`,
      tone: hasPaperStatus ? "live" : "warn",
    },
    {
      key: "strategyLedger",
      label: "STRATEGY LEDGER",
      href: "/strategy-ledger",
      status: ledgerErr || !ledgerReady ? "degraded" : "gate-v2",
      metric: `${compactCount(ledgerPassCount)} pass`,
      detail: ledgerReady
        ? `${compactCount(ledgerFailCount)} fail · ${compactCount(ledgerTotal)} verdicts`
        : "verdict ledger unavailable",
      tone: ledgerErr || !ledgerReady ? "warn" : "live",
    },
    {
      key: "dataIntegrity",
      label: "DATA INTEGRITY",
      href: "/data-integrity",
      status: integrityErr || !integrityReady ? "degraded" : "streams",
      metric: compactCount(integrityCount),
      detail: integrityReady
        ? staleFeeds > 0
          ? `${staleFeeds} stale feed${staleFeeds === 1 ? "" : "s"}`
          : "no stale feed reported"
        : "stream health unavailable",
      tone: integrityErr || !integrityReady ? "warn" : staleFeeds > 0 ? "warn" : "live",
    },
    {
      key: "researchIntake",
      label: "RESEARCH INTAKE",
      href: "/research-log",
      status: "planned",
      metric: "P7",
      detail: "candidate intake surface follows this shell",
      tone: "static",
    },
  ];
}
