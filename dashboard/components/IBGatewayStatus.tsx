"use client";

import { useState, useEffect, useCallback } from "react";
import { AlertCircle, Loader2, Wifi, WifiOff, Zap, RefreshCw } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { StalenessIndicator } from "@/components/ui/staleness-indicator";
import { fetchEngine, postEngine } from "@/lib/api";

// ── Types ─────────────────────────────────────────────────────────────────────

interface IBConnectionTestResult {
  connected: boolean;
  port: number;
  mode: string;
  latency_ms: number | null;
  account_id: string | null;
  error: string | null;
}

interface IBConnectResult {
  reconnected: boolean;
  message: string;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Format latency with color coding */
function LatencyBadge({ ms }: { ms: number | null }) {
  if (ms === null) return null;
  const color =
    ms < 50
      ? "text-bull"
      : ms < 200
      ? "text-warn"
      : "text-bear";
  return (
    <span className={`flex items-center gap-0.5 text-[10px] font-mono ${color}`}>
      <Zap className="h-2.5 w-2.5" />
      {ms.toFixed(1)}ms
    </span>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export function IBGatewayStatus() {
  const [data, setData] = useState<IBConnectionTestResult | null>(null);
  const [error, setError] = useState<boolean>(false);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isConnecting, setIsConnecting] = useState<boolean>(false);
  const [connectMessage, setConnectMessage] = useState<string | null>(null);
  const [lastChecked, setLastChecked] = useState<Date | null>(null);

  // ── Poll /ib/connection-test every 10 seconds ──────────────────────────────

  const poll = useCallback(async () => {
    try {
      const result = await fetchEngine<IBConnectionTestResult>("/ib/connection-test");
      setData(result);
      setError(false);
      setLastChecked(new Date());
    } catch {
      setError(true);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    poll();
    const id = setInterval(poll, 10_000);
    return () => clearInterval(id);
  }, [poll]);

  // ── Connect button handler ────────────────────────────────────────────────

  const handleConnect = useCallback(async () => {
    setIsConnecting(true);
    setConnectMessage(null);
    try {
      // GT-38: there is no /ib/connect route — the engine only exposes the
      // IBKR data-leg reconnect at POST /data/reconnect (idempotent, safe to
      // call any time; no-ops if already connected). That's the real action
      // behind this button's "Start IB Gateway, then click Connect" copy.
      const result = await postEngine<IBConnectResult>("/data/reconnect");
      setConnectMessage(result.message);
      // Immediately re-poll to refresh status
      await poll();
    } catch {
      setConnectMessage("Reconnect failed. Is IB Gateway running on port 4002?");
    } finally {
      setIsConnecting(false);
      // Clear the feedback message after 8 seconds
      setTimeout(() => setConnectMessage(null), 8_000);
    }
  }, [poll]);

  // ── Loading ────────────────────────────────────────────────────────────────

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-2 text-xs text-muted-foreground animate-pulse">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        <span>IB Gateway\u2026</span>
      </div>
    );
  }

  // ── Engine unreachable ────────────────────────────────────────────────────

  if (error || !data) {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-bear/30 bg-bear/5 px-3 py-2 text-xs text-bear">
        <AlertCircle className="h-3.5 w-3.5 shrink-0" />
        <span className="font-medium">IB Gateway</span>
        <span className="text-muted-foreground">engine unreachable</span>
      </div>
    );
  }

  // ── Connection state helpers ───────────────────────────────────────────────

  const connected = data.connected;

  const dotColor = connected ? "bg-bull" : "bg-bear";
  const ConnectionIcon = connected ? Wifi : WifiOff;
  const iconColor = connected ? "text-bull" : "text-muted-foreground";
  const connectionLabel = connected ? "Connected" : "Disconnected";

  return (
    <div className="rounded-lg border border-border bg-card">
      {/* Safety banner — paper mode lock */}
      <div className="flex items-center gap-2 rounded-t-lg bg-warn/5 border-b border-warn/20 px-3 py-1.5">
        <Badge variant="warn" className="text-[10px] px-1.5 py-0">
          PAPER ONLY
        </Badge>
        <span className="text-[10px] text-warn/80 font-medium">
          Port 4002 locked \u2014 live trading (4001) permanently disabled
        </span>
      </div>

      {/* Main status row */}
      <div className="flex items-center gap-3 px-3 py-2">
        {/* Connection icon */}
        <ConnectionIcon className={`h-4 w-4 shrink-0 ${iconColor}`} />

        {/* Label + status */}
        <div className="flex flex-col min-w-0">
          <span className="text-xs font-semibold text-foreground">IB Gateway</span>
          <div className="flex items-center gap-1.5 mt-0.5">
            {/* Live status dot */}
            <span className={`inline-block h-1.5 w-1.5 rounded-full shrink-0 ${dotColor}`} />
            <span
              className={`text-[11px] font-medium ${
                connected ? "text-bull" : "text-muted-foreground"
              }`}
            >
              {connectionLabel}
            </span>
            <span className="text-[11px] text-muted-foreground/60">\u00b7 port 4002</span>
            {/* Latency display when connected */}
            {connected && <LatencyBadge ms={data.latency_ms} />}
          </div>
        </div>

        {/* Right-side metadata + connect button */}
        <div className="flex flex-col items-end gap-1 ml-auto shrink-0">
          {data.account_id && (
            <span className="font-mono text-[11px] text-muted-foreground">
              {data.account_id}
            </span>
          )}

          {lastChecked && <StalenessIndicator lastUpdated={lastChecked} className="text-[10px] px-1.5 py-0" />}

          {/* Connect / status button */}
          {!connected && (
            <button
              onClick={handleConnect}
              disabled={isConnecting}
              className="mt-0.5 flex items-center gap-1 rounded border border-bull/40 bg-bull/5 px-2 py-0.5 text-[10px] font-semibold text-bull transition-colors hover:bg-bull/10 disabled:opacity-50"
            >
              {isConnecting ? (
                <>
                  <Loader2 className="h-2.5 w-2.5 animate-spin" />
                  Connecting\u2026
                </>
              ) : (
                <>
                  <RefreshCw className="h-2.5 w-2.5" />
                  Connect
                </>
              )}
            </button>
          )}
        </div>
      </div>

      {/* Connect feedback message */}
      {connectMessage && (
        <div className="border-t border-border/50 px-3 py-1.5">
          <p className="text-[10px] text-muted-foreground">{connectMessage}</p>
        </div>
      )}

      {/* Disconnected helper text */}
      {!connected && !connectMessage && (
        <div className="border-t border-border/50 px-3 py-1.5">
          <p className="text-[10px] text-muted-foreground/70">
            Start IB Gateway on port 4002 (paper trading), then click Connect.
          </p>
        </div>
      )}
    </div>
  );
}
