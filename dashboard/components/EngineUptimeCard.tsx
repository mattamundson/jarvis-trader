"use client";

import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { fetchEngine } from "@/lib/api";


// ── Response shape ─────────────────────────────────────────────────────────────

interface HealthResponse {
  status: string;
  version: string;
  timestamp: string;
  live_trading: boolean;
  kill_switch_active: boolean;
  paper_mode: boolean;
  database: string;
  ibkr_connected: boolean;
  schwab_connected: boolean;
  uptime_seconds: number;
}

// ── Helpers ────────────────────────────────────────────────────────────────────

function formatUptime(seconds: number): string {
  if (seconds < 60) return `${Math.floor(seconds)}s`;
  const totalMinutes = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  if (totalMinutes < 60) return `${totalMinutes}m ${s}s`;
  const h = Math.floor(totalMinutes / 60);
  const m = totalMinutes % 60;
  const d = Math.floor(h / 24);
  const hRem = h % 24;
  if (d > 0) return `${d}d ${hRem}h ${m}m`;
  return `${h}h ${m}m`;
}

function formatTimestamp(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString("en-US", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    });
  } catch {
    return iso;
  }
}

// ── Component ──────────────────────────────────────────────────────────────────

export function EngineUptimeCard() {
  const [data, setData] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastChecked, setLastChecked] = useState<string | null>(null);

  async function fetchHealth() {
    try {
      const payload = await fetchEngine<HealthResponse>(`/health`);
      setData(payload);
      setError(null);
      setLastChecked(new Date().toLocaleTimeString("en-US", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false,
      }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unreachable");
      setData(null);
      setLastChecked(new Date().toLocaleTimeString("en-US", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false,
      }));
    }
  }

  useEffect(() => {
    fetchHealth();
    const id = setInterval(fetchHealth, 30_000);
    return () => clearInterval(id);
  }, []);

  const isUp = data !== null && !error;
  const mode = data ? (data.paper_mode ? "Paper" : "Live") : null;

  return (
    <Card className="border-border bg-card">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-semibold text-foreground">
            Engine Status
          </CardTitle>
          <div className="flex items-center gap-2">
            {isUp ? (
              <span className="flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full bg-bull animate-pulse" />
                <span className="text-xs text-bull font-medium">Live</span>
              </span>
            ) : (
              <span className="flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full bg-bear" />
                <span className="text-xs text-bear font-medium">Down</span>
              </span>
            )}
          </div>
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* Big uptime display */}
        <div className="flex flex-col items-center justify-center rounded-xl border border-border bg-muted/30 py-5 gap-1">
          {isUp && data ? (
            <>
              <span className="text-3xl font-bold font-mono text-foreground tracking-tight">
                {formatUptime(data.uptime_seconds)}
              </span>
              <span className="text-xs text-muted-foreground uppercase tracking-widest">
                Uptime
              </span>
            </>
          ) : (
            <>
              <span className="text-2xl font-bold font-mono text-bear">—</span>
              <span className="text-xs text-muted-foreground uppercase tracking-widest">
                Uptime
              </span>
            </>
          )}
        </div>

        {/* Status grid */}
        <div className="space-y-2">
          {/* Version */}
          <div className="flex items-center justify-between py-1.5 border-b border-border/50">
            <span className="text-xs text-muted-foreground">Version</span>
            {isUp && data ? (
              <span className="text-xs font-mono font-semibold text-foreground">
                v{data.version}
              </span>
            ) : (
              <span className="text-xs text-muted-foreground">—</span>
            )}
          </div>

          {/* Mode */}
          <div className="flex items-center justify-between py-1.5 border-b border-border/50">
            <span className="text-xs text-muted-foreground">Mode</span>
            {mode !== null ? (
              <Badge variant={mode === "Live" ? "bull" : "info"}>
                {mode}
              </Badge>
            ) : (
              <span className="text-xs text-muted-foreground">—</span>
            )}
          </div>

          {/* Status */}
          <div className="flex items-center justify-between py-1.5 border-b border-border/50">
            <span className="text-xs text-muted-foreground">Status</span>
            {isUp && data ? (
              <Badge variant={data.status === "ok" ? "bull" : "warn"}>
                {data.status === "ok" ? "Running" : data.status}
              </Badge>
            ) : (
              <Badge variant="bear">
                Unreachable
              </Badge>
            )}
          </div>

          {/* Kill Switch */}
          {isUp && data && (
            <div className="flex items-center justify-between py-1.5 border-b border-border/50">
              <span className="text-xs text-muted-foreground">Kill Switch</span>
              <Badge variant={data.kill_switch_active ? "bear" : "bull"}>
                {data.kill_switch_active ? "Active" : "Inactive"}
              </Badge>
            </div>
          )}

          {/* Database */}
          {isUp && data && (
            <div className="flex items-center justify-between py-1.5">
              <span className="text-xs text-muted-foreground">Database</span>
              <Badge variant={data.database === "connected" ? "bull" : "bear"}>
                {data.database === "connected" ? "Connected" : data.database}
              </Badge>
            </div>
          )}
        </div>

        {/* Last checked */}
        {lastChecked && (
          <p className="text-[11px] text-muted-foreground text-right">
            Last checked {lastChecked}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
