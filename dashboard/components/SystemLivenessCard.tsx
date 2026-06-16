"use client";

import useSWR from "swr";
import {
  fetchEngine,
  type FullHealthResponse,
  type IBGatewayHealth,
  type LLMSubsystemHealth,
} from "@/lib/api";

const REFRESH_MS = 15_000;

type Tone = "ok" | "warn" | "bad" | "unknown";

const TONE: Record<Tone, { bg: string; border: string; fg: string }> = {
  ok: { bg: "rgba(21,128,61,0.12)", border: "#15803d", fg: "#86efac" },
  warn: { bg: "rgba(180,83,9,0.14)", border: "#b45309", fg: "#fcd34d" },
  bad: { bg: "rgba(185,28,28,0.14)", border: "#b91c1c", fg: "#fca5a5" },
  unknown: { bg: "rgba(120,120,120,0.10)", border: "#6b7280", fg: "#cbd5e1" },
};

function Chip({ label, tone, value, sub }: { label: string; tone: Tone; value: string; sub?: string }) {
  const t = TONE[tone];
  return (
    <div
      className="rounded-md px-3 py-2 flex flex-col gap-0.5 min-w-0"
      style={{ backgroundColor: t.bg, border: `1px solid ${t.border}` }}
    >
      <span className="font-mono text-[10px] uppercase tracking-wide text-muted-foreground">
        {label}
      </span>
      <span className="font-mono text-sm font-bold truncate" style={{ color: t.border }}>
        {value}
      </span>
      {sub && <span className="font-mono text-[10px] text-muted-foreground truncate">{sub}</span>}
    </div>
  );
}

/**
 * Compact both-systems liveness card (C5): engine + data leg + watchdog + LLM in
 * one row, composed from a single /health/full read (the US-001/US-002/US-004
 * signals). Lives on an existing status page; fully defensive — a fetch error
 * shows engine OFFLINE and the rest "—" rather than a false green.
 */
export function SystemLivenessCard() {
  const { data, error } = useSWR<FullHealthResponse>(
    "system-liveness-health-full",
    () => fetchEngine<FullHealthResponse>("/health/full"),
    { refreshInterval: REFRESH_MS }
  );

  const offline = !!error || !data;
  const ib: IBGatewayHealth | undefined = data?.subsystems?.ib_gateway;
  const llm: LLMSubsystemHealth | undefined = data?.subsystems?.llm;

  // Engine
  const overall = data?.overall;
  const engineTone: Tone = offline
    ? "bad"
    : overall === "healthy"
      ? "ok"
      : overall === "kill_switch_active"
        ? "bad"
        : "warn";
  const engineValue = offline ? "OFFLINE" : (overall ?? "unknown").toUpperCase();

  // Data leg
  const dataSource = ib?.data_source ?? null;
  const dataConnected = ib?.data_connected;
  const dataTone: Tone = offline || !ib
    ? "unknown"
    : dataConnected === false
      ? "bad"
      : dataSource && dataSource !== "ibkr"
        ? "warn"
        : dataSource === "ibkr"
          ? "ok"
          : "unknown";
  const dataValue = offline || !ib ? "—" : (dataSource ?? "unknown").toString().toUpperCase();

  // Watchdog
  const wd = ib?.watchdog;
  const wdFailures = wd?.consecutive_failures ?? 0;
  const wdTone: Tone = offline || !wd
    ? "unknown"
    : wd.enabled === false
      ? "unknown"
      : wdFailures && wdFailures > 0
        ? "warn"
        : wd.running
          ? "ok"
          : "warn";
  const wdValue = offline || !wd
    ? "—"
    : wd.enabled === false
      ? "DISABLED"
      : wdFailures && wdFailures > 0
        ? `RETRY ×${wdFailures}`
        : wd.running
          ? "RUNNING"
          : "IDLE";

  // LLM
  const llmTone: Tone = offline || !llm
    ? "unknown"
    : llm.status === "unknown"
      ? "bad"
      : llm.fallback_active || llm.status === "degraded"
        ? "warn"
        : "ok";
  const llmValue = offline || !llm ? "—" : (llm.provider ?? "unknown").toString().toUpperCase();
  const llmSub = llm?.fallback_active ? "fallback" : undefined;

  return (
    <div className="border border-border rounded-lg p-4 bg-card">
      <div className="flex items-baseline justify-between gap-3 mb-3">
        <h2 className="font-mono text-sm font-bold text-foreground">System liveness</h2>
        <span className="font-mono text-[10px] text-muted-foreground">
          {offline ? "engine unreachable" : `overall ${(overall ?? "—").toUpperCase()}`}
        </span>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        <Chip label="Engine" tone={engineTone} value={engineValue} />
        <Chip
          label="Data leg"
          tone={dataTone}
          value={dataValue}
          sub={dataConnected === false ? "disconnected" : undefined}
        />
        <Chip label="Data watchdog" tone={wdTone} value={wdValue} />
        <Chip label="LLM" tone={llmTone} value={llmValue} sub={llmSub} />
      </div>
    </div>
  );
}
