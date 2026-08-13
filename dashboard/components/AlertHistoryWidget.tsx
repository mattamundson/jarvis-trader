"use client";

import { POLL_INTERVAL } from "@/lib/polling-config";

import useSWR from "swr";
import { Bell, MessageSquare, Hash } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { fetchEngine } from "@/lib/api";

// ── Types ──────────────────────────────────────────────────────────────────────

interface SafetyAlertEntry {
  ts: string;
  key: string;
  message: string;
}

interface SafetyAlertHistoryResponse {
  alerts: SafetyAlertEntry[];
  fired_keys: Record<string, boolean>;
  total_today: number;
  status: string;
}

type BadgeVariant = "bull" | "bear" | "warn" | "info" | "neutral";
type AlertSeverity = "loss" | "kill" | "profit" | "info";

// ── Helpers ────────────────────────────────────────────────────────────────────

function fetcher<T = unknown>(path: string): Promise<T> {
  return fetchEngine<T>(path);
}

function classifyAlert(key: string): AlertSeverity {
  if (key.includes("kill") || key.includes("halt") || key.includes("drawdown_10")) return "kill";
  if (key.includes("loss") || key.includes("drawdown")) return "loss";
  if (key.includes("profit") || key.includes("gain") || key.includes("target")) return "profit";
  return "info";
}

function severityStyles(severity: AlertSeverity): {
  dot: string;
  border: string;
  bg: string;
  text: string;
  badge: BadgeVariant;
} {
  switch (severity) {
    case "kill":
      return { dot: "bg-bear", border: "border-bear/30", bg: "bg-bear/5", text: "text-bear", badge: "bear" };
    case "loss":
      return { dot: "bg-warn", border: "border-warn/30", bg: "bg-warn/5", text: "text-warn", badge: "warn" };
    case "profit":
      return { dot: "bg-bull", border: "border-bull/30", bg: "bg-bull/5", text: "text-bull", badge: "bull" };
    default:
      return { dot: "bg-cyan-400", border: "border-cyan-400/20", bg: "bg-cyan-400/5", text: "text-cyan-400", badge: "info" };
  }
}

function formatTs(ts: string): string {
  try {
    return new Date(ts).toLocaleTimeString("en-US", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    });
  } catch {
    return ts;
  }
}

function formatKey(key: string): string {
  return key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

// ── Component ──────────────────────────────────────────────────────────────────

export function AlertHistoryWidget() {
  const { data, error } = useSWR<SafetyAlertHistoryResponse>(
    "/safety/alerts/history?limit=10",
    fetcher,
    { refreshInterval: POLL_INTERVAL.SLOW, shouldRetryOnError: false }
  );

  const loading = !data && !error;

  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-950 p-4 space-y-3">
      {/* Header */}
      <div className="flex items-center gap-2">
        <Bell className="h-4 w-4 text-cyan-400" />
        <span className="font-mono text-[11px] font-bold tracking-widest uppercase text-cyan-400">
          Alert History
        </span>
        {data && data.total_today > 0 && (
          <Badge variant="warn" className="ml-1">{data.total_today} today</Badge>
        )}
        <span className="ml-auto font-mono text-[9px] text-zinc-600 uppercase tracking-wider">30s poll</span>
      </div>

      <div className="h-px bg-zinc-800" />

      {/* Loading */}
      {loading && (
        <div className="space-y-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-12 animate-pulse rounded-lg bg-zinc-800/40" />
          ))}
        </div>
      )}

      {/* Error */}
      {error && (
        <p className="text-xs text-muted-foreground font-mono">Engine offline — alert history unavailable.</p>
      )}

      {/* Empty state */}
      {data && (data.alerts ?? []).length === 0 && (
        <div className="flex flex-col items-center justify-center py-6 gap-2">
          <Bell className="h-8 w-8 text-zinc-700" />
          <p className="font-mono text-xs text-zinc-600">No alerts fired today</p>
          {data.status !== "ok" && (
            <p className="font-mono text-[10px] text-zinc-700">{data.status}</p>
          )}
        </div>
      )}

      {/* Alert timeline */}
      {data && (data.alerts ?? []).length > 0 && (
        <div className="space-y-2 max-h-72 overflow-y-auto pr-1">
          {(data.alerts ?? []).map((alert, idx) => {
            const severity = classifyAlert(alert.key);
            const styles = severityStyles(severity);
            return (
              <div
                key={`${alert.ts}-${idx}`}
                className={`rounded-lg border ${styles.border} ${styles.bg} p-2.5 flex gap-2.5`}
              >
                <div className="flex flex-col items-center pt-0.5 gap-1">
                  <div className={`h-2 w-2 rounded-full shrink-0 ${styles.dot}`} />
                </div>
                <div className="flex-1 min-w-0 space-y-1">
                  <div className="flex items-start justify-between gap-2">
                    <span className={`font-mono text-[10px] font-semibold uppercase tracking-wide ${styles.text}`}>
                      {formatKey(alert.key)}
                    </span>
                    <div className="flex items-center gap-1.5 shrink-0">
                      <MessageSquare className="h-3 w-3 text-zinc-600" aria-label="WhatsApp" />
                      <Hash className="h-3 w-3 text-zinc-600" aria-label="Discord" />
                      <span className="font-mono text-[10px] text-zinc-600 tabular-nums whitespace-nowrap">
                        {formatTs(alert.ts)}
                      </span>
                    </div>
                  </div>
                  <p className="font-mono text-[10px] text-zinc-400 leading-snug line-clamp-2">
                    {alert.message}
                  </p>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Fired keys summary */}
      {data && Object.keys(data.fired_keys).length > 0 && (
        <div className="pt-1 border-t border-zinc-800">
          <p className="font-mono text-[9px] text-zinc-600 uppercase tracking-widest mb-1.5">
            Fired thresholds today
          </p>
          <div className="flex flex-wrap gap-1">
            {Object.keys(data.fired_keys).map((k) => (
              <Badge key={k} variant={severityStyles(classifyAlert(k)).badge}>
                {formatKey(k)}
              </Badge>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
