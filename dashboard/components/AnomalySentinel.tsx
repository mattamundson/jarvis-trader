"use client";

import { useMemo, useState } from "react";
import useSWR from "swr";
import {
  fetchEngine,
  type HealthResponse,
  type SafetyStatus,
} from "@/lib/api";

// The real drawdown halt limit is config/.env-driven and surfaced by the engine
// as drawdown_limit_pct (a negative decimal). We fall back to -10% only if the
// field is absent. "Approaching" = within 80% of the live limit.
const DRAWDOWN_LIMIT_FALLBACK = 0.1;
const DRAWDOWN_WARN_FRACTION = 0.8;
const DRAWDOWN_IMPLAUSIBLE = 0.5; // >50% on a paper book ⇒ likely data contamination

type Severity = "critical" | "warn";
interface Anomaly {
  severity: Severity;
  message: string;
}

const fetcher = <T,>(path: string) => fetchEngine<T>(path);

/**
 * Persistent top-of-screen integrity sentinel. Renders nothing when all clear;
 * lights up amber/red when an anomaly is detected (kill switch, drawdown nearing
 * or implausibly past the halt, dead data feed, unhealthy TV/LLM path). Mounted
 * globally so it is impossible to miss from any page. Dismiss hides it only until
 * the set of anomalies changes.
 */
export function AnomalySentinel() {
  const { data: health } = useSWR<HealthResponse>("/health", fetcher, {
    refreshInterval: 5_000,
    shouldRetryOnError: false,
  });
  const { data: safety } = useSWR<SafetyStatus>("/safety/status", fetcher, {
    refreshInterval: 5_000,
    shouldRetryOnError: false,
  });

  const anomalies = useMemo<Anomaly[]>(() => {
    const out: Anomaly[] = [];

    if (health?.kill_switch_active || safety?.kill_switch_active) {
      const reason = safety?.kill_switch_reason?.trim();
      out.push({
        severity: "critical",
        message: `KILL SWITCH ACTIVE${reason ? ` — ${reason}` : ""}`,
      });
    }

    // Engine returns current drawdown as drawdown_pct and the live limit as
    // drawdown_limit_pct (negative decimal). drawdown_breached is authoritative.
    // Magnitude — the engine reports drawdown_pct positive, but guard against
    // either sign convention so a flip can never silently disable the alert.
    const dd =
      typeof safety?.drawdown_pct === "number" ? Math.abs(safety.drawdown_pct) : undefined;
    const limit =
      typeof safety?.drawdown_limit_pct === "number"
        ? Math.abs(safety.drawdown_limit_pct)
        : DRAWDOWN_LIMIT_FALLBACK;
    if (typeof dd === "number" && dd > 0) {
      if (dd >= DRAWDOWN_IMPLAUSIBLE) {
        out.push({
          severity: "critical",
          message: `Implausible drawdown ${(dd * 100).toFixed(1)}% — likely P&L data contamination, verify before trusting`,
        });
      } else if (safety?.drawdown_breached || dd >= limit * DRAWDOWN_WARN_FRACTION) {
        out.push({
          severity: "critical",
          message: `Drawdown ${(dd * 100).toFixed(1)}% ${safety?.drawdown_breached ? "breached" : "approaching"} the ${(limit * 100).toFixed(0)}% halt`,
        });
      }
    }

    if (health?.ibkr_data_connected === false) {
      out.push({ severity: "warn", message: "Market data feed disconnected (IBKR data)" });
    }
    if (health?.tradingview_mcp_healthy === false) {
      out.push({ severity: "warn", message: "TradingView MCP unhealthy" });
    }
    if (health?.llm_path_healthy === false) {
      out.push({ severity: "warn", message: "LLM path unhealthy" });
    }

    return out;
  }, [health, safety]);

  const signature = anomalies.map((a) => a.message).join("|");
  const [dismissedSig, setDismissedSig] = useState<string | null>(null);

  if (anomalies.length === 0 || signature === dismissedSig) return null;

  const hasCritical = anomalies.some((a) => a.severity === "critical");
  const palette = hasCritical
    ? { bg: "#3a0d0d", border: "#ff4444", dot: "#ff6666", text: "#ffd5d5" }
    : { bg: "#3a2c0d", border: "#ffcc00", dot: "#ffdd55", text: "#fff0c2" };

  return (
    <div
      role="alert"
      aria-live="assertive"
      className="fixed top-0 left-0 right-0 z-[9998] flex items-center justify-between gap-4 px-4 py-2"
      style={{ backgroundColor: palette.bg, borderBottom: `2px solid ${palette.border}` }}
    >
      <div className="flex min-w-0 items-center gap-3">
        <span
          className="inline-block h-2.5 w-2.5 shrink-0 animate-pulse rounded-full"
          style={{ backgroundColor: palette.dot }}
        />
        <span
          className="shrink-0 font-mono text-[10px] font-bold uppercase tracking-widest"
          style={{ color: palette.text }}
        >
          JARVIS ALERT
        </span>
        <p className="truncate font-mono text-xs" style={{ color: palette.text }}>
          {anomalies.map((a) => a.message).join("   ·   ")}
        </p>
      </div>
      <button
        onClick={() => setDismissedSig(signature)}
        aria-label="Dismiss alert until conditions change"
        className="shrink-0 rounded px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider transition-opacity hover:opacity-70"
        style={{ color: palette.text, border: `1px solid ${palette.border}` }}
      >
        Dismiss
      </button>
    </div>
  );
}
