"use client";

import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
} from "@/components/ui/card";

const ENGINE_URL = process.env.NEXT_PUBLIC_ENGINE_URL || "http://localhost:8010";

// ── Types ──────────────────────────────────────────────────────────────────────

interface AlertRow {
  id: number;
  alert_type: string | null;
  symbol: string | null;
  message: string | null;
  channel: string | null;
  status: string | null;
  error: string | null;
  created_at: string | null;
}

interface AlertsResponse {
  alerts: AlertRow[];
  count: number;
}

type BadgeVariant = "bull" | "bear" | "warn" | "info" | "neutral";

// ── Helpers ────────────────────────────────────────────────────────────────────

function levelToBadge(alertType: string | null, status: string | null): BadgeVariant {
  const t = (alertType ?? "").toLowerCase();
  const s = (status ?? "").toLowerCase();

  if (t === "critical" || t === "error") return "bear";
  if (t === "warning" || t === "warn") return "warn";
  if (t === "info" || t === "signal") return "info";
  if (t === "success" || s === "sent") return "bull";
  return "neutral";
}

function labelForLevel(alertType: string | null, status: string | null): string {
  if (alertType) return alertType.toUpperCase();
  if (status) return status.toUpperCase();
  return "ALERT";
}

function relativeTime(isoString: string | null): string {
  if (!isoString) return "—";
  const ts = new Date(isoString).getTime();
  if (isNaN(ts)) return "—";
  const diffMs = Date.now() - ts;
  if (diffMs < 0) return "just now";
  const diffSec = Math.floor(diffMs / 1_000);
  if (diffSec < 60) return `${diffSec}s ago`;
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDay = Math.floor(diffHr / 24);
  return `${diffDay}d ago`;
}

function isWithin24h(isoString: string | null): boolean {
  if (!isoString) return false;
  const ts = new Date(isoString).getTime();
  if (isNaN(ts)) return false;
  return Date.now() - ts <= 24 * 60 * 60 * 1_000;
}

// ── Component ──────────────────────────────────────────────────────────────────

export function AlertHistoryWidget() {
  const [alerts, setAlerts] = useState<AlertRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);
  const [countdown, setCountdown] = useState(60);

  const fetchAlerts = async () => {
    try {
      const res = await fetch(`${ENGINE_URL}/alerts/history?limit=15`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: AlertsResponse = await res.json();
      setAlerts(data.alerts ?? []);
      setError(null);
      setLastRefresh(new Date());
      setCountdown(60);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch alerts");
    } finally {
      setLoading(false);
    }
  };

  // Initial fetch + 60s interval refresh
  useEffect(() => {
    fetchAlerts();
    const interval = setInterval(() => {
      fetchAlerts();
    }, 60_000);
    return () => clearInterval(interval);
  }, []);

  // Countdown ticker
  useEffect(() => {
    const tick = setInterval(() => {
      setCountdown((prev) => (prev <= 1 ? 60 : prev - 1));
    }, 1_000);
    return () => clearInterval(tick);
  }, []);

  // ── Summary counts (last 24h) ──────────────────────────────────────────────
  const recent = alerts.filter((a) => isWithin24h(a.created_at));
  const criticalCount = recent.filter(
    (a) =>
      (a.alert_type ?? "").toLowerCase() === "critical" ||
      (a.alert_type ?? "").toLowerCase() === "error"
  ).length;
  const warningCount = recent.filter(
    (a) =>
      (a.alert_type ?? "").toLowerCase() === "warning" ||
      (a.alert_type ?? "").toLowerCase() === "warn"
  ).length;
  const infoCount = recent.filter(
    (a) =>
      (a.alert_type ?? "").toLowerCase() === "info" ||
      (a.alert_type ?? "").toLowerCase() === "signal"
  ).length;

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <Card className="border-border bg-card">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="font-mono text-xs font-bold tracking-[0.15em] uppercase text-muted-foreground">
            Alert History
          </CardTitle>
          <div className="flex items-center gap-3">
            {/* 24h summary counts */}
            {!loading && !error && (
              <div className="hidden sm:flex items-center gap-2 font-mono text-[10px]">
                {criticalCount > 0 && (
                  <span className="text-bear font-semibold tabular-nums">
                    {criticalCount} critical
                  </span>
                )}
                {warningCount > 0 && (
                  <span className="text-warn font-semibold tabular-nums">
                    {warningCount} warn
                  </span>
                )}
                <span className="text-info tabular-nums">{infoCount} info</span>
                <span className="text-muted-foreground/40">/ 24h</span>
              </div>
            )}
            {/* Refresh indicator */}
            <div className="flex items-center gap-1.5 font-mono text-[10px] text-muted-foreground/50">
              <span
                className="inline-block h-1.5 w-1.5 rounded-full bg-info animate-pulse"
                aria-hidden="true"
              />
              <span className="tabular-nums">{countdown}s</span>
            </div>
          </div>
        </div>

        {/* Last refresh timestamp */}
        {lastRefresh && (
          <p className="font-mono text-[10px] text-muted-foreground/40 mt-0.5">
            Last refreshed {relativeTime(lastRefresh.toISOString())}
          </p>
        )}
      </CardHeader>

      <CardContent className="pt-0">
        {/* Loading state */}
        {loading && (
          <div className="flex items-center justify-center py-10 font-mono text-xs text-muted-foreground/50">
            Loading alerts…
          </div>
        )}

        {/* Error state */}
        {!loading && error && (
          <div className="flex items-center justify-center py-10 font-mono text-xs text-bear">
            Error: {error}
          </div>
        )}

        {/* Empty state */}
        {!loading && !error && alerts.length === 0 && (
          <div className="flex flex-col items-center justify-center py-10 gap-1 font-mono">
            <span className="text-xs text-muted-foreground/50">No recent alerts</span>
          </div>
        )}

        {/* Alert timeline */}
        {!loading && !error && alerts.length > 0 && (
          <div className="max-h-72 overflow-y-auto space-y-px pr-1">
            {alerts.map((alert) => {
              const variant = levelToBadge(alert.alert_type, alert.status);
              const label = labelForLevel(alert.alert_type, alert.status);
              const timeAgo = relativeTime(alert.created_at);
              const message = alert.message ?? alert.error ?? "—";

              return (
                <div
                  key={alert.id}
                  className="flex items-start gap-3 rounded-md px-3 py-2.5 hover:bg-muted/30 transition-colors"
                >
                  {/* Time */}
                  <span className="shrink-0 font-mono text-[10px] text-muted-foreground/50 tabular-nums pt-0.5 w-12 text-right">
                    {timeAgo}
                  </span>

                  {/* Badge */}
                  <div className="shrink-0 pt-0.5">
                    <Badge variant={variant} className="font-mono text-[9px] px-1.5 py-0 tracking-wider">
                      {label}
                    </Badge>
                  </div>

                  {/* Message + optional symbol */}
                  <div className="min-w-0 flex-1">
                    <p className="font-mono text-[11px] text-foreground/80 leading-relaxed truncate">
                      {alert.symbol && (
                        <span className="text-accent font-semibold mr-1.5">{alert.symbol}</span>
                      )}
                      {message}
                    </p>
                    {alert.channel && (
                      <p className="font-mono text-[9px] text-muted-foreground/40 mt-0.5">
                        via {alert.channel}
                      </p>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
