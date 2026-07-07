"use client";

import useSWR from "swr";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { HealthResponse } from "@/lib/api";
import { fetcher, UnreachableNote } from "./shared";

// GET /brokers/positions — engine/routers/brokers_router.py get_broker_positions()
interface BrokerPositionsLive {
  ibkr: { connected: boolean; positions: unknown[] };
  schwab: { connected: boolean; positions: unknown[] };
  paper: { positions: unknown[] };
  reconciliation?: Record<string, unknown>;
}

function formatUptime(seconds: number | undefined): string {
  if (seconds == null) return "—";
  if (seconds < 60) return `${Math.floor(seconds)}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return `${h}h ${m}m`;
}

function BoolBadge({
  label,
  value,
  warnOnFalse = true,
}: {
  label: string;
  value: boolean | null | undefined;
  warnOnFalse?: boolean;
}) {
  const variant: "bull" | "bear" | "warn" | "neutral" =
    value === true ? "bull" : value === false ? (warnOnFalse ? "bear" : "warn") : "neutral";
  return (
    <div className="flex items-center gap-1.5 rounded-lg border border-border bg-muted/30 px-2.5 py-1.5">
      <span className="text-[11px] text-muted-foreground">{label}</span>
      <Badge variant={variant}>{value === true ? "OK" : value === false ? "DOWN" : "?"}</Badge>
    </div>
  );
}

export function EngineDataPanel() {
  const {
    data: health,
    error: healthError,
    isLoading: healthLoading,
  } = useSWR<HealthResponse>("/health", fetcher, { refreshInterval: 15_000 });

  const { data: brokers, error: brokersError } = useSWR<BrokerPositionsLive>(
    "/brokers/positions",
    fetcher,
    { refreshInterval: 30_000 }
  );

  return (
    <Card>
      <CardHeader>
        <CardTitle>Engine &amp; Data</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {healthError ? (
          <UnreachableNote endpoint="/health" />
        ) : (
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex items-center gap-1.5 rounded-lg border border-border bg-muted/30 px-2.5 py-1.5">
              <span className="text-[11px] text-muted-foreground">Status</span>
              <Badge variant={health?.status === "ok" ? "bull" : "bear"}>
                {healthLoading ? "…" : (health?.status ?? "?").toUpperCase()}
              </Badge>
            </div>
            <BoolBadge label="TradingView MCP" value={health?.tradingview_mcp_healthy} />
            <BoolBadge label="LLM Path" value={health?.llm_path_healthy} />
            <BoolBadge label="IB Exec" value={health?.ibkr_execution_connected} warnOnFalse={false} />
            <BoolBadge label="IB Data" value={health?.ibkr_data_connected} warnOnFalse={false} />
            <div className="flex items-center gap-1.5 rounded-lg border border-border bg-muted/30 px-2.5 py-1.5">
              <span className="text-[11px] text-muted-foreground">Uptime</span>
              <span className="font-mono text-xs font-semibold text-foreground">
                {formatUptime(health?.uptime_seconds)}
              </span>
            </div>
          </div>
        )}

        {/* /brokers/positions reachability — the /health-vs-brokers divergence
            is a known trap: /health can be status=ok while the broker view is
            blind. Surface both so the divergence is visible at a glance. */}
        <div className="border-t border-border pt-3 space-y-2">
          <p className="text-[11px] uppercase tracking-wide text-muted-foreground">
            Broker truth check (/brokers/positions)
          </p>
          {brokersError ? (
            <UnreachableNote endpoint="/brokers/positions" />
          ) : brokers ? (
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="bull">REACHABLE</Badge>
              <BoolBadge label="IBKR" value={brokers.ibkr?.connected} warnOnFalse={false} />
              <span className="text-[11px] text-muted-foreground">
                {brokers.ibkr?.positions?.length ?? 0} IBKR · {brokers.paper?.positions?.length ?? 0}{" "}
                paper positions
              </span>
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">Checking…</p>
          )}
          {health?.status === "ok" && brokers && brokers.ibkr?.connected === false && (
            <p className="text-[11px] text-warn">
              Divergence: /health reports ok but IBKR is disconnected at /brokers/positions — broker
              view may be blind (known /health short-circuit).
            </p>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
