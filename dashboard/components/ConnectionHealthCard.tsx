"use client";

import { useCallback, useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { fetchEngine } from "@/lib/api";


// ── Response shapes ────────────────────────────────────────────────────────────

// Mirrors the REAL engine/routers/health_router.py GET /health response
// (line ~528: status = "ok" if (db_ok and llm_path_healthy) else "degraded").
// This previously declared "healthy"/"error"/"mode" -- values the backend
// never actually sends -- so `engineStatus === "healthy"` was always false
// and Trading Engine showed OFFLINE unconditionally, and `h.mode` was always
// undefined (only `paper_mode: boolean` exists) so Trading Mode showed
// UNKNOWN unconditionally, regardless of the engine's real state.
interface HealthResponse {
  status: "ok" | "degraded";
  version?: string;
  paper_mode?: boolean;
  kill_switch_active?: boolean;
  timestamp?: string;
}

interface IBConnectionTestResponse {
  connected: boolean;
  host?: string;
  port?: number;
  client_id?: number;
  error?: string | null;
}

// ── State defaults ─────────────────────────────────────────────────────────────

// "unreachable" is a purely client-side sentinel (fetch failed / not yet
// fetched) -- the backend itself only ever sends "ok" or "degraded".
type EngineStatus = "ok" | "degraded" | "unreachable";
const DEFAULT_ENGINE_STATUS: EngineStatus = "unreachable";
const DEFAULT_IB_CONNECTED = false;

// ── Component ──────────────────────────────────────────────────────────────────

export function ConnectionHealthCard() {
  const [engineStatus, setEngineStatus] = useState<EngineStatus>(DEFAULT_ENGINE_STATUS);
  const [engineVersion, setEngineVersion] = useState<string | null>(null);
  const [mode, setMode] = useState<string | null>(null);
  const [killSwitchActive, setKillSwitchActive] = useState(false);

  const [ibConnected, setIbConnected] = useState(DEFAULT_IB_CONNECTED);
  const [ibError, setIbError] = useState<string | null>(null);

  const fetchAll = useCallback(async () => {
    const [healthResult, ibResult] = await Promise.allSettled([
      fetchEngine<HealthResponse>(`/health`),
      fetchEngine<IBConnectionTestResponse>(`/ib/connection-test`),
    ]);

    // Engine health
    if (healthResult.status === "fulfilled") {
      const h = healthResult.value;
      setEngineStatus(h.status ?? "unreachable");
      setEngineVersion(h.version ?? null);
      setMode(h.paper_mode === undefined ? null : h.paper_mode ? "paper" : "live");
      setKillSwitchActive(h.kill_switch_active ?? false);
    } else {
      setEngineStatus("unreachable");
      setEngineVersion(null);
      setMode(null);
      setKillSwitchActive(false);
    }

    // IB connection test
    if (ibResult.status === "fulfilled") {
      const ib = ibResult.value;
      setIbConnected(ib.connected ?? false);
      setIbError(ib.error ?? null);
    } else {
      setIbConnected(false);
      setIbError("Network error");
    }
  }, []);

  useEffect(() => {
    fetchAll();
    const interval = setInterval(fetchAll, 30_000);
    return () => clearInterval(interval);
  }, [fetchAll]);

  // ── Derived values ───────────────────────────────────────────────────────────

  const engineConnected = engineStatus === "ok" || engineStatus === "degraded";
  const connectedCount = [engineConnected, ibConnected].filter(Boolean).length;
  const totalCount = 2;
  const allConnected = connectedCount === totalCount;
  const someConnected = connectedCount > 0 && connectedCount < totalCount;

  const overallVariant: "bull" | "warn" | "bear" = allConnected
    ? "bull"
    : someConnected
    ? "warn"
    : "bear";

  const engineBadgeVariant: "bull" | "warn" | "bear" =
    engineStatus === "ok" ? "bull" : engineStatus === "degraded" ? "warn" : "bear";

  const engineLabel =
    engineStatus === "ok" ? "ONLINE" : engineStatus === "degraded" ? "DEGRADED" : "OFFLINE";

  const modeBadgeVariant: "info" | "bull" | "neutral" =
    mode === "paper" ? "info" : mode === "live" ? "bull" : "neutral";

  return (
    <Card>
      <CardHeader className={cn("flex flex-row items-center justify-between space-y-0")}>
        <CardTitle>Connection Status</CardTitle>
        <Badge variant={overallVariant}>
          {connectedCount}/{totalCount} Connected
        </Badge>
      </CardHeader>

      <CardContent>
        <div className="space-y-2">
          {/* Trading Engine row */}
          <div className="flex items-center justify-between py-1.5 border-b border-border">
            <div>
              <p className="text-sm font-medium">Trading Engine</p>
              <p className="text-xs text-muted-foreground">FastAPI • via dashboard proxy</p>
            </div>
            <div className="flex items-center gap-2">
              <Badge variant={engineBadgeVariant}>{engineLabel}</Badge>
              {engineVersion && (
                <span className="text-xs text-muted-foreground">v{engineVersion}</span>
              )}
            </div>
          </div>

          {/* IB Gateway row */}
          <div className="flex items-center justify-between py-1.5 border-b border-border">
            <div>
              <p className="text-sm font-medium">IB Gateway (Paper)</p>
              <p className="text-xs text-muted-foreground">TWS Paper • Port 4002</p>
            </div>
            <div className="flex items-center gap-2">
              <Badge variant={ibConnected ? "bull" : "bear"}>
                {ibConnected ? "CONNECTED" : "DISCONNECTED"}
              </Badge>
              {ibError && (
                <span className="text-xs text-red-400 max-w-[120px] truncate">{ibError}</span>
              )}
            </div>
          </div>

          {/* Trading Mode row */}
          <div className="flex items-center justify-between py-1.5 border-b border-border">
            <div>
              <p className="text-sm font-medium">Trading Mode</p>
              <p className="text-xs text-muted-foreground">Execution mode</p>
            </div>
            <Badge variant={modeBadgeVariant}>
              {(mode || "UNKNOWN").toUpperCase()}
            </Badge>
          </div>

          {/* Kill Switch row */}
          <div className="flex items-center justify-between py-1.5">
            <div>
              <p className="text-sm font-medium">Kill Switch</p>
              <p className="text-xs text-muted-foreground">Emergency stop</p>
            </div>
            <Badge variant={killSwitchActive ? "bear" : "bull"}>
              {killSwitchActive ? "ACTIVE" : "INACTIVE"}
            </Badge>
          </div>
        </div>

        <p className="text-xs text-muted-foreground mt-3">Refreshes every 30s</p>
      </CardContent>
    </Card>
  );
}
