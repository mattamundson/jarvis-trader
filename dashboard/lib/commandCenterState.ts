import type {
  CommandCenterBarQualityData,
  CommandCenterDataIntegrityResponse,
  CommandCenterEdgeLedgerData,
  CommandCenterHealthData,
  CommandCenterMacroData,
  CommandCenterSafetyData,
  CommandCenterSessionTodayData,
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

export interface CommandCenterSummaryRow {
  label: string;
  state: string;
  detail: string;
  tone: CommandCenterStatusTone;
}

export function compactCount(value: number | undefined | null): string {
  return typeof value === "number" && Number.isFinite(value) ? String(value) : "—";
}

function pctLabel(value: number | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "unknown";
  return `${(Math.abs(value) * 100).toFixed(2)}%`;
}

function moneyLabel(value: number | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "unknown";
  const sign = value > 0 ? "+" : value < 0 ? "-" : "";
  return `${sign}$${Math.abs(value).toFixed(2)}`;
}

export function commandCenterOperationTone(status: string): CommandCenterStatusTone {
  const normalized = status.toLowerCase();
  if (["clear", "safe", "connected", "within limit", "online"].includes(normalized)) return "ok";
  if (["active", "near limit", "no broker ack", "unprobed", "stale"].includes(normalized)) return "warn";
  if (["offline", "halted", "breached", "disconnected", "simulated"].includes(normalized)) return "bad";
  return "unknown";
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

export function deriveCommandCenterOperationsSummaryRows({
  health,
  healthErr,
  safety,
  safetyErr,
  execution,
}: {
  health: CommandCenterHealthData | undefined;
  healthErr: boolean;
  safety: CommandCenterSafetyData | undefined;
  safetyErr: boolean;
  execution: Pick<ExecutionStatus, "label" | "detail">;
}): CommandCenterSummaryRow[] {
  const orderLimit = safety?.orders_per_minute_limit ?? 10;
  const orderRateState = safetyErr || !safety ? "unknown" : `${safety.orders_last_minute}/${orderLimit}`;
  const drawdownState = safetyErr || !safety ? "unknown" : pctLabel(safety.drawdown_pct);
  const killState = safetyErr || !safety ? "unknown" : safety.kill_switch_active ? "active" : "clear";
  const engineDataState = healthErr || !health
    ? "unknown"
    : health.ibkr_data_connected === true
      ? "online"
      : health.ibkr_data_connected === false
        ? "offline"
        : "unknown";

  return [
    {
      label: "Kill Switch",
      state: killState,
      detail: safetyErr ? "safety endpoint unavailable" : "operations risk surface",
      tone: commandCenterOperationTone(killState),
    },
    {
      label: "Order Rate",
      state: orderRateState,
      detail: safetyErr ? "order limiter unavailable" : "orders per minute limit",
      tone: commandCenterOperationTone(orderRateState),
    },
    {
      label: "Drawdown",
      state: drawdownState,
      detail: safetyErr ? "drawdown unavailable" : "live safety drawdown",
      tone: commandCenterOperationTone(drawdownState),
    },
    {
      label: "Broker Execution",
      state: execution.label.toLowerCase(),
      detail: execution.detail,
      tone: commandCenterOperationTone(execution.label),
    },
    {
      label: "Data Leg",
      state: engineDataState,
      detail: healthErr ? "health endpoint unavailable" : "IBKR data connection flag",
      tone: commandCenterOperationTone(engineDataState),
    },
  ];
}

export function deriveCommandCenterDailyBriefSummaryRows({
  health,
  sessionToday,
  sessionTodayErr,
  macro,
  execution,
}: {
  health: CommandCenterHealthData | undefined;
  sessionToday: CommandCenterSessionTodayData | undefined;
  sessionTodayErr: boolean;
  macro: CommandCenterMacroData | undefined;
  execution: Pick<ExecutionStatus, "label" | "tone" | "detail">;
}): CommandCenterSummaryRow[] {
  const mode = health?.paper_trading ? "paper" : health ? "live" : "unknown";
  const tradesToday = sessionToday
    ? `${sessionToday.closed_trades + sessionToday.open_trades}`
    : "unknown";
  const pnl = sessionToday ? moneyLabel(sessionToday.gross_pnl) : "unknown";
  const openTrades = sessionToday ? `${sessionToday.open_trades}` : "unknown";
  const marketContext = macro?.regime ?? macro?.vix_regime ?? "unknown";
  const executionTone: CommandCenterStatusTone =
    execution.tone === "bull"
      ? "ok"
      : execution.tone === "warn"
        ? "warn"
        : execution.tone === "bear"
          ? "bad"
          : "unknown";

  return [
    { label: "Mode", state: mode, detail: "from /health paper_trading", tone: mode === "unknown" ? "unknown" : "ok" },
    {
      label: "Execution",
      state: execution.label.toLowerCase(),
      detail: execution.detail,
      tone: executionTone,
    },
    {
      label: "Trades",
      state: tradesToday,
      detail: sessionTodayErr ? "session endpoint unavailable" : "closed plus open",
      tone: tradesToday === "unknown" ? "unknown" : "ok",
    },
    {
      label: "Session P&L",
      state: pnl,
      detail: "gross session P&L",
      tone: pnl === "unknown" ? "unknown" : "ok",
    },
    { label: "Open", state: openTrades, detail: "open session trades", tone: openTrades === "unknown" ? "unknown" : "ok" },
    {
      label: "Market",
      state: marketContext.toLowerCase(),
      detail: "macro/regime context",
      tone: marketContext === "unknown" ? "unknown" : "ok",
    },
  ];
}

export function deriveCommandCenterTrustAuditSummaryRows({
  health,
  healthErr,
  barQuality,
  barQualityErr,
  edgeLedger,
  edgeLedgerErr,
}: {
  health: CommandCenterHealthData | undefined;
  healthErr: boolean;
  barQuality: CommandCenterBarQualityData | undefined;
  barQualityErr: boolean;
  edgeLedger: CommandCenterEdgeLedgerData | undefined;
  edgeLedgerErr: boolean;
}): CommandCenterSummaryRow[] {
  const liveness = healthErr || !health ? "unknown" : health.status === "ok" ? "ok" : "degraded";
  const barRejects = barQualityErr || !barQuality ? "unknown" : `${barQuality.total_rejections}`;
  const barGateDetail = barQualityErr || !barQuality
    ? "bar-quality unavailable"
    : `${barQuality.gate_active ? "gate active" : "gate off"} · ${barQuality.window_hours}h`;
  const edgeState = edgeLedgerErr || !edgeLedger ? "unknown" : `${edgeLedger.n_pass}/${edgeLedger.total}`;
  const edgeDetail = edgeLedgerErr || !edgeLedger
    ? "edge ledger unavailable"
    : `PASS ${edgeLedger.n_pass} · FAIL ${edgeLedger.n_fail}`;
  const dataLeg = healthErr || !health
    ? "unknown"
    : health.ibkr_data_connected === true
      ? "live"
      : health.ibkr_data_connected === false
        ? "offline"
        : "unknown";
  const liveSources = [
    healthErr || !health ? null : "health",
    barQualityErr || !barQuality ? null : "bar-quality",
    edgeLedgerErr || !edgeLedger ? null : "edge-ledger",
  ].filter(Boolean).length;
  const provenance =
    liveSources === 3 ? "live" : liveSources > 0 ? "partial" : "unknown";

  return [
    { label: "Liveness", state: liveness, detail: "engine status", tone: commandCenterOperationTone(liveness) },
    {
      label: "Provenance",
      state: provenance,
      detail: `${liveSources}/3 live sources`,
      tone: provenance === "live" ? "ok" : provenance === "partial" ? "warn" : "unknown",
    },
    {
      label: "Bar Rejects",
      state: barRejects,
      detail: barGateDetail,
      tone: barRejects === "unknown" ? "unknown" : Number(barRejects) > 0 ? "warn" : "ok",
    },
    {
      label: "Edge Ledger",
      state: edgeState,
      detail: edgeDetail,
      tone: edgeState === "unknown" ? "unknown" : "ok",
    },
    { label: "Data Leg", state: dataLeg, detail: "IBKR market-data provenance", tone: commandCenterOperationTone(dataLeg) },
    {
      label: "Post-Trade",
      state: "linked",
      detail: "/trust-pane execution + quality",
      tone: "ok",
    },
  ];
}
