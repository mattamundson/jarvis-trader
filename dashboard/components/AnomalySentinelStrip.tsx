"use client";

import useSWR from "swr";
import { AlertTriangle, ShieldAlert } from "lucide-react";
import { fetchEngine } from "@/lib/api";

/**
 * Anomaly sentinel HUD strip — a persistent top banner that lights up when an
 * integrity/safety anomaly is present and is dormant (renders nothing) when all
 * clear. It never shows fake data: if the engine is unreachable the fetches
 * fail and no anomalies are derived, so the strip stays dormant (the
 * EngineAvailabilityHint banner already owns the "engine down" message).
 *
 * Guaranteed signals (verified contracts):
 *   /safety/status        → kill switch, drawdown/daily-loss breach, drawdown nearing halt
 *   /system/data-integrity → stale data feeds (status === "stale")
 * Best-effort signal (graceful if absent):
 *   /alerts/history?alert_type=trade_pnl_outlier → implausible per-trade P&L (a3ec6b8).
 *   This depends on the events-bus → alert_log write path; if it is not wired the
 *   query simply returns nothing and the strip shows no outlier row (no false alarm).
 */

type SafetyStatus = {
  kill_switch_active?: boolean;
  kill_switch_reason?: string | null;
  drawdown_pct?: number; // negative fraction, e.g. -0.039
  drawdown_limit_pct?: number; // negative fraction, default -0.10
  drawdown_breached?: boolean;
  daily_limit_breached?: boolean;
};

type IntegritySource = { source: string; status: string; latency_sec?: number };
type DataIntegrity = { sources?: IntegritySource[]; count?: number };

type AlertRow = { alert_type?: string; message?: string };
type AlertHistory = { alerts?: AlertRow[]; count?: number };

type Severity = "critical" | "warn";
type Anomaly = { severity: Severity; text: string };

const POLL_MS = 15_000;
const swrOpts = { refreshInterval: POLL_MS, shouldRetryOnError: false } as const;

function deriveAnomalies(
  safety: SafetyStatus | undefined,
  integrity: DataIntegrity | undefined,
  outliers: AlertHistory | undefined,
): Anomaly[] {
  const out: Anomaly[] = [];

  if (safety) {
    if (safety.kill_switch_active) {
      out.push({
        severity: "critical",
        text: `Kill switch ACTIVE — trading halted${
          safety.kill_switch_reason ? ` (${safety.kill_switch_reason})` : ""
        }`,
      });
    }
    if (safety.drawdown_breached) {
      out.push({ severity: "critical", text: "Max drawdown limit breached" });
    }
    if (safety.daily_limit_breached) {
      out.push({ severity: "critical", text: "Daily loss limit breached" });
    }
    // Nearing-halt: both are negative fractions; warn at >=80% of the limit.
    const dd = safety.drawdown_pct;
    const lim = safety.drawdown_limit_pct;
    if (
      !safety.drawdown_breached &&
      typeof dd === "number" &&
      typeof lim === "number" &&
      lim < 0 &&
      dd <= lim * 0.8
    ) {
      out.push({
        severity: "warn",
        text: `Drawdown ${(dd * 100).toFixed(1)}% nearing the ${(lim * 100).toFixed(0)}% halt`,
      });
    }
  }

  if (integrity?.sources?.length) {
    const stale = integrity.sources.filter((s) => s.status === "stale");
    if (stale.length) {
      out.push({
        severity: "warn",
        text: `${stale.length} data feed${stale.length > 1 ? "s" : ""} stale: ${stale
          .map((s) => s.source)
          .join(", ")}`,
      });
    }
  }

  const n = outliers?.alerts?.length ?? 0;
  if (n > 0) {
    out.push({
      severity: "warn",
      text: `${n} implausible per-trade P&L alert${n > 1 ? "s" : ""} flagged`,
    });
  }

  return out;
}

export function AnomalySentinelStrip() {
  const { data: safety } = useSWR<SafetyStatus>(
    "/safety/status",
    (p: string) => fetchEngine<SafetyStatus>(p),
    swrOpts,
  );
  const { data: integrity } = useSWR<DataIntegrity>(
    "/system/data-integrity",
    (p: string) => fetchEngine<DataIntegrity>(p),
    swrOpts,
  );
  // Best-effort; errors are swallowed so a missing feed never breaks the strip.
  const { data: outliers } = useSWR<AlertHistory>(
    "/alerts/history?alert_type=trade_pnl_outlier&limit=5",
    (p: string) => fetchEngine<AlertHistory>(p).catch(() => ({ alerts: [], count: 0 })),
    swrOpts,
  );

  const anomalies = deriveAnomalies(safety, integrity, outliers);
  if (anomalies.length === 0) return null; // dormant when all clear

  const critical = anomalies.some((a) => a.severity === "critical");
  const tone = critical
    ? "border-bear/50 bg-bear/15 text-bear"
    : "border-warn/50 bg-warn/15 text-warn";
  const Icon = critical ? ShieldAlert : AlertTriangle;

  return (
    <div
      role="alert"
      aria-live="polite"
      className={`sticky top-0 z-40 flex flex-wrap items-center gap-x-4 gap-y-1 border-b px-4 py-2 font-mono text-xs ${tone}`}
    >
      <span className="flex items-center gap-1.5 font-bold uppercase tracking-widest">
        <Icon className="h-3.5 w-3.5" />
        Sentinel
      </span>
      {anomalies.map((a, i) => (
        <span key={i} className="flex items-center gap-1.5">
          <span
            className={`h-1.5 w-1.5 rounded-full ${
              a.severity === "critical" ? "bg-bear animate-pulse" : "bg-warn"
            }`}
          />
          {a.text}
        </span>
      ))}
    </div>
  );
}
