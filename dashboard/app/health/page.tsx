"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Database,
  RefreshCw,
  Server,
  Shield,
  ShieldOff,
  TrendingUp,
  Wifi,
  WifiOff,
  XCircle,
  Clock,
  BarChart2,
  GitCompare,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { fetchEngine, type ProcessSupervisionHealth } from "@/lib/api";
import { PreFlightWidget } from "@/components/PreFlightWidget";
import { SystemMetricsPanel } from "@/components/SystemMetricsPanel";
import { AlertSummaryWidget } from "@/components/AlertSummaryWidget";
import { WidgetErrorBoundary } from "@/components/WidgetErrorBoundary";
import { ConnectionHealthCard } from "@/components/ConnectionHealthCard";
import { DatabaseStatsCard } from "@/components/DatabaseStatsCard";
import { EngineUptimeCard } from "@/components/EngineUptimeCard";
import { IbGatewayDetailCard } from "@/components/IbGatewayDetailCard";
import { IBGatewayStatus } from "@/components/IBGatewayStatus";
import { SystemLivenessCard } from "@/components/SystemLivenessCard";
import { CacheStatsCard } from "@/components/CacheStatsCard";

// ── Types ─────────────────────────────────────────────────────────────────────

interface SubsystemStatus {
  status: string;
  error?: string;
  // database
  details?: unknown;
  // safety_layer
  kill_switch_active?: boolean;
  kill_switch_reason?: string | null;
  // ib_gateway
  connected?: boolean;
  mode?: string;
  // circuit_breakers
  all_clear?: boolean;
  daily_pnl?: number;
  drawdown_pct?: number;
  // portfolio
  open_positions?: number;
  // pnl_monitor
  source?: string;
  current_balance?: number;
  starting_balance?: number;
}

interface FullHealthResponse {
  overall: string;
  timestamp: string;
  uptime_seconds: number;
  version: string;
  phase: string;
  subsystems: {
    database?: SubsystemStatus;
    safety_layer?: SubsystemStatus;
    ib_gateway?: SubsystemStatus;
    circuit_breakers?: SubsystemStatus;
    portfolio?: SubsystemStatus;
    pnl_monitor?: SubsystemStatus;
    process_supervision?: ProcessSupervisionHealth;
  };
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fetcher<T>(url: string): Promise<T> {
  return fetchEngine<T>(url);
}

function formatUptime(seconds: number): string {
  if (seconds < 60) return `${Math.floor(seconds)}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.floor(seconds % 60)}s`;
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return `${h}h ${m}m`;
}

function formatTimestamp(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString("en-US", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    });
  } catch {
    return iso;
  }
}

// ── Overall status badge ───────────────────────────────────────────────────────

function OverallStatusBadge({ overall }: { overall: string }) {
  const normalized = overall?.toLowerCase() ?? "unknown";

  if (normalized === "healthy") {
    return (
      <div className="flex items-center gap-2 rounded-full bg-bull/15 border border-bull/25 px-4 py-2">
        <CheckCircle2 className="h-5 w-5 text-bull" />
        <span className="text-sm font-bold text-bull tracking-wide">HEALTHY</span>
      </div>
    );
  }

  if (normalized === "kill_switch_active") {
    return (
      <div className="flex items-center gap-2 rounded-full bg-bear/15 border border-bear/25 px-4 py-2">
        <ShieldOff className="h-5 w-5 text-bear" />
        <span className="text-sm font-bold text-bear tracking-wide">KILL SWITCH ACTIVE</span>
      </div>
    );
  }

  if (normalized.startsWith("degraded") || normalized === "circuit_breaker_tripped") {
    return (
      <div className="flex items-center gap-2 rounded-full bg-warn/15 border border-warn/25 px-4 py-2">
        <AlertTriangle className="h-5 w-5 text-warn" />
        <span className="text-sm font-bold text-warn tracking-wide">DEGRADED</span>
      </div>
    );
  }

  if (normalized === "down") {
    return (
      <div className="flex items-center gap-2 rounded-full bg-bear/15 border border-bear/25 px-4 py-2">
        <WifiOff className="h-5 w-5 text-bear" />
        <span className="text-sm font-bold text-bear tracking-wide">SYSTEM DOWN</span>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2 rounded-full bg-muted border border-border px-4 py-2">
      <XCircle className="h-5 w-5 text-muted-foreground" />
      <span className="text-sm font-bold text-muted-foreground tracking-wide">
        {overall?.toUpperCase() ?? "UNKNOWN"}
      </span>
    </div>
  );
}

// ── Subsystem card ─────────────────────────────────────────────────────────────

// Excludes "process_supervision": it has its own richer shape (ProcessSupervisionHealth)
// and is rendered via the dedicated ProcessSupervisionCard below, not this generic loop.
interface SubsystemConfig {
  key: Exclude<keyof FullHealthResponse["subsystems"], "process_supervision">;
  label: string;
  icon: React.ReactNode;
  detail: (s: SubsystemStatus) => string | null;
}

const SUBSYSTEMS: SubsystemConfig[] = [
  {
    key: "database",
    label: "Database (SQLite)",
    icon: <Database className="h-5 w-5" />,
    detail: (s) => {
      if (s.status === "ok") return "Connected";
      if (s.status === "not_initialized") return "Not initialized";
      return s.error ?? null;
    },
  },
  {
    key: "ib_gateway",
    label: "IB Gateway",
    icon: <Wifi className="h-5 w-5" />,
    detail: (s) => {
      if (s.status === "not_configured") return `Mode: ${s.mode ?? "paper_only"}`;
      if (s.connected === true) return "Connected";
      if (s.connected === false) return "Disconnected (paper only)";
      return s.error ?? null;
    },
  },
  {
    key: "safety_layer",
    label: "Safety Layer",
    icon: <Shield className="h-5 w-5" />,
    detail: (s) => {
      if (s.kill_switch_active) {
        return `Kill switch active${s.kill_switch_reason ? `: ${s.kill_switch_reason}` : ""}`;
      }
      if (s.status === "ok") return "Kill switch inactive";
      return s.error ?? null;
    },
  },
  {
    key: "portfolio",
    label: "Portfolio Tracker",
    icon: <TrendingUp className="h-5 w-5" />,
    detail: (s) => {
      if (s.status === "ok") return `${s.open_positions ?? 0} open position${s.open_positions !== 1 ? "s" : ""}`;
      return s.error ?? null;
    },
  },
  {
    key: "pnl_monitor",
    label: "P&L Monitor",
    icon: <BarChart2 className="h-5 w-5" />,
    detail: (s) => {
      if (s.status === "ok") {
        const pnl = s.daily_pnl ?? 0;
        const sign = pnl >= 0 ? "+" : "";
        return `Daily P&L: ${sign}$${pnl.toFixed(2)} | Source: ${s.source ?? "memory"}`;
      }
      return s.error ?? null;
    },
  },
  {
    key: "circuit_breakers",
    label: "Circuit Breakers",
    icon: <Server className="h-5 w-5" />,
    detail: (s) => {
      if (s.status === "not_available") return "Not available";
      if (s.all_clear === true) return "All clear";
      if (s.all_clear === false) return "Circuit breaker tripped";
      return s.error ?? null;
    },
  },
];

function subsystemIsHealthy(key: string, s: SubsystemStatus | undefined): "healthy" | "warn" | "error" | "unknown" {
  if (!s) return "unknown";

  // Special case: ib_gateway not_configured is expected/normal
  if (key === "ib_gateway" && s.status === "not_configured") return "warn";
  if (key === "ib_gateway" && s.connected === false) return "warn";

  // Kill switch = bear/error
  if (key === "safety_layer" && s.kill_switch_active) return "error";

  // Circuit breakers tripped = warn
  if (key === "circuit_breakers" && s.all_clear === false) return "warn";

  if (s.status === "ok" || s.status === "healthy") return "healthy";
  if (s.status === "not_initialized") return "warn";
  if (s.status === "error") return "error";

  return "unknown";
}

function SubsystemCard({
  config,
  data,
}: {
  config: SubsystemConfig;
  data: SubsystemStatus | undefined;
}) {
  const health = subsystemIsHealthy(config.key, data);

  const borderClass =
    health === "healthy"
      ? "border-bull/20 bg-card"
      : health === "warn"
      ? "border-warn/30 bg-warn/5"
      : health === "error"
      ? "border-bear/30 bg-bear/5"
      : "border-border bg-card";

  const iconClass =
    health === "healthy"
      ? "text-bull bg-bull/10"
      : health === "warn"
      ? "text-warn bg-warn/10"
      : health === "error"
      ? "text-bear bg-bear/10"
      : "text-muted-foreground bg-muted";

  const statusIcon =
    health === "healthy" ? (
      <CheckCircle2 className="h-4 w-4 text-bull" />
    ) : health === "warn" ? (
      <AlertTriangle className="h-4 w-4 text-warn" />
    ) : health === "error" ? (
      <XCircle className="h-4 w-4 text-bear" />
    ) : (
      <Clock className="h-4 w-4 text-muted-foreground" />
    );

  const statusLabel =
    health === "healthy"
      ? "Healthy"
      : health === "warn"
      ? "Warning"
      : health === "error"
      ? "Error"
      : "Unknown";

  const statusVariant: "bull" | "warn" | "bear" | "neutral" =
    health === "healthy"
      ? "bull"
      : health === "warn"
      ? "warn"
      : health === "error"
      ? "bear"
      : "neutral";

  const detail = data ? config.detail(data) : null;

  return (
    <div className={`rounded-xl border p-4 space-y-3 ${borderClass}`}>
      {/* Header row */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2.5">
          <div className={`flex h-9 w-9 items-center justify-center rounded-lg ${iconClass}`}>
            {config.icon}
          </div>
          <div>
            <p className="text-sm font-semibold text-foreground">{config.label}</p>
            {detail && (
              <p className="text-xs text-muted-foreground mt-0.5 max-w-[240px] truncate">
                {detail}
              </p>
            )}
          </div>
        </div>
        <Badge variant={statusVariant}>
          <span className="flex items-center gap-1">
            {statusIcon}
            {statusLabel}
          </span>
        </Badge>
      </div>

      {/* Error message (if any) */}
      {data?.error && (
        <div className="rounded-lg bg-bear/10 border border-bear/20 px-3 py-2">
          <p className="text-xs text-bear font-mono break-all">{data.error}</p>
        </div>
      )}
    </div>
  );
}

// ── Process supervision card (PRB-24) ────────────────────────────────────────
//
// pm2 jlist (what pm2 BELIEVES it supervises) and a live TCP port + PID probe
// (what is ACTUALLY listening) can independently disagree — an orphan process
// serving a port pm2 thinks is dead, or vice versa. This is the specific
// failure shape behind the 2026-07-28/29 incidents where nothing surfaced a
// mismatch as a finding and a human had to check pm2/health/the port
// side-by-side to notice. Rendered as its own card (not folded into the
// generic SUBSYSTEMS grid above) because a mismatch needs the per-app
// pm2-vs-actual detail, not just a one-line status.
function ProcessSupervisionCard({ data }: { data: ProcessSupervisionHealth | undefined }) {
  const status = data?.status; // ok | mismatch | unavailable | error
  const details = data?.details;
  const apps = details?.apps ?? {};
  const appEntries = Object.entries(apps);
  const hasMismatch = status === "mismatch";

  const borderClass = hasMismatch
    ? "border-bear/40 bg-bear/5"
    : status === "ok"
    ? "border-bull/20 bg-card"
    : "border-border bg-card";

  const badgeVariant: "bull" | "warn" | "bear" | "neutral" =
    status === "ok" ? "bull" : hasMismatch ? "bear" : "neutral";

  const badgeLabel =
    status === "ok"
      ? "In sync"
      : hasMismatch
      ? "MISMATCH"
      : status === "unavailable"
      ? "Unavailable"
      : status === "error"
      ? "Error"
      : "Unknown";

  const badgeIcon = hasMismatch ? (
    <AlertTriangle className="h-4 w-4 text-bear" />
  ) : status === "ok" ? (
    <CheckCircle2 className="h-4 w-4 text-bull" />
  ) : (
    <Clock className="h-4 w-4 text-muted-foreground" />
  );

  return (
    <div className={`rounded-xl border p-4 space-y-3 ${borderClass}`}>
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2.5">
          <div
            className={`flex h-9 w-9 items-center justify-center rounded-lg ${
              hasMismatch ? "text-bear bg-bear/10" : status === "ok" ? "text-bull bg-bull/10" : "text-muted-foreground bg-muted"
            }`}
          >
            <GitCompare className="h-5 w-5" />
          </div>
          <div>
            <p className="text-sm font-semibold text-foreground">Process Supervision (pm2 vs reality)</p>
            <p className="text-xs text-muted-foreground mt-0.5">
              {status === "unavailable"
                ? (data?.error ?? details?.error ?? "pm2 unreachable")
                : hasMismatch
                ? "pm2's belief disagrees with the actual TCP port owner"
                : status === "ok"
                ? "pm2 and live port/PID state agree"
                : "No data yet"}
            </p>
          </div>
        </div>
        <Badge variant={badgeVariant}>
          <span className="flex items-center gap-1">
            {badgeIcon}
            {badgeLabel}
          </span>
        </Badge>
      </div>

      {appEntries.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 pt-1">
          {appEntries.map(([name, app]) => {
            const mismatched = !!app.mismatch_reason;
            return (
              <div
                key={name}
                className={`rounded-lg border px-3 py-2 space-y-1 ${
                  mismatched ? "border-bear/30 bg-bear/10" : "border-border bg-muted/30"
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="text-xs font-mono font-semibold text-foreground">{name}</span>
                  <span className="text-[10px] font-mono text-muted-foreground">:{app.port}</span>
                </div>
                <p className="text-[11px] text-muted-foreground">
                  pm2: <span className="font-mono">{app.pm2_status ?? "not tracked"}</span>
                  {app.pm2_pid != null && <span className="font-mono"> (pid {app.pm2_pid})</span>}
                </p>
                <p className="text-[11px] text-muted-foreground">
                  port: <span className="font-mono">{app.port_alive ? "alive" : "dead"}</span>
                  {app.actual_pid != null && <span className="font-mono"> (pid {app.actual_pid})</span>}
                </p>
                {mismatched && (
                  <p className="text-[11px] text-bear font-mono break-words">{app.mismatch_reason}</p>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────────

export default function HealthPage() {
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const {
    data,
    error,
    isLoading,
    mutate,
  } = useSWR<FullHealthResponse>("/health/full", fetcher, {
    refreshInterval: 15_000,
    onSuccess: () => setLastUpdated(new Date()),
  });

  // Track time since last update
  const [secondsSince, setSecondsSince] = useState(0);
  useEffect(() => {
    const interval = setInterval(() => {
      if (lastUpdated) {
        setSecondsSince(Math.floor((Date.now() - lastUpdated.getTime()) / 1000));
      }
    }, 1000);
    return () => clearInterval(interval);
  }, [lastUpdated]);

  const handleRefresh = useCallback(() => {
    mutate();
  }, [mutate]);

  const overall = data?.overall ?? (error ? "down" : "loading");
  const subsystems = data?.subsystems ?? {};

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="sticky top-0 z-50 border-b border-border bg-background/95 backdrop-blur">
        <div className="mx-auto max-w-[1600px] 2xl:max-w-[2000px] flex items-center justify-between px-6 py-3">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent/10">
              <Activity className="h-5 w-5 text-accent" />
            </div>
            <div>
              <h1 className="font-bold text-foreground tracking-tight">JARVIS TRADER</h1>
              <p className="text-xs text-muted-foreground">IBKR Futures + Schwab Options</p>
            </div>
            <nav className="hidden lg:flex items-center gap-4 ml-6">
              <Link href="/" className="text-xs text-muted-foreground hover:text-foreground transition-colors">
                Dashboard
              </Link>
              <Link href="/analysis" className="text-xs text-muted-foreground hover:text-foreground transition-colors">
                Analysis
              </Link>
              <Link href="/backtest" className="text-xs text-muted-foreground hover:text-foreground transition-colors">
                Backtest
              </Link>
              <Link href="/performance" className="text-xs text-muted-foreground hover:text-foreground transition-colors">
                Performance
              </Link>
              <Link href="/validation" className="text-xs text-muted-foreground hover:text-foreground transition-colors">
                Validation
              </Link>
              <Link href="/journal" className="text-xs text-muted-foreground hover:text-foreground transition-colors">
                Journal
              </Link>
              <Link href="/paper" className="text-xs text-muted-foreground hover:text-foreground transition-colors">
                Paper Trading
              </Link>
              <Link href="/watchlist" className="text-xs text-muted-foreground hover:text-foreground transition-colors">
                Watchlist
              </Link>
              <Link href="/scorecard" className="text-xs text-muted-foreground hover:text-foreground transition-colors">
                Scorecard
              </Link>
              <Link href="/settings" className="text-xs text-muted-foreground hover:text-foreground transition-colors">
                Settings
              </Link>
              <Link href="/health" className="text-xs text-foreground font-semibold border-b border-accent pb-0.5">
                Health
              </Link>
            </nav>
          </div>

          <div className="flex items-center gap-3">
            {lastUpdated && (
              <span className="text-xs text-muted-foreground">
                Updated {secondsSince}s ago
              </span>
            )}
            <button
              onClick={handleRefresh}
              className="flex items-center gap-1.5 rounded-lg border border-border bg-card px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${isLoading ? "animate-spin" : ""}`} />
              Refresh
            </button>
          </div>
        </div>
      </header>

      {/* Page content */}
      <main className="mx-auto max-w-[1600px] 2xl:max-w-[2000px] px-6 py-6 space-y-6">
        {/* Both-systems liveness (C5) — engine + data + watchdog + LLM at a glance */}
        <WidgetErrorBoundary name="System Liveness">
          <SystemLivenessCard />
        </WidgetErrorBoundary>

        {/* Connection health — most critical info at the top */}
        <WidgetErrorBoundary name="Connection Health">
          <ConnectionHealthCard />
        </WidgetErrorBoundary>

        {/* Engine uptime + /health summary */}
        <WidgetErrorBoundary name="Engine Uptime">
          <EngineUptimeCard />
        </WidgetErrorBoundary>

        {/* IB Gateway detail — connection status, account, mode, latency */}
        <WidgetErrorBoundary name="IB Gateway Detail">
          <IbGatewayDetailCard />
        </WidgetErrorBoundary>

        {/*
          IB Gateway status (Phase 6.5, D3) — was built, never mounted anywhere.
          Distinct from IbGatewayDetailCard above: that one is read-only detail,
          this one adds a "Connect" action button. Boundary (D3): the button
          only hits POST /data/reconnect, the engine's idempotent IBKR data-leg
          reconnect (see GT-38 comment in the component) — it does NOT and
          cannot start the IB Gateway OS process itself. A FastAPI handler has
          no way to launch a desktop app on Amo's machine; that step stays
          manual (see docs/runbooks/IB_RECONNECT_AND_HEALTH.md). No
          /ib/connect engine endpoint exists or should be built for this.
        */}
        <WidgetErrorBoundary name="IB Gateway Status">
          <IBGatewayStatus />
        </WidgetErrorBoundary>

        {/* Page title + overall status */}
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="flex items-center gap-3">
            <Server className="h-5 w-5 text-muted-foreground" />
            <div>
              <h2 className="text-lg font-bold text-foreground">System Health</h2>
              <p className="text-xs text-muted-foreground">
                6-subsystem health check — auto-refreshes every 15 seconds
              </p>
            </div>
          </div>
          <OverallStatusBadge overall={overall} />
        </div>

        {/* Meta row: version, uptime, phase, timestamp */}
        {data && (
          <div className="flex flex-wrap gap-3">
            {data.version && (
              <div className="flex items-center gap-1.5 rounded-lg border border-border bg-card px-3 py-1.5">
                <span className="text-[11px] text-muted-foreground">Version</span>
                <span className="text-[11px] font-mono font-semibold text-foreground">{data.version}</span>
              </div>
            )}
            {data.phase && (
              <div className="flex items-center gap-1.5 rounded-lg border border-border bg-card px-3 py-1.5">
                <span className="text-[11px] text-muted-foreground">Phase</span>
                <span className="text-[11px] font-mono font-semibold text-foreground">
                  {data.phase.replace(/_/g, " ")}
                </span>
              </div>
            )}
            {data.uptime_seconds !== undefined && (
              <div className="flex items-center gap-1.5 rounded-lg border border-border bg-card px-3 py-1.5">
                <span className="text-[11px] text-muted-foreground">Uptime</span>
                <span className="text-[11px] font-mono font-semibold text-foreground">
                  {formatUptime(data.uptime_seconds)}
                </span>
              </div>
            )}
            {data.timestamp && (
              <div className="flex items-center gap-1.5 rounded-lg border border-border bg-card px-3 py-1.5">
                <Clock className="h-3 w-3 text-muted-foreground" />
                <span className="text-[11px] text-muted-foreground">Last check</span>
                <span className="text-[11px] font-mono font-semibold text-foreground">
                  {formatTimestamp(data.timestamp)}
                </span>
              </div>
            )}
          </div>
        )}

        {/* Loading state */}
        {isLoading && !data && (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="rounded-xl border border-border bg-card p-4 animate-pulse space-y-3">
                <div className="flex items-center gap-2.5">
                  <div className="h-9 w-9 rounded-lg bg-muted" />
                  <div className="space-y-1.5 flex-1">
                    <div className="h-3.5 w-32 rounded bg-muted" />
                    <div className="h-3 w-24 rounded bg-muted" />
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Error state — engine unreachable */}
        {error && !isLoading && (
          <div className="rounded-xl border border-bear/30 bg-bear/5 p-6 text-center space-y-2">
            <XCircle className="h-8 w-8 text-bear mx-auto" />
            <p className="text-sm font-semibold text-bear">Engine unreachable</p>
            <p className="text-xs text-muted-foreground">
              Could not fetch /health/full — verify the engine is running and the dashboard proxy can reach it.
            </p>
          </div>
        )}

        {/* Pre-Flight Widget */}
        <WidgetErrorBoundary name="Pre-Flight">
          <PreFlightWidget />
        </WidgetErrorBoundary>

        {/* Subsystem grid */}
        {data && (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {SUBSYSTEMS.map((cfg) => (
              <SubsystemCard
                key={cfg.key}
                config={cfg}
                data={subsystems[cfg.key]}
              />
            ))}
          </div>
        )}

        {/* Process supervision (PRB-24) — pm2 belief vs TCP-port/PID reality */}
        {data && <ProcessSupervisionCard data={subsystems.process_supervision} />}

        {/* System Metrics Panel — DB record counts + engine meta */}
        <WidgetErrorBoundary name="System Metrics">
          <SystemMetricsPanel />
        </WidgetErrorBoundary>

        {/* Alert Summary Widget — recent alert log + stats */}
        <WidgetErrorBoundary name="Alert Summary">
          <AlertSummaryWidget />
        </WidgetErrorBoundary>

        {/* Database Statistics — record counts across trades, decisions, alerts */}
        <WidgetErrorBoundary name="Database Stats">
          <DatabaseStatsCard />
        </WidgetErrorBoundary>

        {/* Engine signal-cache hit/miss stats — read-only */}
        <WidgetErrorBoundary name="Cache Stats">
          <CacheStatsCard />
        </WidgetErrorBoundary>

        {/* Auto-refresh notice */}
        <p className="text-xs text-muted-foreground text-center pb-2">
          Auto-refreshes every 15 seconds. Use the Refresh button for an immediate update.
        </p>
      </main>
    </div>
  );
}
