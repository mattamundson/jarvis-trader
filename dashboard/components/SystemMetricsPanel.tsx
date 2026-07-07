"use client";

import { useEffect, useState } from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { StalenessIndicator } from "@/components/ui/staleness-indicator";
import { Database, Activity } from "lucide-react";
import { fetchEngine } from "@/lib/api";


// Shape of GET /health response
interface HealthResponse {
  status?: string;
  version?: string;
  timestamp?: string;
  uptime_seconds?: number;
  live_trading?: boolean;
  kill_switch_active?: boolean;
  paper_mode?: boolean;
  database?: string;
  ibkr_connected?: boolean;
  ibkr_execution_connected?: boolean | null;
  ibkr_data_connected?: boolean | null;
  schwab_connected?: boolean;
}

// Shape of GET /health/full subsystems.database.details
interface DbDetails {
  db_path?: string;
  schema_version?: number;
  row_counts?: {
    paper_trades?: number;
    decisions?: number;
    pipeline_runs?: number;
    daily_pnl?: number;
    positions?: number;
    settings?: number;
    trade_journal?: number;
    [key: string]: number | undefined;
  };
}

// Minimal shape of /health/full we care about
interface FullHealthPartial {
  subsystems?: {
    database?: {
      status?: string;
      details?: DbDetails;
    };
  };
}

interface MetricTileProps {
  label: string;
  value: number | string;
  sub?: string;
}

function MetricTile({ label, value, sub }: MetricTileProps) {
  return (
    <div className="rounded-lg border border-border bg-background px-4 py-3 flex flex-col gap-1">
      <span className="text-[11px] uppercase tracking-wider text-muted-foreground font-medium">
        {label}
      </span>
      <span className="text-2xl font-bold font-mono text-foreground tabular-nums">
        {value}
      </span>
      {sub && (
        <span className="text-[11px] text-muted-foreground">{sub}</span>
      )}
    </div>
  );
}

function SkeletonTile() {
  return (
    <div className="rounded-lg border border-border bg-background px-4 py-3 animate-pulse space-y-2">
      <div className="h-2.5 w-20 rounded bg-muted" />
      <div className="h-7 w-14 rounded bg-muted" />
      <div className="h-2 w-16 rounded bg-muted" />
    </div>
  );
}

function formatUptime(seconds: number): string {
  if (seconds < 60) return `${Math.floor(seconds)}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.floor(seconds % 60)}s`;
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return `${h}h ${m}m`;
}

export function SystemMetricsPanel() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [dbDetails, setDbDetails] = useState<DbDetails | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  useEffect(() => {
    const load = async () => {
      try {
        // Fetch basic health
        const json = await fetchEngine<HealthResponse>(`/health`);
        setHealth(json);
      } catch {
        // ignore — engine may be offline
      }

      try {
        // Fetch full health to get DB row counts from subsystems.database.details
        const fullJson = await fetchEngine<FullHealthPartial>(`/health/full`);
        const details = fullJson?.subsystems?.database?.details;
        if (details) {
          setDbDetails(details);
        }
      } catch {
        // ignore
      }

      setLoading(false);
      setLastUpdated(new Date());
    };

    load();
    const t = setInterval(load, 60_000);
    return () => clearInterval(t);
  }, []);

  const statusVariant: "bull" | "bear" | "warn" | "info" | "neutral" =
    health?.status === "ok" ? "bull" : health?.status ? "bear" : "neutral";

  const rowCounts = dbDetails?.row_counts;

  const dbMetrics: { label: string; key: keyof NonNullable<typeof rowCounts> }[] = [
    { label: "Paper Trades", key: "paper_trades" },
    { label: "Pipeline Runs", key: "pipeline_runs" },
    { label: "Decisions", key: "decisions" },
    { label: "Daily P&L Rows", key: "daily_pnl" },
  ];

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-info/10">
              <Database className="h-4 w-4 text-info" />
            </div>
            <CardTitle>System Metrics</CardTitle>
          </div>
          <div className="flex items-center gap-2">
            {health?.status && (
              <Badge variant={statusVariant}>
                {health.status === "ok" ? "Engine OK" : health.status.toUpperCase()}
              </Badge>
            )}
            {health?.version && (
              <span className="text-[11px] font-mono text-muted-foreground border border-border rounded px-2 py-0.5">
                v{health.version}
              </span>
            )}
          </div>
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* DB record counts — 4-column grid */}
        <div>
          <p className="text-[11px] uppercase tracking-wider text-muted-foreground font-medium mb-2 flex items-center gap-1.5">
            <Database className="h-3 w-3" />
            Database Record Counts
          </p>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {loading
              ? Array.from({ length: 4 }).map((_, i) => <SkeletonTile key={i} />)
              : dbMetrics.map(({ label, key }) => (
                  <MetricTile
                    key={key}
                    label={label}
                    value={rowCounts?.[key] ?? "—"}
                    sub={rowCounts ? "rows" : "unavailable"}
                  />
                ))}
          </div>
        </div>

        {/* Engine meta row */}
        <div className="flex flex-wrap items-center gap-3 pt-1 border-t border-border">
          {/* Uptime */}
          {health?.uptime_seconds !== undefined && (
            <div className="flex items-center gap-1.5">
              <Activity className="h-3 w-3 text-muted-foreground" />
              <span className="text-[11px] text-muted-foreground">Uptime</span>
              <span className="text-[11px] font-mono font-semibold text-foreground">
                {formatUptime(health.uptime_seconds)}
              </span>
            </div>
          )}

          {/* Paper mode */}
          {health?.paper_mode !== undefined && (
            <div className="flex items-center gap-1.5">
              <span className="text-[11px] text-muted-foreground">Mode</span>
              <Badge variant={health.paper_mode ? "info" : "bear"}>
                {health.paper_mode ? "Paper" : "Live"}
              </Badge>
            </div>
          )}

          {/* Kill switch */}
          {health?.kill_switch_active !== undefined && (
            <div className="flex items-center gap-1.5">
              <span className="text-[11px] text-muted-foreground">Kill Switch</span>
              <Badge variant={health.kill_switch_active ? "bear" : "bull"}>
                {health.kill_switch_active ? "Active" : "Inactive"}
              </Badge>
            </div>
          )}

          {/* Last updated */}
          {lastUpdated && (
            <div className="ml-auto">
              <StalenessIndicator lastUpdated={lastUpdated} />
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
