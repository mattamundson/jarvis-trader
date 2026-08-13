"use client";

import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { fetchEngine } from "@/lib/api";
import { summarizeAlertStatusCounts, type AlertStatsRaw } from "@/lib/alertStats";


// ── Types ──────────────────────────────────────────────────────────────────────

type AlertType = "signal" | "risk" | "notification" | "error";
type AlertStatus = "sent" | "failed" | "pending";
type AlertChannel = "whatsapp" | "log" | "internal";

interface Alert {
  id: number;
  alert_type: AlertType;
  symbol: string | null;
  message: string;
  channel: AlertChannel;
  status: AlertStatus;
  error: string | null;
  created_at: string;
}

interface AlertHistoryResponse {
  alerts: Alert[];
  total: number;
}

// ── Badge helpers ──────────────────────────────────────────────────────────────

function alertTypeBadge(type: string): "info" | "bear" | "neutral" {
  switch (type) {
    case "signal":
      return "info";
    case "risk":
      return "bear";
    case "notification":
      return "neutral";
    case "error":
      return "bear";
    default:
      return "neutral";
  }
}

function statusBadge(status: string): "bull" | "bear" | "warn" | "neutral" {
  switch (status) {
    case "sent":
      return "bull";
    case "failed":
      return "bear";
    case "pending":
      return "warn";
    default:
      return "neutral";
  }
}

function timeAgo(isoString: string): string {
  try {
    const diffMs = Date.now() - new Date(isoString).getTime();
    const diffSec = Math.floor(diffMs / 1000);
    if (diffSec < 60) return `${diffSec}s ago`;
    const diffMin = Math.floor(diffSec / 60);
    if (diffMin < 60) return `${diffMin}m ago`;
    const diffHr = Math.floor(diffMin / 60);
    if (diffHr < 24) return `${diffHr}h ago`;
    const diffDays = Math.floor(diffHr / 24);
    return `${diffDays}d ago`;
  } catch {
    return "";
  }
}

// ── Component ─────────────────────────────────────────────────────────────────

export function AlertSummaryWidget() {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [stats, setStats] = useState<AlertStatsRaw | null>(null);
  const [historyTotal, setHistoryTotal] = useState(0);

  async function fetchData() {
    try {
      const [historyRes, statsRes] = await Promise.allSettled([
        fetchEngine<AlertHistoryResponse>(`/alerts/history?limit=10`),
        fetchEngine<AlertStatsRaw>(`/alerts/stats`),
      ]);

      if (historyRes.status === "fulfilled") {
        const data = historyRes.value;
        setAlerts(data.alerts ?? []);
        setHistoryTotal(data.total ?? 0);
      }

      if (statsRes.status === "fulfilled") {
        setStats(statsRes.value);
      }
    } catch {
      // Graceful fallback — keep previous state
    }
  }

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 60_000);
    return () => clearInterval(interval);
  }, []);

  const statusCounts = summarizeAlertStatusCounts(stats);
  const sentCount = statusCounts.sent;
  const failedCount = statusCounts.failed;
  const pendingCount = statusCounts.pending;
  const total = stats?.total ?? historyTotal;

  return (
    <Card>
      <CardHeader className="flex flex-row justify-between items-center">
        <CardTitle>Alert Log</CardTitle>
        <div className="flex gap-2">
          <Badge variant={failedCount > 0 ? "bear" : "bull"}>
            {failedCount > 0 ? `${failedCount} Failed` : "All OK"}
          </Badge>
          <Badge variant="neutral">{total} Total</Badge>
        </div>
      </CardHeader>
      <CardContent>
        {/* Stats row */}
        <div className="grid grid-cols-3 gap-2 mb-3 text-center text-xs">
          <div className="rounded bg-muted p-2">
            <p className="text-muted-foreground">Sent</p>
            <p className="font-mono font-medium">{sentCount}</p>
          </div>
          <div className="rounded bg-muted p-2">
            <p className="text-muted-foreground">Failed</p>
            <p className={cn("font-mono font-medium", failedCount > 0 ? "text-red-400" : "")}>
              {failedCount}
            </p>
          </div>
          <div className="rounded bg-muted p-2">
            <p className="text-muted-foreground">Pending</p>
            <p className="font-mono font-medium">{pendingCount}</p>
          </div>
        </div>

        {/* Recent alerts table */}
        {alerts.length === 0 ? (
          <p className="text-xs text-muted-foreground text-center py-4">No alerts recorded</p>
        ) : (
          <div className="space-y-1">
            {alerts.slice(0, 8).map((alert) => (
              <div
                key={alert.id}
                className="flex items-center justify-between text-xs py-1 border-b border-border last:border-0"
              >
                <div className="flex items-center gap-2 min-w-0">
                  <Badge variant={alertTypeBadge(alert.alert_type)} className="shrink-0">
                    {alert.alert_type}
                  </Badge>
                  <span className="text-muted-foreground truncate max-w-[160px]">
                    {alert.message}
                  </span>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  {alert.symbol && (
                    <span className="font-mono text-muted-foreground">{alert.symbol}</span>
                  )}
                  <Badge variant={statusBadge(alert.status)}>{alert.status}</Badge>
                  <span className="text-muted-foreground">{timeAgo(alert.created_at)}</span>
                </div>
              </div>
            ))}
          </div>
        )}
        <p className="text-xs text-muted-foreground mt-2">Refreshes every 60s</p>
      </CardContent>
    </Card>
  );
}
