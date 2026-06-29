"use client";

import { useEffect, useState } from "react";
import { Database, RefreshCw } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { fetchEngine } from "@/lib/api";


// ── Types ──────────────────────────────────────────────────────────────────────

interface TradesResponse {
  trades: unknown[];
  count: number;
  error?: string;
  note?: string;
}

interface DecisionsResponse {
  decisions: unknown[];
  count: number;
  error?: string;
  note?: string;
}

interface AlertsResponse {
  alerts: unknown[];
  count: number;
  error?: string;
}

interface DbStats {
  totalTrades: number;
  totalDecisions: number;
  totalAlerts: number;
  dbStatus: "healthy" | "degraded" | "error";
  fetchErrors: string[];
  lastUpdated: Date;
}

// ── Stat tile ──────────────────────────────────────────────────────────────────

function StatTile({
  label,
  value,
  error,
}: {
  label: string;
  value: number | null;
  error?: boolean;
}) {
  return (
    <div className="rounded-lg border border-border bg-muted/40 p-3 space-y-1 text-center">
      <p className="text-[11px] text-muted-foreground uppercase tracking-wide">{label}</p>
      {value === null || error ? (
        <p className="text-lg font-mono font-semibold text-warn">—</p>
      ) : (
        <p className="text-lg font-mono font-semibold text-foreground">{value.toLocaleString()}</p>
      )}
    </div>
  );
}

// ── Component ──────────────────────────────────────────────────────────────────

export function DatabaseStatsCard() {
  const [stats, setStats] = useState<DbStats | null>(null);
  const [loading, setLoading] = useState(true);

  async function fetchStats() {
    setLoading(true);

    const [tradesResult, decisionsResult, alertsResult] = await Promise.allSettled([
      fetchEngine<TradesResponse>(`/portfolio/history/trades?limit=500&status=CLOSED`),
      fetchEngine<DecisionsResponse>(`/portfolio/history/decisions?limit=500`),
      fetchEngine<AlertsResponse>(`/alerts/history?limit=500`),
    ]);

    const errors: string[] = [];

    let totalTrades = 0;
    let tradesOk = false;
    if (tradesResult.status === "fulfilled" && !tradesResult.value.error) {
      totalTrades = tradesResult.value.count ?? tradesResult.value.trades?.length ?? 0;
      tradesOk = true;
    } else {
      errors.push("trades");
    }

    let totalDecisions = 0;
    let decisionsOk = false;
    if (decisionsResult.status === "fulfilled" && !decisionsResult.value.error) {
      totalDecisions = decisionsResult.value.count ?? decisionsResult.value.decisions?.length ?? 0;
      decisionsOk = true;
    } else {
      errors.push("decisions");
    }

    let totalAlerts = 0;
    let alertsOk = false;
    if (alertsResult.status === "fulfilled" && !alertsResult.value.error) {
      totalAlerts = alertsResult.value.count ?? alertsResult.value.alerts?.length ?? 0;
      alertsOk = true;
    } else {
      errors.push("alerts");
    }

    const successCount = [tradesOk, decisionsOk, alertsOk].filter(Boolean).length;
    const dbStatus: "healthy" | "degraded" | "error" =
      successCount === 3 ? "healthy" : successCount > 0 ? "degraded" : "error";

    setStats({
      totalTrades,
      totalDecisions,
      totalAlerts,
      dbStatus,
      fetchErrors: errors,
      lastUpdated: new Date(),
    });

    setLoading(false);
  }

  useEffect(() => {
    fetchStats();
    const interval = setInterval(fetchStats, 300_000); // 5 minutes
    return () => clearInterval(interval);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const statusVariant: "bull" | "bear" | "warn" =
    stats?.dbStatus === "healthy"
      ? "bull"
      : stats?.dbStatus === "degraded"
      ? "warn"
      : "bear";

  const statusLabel =
    stats?.dbStatus === "healthy"
      ? "Healthy"
      : stats?.dbStatus === "degraded"
      ? "Degraded"
      : "Error";

  const tradesError = stats?.fetchErrors.includes("trades") ?? false;
  const decisionsError = stats?.fetchErrors.includes("decisions") ?? false;
  const alertsError = stats?.fetchErrors.includes("alerts") ?? false;

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-2 pb-3">
        <div className="flex items-center gap-2">
          <Database className="h-4 w-4 text-muted-foreground" />
          <CardTitle>Database Statistics</CardTitle>
        </div>
        <div className="flex items-center gap-2">
          {loading && (
            <RefreshCw className="h-3.5 w-3.5 text-muted-foreground animate-spin" />
          )}
          {stats && (
            <Badge variant={statusVariant}>{statusLabel}</Badge>
          )}
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* Stat grid */}
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          <StatTile
            label="Total Trades"
            value={stats?.totalTrades ?? null}
            error={tradesError}
          />
          <StatTile
            label="Total Decisions"
            value={stats?.totalDecisions ?? null}
            error={decisionsError}
          />
          <StatTile
            label="Total Alerts"
            value={stats?.totalAlerts ?? null}
            error={alertsError}
          />
          <div className="rounded-lg border border-border bg-muted/40 p-3 space-y-1 text-center col-span-2 sm:col-span-1">
            <p className="text-[11px] text-muted-foreground uppercase tracking-wide">DB Status</p>
            {stats ? (
              <div className="flex items-center justify-center pt-0.5">
                <Badge variant={statusVariant}>{statusLabel}</Badge>
              </div>
            ) : (
              <p className="text-lg font-mono font-semibold text-muted-foreground">—</p>
            )}
          </div>
        </div>

        {/* Degraded warning */}
        {stats && stats.fetchErrors.length > 0 && (
          <div className="rounded-lg border border-warn/25 bg-warn/8 px-3 py-2">
            <p className="text-xs text-warn">
              Partial data — failed to fetch: {stats.fetchErrors.join(", ")}
            </p>
          </div>
        )}

        {/* Footer */}
        <p className="text-xs text-muted-foreground">
          {stats
            ? `Last updated ${stats.lastUpdated.toLocaleTimeString("en-US", {
                hour: "2-digit",
                minute: "2-digit",
                second: "2-digit",
                hour12: false,
              })} — refreshes every 5 minutes`
            : "Loading…"}
        </p>
      </CardContent>
    </Card>
  );
}
