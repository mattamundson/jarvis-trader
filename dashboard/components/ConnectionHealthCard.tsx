"use client";

import { useCallback, useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { fetchEngine } from "@/lib/api";


// ── Response shapes ────────────────────────────────────────────────────────────

interface HealthResponse {
  status: "healthy" | "degraded" | "error";
  version?: string;
  mode?: string;
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

const DEFAULT_ENGINE_STATUS: "healthy" | "degraded" | "error" = "error";
const DEFAULT_IB_CONNECTED = false;

// ── Component ──────────────────────────────────────────────────────────────────

export function ConnectionHealthCard() {
  const [engineStatus, setEngineStatus] = useState<"healthy" | "degraded" | "error">(
    DEFAULT_ENGINE_STATUS
  );
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
      setEngineStatus(h.status ?? "error");
      setEngineVersion(h.version ?? null);
      setMode(h.mode ?? null);
      setKillSwitchActive(h.kill_switch_active ?? false);
    } else {
      setEngineStatus("error");
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

  const engineConnected = engineStatus === "healthy" || engineStatus === "degraded";
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
    engineStatus === "healthy" ? "bull" : engineStatus === "degraded" ? "warn" : "bear";

  const engineLabel =
    engineStatus === "healthy" ? "ONLINE" : engineStatus === "degraded" ? "DEGRADED" : "OFFLINE";

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
