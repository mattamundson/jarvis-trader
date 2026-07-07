"use client";

import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { StalenessIndicator } from "@/components/ui/staleness-indicator";
import { Database } from "lucide-react";
import { fetchEngine, fetchEngineRaw } from "@/lib/api";


// ── Types ─────────────────────────────────────────────────────────────────────

interface DbTables {
  trades?: number;
  decisions?: number;
  alerts?: number;
  pipeline_runs?: number;
  daily_pnl?: number;
  [key: string]: number | undefined;
}

interface DbInfo {
  connected?: boolean;
  path?: string;
  size_bytes?: number;
  tables?: DbTables;
}

interface HealthResponse {
  status?: string;
  database?: DbInfo | string;
  uptime_seconds?: number;
}

interface WidgetState {
  connected: boolean | null;
  path: string | null;
  size_bytes: number | null;
  tables: DbTables | null;
  uptime_seconds: number | null;
  loading: boolean;
  error: boolean;
  lastChecked: Date | null;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatFileSize(bytes: number): string {
  if (bytes >= 1024 * 1024) {
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }
  return `${Math.round(bytes / 1024)} KB`;
}

function formatUptime(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return `${h}h ${m}m`;
}

const TABLE_LABELS: { key: keyof DbTables; label: string }[] = [
  { key: "trades", label: "Trades" },
  { key: "decisions", label: "Decisions" },
  { key: "alerts", label: "Alerts" },
  { key: "pipeline_runs", label: "Pipeline Runs" },
  { key: "daily_pnl", label: "Daily P&L" },
];

// ── Component ─────────────────────────────────────────────────────────────────

export function DatabaseStatusWidget() {
  const [state, setState] = useState<WidgetState>({
    connected: null,
    path: null,
    size_bytes: null,
    tables: null,
    uptime_seconds: null,
    loading: true,
    error: false,
    lastChecked: null,
  });

  async function fetchStatus() {
    try {
      const json = await fetchEngine<HealthResponse>(`/health`);
      const db = json.database;

      if (typeof db === "string") {
        setState({
          connected: db === "connected",
          path: null,
          size_bytes: null,
          tables: null,
          uptime_seconds: json.uptime_seconds ?? null,
          loading: false,
          error: false,
          lastChecked: new Date(),
        });
      } else if (db && typeof db === "object") {
        setState({
          connected: db.connected ?? true,
          path: db.path ?? null,
          size_bytes: db.size_bytes ?? null,
          tables: db.tables ?? null,
          uptime_seconds: json.uptime_seconds ?? null,
          loading: false,
          error: false,
          lastChecked: new Date(),
        });
      } else {
        // /health returned OK but no database key — try fallback
        try {
          const fallback = await fetchEngineRaw(`/portfolio/history/trades?limit=1`);
          setState({
            connected: fallback.ok,
            path: null,
            size_bytes: null,
            tables: null,
            uptime_seconds: json.uptime_seconds ?? null,
            loading: false,
            error: false,
            lastChecked: new Date(),
          });
        } catch {
          setState({
            connected: false,
            path: null,
            size_bytes: null,
            tables: null,
            uptime_seconds: json.uptime_seconds ?? null,
            loading: false,
            error: false,
            lastChecked: new Date(),
          });
        }
      }
    } catch {
      setState((prev) => ({
        ...prev,
        connected: false,
        loading: false,
        error: true,
        lastChecked: new Date(),
      }));
    }
  }

  useEffect(() => {
    fetchStatus();
    const pollInterval = setInterval(fetchStatus, 60_000);
    return () => clearInterval(pollInterval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Badge logic ───────────────────────────────────────────────────────────

  type BadgeVariant = "bull" | "bear" | "warn" | "neutral";

  function getBadge(): { variant: BadgeVariant; label: string } {
    if (state.loading) return { variant: "neutral", label: "UNKNOWN" };
    if (!state.connected) return { variant: "bear", label: "DISCONNECTED" };
    const tradeCount = state.tables?.trades;
    if (tradeCount === undefined || tradeCount === null) {
      return { variant: "bull", label: "HEALTHY" };
    }
    if (tradeCount > 0) return { variant: "bull", label: "HEALTHY" };
    return { variant: "warn", label: "EMPTY" };
  }

  const badge = getBadge();

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Database className="h-4 w-4 text-muted-foreground" />
            <CardTitle>Database Status</CardTitle>
          </div>
          <Badge variant={badge.variant}>{badge.label}</Badge>
        </div>
      </CardHeader>

      <CardContent>
        {/* Loading skeleton */}
        {state.loading && (
          <div className="space-y-3 animate-pulse">
            <div className="h-4 w-32 rounded bg-muted" />
            <div className="h-3 w-48 rounded bg-muted" />
            <div className="space-y-2">
              {Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className="flex justify-between">
                  <div className="h-3 w-24 rounded bg-muted" />
                  <div className="h-3 w-8 rounded bg-muted" />
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Error state */}
        {!state.loading && state.error && (
          <p className="text-sm text-muted-foreground text-center py-4">
            Database status unavailable
          </p>
        )}

        {/* Content */}
        {!state.loading && !state.error && (
          <div className="space-y-4">
            {/* Connection status */}
            <div className="flex items-center gap-2">
              <span
                className={`h-2.5 w-2.5 rounded-full flex-shrink-0 ${
                  state.connected ? "bg-bull" : "bg-bear"
                }`}
              />
              <span className="text-sm font-medium text-foreground">
                {state.connected ? "Connected" : "Disconnected"}
              </span>
            </div>

            {/* DB file path */}
            {state.path && (
              <p className="text-[11px] font-mono text-muted-foreground break-all">
                {state.path}
              </p>
            )}

            {/* File size + uptime row */}
            <div className="flex flex-wrap gap-3">
              {state.size_bytes !== null && state.size_bytes > 0 && (
                <div className="flex items-center gap-1.5 rounded-lg border border-border bg-muted/30 px-3 py-1.5">
                  <span className="text-[11px] text-muted-foreground">Size</span>
                  <span className="text-[11px] font-mono font-semibold text-foreground">
                    {formatFileSize(state.size_bytes)}
                  </span>
                </div>
              )}
              {state.uptime_seconds !== null && (
                <div className="flex items-center gap-1.5 rounded-lg border border-border bg-muted/30 px-3 py-1.5">
                  <span className="text-[11px] text-muted-foreground">Uptime</span>
                  <span className="text-[11px] font-mono font-semibold text-foreground">
                    {formatUptime(state.uptime_seconds)}
                  </span>
                </div>
              )}
            </div>

            {/* Record counts table */}
            {state.tables && (
              <div className="rounded-lg border border-border overflow-hidden">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-border bg-muted/40">
                      <th className="text-left px-3 py-2 text-muted-foreground font-medium">
                        Table
                      </th>
                      <th className="text-right px-3 py-2 text-muted-foreground font-medium">
                        Records
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {TABLE_LABELS.map(({ key, label }, i) => {
                      const count = state.tables?.[key];
                      if (count === undefined) return null;
                      return (
                        <tr
                          key={key}
                          className={
                            i % 2 === 0 ? "bg-background" : "bg-muted/20"
                          }
                        >
                          <td className="px-3 py-1.5 text-foreground font-mono">
                            {label}
                          </td>
                          <td className="px-3 py-1.5 text-right font-mono font-semibold text-foreground">
                            {count.toLocaleString()}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}

            {/* Last checked */}
            {state.lastChecked && (
              <StalenessIndicator lastUpdated={state.lastChecked} />
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
