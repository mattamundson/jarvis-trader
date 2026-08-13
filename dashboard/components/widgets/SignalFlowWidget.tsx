"use client";

import { POLL_INTERVAL } from "@/lib/polling-config";

import useSWR from "swr";
import { fetchEngine } from "@/lib/api";
import { formatChangePct } from "@/lib/signalFlowFormatters";

// ── Types ──────────────────────────────────────────────────────────────────

interface SignalDebugEntry {
  timestamp: string;
  symbol: string;
  stc_val: number;
  stage_blocked: string;
  reason: string;
}

interface SignalDebugResponse {
  entries: SignalDebugEntry[];
  count: number;
}

interface PriceSnapshot {
  symbol: string;
  // The engine returns null for these when no market data is available
  // (no IB Gateway, market closed, data gap) — alongside an `error` field.
  last_price: number | null;
  prev_close: number | null;
  change_pct: number | null;
  source?: string;
  error?: string;
}

type PricesResponse = Record<string, PriceSnapshot>;

// ── Constants ─────────────────────────────────────────────────────────────

const INSTRUMENTS = ["MCL", "MNQ", "MES"] as const;
type Instrument = (typeof INSTRUMENTS)[number];

const STAGE_LABELS: Record<string, string> = {
  pre_filter: "PRE-FILTER",
  mtf: "MTF",
  debate: "DEBATE HOLD",
  risk: "RISK VETO",
  approved: "APPROVED",
  unknown: "UNKNOWN",
};

// ── Color helpers ─────────────────────────────────────────────────────────

function stageColor(stage: string): string {
  switch (stage) {
    case "approved":
      return "#00ff88"; // GREEN
    case "mtf":
      return "#ffcc00"; // YELLOW
    case "pre_filter":
      return "#ff8800"; // ORANGE
    case "debate":
      return "#00d4ff"; // BLUE
    case "risk":
      return "#ff4444"; // RED
    default:
      return "#666";
  }
}

function stageBg(stage: string): string {
  switch (stage) {
    case "approved":
      return "rgba(0,255,136,0.08)";
    case "mtf":
      return "rgba(255,204,0,0.08)";
    case "pre_filter":
      return "rgba(255,136,0,0.08)";
    case "debate":
      return "rgba(0,212,255,0.08)";
    case "risk":
      return "rgba(255,68,68,0.08)";
    default:
      return "rgba(255,255,255,0.04)";
  }
}

function stcBarColor(val: number): string {
  if (val >= 83) return "#ff8800"; // overbought
  if (val <= 15) return "#00d4ff"; // oversold
  return "#555";
}

function pctColor(pct: number): string {
  if (pct >= 0.1) return "#00ff88";
  if (pct <= -0.1) return "#ff4444";
  return "#999";
}

function formatTimestamp(ts: string): string {
  try {
    const d = new Date(ts);
    return d.toLocaleTimeString("en-US", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    });
  } catch {
    return "—";
  }
}

// ── STC Bar ───────────────────────────────────────────────────────────────

function StcBar({ value }: { value: number }) {
  const pct = Math.max(0, Math.min(100, value));
  const color = stcBarColor(value);
  const isOB = value >= 83;
  const isOS = value <= 15;

  return (
    <div className="flex items-center gap-2">
      <div
        className="relative h-1.5 flex-1 overflow-hidden rounded-full"
        style={{ backgroundColor: "#1a1a2e" }}
      >
        {/* OB zone marker at 83% */}
        <div
          className="absolute top-0 h-full w-px"
          style={{ left: "83%", backgroundColor: "rgba(255,136,0,0.4)" }}
        />
        {/* OS zone marker at 15% */}
        <div
          className="absolute top-0 h-full w-px"
          style={{ left: "15%", backgroundColor: "rgba(0,212,255,0.4)" }}
        />
        {/* Value bar */}
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{ width: `${pct}%`, backgroundColor: color }}
        />
      </div>
      <span
        className="font-mono text-xs tabular-nums font-bold w-10 text-right"
        style={{
          color,
        }}
      >
        {value.toFixed(1)}
      </span>
      {(isOB || isOS) && (
        <span
          className="font-mono text-[9px] px-1 py-0.5 rounded border"
          style={{
            color: isOB ? "#ff8800" : "#00d4ff",
            borderColor: isOB ? "rgba(255,136,0,0.3)" : "rgba(0,212,255,0.3)",
            backgroundColor: isOB ? "rgba(255,136,0,0.1)" : "rgba(0,212,255,0.1)",
          }}
        >
          {isOB ? "OB" : "OS"}
        </span>
      )}
    </div>
  );
}

// ── Instrument Row ────────────────────────────────────────────────────────

interface InstrumentRowProps {
  symbol: Instrument;
  latestEntry: SignalDebugEntry | null;
  price: PriceSnapshot | null;
}

function InstrumentRow({ symbol, latestEntry, price }: InstrumentRowProps) {
  const stage = latestEntry?.stage_blocked ?? "unknown";
  const color = stageColor(stage);
  const bg = stageBg(stage);
  const label = STAGE_LABELS[stage] ?? stage.toUpperCase();

  return (
    <div
      className="rounded-lg p-3 space-y-2.5"
      style={{ backgroundColor: bg, border: `1px solid ${color}22` }}
    >
      {/* Top row: symbol + price + stage badge */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          {/* Symbol */}
          <span className="font-mono text-sm font-bold" style={{ color: "#e0e0e0" }}>
            {symbol}
          </span>
          {/* Price */}
          {price && price.last_price != null ? (
            <div className="flex items-center gap-1.5">
              <span className="font-mono text-sm tabular-nums font-semibold" style={{ color: "#ccc" }}>
                {price.last_price.toLocaleString("en-US", {
                  minimumFractionDigits: 2,
                  maximumFractionDigits: 2,
                })}
              </span>
              {price.change_pct != null && (
                <span
                  className="font-mono text-[10px] tabular-nums"
                  style={{ color: pctColor(price.change_pct) }}
                >
                  {formatChangePct(price.change_pct)}
                </span>
              )}
            </div>
          ) : (
            <span className="font-mono text-xs" style={{ color: "#444" }}>
              —
            </span>
          )}
        </div>

        {/* Stage badge */}
        <div className="flex items-center gap-2">
          {/* Stage indicator dot */}
          <div
            className="h-1.5 w-1.5 rounded-full"
            style={{ backgroundColor: color, boxShadow: `0 0 4px ${color}` }}
          />
          <span
            className="font-mono text-[10px] font-bold tracking-wider"
            style={{ color }}
          >
            {label}
          </span>
        </div>
      </div>

      {/* STC bar */}
      {latestEntry ? (
        <div className="space-y-1">
          <div className="flex items-center justify-between mb-1">
            <span className="font-mono text-[9px] tracking-widest uppercase" style={{ color: "#555" }}>
              STC
            </span>
            {price && (
              <span className="font-mono text-[9px]" style={{ color: "#444" }}>
                src: {price.source}
              </span>
            )}
          </div>
          <StcBar value={latestEntry.stc_val} />
        </div>
      ) : (
        <div className="font-mono text-[10px]" style={{ color: "#444" }}>
          No signal data
        </div>
      )}

      {/* Block reason + timestamp */}
      {latestEntry && (
        <div className="flex items-start justify-between gap-2">
          <span
            className="font-mono text-[10px] leading-relaxed flex-1"
            style={{ color: "#666" }}
          >
            {latestEntry.reason}
          </span>
          <span
            className="font-mono text-[10px] shrink-0 tabular-nums"
            style={{ color: "#444" }}
          >
            {formatTimestamp(latestEntry.timestamp)}
          </span>
        </div>
      )}
    </div>
  );
}

// ── Main Widget ───────────────────────────────────────────────────────────

function fetcher<T = unknown>(url: string): Promise<T> {
  return fetchEngine<T>(url);
}

export function SignalFlowWidget() {
  const { data: debugData, isLoading: loadingDebug } =
    useSWR<SignalDebugResponse>("/pipeline/signal-debug", fetcher, {
      refreshInterval: POLL_INTERVAL.SLOW,
      shouldRetryOnError: false,
    });

  const { data: pricesData } =
    useSWR<PricesResponse>("/prices/snapshot", fetcher, {
      refreshInterval: POLL_INTERVAL.STATUS,
      shouldRetryOnError: false,
    });

  // Build latest entry per instrument (most recent timestamp)
  const latestBySymbol = new Map<string, SignalDebugEntry>();
  if (debugData?.entries) {
    for (const entry of debugData.entries) {
      const existing = latestBySymbol.get(entry.symbol);
      if (!existing || entry.timestamp > existing.timestamp) {
        latestBySymbol.set(entry.symbol, entry);
      }
    }
  }

  // Legend items
  const LEGEND = [
    { label: "APPROVED", color: "#00ff88" },
    { label: "MTF BLOCKED", color: "#ffcc00" },
    { label: "PRE-FILTER", color: "#ff8800" },
    { label: "DEBATE HOLD", color: "#00d4ff" },
    { label: "RISK VETO", color: "#ff4444" },
  ] as const;

  return (
    <div
      className="rounded-xl p-4 space-y-3"
      style={{
        backgroundColor: "#0a0a0a",
        border: "1px solid #1a1a2e",
      }}
    >
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span
            className="font-mono text-[10px] font-bold tracking-[0.2em] uppercase"
            style={{ color: "#00ff88" }}
          >
            SIGNAL FLOW
          </span>
          <span
            className="font-mono text-[9px] px-1.5 py-0.5 rounded border"
            style={{
              borderColor: "#00d4ff33",
              backgroundColor: "#00d4ff10",
              color: "#00d4ff",
            }}
          >
            LIVE
          </span>
        </div>
        <span className="font-mono text-[9px]" style={{ color: "#555" }}>
          30s refresh
        </span>
      </div>

      {/* Legend row */}
      <div className="flex flex-wrap gap-3">
        {LEGEND.map(({ label, color }) => (
          <div key={label} className="flex items-center gap-1">
            <div
              className="h-1.5 w-1.5 rounded-full"
              style={{ backgroundColor: color }}
            />
            <span className="font-mono text-[9px]" style={{ color: "#555" }}>
              {label}
            </span>
          </div>
        ))}
      </div>

      {/* STC zone reference */}
      <div className="flex items-center gap-4 font-mono text-[9px]" style={{ color: "#444" }}>
        <span style={{ color: "#00d4ff" }}>OS &lt;= 15</span>
        <span>neutral 15–83</span>
        <span style={{ color: "#ff8800" }}>OB &gt;= 83</span>
      </div>

      {/* Instrument rows */}
      {loadingDebug ? (
        <div className="space-y-2">
          {INSTRUMENTS.map((sym) => (
            <div
              key={sym}
              className="rounded-lg p-3 h-20 animate-pulse"
              style={{ backgroundColor: "#111" }}
            />
          ))}
        </div>
      ) : (
        <div className="space-y-2">
          {INSTRUMENTS.map((sym) => (
            <InstrumentRow
              key={sym}
              symbol={sym}
              latestEntry={latestBySymbol.get(sym) ?? null}
              price={pricesData?.[sym] ?? null}
            />
          ))}
        </div>
      )}

      {/* Footer counts */}
      {debugData && (
        <div
          className="pt-2 flex items-center justify-between font-mono text-[9px]"
          style={{ borderTop: "1px solid #1a1a2e", color: "#444" }}
        >
          <span>{debugData.count} recent pre-filter decision{debugData.count !== 1 ? "s" : ""}</span>
          <span>instruments: MCL / MNQ / MES</span>
        </div>
      )}
    </div>
  );
}
