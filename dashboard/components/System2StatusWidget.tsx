"use client";

import React from "react";
import useSWR from "swr";
import { fetchEngine } from "@/lib/api";
import { Activity, AlertTriangle, TrendingUp, TrendingDown, Clock, Zap } from "lucide-react";

interface System2Trade {
  event: string;
  ts: string;
  symbol: string;
  entry_price?: number;
  stop_price?: number;
  t1_price?: number;
  t2_price?: number;
  atr?: number;
  bar_time?: string;
  pnl?: number;
  exit_price?: number;
  stage?: string;
}

interface System2Status {
  running: boolean;
  mode: string;
  last_heartbeat: string | null;
  pid: number | null;
  port: number | null;
  recent_trades: System2Trade[];
  last_signal: System2Trade | null;
}

function fmt(n: number | undefined, decimals = 2) {
  if (n == null) return "—";
  return n.toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

function timeAgo(ts: string) {
  const diff = Date.now() - new Date(ts).getTime();
  const s = Math.floor(diff / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  return `${h}h ago`;
}

export function System2StatusWidget() {
  const { data, error, isLoading } = useSWR<System2Status>(
    "/system2/status",
    () => fetchEngine<System2Status>("/system2/status"),
    { refreshInterval: 15000, shouldRetryOnError: false }
  );

  const offline = error || (!isLoading && !data);

  // ── offline / engine down ──────────────────────────────────────────────────
  if (offline) {
    return (
      <div
        className="rounded border p-3 text-xs font-mono"
        style={{ background: "#0d1117", borderColor: "#1e293b" }}
      >
        <div className="flex items-center gap-2 mb-2">
          <div className="w-2 h-2 rounded-full bg-slate-600" />
          <span className="text-slate-400 font-bold tracking-widest text-[10px]">SYSTEM 2 — ES/NQ EXECUTOR</span>
          <span className="ml-auto text-[10px] text-slate-600">ENGINE OFFLINE</span>
        </div>
        <div className="text-slate-600 text-[10px]">
          Start engine to see executor status · Port 4002 (paper)
        </div>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div
        className="rounded border p-3 text-xs font-mono animate-pulse"
        style={{ background: "#0d1117", borderColor: "#1e293b" }}
      >
        <div className="h-3 w-48 bg-slate-800 rounded" />
      </div>
    );
  }

  const s = data!;
  const running = s.running;
  const sig = s.last_signal;

  return (
    <div
      className="rounded border p-3 text-xs font-mono"
      style={{ background: "#0d1117", borderColor: running ? "#1e3a5f" : "#2d1b1b" }}
    >
      {/* Header */}
      <div className="flex items-center gap-2 mb-3">
        <div
          className={`w-2 h-2 rounded-full ${running ? "bg-cyan-400 animate-pulse" : "bg-red-500"}`}
        />
        <span
          className="font-bold tracking-widest text-[10px]"
          style={{ color: running ? "#00d4ff" : "#ff4444" }}
        >
          SYSTEM 2 — ES/NQ EXECUTOR
        </span>
        <span
          className="ml-auto text-[10px] px-1.5 py-0.5 rounded border font-bold"
          style={{
            color: running ? "#00d4ff" : "#ff4444",
            borderColor: running ? "#1e3a5f" : "#3d1a1a",
            background: running ? "#0a1929" : "#1a0a0a",
          }}
        >
          {running ? `RUNNING · ${s.mode?.toUpperCase() ?? "PAPER"}` : "HALTED"}
        </span>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-4 gap-2 mb-3">
        <div className="text-center">
          <div className="text-[10px] text-slate-500 mb-0.5">PORT</div>
          <div className="text-white">{s.port ?? "—"}</div>
        </div>
        <div className="text-center">
          <div className="text-[10px] text-slate-500 mb-0.5">PID</div>
          <div className="text-white">{s.pid ?? "—"}</div>
        </div>
        <div className="text-center">
          <div className="text-[10px] text-slate-500 mb-0.5">HEARTBEAT</div>
          <div className={s.last_heartbeat ? "text-green-400" : "text-slate-600"}>
            {s.last_heartbeat ? timeAgo(s.last_heartbeat) : "—"}
          </div>
        </div>
        <div className="text-center">
          <div className="text-[10px] text-slate-500 mb-0.5">SIGNALS</div>
          <div className="text-white">{s.recent_trades?.length ?? 0}</div>
        </div>
      </div>

      {/* Last signal */}
      {sig && (
        <div
          className="rounded p-2 mb-2"
          style={{ background: "#070d14", border: "1px solid #1e293b" }}
        >
          <div className="flex items-center gap-2 mb-1.5">
            <Zap className="w-3 h-3 text-yellow-400" />
            <span className="text-[10px] text-slate-400">LAST SIGNAL</span>
            <span className="ml-auto text-[10px] text-slate-600">{timeAgo(sig.ts)}</span>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-cyan-400 font-bold">{sig.symbol}</span>
            <span className="text-white">ENTRY {fmt(sig.entry_price)}</span>
            <span className="text-red-400">STOP {fmt(sig.stop_price)}</span>
            <span className="text-green-400">T1 {fmt(sig.t1_price)}</span>
            <span className="text-emerald-400">T2 {fmt(sig.t2_price)}</span>
          </div>
          {sig.atr != null && (
            <div className="text-[10px] text-slate-600 mt-1">
              ATR {fmt(sig.atr)} · Bar {sig.bar_time ? new Date(sig.bar_time).toLocaleDateString() : "—"}
            </div>
          )}
        </div>
      )}

      {/* Recent trades */}
      {s.recent_trades && s.recent_trades.length > 0 && (
        <div className="space-y-0.5">
          <div className="text-[10px] text-slate-600 mb-1">RECENT EVENTS</div>
          {s.recent_trades.slice(0, 4).map((t, i) => (
            <div key={i} className="flex items-center gap-2 text-[10px]">
              <span
                className={`w-12 text-center px-1 rounded font-bold ${
                  t.event === "SIGNAL"
                    ? "text-yellow-400 bg-yellow-900/20"
                    : t.pnl != null && t.pnl > 0
                    ? "text-green-400 bg-green-900/20"
                    : "text-red-400 bg-red-900/20"
                }`}
              >
                {t.event}
              </span>
              <span className="text-cyan-400">{t.symbol}</span>
              {t.pnl != null && (
                <span className={t.pnl >= 0 ? "text-green-400" : "text-red-400"}>
                  {t.pnl >= 0 ? "+" : ""}{fmt(t.pnl, 0)}
                </span>
              )}
              <span className="ml-auto text-slate-600">{timeAgo(t.ts)}</span>
            </div>
          ))}
        </div>
      )}

      {/* Run command hint */}
      {!running && (
        <div className="mt-2 text-[10px] text-slate-600 border-t border-slate-800 pt-2">
          Run: <span className="text-slate-500">.venv\Scripts\python.exe -m system2.executor --paper</span>
        </div>
      )}
    </div>
  );
}
