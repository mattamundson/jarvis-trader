"use client";

import React, { useState, useEffect } from "react";
import { fetchEngine } from "@/lib/api";
import { useMarketSession } from "@/hooks/useMarketSession";
import type { HealthResponse } from "@/lib/api";

interface CommandCenterShellProps {
  health: HealthResponse | undefined;
  refreshInterval: number;
  onKillSwitch?: () => void;
}

export function CommandCenterShell({
  health,
  refreshInterval,
  onKillSwitch,
}: CommandCenterShellProps) {
  const session = useMarketSession();
  const [clock, setClock] = useState<string>("");
  const [killLoading, setKillLoading] = useState(false);

  // Update clock every second
  useEffect(() => {
    function tick() {
      const now = new Date();
      setClock(
        now.toLocaleTimeString("en-US", {
          hour12: false,
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
        })
      );
    }
    tick();
    const id = setInterval(tick, 1_000);
    return () => clearInterval(id);
  }, []);

  async function handleKillSwitch() {
    const confirmed = window.confirm("Activate kill switch? This will halt all trading.");
    if (!confirmed) return;
    setKillLoading(true);
    try {
      await fetchEngine("/safety/kill-switch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ activate: true }),
      });
      onKillSwitch?.();
    } catch (err) {
      console.error("Kill switch failed:", err);
      window.alert("Kill switch request failed. Check engine connection.");
    } finally {
      setKillLoading(false);
    }
  }

  const isReachable = !!health;
  const isHealthy = health?.status === "ok" || health?.status === "healthy";
  const isDegraded = isReachable && !isHealthy;
  const isPaper = health?.paper_mode !== false;
  const killActive = health?.kill_switch_active ?? false;

  return (
    <header className="bg-[#060d1a] border-b border-cyan-900/30 px-4 py-2 flex items-center justify-between gap-4">
      {/* Left: Title + version */}
      <div className="flex items-center gap-3 min-w-0">
        <h1 className="text-sm font-bold tracking-widest whitespace-nowrap bg-gradient-to-r from-cyan-400 to-sky-300 bg-clip-text text-transparent">
          JARVIS TRADER — COMMAND CENTER
        </h1>
        <span className="text-[10px] font-mono px-1.5 py-0.5 rounded border border-cyan-800 text-cyan-600 bg-cyan-950/40 shrink-0">
          v2.7
        </span>
      </div>

      {/* Center: Clock + session */}
      <div className="flex items-center gap-3 absolute left-1/2 -translate-x-1/2">
        <span className="font-mono text-sm text-slate-300 tabular-nums">
          {clock || "—:—:—"}
        </span>
        {session.label && (
          <span
            className={`text-[10px] font-mono px-2 py-0.5 rounded border tracking-wider ${session.badge}`}
          >
            {session.label}
          </span>
        )}
      </div>

      {/* Right: Status badges + kill switch */}
      <div className="flex items-center gap-2 shrink-0">
        {/* Refresh interval indicator */}
        <span className="text-[9px] font-mono text-slate-600 hidden sm:block">
          {refreshInterval / 1000}s
        </span>

        {isPaper && (
          <span className="text-[10px] font-mono px-2 py-0.5 rounded border border-cyan-800 bg-cyan-950/40 text-cyan-400 tracking-wider">
            PAPER
          </span>
        )}

        {isReachable ? (
          <span className="text-[10px] font-mono px-2 py-0.5 rounded border border-emerald-800 bg-emerald-950/40 text-emerald-400 tracking-wider">
            {isDegraded ? "ENGINE DEGRADED" : "ENGINE ONLINE"}
          </span>
        ) : (
          <span className="text-[10px] font-mono px-2 py-0.5 rounded border border-red-800 bg-red-950/40 text-red-400 tracking-wider">
            ENGINE OFFLINE
          </span>
        )}

        {/* Kill Switch button */}
        <button
          onClick={handleKillSwitch}
          disabled={killLoading || killActive}
          aria-label="Activate kill switch to halt all trading"
          className={[
            "text-[10px] font-mono px-3 py-1 rounded border tracking-wider transition-all",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-500",
            killActive
              ? "border-red-500 bg-red-900/60 text-red-300 animate-pulse cursor-not-allowed"
              : "border-red-800 bg-red-950/30 text-red-500 hover:bg-red-900/50 hover:text-red-300 hover:border-red-600",
            killLoading ? "opacity-50 cursor-not-allowed" : "",
          ]
            .filter(Boolean)
            .join(" ")}
        >
          {killActive ? "KILL ACTIVE" : killLoading ? "..." : "KILL SWITCH"}
        </button>
      </div>
    </header>
  );
}
