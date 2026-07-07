"use client";

import React from "react";
import type { SWRResponse } from "swr";
import {
  Activity,
  Clock,
  CheckCircle,
  RefreshCw,
  Wifi,
  WifiOff,
  Cpu,
  Database,
  Shield,
  Settings,
  TrendingUp,
  Zap,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

// ── Local types (mirrors command-center page) ─────────────────────────────

interface HealthData {
  status: string;
  kill_switch_active: boolean;
  uptime_seconds: number;
  ibkr_connected: boolean;
  ibkr_execution_connected?: boolean | null;
  ibkr_data_connected?: boolean | null;
  paper_trading?: boolean;
  version?: string;
}

interface SafetyData {
  daily_pnl: number;
  equity_peak: number;
  drawdown_pct: number;
  orders_last_minute: number;
  consecutive_losses?: number;
  kill_switch_active?: boolean;
}

interface SchedulerData {
  running: boolean;
  jobs?: { name: string; last_run: string | null; next_run: string | null; running: boolean; interval?: string }[];
  total_decisions_logged: number;
  last_scan?: string;
  next_scan?: string;
}

interface MacroData {
  vix?: number;
  vix_regime?: string;
  regime?: string;
  timestamp?: string;
}

interface SessionInfo {
  name?: string;
  label?: string;
  color: string;
  badge: string;
  isActive: boolean;
  description?: string;
  start?: string;
  end?: string;
}

export interface CommandCenterData {
  session: SessionInfo;
  health: SWRResponse<HealthData>;
  safety: SWRResponse<SafetyData>;
  portfolio: SWRResponse<unknown>;
  decisions: SWRResponse<unknown[]>;
  scheduler: SWRResponse<SchedulerData>;
  macro: SWRResponse<MacroData>;
  trades: SWRResponse<unknown[]>;
  refreshInterval: number;
}

// ── Helpers ───────────────────────────────────────────────────────────────

function fmtUptime(s: number): string {
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  return d > 0 ? `${d}d ${h}h ${m}m` : `${h}h ${m}m`;
}

function fmtTime(ts: string | null | undefined): string {
  if (!ts) return "—";
  try {
    return new Date(ts).toLocaleTimeString("en-US", {
      hour12: false,
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return "—";
  }
}

// ── OPTIONS FILES ─────────────────────────────────────────────────────────

const OPTIONS_FILES = [
  "greeks_monitor.py",
  "strategy_executor.py",
  "chain_fetcher.py",
  "premium_calculator.py",
  "position_manager.py",
] as const;

const OPTIONS_STRATEGIES = [
  "Covered Calls",
  "Credit Spreads",
  "Iron Condors",
  "Protective Puts",
  "Straddles",
  "Strangles",
  "Ratio Spreads",
] as const;

// ── SCHEDULER STATUS CARD ─────────────────────────────────────────────────

function SchedulerCard({ scheduler }: { scheduler: SWRResponse<SchedulerData> }) {
  const data = scheduler.data;

  return (
    <Card className="bg-slate-900/60 border border-cyan-900/50 h-full">
      <CardHeader className="pb-2 pt-3 px-4">
        <CardTitle className="text-xs font-mono text-cyan-400 tracking-widest flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <Clock className="w-3 h-3" />
            SCHEDULER STATUS
          </div>
          {data ? (
            <Badge
              className={cn(
                "text-xs font-mono py-0 px-2 border",
                data.running
                  ? "bg-green-950 text-green-300 border-green-700"
                  : "bg-amber-950 text-amber-300 border-amber-700"
              )}
            >
              {data.running ? "RUNNING" : "IDLE"}
            </Badge>
          ) : null}
        </CardTitle>
      </CardHeader>
      <CardContent className="px-4 pb-4 space-y-3">
        {!data ? (
          <p className="text-xs text-slate-500 font-mono italic">No scheduler data</p>
        ) : (
          <>
            {/* Key metrics */}
            <div className="space-y-1.5">
              <div className="flex justify-between items-baseline">
                <span className="text-xs text-slate-500 font-mono">Total Decisions Logged</span>
                <span className="font-mono text-sm text-white font-bold">
                  {data.total_decisions_logged ?? "—"}
                </span>
              </div>
              <div className="flex justify-between items-baseline">
                <span className="text-xs text-slate-500 font-mono">Last Scan</span>
                <span className="font-mono text-xs text-slate-300">
                  {fmtTime(data.last_scan)}
                </span>
              </div>
              <div className="flex justify-between items-baseline">
                <span className="text-xs text-slate-500 font-mono">Next Scan</span>
                <span className="font-mono text-xs text-cyan-300">
                  {fmtTime(data.next_scan)}
                </span>
              </div>
            </div>

            {/* Jobs list */}
            {data.jobs && data.jobs.length > 0 ? (
              <div className="border-t border-slate-800 pt-3">
                <p className="text-xs text-slate-600 font-mono uppercase tracking-wider mb-2">
                  Scheduled Jobs
                </p>
                <div className="space-y-2">
                  {data.jobs.map((job) => (
                    <div
                      key={job.name}
                      className="bg-slate-800/50 rounded px-2.5 py-1.5 space-y-1"
                    >
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-1.5">
                          <span
                            className={cn(
                              "w-1.5 h-1.5 rounded-full flex-shrink-0",
                              job.running ? "bg-green-400 animate-pulse" : "bg-slate-600"
                            )}
                          />
                          <span className="font-mono text-xs text-white font-medium truncate max-w-[120px]">
                            {job.name}
                          </span>
                        </div>
                        {job.interval && (
                          <Badge className="text-xs font-mono py-0 px-1.5 bg-slate-700 text-slate-400 border-slate-600">
                            {job.interval}
                          </Badge>
                        )}
                      </div>
                      <div className="flex justify-between text-xs text-slate-500 font-mono pl-3">
                        <span>Last: {fmtTime(job.last_run) === "—" ? "Never" : fmtTime(job.last_run)}</span>
                        <span>Next: {fmtTime(job.next_run)}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div className="border-t border-slate-800 pt-3">
                <p className="text-xs text-slate-500 font-mono italic">No jobs registered</p>
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}

// ── OPTIONS ENGINE CARD ───────────────────────────────────────────────────

function OptionsEngineCard({ macro }: { macro: SWRResponse<MacroData> }) {
  const macroData = macro.data;

  return (
    <Card className="bg-slate-900/60 border border-cyan-900/50 h-full">
      <CardHeader className="pb-2 pt-3 px-4">
        <CardTitle className="text-xs font-mono text-cyan-400 tracking-widest flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <TrendingUp className="w-3 h-3" />
            OPTIONS ENGINE
          </div>
          <Badge className="text-xs font-mono py-0 px-2 border bg-amber-950 text-amber-300 border-amber-700">
            NOT ACTIVE
          </Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="px-4 pb-4 space-y-3">
        {/* Module list */}
        <div>
          <p className="text-xs text-slate-600 font-mono uppercase tracking-wider mb-2">
            Modules Built
          </p>
          <div className="space-y-1">
            {OPTIONS_FILES.map((file) => (
              <div key={file} className="flex items-center justify-between">
                <div className="flex items-center gap-1.5">
                  <CheckCircle className="w-3 h-3 text-green-400 flex-shrink-0" />
                  <span className="font-mono text-xs text-slate-300">{file}</span>
                </div>
                <Badge className="text-xs font-mono py-0 px-1.5 bg-green-950 text-green-300 border border-green-800">
                  BUILT
                </Badge>
              </div>
            ))}
          </div>
        </div>

        {/* Strategies */}
        <div className="border-t border-slate-800 pt-3">
          <div className="flex items-center justify-between mb-2">
            <p className="text-xs text-slate-600 font-mono uppercase tracking-wider">
              Strategies
            </p>
            <Badge className="text-xs font-mono py-0 px-2 bg-cyan-950 text-cyan-300 border border-cyan-800">
              7 AVAILABLE
            </Badge>
          </div>
          <div className="flex flex-wrap gap-1">
            {OPTIONS_STRATEGIES.map((s) => (
              <span
                key={s}
                className="text-xs font-mono text-slate-400 bg-slate-800/60 border border-slate-700 rounded px-1.5 py-0.5"
              >
                {s}
              </span>
            ))}
          </div>
        </div>

        {/* IV Proxy from VIX */}
        <div className="border-t border-slate-800 pt-3 space-y-1.5">
          <div className="flex justify-between items-baseline">
            <span className="text-xs text-slate-500 font-mono">IV Proxy (VIX)</span>
            <span className="font-mono text-sm text-white font-bold">
              {macroData?.vix != null ? macroData.vix.toFixed(2) : "—"}
            </span>
          </div>
          <div className="flex justify-between items-baseline">
            <span className="text-xs text-slate-500 font-mono">VIX Regime</span>
            <span className="font-mono text-xs text-cyan-300">
              {macroData?.vix_regime ?? macroData?.regime ?? "—"}
            </span>
          </div>
        </div>

        {/* Footer */}
        <div className="border-t border-slate-800 pt-2.5">
          <p className="text-xs text-slate-600 font-mono italic text-center">
            Awaiting activation — paper trading futures first
          </p>
        </div>
      </CardContent>
    </Card>
  );
}

// ── ENGINE HEALTH CARD ────────────────────────────────────────────────────

function EngineHealthCard({
  health,
}: {
  health: SWRResponse<HealthData>;
}) {
  const data = health.data;
  const isOnline = !!data && !health.error;

  return (
    <Card className="bg-slate-900/60 border border-cyan-900/50 h-full">
      <CardHeader className="pb-2 pt-3 px-4">
        <CardTitle className="text-xs font-mono text-cyan-400 tracking-widest flex items-center gap-1.5">
          <Activity className="w-3 h-3" />
          ENGINE HEALTH
        </CardTitle>
      </CardHeader>
      <CardContent className="px-4 pb-4 space-y-3">
        {/* Large status indicator */}
        <div className="flex items-center justify-center py-3">
          <div className="flex flex-col items-center gap-2">
            <div
              className={cn(
                "w-12 h-12 rounded-full border-2 flex items-center justify-center",
                isOnline
                  ? "border-green-500 bg-green-950/50"
                  : "border-red-500 bg-red-950/50"
              )}
            >
              {isOnline ? (
                <span
                  className={cn(
                    "w-6 h-6 rounded-full bg-green-400",
                    "animate-pulse"
                  )}
                />
              ) : (
                <span className="w-6 h-6 rounded-full bg-red-500" />
              )}
            </div>
            <span
              className={cn(
                "text-sm font-mono font-bold tracking-widest",
                isOnline ? "text-green-400" : "text-red-400"
              )}
            >
              {isOnline ? "ONLINE" : "OFFLINE"}
            </span>
          </div>
        </div>

        {/* Stats */}
        <div className="space-y-1.5">
          <div className="flex justify-between items-baseline">
            <span className="text-xs text-slate-500 font-mono">Uptime</span>
            <span className="font-mono text-xs text-white">
              {data?.uptime_seconds != null ? fmtUptime(data.uptime_seconds) : "—"}
            </span>
          </div>
          <div className="flex justify-between items-center">
            <span className="text-xs text-slate-500 font-mono">IBKR Gateway</span>
            <Badge
              className={cn(
                "text-xs font-mono py-0 px-1.5 border",
                (data?.ibkr_execution_connected ?? data?.ibkr_connected)
                  ? "bg-green-950 text-green-300 border-green-800"
                  : "bg-red-950 text-red-300 border-red-800"
              )}
              title="Reports execution-connector state when /health exposes ibkr_execution_connected; falls back to legacy ibkr_connected (OR of execution + data) on older engines."
            >
              {(data?.ibkr_execution_connected ?? data?.ibkr_connected) ? (
                <><Wifi className="w-2.5 h-2.5 mr-0.5 inline" />CONNECTED</>
              ) : (
                <><WifiOff className="w-2.5 h-2.5 mr-0.5 inline" />DISCONNECTED</>
              )}
            </Badge>
          </div>
          <div className="flex justify-between items-center">
            <span className="text-xs text-slate-500 font-mono">Paper Mode</span>
            <Badge
              className={cn(
                "text-xs font-mono py-0 px-1.5 border",
                data?.paper_trading !== false
                  ? "bg-yellow-950 text-yellow-300 border-yellow-800"
                  : "bg-slate-800 text-slate-400 border-slate-600"
              )}
            >
              {data?.paper_trading !== false ? "ACTIVE" : "INACTIVE"}
            </Badge>
          </div>
          <div className="flex justify-between items-baseline">
            <span className="text-xs text-slate-500 font-mono">Version</span>
            <span className="font-mono text-xs text-slate-300">
              {data?.version ?? "—"}
            </span>
          </div>
          <div className="flex justify-between items-baseline">
            <span className="text-xs text-slate-500 font-mono">Engine Port</span>
            <span className="font-mono text-xs text-cyan-300">8010</span>
          </div>
        </div>

        {/* Refresh button */}
        <div className="border-t border-slate-800 pt-3">
          <Button
            onClick={() => health.mutate?.()}
            className="w-full font-mono text-xs tracking-wider bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-600 hover:border-cyan-700 hover:text-cyan-300 transition-colors"
            size="sm"
          >
            <RefreshCw className="w-3 h-3 mr-1.5" />
            Refresh Health
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

// ── SYSTEM METRICS TABLE ──────────────────────────────────────────────────

function SystemMetricsTable({
  safety,
  refreshInterval,
}: {
  safety: SWRResponse<SafetyData>;
  refreshInterval: number;
}) {
  const safetyData = safety.data;
  const killSwitchActive = safetyData?.kill_switch_active ?? false;

  const rows = [
    { metric: "Engine", value: "FastAPI / Python 3.12", status: "RUNNING", statusClass: "bg-green-950 text-green-300 border-green-800" },
    { metric: "Dashboard", value: "Next.js 15 / React 19", status: "RUNNING", statusClass: "bg-green-950 text-green-300 border-green-800" },
    { metric: "Port: Engine", value: "8010", status: "ACTIVE", statusClass: "bg-cyan-950 text-cyan-300 border-cyan-800" },
    { metric: "Port: Dashboard", value: "3010", status: "ACTIVE", statusClass: "bg-cyan-950 text-cyan-300 border-cyan-800" },
    { metric: "Database", value: "SQLite (paper)", status: "ACTIVE", statusClass: "bg-cyan-950 text-cyan-300 border-cyan-800" },
    { metric: "Paper Mode", value: "ACTIVE", status: "CONFIRMED", statusClass: "bg-yellow-950 text-yellow-300 border-yellow-800" },
    {
      metric: "Kill Switch",
      value: killSwitchActive ? "ARMED" : "DISENGAGED",
      status: killSwitchActive ? "ARMED" : "DISENGAGED",
      statusClass: killSwitchActive
        ? "bg-red-950 text-red-300 border-red-800"
        : "bg-slate-800 text-slate-400 border-slate-600",
    },
    {
      metric: "Auto-Refresh",
      value: `${refreshInterval / 1000}s interval`,
      status: "ACTIVE",
      statusClass: "bg-cyan-950 text-cyan-300 border-cyan-800",
    },
  ];

  return (
    <Card className="bg-slate-900/60 border border-cyan-900/50">
      <CardHeader className="pb-2 pt-3 px-4">
        <CardTitle className="text-xs font-mono text-cyan-400 tracking-widest flex items-center gap-1.5">
          <Database className="w-3 h-3" />
          SYSTEM METRICS
        </CardTitle>
      </CardHeader>
      <CardContent className="px-4 pb-4">
        <div className="overflow-x-auto">
          <table className="w-full text-xs font-mono">
            <thead>
              <tr className="border-b border-slate-800">
                <th className="text-left text-slate-600 uppercase tracking-wider pb-2 pr-4 font-medium">
                  Metric
                </th>
                <th className="text-left text-slate-600 uppercase tracking-wider pb-2 pr-4 font-medium">
                  Value
                </th>
                <th className="text-right text-slate-600 uppercase tracking-wider pb-2 font-medium">
                  Status
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60">
              {rows.map((row) => (
                <tr key={row.metric} className="hover:bg-slate-800/20 transition-colors">
                  <td className="py-2 pr-4 text-slate-400">{row.metric}</td>
                  <td className="py-2 pr-4 text-white">{row.value}</td>
                  <td className="py-2 text-right">
                    <Badge
                      className={cn(
                        "text-xs font-mono py-0 px-1.5 border",
                        row.statusClass
                      )}
                    >
                      {row.status}
                    </Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}

// ── MAIN EXPORT ───────────────────────────────────────────────────────────

export default function SystemsTab({ data }: { data: CommandCenterData }) {
  return (
    <div className="space-y-4">
      {/* 3-column card grid */}
      <div className="grid grid-cols-3 gap-4">
        <SchedulerCard scheduler={data.scheduler} />
        <OptionsEngineCard macro={data.macro} />
        <EngineHealthCard health={data.health} />
      </div>

      {/* Full-width system metrics table */}
      <SystemMetricsTable safety={data.safety} refreshInterval={data.refreshInterval} />
    </div>
  );
}
