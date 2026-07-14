"use client";

import React, { useEffect, useState } from "react";
import {
  fetchPm2Status,
  fetchOpenPositions,
  Pm2StatusResponse,
  OpenPositionsResponse,
} from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Activity, AlertTriangle, CheckCircle, Shield, TrendingUp } from "lucide-react";

const POLL_MS = 30_000;

function formatUptime(ms?: number): string {
  if (!ms) return "—";
  const s = Math.floor((Date.now() - ms) / 1000);
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
}

export const Pm2StabilityWidget: React.FC = () => {
  const [pm2, setPm2] = useState<Pm2StatusResponse | null>(null);
  const [positions, setPositions] = useState<OpenPositionsResponse | null>(null);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    try {
      const [p, pos] = await Promise.all([fetchPm2Status(), fetchOpenPositions()]);
      setPm2(p);
      setPositions(pos);
    } catch {
      // silent — show stale data
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    const t = setInterval(load, POLL_MS);
    return () => clearInterval(t);
  }, []);

  const restartCount = pm2?.restart_count ?? 0;
  const unstable = pm2?.unstable_restarts ?? 0;
  const openCount = positions?.count ?? 0;
  const stpCount =
    positions?.positions.filter((p) => {
      // broker_stp_order_id is stored in strategy_params JSON-encoded in the notes field
      if (!p.notes) return false;
      try {
        const meta = typeof p.notes === "string" ? JSON.parse(p.notes) : p.notes;
        return !!meta?.broker_stp_order_id;
      } catch {
        return false;
      }
    }).length ?? 0;

  const pm2StatusVariant: "bull" | "bear" | "warn" | "neutral" =
    !pm2?.found
      ? "neutral"
      : unstable > 0
      ? "bear"
      : restartCount > 100
      ? "warn"
      : "bull";

  return (
    <Card className="bg-black/40 border-neutral-800 backdrop-blur-md shadow-2xl">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-mono text-neutral-300 flex items-center gap-2">
          <Activity className="w-4 h-4 text-cyan-400" />
          PM2 Stability Monitor
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {loading && (
          <p className="text-xs text-neutral-500 font-mono">Loading...</p>
        )}

        {/* PM2 Process Health */}
        <div className="grid grid-cols-2 gap-2">
          <div className="bg-neutral-900/60 rounded p-2">
            <p className="text-xs text-neutral-500 font-mono mb-1">Process</p>
            <div className="flex items-center gap-1">
              {pm2?.status === "online" ? (
                <CheckCircle className="w-3 h-3 text-green-400" />
              ) : (
                <AlertTriangle className="w-3 h-3 text-red-400" />
              )}
              <Badge variant={pm2StatusVariant} className="text-xs">
                {pm2?.found ? pm2.status ?? "—" : "not found"}
              </Badge>
            </div>
          </div>

          <div className="bg-neutral-900/60 rounded p-2">
            <p className="text-xs text-neutral-500 font-mono mb-1">Uptime</p>
            <p className="text-sm font-mono text-white">{formatUptime(pm2?.uptime_ms)}</p>
          </div>

          <div className="bg-neutral-900/60 rounded p-2">
            <p className="text-xs text-neutral-500 font-mono mb-1">Restarts</p>
            <p
              className={`text-sm font-mono font-bold ${
                restartCount > 100 ? "text-yellow-400" : "text-green-400"
              }`}
            >
              {restartCount}
            </p>
          </div>

          <div className="bg-neutral-900/60 rounded p-2">
            <p className="text-xs text-neutral-500 font-mono mb-1">Unstable</p>
            <p
              className={`text-sm font-mono font-bold ${
                unstable > 0 ? "text-red-400" : "text-green-400"
              }`}
            >
              {unstable}
            </p>
          </div>
        </div>

        {/* Memory + CPU */}
        {pm2?.found && (
          <div className="flex gap-3 text-xs font-mono text-neutral-400">
            <span>
              CPU: <span className="text-white">{pm2.cpu_pct ?? 0}%</span>
            </span>
            <span>
              MEM: <span className="text-white">{pm2.memory_mb ?? 0} MB</span>
            </span>
            <span>
              PID: <span className="text-white">{pm2.pid ?? "—"}</span>
            </span>
          </div>
        )}

        {/* Open Positions + STPs */}
        <div className="border-t border-neutral-800 pt-2">
          <div className="flex items-center justify-between">
            <span className="text-xs font-mono text-neutral-400 flex items-center gap-1">
              <TrendingUp className="w-3 h-3" /> Open Positions
            </span>
            <Badge variant={openCount > 0 ? "info" : "neutral"} className="text-xs">
              {openCount}
            </Badge>
          </div>
          <div className="flex items-center justify-between mt-1">
            <span className="text-xs font-mono text-neutral-400 flex items-center gap-1">
              <Shield className="w-3 h-3" /> Broker STPs
            </span>
            <Badge
              variant={
                openCount > 0 && stpCount < openCount
                  ? "bear"
                  : stpCount > 0
                  ? "bull"
                  : "neutral"
              }
              className="text-xs"
            >
              {stpCount}/{openCount}
            </Badge>
          </div>
        </div>

        {/* OU-1 alert */}
        {unstable > 0 && (
          <div className="bg-red-950/40 border border-red-800 rounded p-2 text-xs font-mono text-red-400">
            OU-1 ALERT: {unstable} unstable restarts detected. Check for elevated orphan PIDs.
          </div>
        )}

        {openCount > 0 && stpCount < openCount && (
          <div className="bg-yellow-950/40 border border-yellow-800 rounded p-2 text-xs font-mono text-yellow-400">
            {openCount - stpCount} position(s) without broker-side STP!
          </div>
        )}
      </CardContent>
    </Card>
  );
};
