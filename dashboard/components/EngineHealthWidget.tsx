"use client";

import { useContext, useEffect, useState } from "react";
import Link from "next/link";
import {
  Activity,
  ArrowUpRight,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Wifi,
  WifiOff,
} from "lucide-react";
import { fetchEngine } from "@/lib/api";
import type { HealthResponse } from "@/lib/api";
import { EngineWebSocketContext } from "@/lib/engine-websocket-context";

function formatUptime(s: number): string {
  if (s < 60) return `${Math.floor(s)}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (h < 24) return `${h}h ${m}m`;
  const d = Math.floor(h / 24);
  return `${d}d ${h % 24}h`;
}

type StatusDot = "ok" | "warn" | "error" | "unknown";

function Dot({ state, label }: { state: StatusDot; label: string }) {
  const color =
    state === "ok"
      ? "text-bull"
      : state === "warn"
      ? "text-warn"
      : state === "error"
      ? "text-bear"
      : "text-muted-foreground";

  const Icon =
    state === "ok" ? CheckCircle2 : state === "warn" ? AlertTriangle : XCircle;

  return (
    <div className="flex items-center gap-1.5">
      <Icon className={`h-3.5 w-3.5 ${color}`} />
      <span className={`text-xs font-medium ${color}`}>{label}</span>
    </div>
  );
}

export function EngineHealthWidget() {
  const [data, setData] = useState<HealthResponse | null>(null);
  const [error, setError] = useState(false);
  // Non-throwing read: null when rendered outside the provider — degrades to
  // "Polling" rather than crashing. Honest about whether the 15s poll below
  // is being shadowed by a live WS push stream or is the sole data path.
  const wsCtx = useContext(EngineWebSocketContext);
  const wsLive = wsCtx?.isConnected ?? false;

  async function refresh() {
    try {
      const payload = await fetchEngine<HealthResponse>("/health");
      setData(payload);
      setError(false);
    } catch {
      setError(true);
      setData(null);
    }
  }

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 15_000);
    return () => clearInterval(id);
  }, []);

  const overall: StatusDot =
    error || !data
      ? "error"
      : data.kill_switch_active
      ? "warn"
      : data.status === "ok" || data.status === "healthy"
      ? "ok"
      : "warn";

  const tv: StatusDot =
    data == null
      ? "unknown"
      : data.tradingview_mcp_healthy === true
      ? "ok"
      : data.tradingview_mcp_healthy === false
      ? "error"
      : "unknown";

  const llm: StatusDot =
    data == null
      ? "unknown"
      : data.llm_path_healthy === true
      ? "ok"
      : data.llm_path_healthy === false
      ? "error"
      : "unknown";

  const ibkrExec: StatusDot =
    data == null
      ? "unknown"
      : data.ibkr_execution_connected === true
      ? "ok"
      : data.ibkr_execution_connected === false
      ? "warn"
      : data.ibkr_connected
      ? "ok"
      : "warn";

  const ibkrData: StatusDot =
    data == null
      ? "unknown"
      : data.ibkr_data_connected === true
      ? "ok"
      : data.ibkr_data_connected === false
      ? "warn"
      : "unknown";

  const borderClass =
    overall === "ok"
      ? "border-bull/20"
      : overall === "warn"
      ? "border-warn/30"
      : "border-bear/30";

  return (
    <div className={`rounded-xl border bg-card p-4 space-y-3 ${borderClass}`}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Activity className="h-4 w-4 text-accent" />
          <span className="text-sm font-semibold text-foreground">Engine Health</span>
        </div>
        <div className="flex items-center gap-2">
          <div
            className="flex items-center gap-1"
            title={
              wsLive
                ? "Live WebSocket stream connected"
                : "WebSocket disconnected — falling back to 15s polling"
            }
          >
            {wsLive ? (
              <Wifi className="h-3.5 w-3.5 text-bull" />
            ) : (
              <WifiOff className="h-3.5 w-3.5 text-muted-foreground" />
            )}
            <span
              className={`text-[11px] font-medium ${
                wsLive ? "text-bull" : "text-muted-foreground"
              }`}
            >
              {wsLive ? "Live" : "Polling"}
            </span>
          </div>
          {data && (
            <span className="text-xs text-muted-foreground font-mono">
              up {formatUptime(data.uptime_seconds)}
            </span>
          )}
          <Link
            href="/health"
            className="flex items-center gap-0.5 text-[11px] text-muted-foreground hover:text-foreground transition-colors"
          >
            Full
            <ArrowUpRight className="h-3 w-3" />
          </Link>
        </div>
      </div>

      {/* Overall status pill */}
      <div
        className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold ${
          overall === "ok"
            ? "bg-bull/10 text-bull"
            : overall === "warn"
            ? "bg-warn/10 text-warn"
            : "bg-bear/10 text-bear"
        }`}
      >
        {overall === "ok" ? (
          <CheckCircle2 className="h-3.5 w-3.5" />
        ) : overall === "warn" ? (
          <AlertTriangle className="h-3.5 w-3.5" />
        ) : (
          <XCircle className="h-3.5 w-3.5" />
        )}
        {error
          ? "Engine unreachable"
          : data?.kill_switch_active
          ? "Kill switch active"
          : overall === "ok"
          ? `OK — v${data?.version ?? "?"}`
          : "Degraded"}
      </div>

      {/* 4 subsystem checks */}
      <div className="grid grid-cols-2 gap-x-4 gap-y-2">
        <Dot state={tv} label="TV MCP" />
        <Dot state={llm} label="LLM path" />
        <Dot state={ibkrExec} label="IBKR exec" />
        <Dot state={ibkrData} label="IBKR data" />
      </div>

      {/* TV MCP detail if down */}
      {data?.tradingview_mcp_healthy === false && data.tradingview_mcp_details && (
        <p className="text-[11px] text-bear/80 font-mono truncate">
          {data.tradingview_mcp_details}
        </p>
      )}
    </div>
  );
}
