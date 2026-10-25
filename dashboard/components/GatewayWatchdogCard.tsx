"use client";

import { useEffect, useState } from "react";
import { Shield, Activity, Clock, Wifi, WifiOff } from "lucide-react";
import { fetchEngine } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { POLL_INTERVAL } from "@/lib/polling-config";

/**
 * Gateway Health Watchdog — Mission Control.
 *
 * One-glance confidence that the IBKR paper Gateway is alive and the
 * engine is receiving fresh market data. Every field comes from GET /health.
 *
 * ● ibgateway_alive — port 4002 is LISTENING  (gateway process is up)
 * ● ibkr_connected   — socket + RPC health     (engine can talk to it)
 * ● market_data_fresh — no stale symbols        (data is current)
 *
 * All three must be green for the paper pipeline to function. Any one
 * turning yellow or red means paper trading is degraded or halted.
 */

interface WatchdogState {
  ibgateway_alive: boolean;
  ibgateway_port: number | null;
  ibkr_connected: boolean;
  ibkr_data_connected: boolean;
  market_data_fresh: boolean;
  live_trading: boolean;
  uptime_seconds: number;
  loaded: boolean;
}

function statusVariant(ok: boolean): "bull" | "bear" | "neutral" {
  if (ok) return "bull";
  return "bear";
}

function statusLabel(ok: boolean): string {
  return ok ? "OK" : "DOWN";
}

function fmtUptime(secs: number): string {
  if (secs < 60) return `${Math.round(secs)}s`;
  const min = Math.floor(secs / 60);
  const h = Math.floor(min / 60);
  if (h > 0) return `${h}h ${min % 60}m`;
  return `${min}m`;
}

export function GatewayWatchdogCard() {
  const [state, setState] = useState<WatchdogState>({
    ibgateway_alive: false,
    ibgateway_port: null,
    ibkr_connected: false,
    ibkr_data_connected: false,
    market_data_fresh: false,
    live_trading: false,
    uptime_seconds: 0,
    loaded: false,
  });

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const d = await fetchEngine<Record<string, unknown>>("/health");
        if (cancelled) return;
        setState({
          ibgateway_alive: !!d.ibgateway_alive,
          ibgateway_port: (d.ibgateway_port as number) ?? null,
          ibkr_connected: !!d.ibkr_connected,
          ibkr_data_connected: !!d.ibkr_data_connected,
          market_data_fresh: !!d.market_data_fresh,
          live_trading: !!d.live_trading,
          uptime_seconds: (d.uptime_seconds as number) ?? 0,
          loaded: true,
        });
      } catch {
        if (!cancelled) setState((s) => ({ ...s, loaded: true }));
      }
    }

    load();
    const interval = setInterval(load, POLL_INTERVAL.HEALTH);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  const allGreen =
    state.ibgateway_alive && state.ibkr_connected && state.market_data_fresh;
  const anyRed =
    state.loaded && (!state.ibgateway_alive || !state.ibkr_connected || !state.market_data_fresh);

  return (
    <div className="rounded-lg border border-border bg-card p-4 space-y-3">
      <div className="flex items-center gap-2">
        <Shield className="h-4 w-4 text-accent" />
        <h3 className="text-sm font-semibold text-foreground">Gateway Watchdog</h3>
        {state.loaded ? (
          allGreen ? (
            <Wifi className="h-3.5 w-3.5 ml-auto text-bull" />
          ) : (
            <WifiOff className="h-3.5 w-3.5 ml-auto text-bear" />
          )
        ) : (
          <Clock className="h-3.5 w-3.5 ml-auto text-muted-foreground animate-pulse" />
        )}
      </div>

      {!state.loaded ? (
        <p className="text-xs text-muted-foreground">Loading gateway status…</p>
      ) : (
        <div className="space-y-2">
          {/* Row: Gateway alive + port */}
          <div className="flex items-center justify-between">
            <span className="text-xs text-muted-foreground flex items-center gap-1.5">
              <Activity className="h-3 w-3" />
              IB Gateway
              {state.ibgateway_port ? (
                <span className="font-mono text-[10px]">:{state.ibgateway_port}</span>
              ) : null}
            </span>
            <Badge variant={statusVariant(state.ibgateway_alive)} className="text-[10px] px-1.5 py-0">
              {statusLabel(state.ibgateway_alive)}
            </Badge>
          </div>

          {/* Row: Engine connected */}
          <div className="flex items-center justify-between">
            <span className="text-xs text-muted-foreground flex items-center gap-1.5">
              <Activity className="h-3 w-3" />
              Engine connected
            </span>
            <Badge variant={statusVariant(state.ibkr_connected)} className="text-[10px] px-1.5 py-0">
              {statusLabel(state.ibkr_connected)}
            </Badge>
          </div>

          {/* Row: Market data fresh */}
          <div className="flex items-center justify-between">
            <span className="text-xs text-muted-foreground flex items-center gap-1.5">
              <Activity className="h-3 w-3" />
              Data fresh
            </span>
            <Badge variant={statusVariant(state.market_data_fresh)} className="text-[10px] px-1.5 py-0">
              {statusLabel(state.market_data_fresh)}
            </Badge>
          </div>

          {/* Row: Trading mode */}
          <div className="flex items-center justify-between">
            <span className="text-xs text-muted-foreground">Trading mode</span>
            <Badge
              variant={state.live_trading ? "bear" : "info"}
              className="text-[10px] px-1.5 py-0"
            >
              {state.live_trading ? "LIVE" : "PAPER"}
            </Badge>
          </div>

          {/* Overall status */}
          <div className="flex items-center justify-between border-t border-border pt-2">
            <span className="text-[10px] text-muted-foreground">
              Engine uptime {fmtUptime(state.uptime_seconds)}
            </span>
            <Badge
              variant={allGreen ? "bull" : anyRed ? "bear" : "neutral"}
              className="text-[10px] px-1.5 py-0"
            >
              {allGreen ? "ALL GREEN" : anyRed ? "DEGRADED" : "PARTIAL"}
            </Badge>
          </div>
        </div>
      )}
    </div>
  );
}