"use client";

import { POLL_INTERVAL } from "@/lib/polling-config";

import useSWR from "swr";
import { Loader2, RefreshCw, WifiOff, Wifi, Zap } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { fetchEngine, postEngine } from "@/lib/api";

// ── Types ──────────────────────────────────────────────────────────────────

interface SchwabStatus {
  connected: boolean;
  state: string;
  reason?: string | null;
  broker_routing?: string | null;
  account_id?: string | null;
  latency_ms?: number | null;
}

// ── Helpers ────────────────────────────────────────────────────────────────

function fetcher(path: string): Promise<SchwabStatus> {
  return fetchEngine<SchwabStatus>(path);
}

function LatencyDisplay({ ms }: { ms: number | null | undefined }) {
  if (ms == null) return null;
  const colorClass =
    ms < 50 ? "text-bull" : ms < 200 ? "text-warn" : "text-bear";
  return (
    <span className={`flex items-center gap-0.5 font-mono text-[10px] ${colorClass}`}>
      <Zap className="h-2.5 w-2.5" />
      {ms.toFixed(1)}ms
    </span>
  );
}

// ── Main Component ─────────────────────────────────────────────────────────

export function SchwabStatusWidget() {
  const { data, error, isLoading, mutate } = useSWR<SchwabStatus>(
    "/schwab/status",
    fetcher,
    { refreshInterval: POLL_INTERVAL.FAST, shouldRetryOnError: false }
  );

  const connected = data?.connected ?? false;
  const state = data?.state ?? "DISCONNECTED";
  const reason = data?.reason ?? null;
  const routing = data?.broker_routing ?? "Equities + Options \u2192 Schwab \u00b7 Futures \u2192 IBKR";
  const accountId = data?.account_id ?? null;
  const latencyMs = data?.latency_ms ?? null;

  const handleConnect = async () => {
    try {
      await postEngine("/schwab/connect", {});
    } catch {
      // Swallow — status will reflect reality on next poll
    }
    mutate();
  };

  const handleDisconnect = async () => {
    try {
      await postEngine("/schwab/disconnect", {});
    } catch {
      // Swallow — status will reflect reality on next poll
    }
    mutate();
  };

  // ── Loading state ──────────────────────────────────────────────────────

  if (isLoading) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="font-mono">SCHWAB / THINKORSWIM</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-2 text-xs text-muted-foreground animate-pulse">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            <span>Checking status&hellip;</span>
          </div>
        </CardContent>
      </Card>
    );
  }

  // ── Engine unreachable ─────────────────────────────────────────────────

  if (error || !data) {
    return (
      <Card className="border-bear/20">
        <CardHeader className="pb-2">
          <CardTitle className="font-mono">SCHWAB / THINKORSWIM</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-2">
            <WifiOff className="h-4 w-4 text-bear shrink-0" />
            <div className="space-y-0.5">
              <Badge variant="bear">ENGINE UNREACHABLE</Badge>
              <p className="text-[10px] text-muted-foreground">
                Cannot reach /schwab/status
              </p>
            </div>
          </div>
        </CardContent>
      </Card>
    );
  }

  // ── Normal render ──────────────────────────────────────────────────────

  const ConnectionIcon = connected ? Wifi : WifiOff;

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="font-mono">SCHWAB / THINKORSWIM</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {/* Status row */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <ConnectionIcon
              className={`h-4 w-4 shrink-0 ${connected ? "text-bull" : "text-muted-foreground"}`}
            />
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <Badge variant={connected ? "bull" : "neutral"}>
                  {connected ? "CONNECTED" : "DISCONNECTED"}
                </Badge>
                {connected && <LatencyDisplay ms={latencyMs} />}
              </div>
              <p className="font-mono text-[10px] text-muted-foreground tracking-wider">
                {state}
              </p>
              {accountId && (
                <p className="font-mono text-[10px] text-muted-foreground/70">
                  {accountId}
                </p>
              )}
            </div>
          </div>

          {/* Action button */}
          <div className="shrink-0">
            {!connected ? (
              <Button
                size="sm"
                variant="outline"
                onClick={handleConnect}
                className="gap-1.5"
              >
                <RefreshCw className="h-3 w-3" />
                Connect
              </Button>
            ) : (
              <Button
                size="sm"
                variant="ghost"
                onClick={handleDisconnect}
                className="text-muted-foreground hover:text-foreground"
              >
                Disconnect
              </Button>
            )}
          </div>
        </div>

        {/* Disconnect reason */}
        {reason && !connected && (
          <p className="text-[10px] text-warn/80 font-mono">{reason}</p>
        )}

        {/* Broker routing footer */}
        <div className="border-t border-border pt-2">
          <p className="text-[10px] text-muted-foreground/70 font-mono">
            {routing}
          </p>
        </div>
      </CardContent>
    </Card>
  );
}
