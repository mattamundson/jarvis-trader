"use client";

import React, { useCallback, useState } from "react";
import useSWR from "swr";
import { Activity, AlertTriangle, RefreshCw, Wifi, WifiOff } from "lucide-react";
import { KillSwitch } from "@/components/KillSwitch";
import { PositionsPanel } from "@/components/PositionsPanel";
import { AgentFeed } from "@/components/AgentFeed";
import { SentimentPanel } from "@/components/SentimentPanel";
import { PerformancePanel } from "@/components/PerformancePanel";
import { WatchlistBar } from "@/components/WatchlistBar";
import { Badge } from "@/components/ui/badge";
import { fetchEngine } from "@/lib/api";
import type {
  HealthResponse,
  SafetyStatus,
  PortfolioSnapshot,
  AgentDecision,
  SentimentData,
  WatchlistItem,
} from "@/lib/api";

const REFRESH_MS = 5000;

function fetcher<T = unknown>(url: string): Promise<T> {
  return fetchEngine<T>(url);
}

export default function DashboardPage() {
  const { data: health, error: healthErr, mutate: mutateHealth } = useSWR<HealthResponse>(
    "/health",
    fetcher,
    { refreshInterval: REFRESH_MS }
  );

  const { data: safety, mutate: mutateSafety } = useSWR<SafetyStatus>(
    "/safety/status",
    fetcher,
    { refreshInterval: REFRESH_MS }
  );

  const { data: portfolio } = useSWR<PortfolioSnapshot>(
    "/portfolio",
    fetcher,
    { refreshInterval: REFRESH_MS }
  );

  const { data: agentDecisions } = useSWR<AgentDecision[]>(
    "/decisions/recent",
    fetcher,
    { refreshInterval: REFRESH_MS }
  );

  const { data: sentiments } = useSWR<SentimentData[]>(
    "/sentiment/recent",
    fetcher,
    { refreshInterval: REFRESH_MS * 6 } // 30s
  );

  const { data: watchlist } = useSWR<WatchlistItem[]>(
    "/watchlist",
    fetcher,
    { refreshInterval: REFRESH_MS * 2 }
  );

  const engineOnline = !healthErr && !!health;

  const [analysisSymbol, setAnalysisSymbol] = React.useState("SPY");
  const [isRunning, setIsRunning] = React.useState(false);
  const [lastResult, setLastResult] = React.useState<Record<string, unknown> | null>(null);

  const runAnalysis = useCallback(async () => {
    if (!engineOnline || isRunning) return;
    setIsRunning(true);
    try {
      const res = await fetchEngine("/pipeline/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbol: analysisSymbol, is_futures: false }),
      });
      setLastResult(res as Record<string, unknown>);
    } catch (e) {
      console.error("Pipeline error:", e);
    } finally {
      setIsRunning(false);
    }
  }, [engineOnline, isRunning, analysisSymbol]);

  const onKillSwitchToggle = useCallback(() => {
    mutateSafety();
    mutateHealth();
  }, [mutateSafety, mutateHealth]);

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="sticky top-0 z-50 border-b border-border bg-background/95 backdrop-blur">
        <div className="mx-auto max-w-[1600px] flex items-center justify-between px-6 py-3">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent/10">
              <Activity className="h-5 w-5 text-accent" />
            </div>
            <div>
              <h1 className="font-bold text-foreground tracking-tight">
                JARVIS TRADER
              </h1>
              <p className="text-xs text-muted-foreground">
                IBKR Futures + Schwab Options
              </p>
            </div>
            <nav className="hidden lg:flex items-center gap-4 ml-6">
              <a href="/analysis" className="text-xs text-muted-foreground hover:text-foreground transition-colors">
                Analysis
              </a>
            </nav>
          </div>

          <div className="flex items-center gap-3">
            {/* Connection status */}
            {engineOnline ? (
              <div className="flex items-center gap-1.5 text-xs text-bull">
                <Wifi className="h-3.5 w-3.5" />
                <span>Engine connected</span>
                {health?.ibkr_connected && <Badge variant="info">IBKR</Badge>}
                {health?.schwab_connected && <Badge variant="info">Schwab</Badge>}
              </div>
            ) : (
              <div className="flex items-center gap-1.5 text-xs text-bear">
                <WifiOff className="h-3.5 w-3.5" />
                <span>Engine offline</span>
              </div>
            )}

            {/* Mode badges */}
            {health?.paper_mode && <Badge variant="warn">PAPER MODE</Badge>}
            {health?.live_trading && <Badge variant="bull">LIVE</Badge>}
            {health?.kill_switch_active && (
              <Badge variant="bear">
                <AlertTriangle className="mr-1 h-3 w-3" />
                KILL SWITCH
              </Badge>
            )}

            <RefreshCw className="h-3.5 w-3.5 text-muted-foreground animate-spin opacity-40" />
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1600px] px-6 py-4 space-y-4">
        {/* Watchlist ticker bar */}
        <WatchlistBar items={watchlist ?? []} />

        {/* Main grid */}
        <div className="grid grid-cols-12 gap-4">
          {/* Left column — positions + performance */}
          <div className="col-span-12 lg:col-span-3 space-y-4">
            <PositionsPanel
              positions={portfolio?.positions ?? []}
              totalEquity={portfolio?.total_equity ?? 0}
              dailyPnl={portfolio?.daily_pnl ?? 0}
              unrealizedPnl={portfolio?.unrealized_pnl ?? 0}
            />
            <PerformancePanel
              metrics={null}
              equityCurve={[]}
            />
          </div>

          {/* Center column — agent activity feed */}
          <div className="col-span-12 lg:col-span-6">
            <AgentFeed decisions={agentDecisions ?? []} />
          </div>

          {/* Right column — safety + sentiment */}
          <div className="col-span-12 lg:col-span-3 space-y-4">
            <KillSwitch
              isActive={safety?.kill_switch_active ?? false}
              reason={safety?.kill_switch_reason}
              onToggle={onKillSwitchToggle}
            />

            {/* Safety metrics */}
            {safety && (
              <div className="rounded-xl border border-border bg-card p-4 space-y-2">
                <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3">
                  Risk Monitor
                </p>
                <RiskRow
                  label="Daily P&L"
                  value={`$${safety.daily_pnl.toFixed(0)}`}
                  limit={`limit: $${Math.abs(safety.max_daily_loss).toFixed(0)}`}
                  pct={Math.abs(safety.daily_pnl) / Math.abs(safety.max_daily_loss || 1)}
                  danger={safety.daily_pnl < safety.max_daily_loss}
                />
                <RiskRow
                  label="Drawdown"
                  value={`${(safety.current_drawdown * 100).toFixed(1)}%`}
                  limit="limit: 10%"
                  pct={safety.current_drawdown / 0.10}
                  danger={safety.current_drawdown > 0.08}
                />
                <RiskRow
                  label="Orders Today"
                  value={String(safety.orders_today)}
                  limit="limit: 50"
                  pct={safety.orders_today / 50}
                  danger={safety.orders_today > 40}
                />
              </div>
            )}

            <SentimentPanel sentiments={sentiments ?? []} />

            {/* Run Analysis */}
            <div className="rounded-xl border border-border bg-card p-4 space-y-3">
              <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Run Analysis
              </p>
              <div className="flex gap-2">
                <input
                  className="flex-1 rounded-lg border border-border bg-background px-3 py-1.5 text-sm font-mono uppercase focus:outline-none focus:ring-1 focus:ring-accent"
                  value={analysisSymbol}
                  onChange={(e) => setAnalysisSymbol(e.target.value.toUpperCase())}
                  placeholder="SPY"
                  maxLength={10}
                />
                <button
                  onClick={runAnalysis}
                  disabled={!engineOnline || isRunning}
                  className="rounded-lg bg-accent/20 px-3 py-1.5 text-xs font-semibold text-accent hover:bg-accent/30 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  {isRunning ? "Running…" : "Analyze"}
                </button>
              </div>
              {lastResult && (
                <div className="rounded-lg bg-muted/50 p-2 text-xs space-y-1">
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Action</span>
                    <span className={`font-bold uppercase ${
                      String(lastResult.final_action) === "buy" ? "text-bull" :
                      String(lastResult.final_action) === "sell" ? "text-bear" : "text-muted-foreground"
                    }`}>{String(lastResult.final_action ?? "—")}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Confidence</span>
                    <span className="tabular-nums">{((Number(lastResult.confidence) || 0) * 100).toFixed(0)}%</span>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}

function RiskRow({
  label,
  value,
  limit,
  pct,
  danger,
}: {
  label: string;
  value: string;
  limit: string;
  pct: number;
  danger: boolean;
}) {
  const clampedPct = Math.min(1, Math.max(0, pct));
  const barColor = danger ? "bg-bear" : clampedPct > 0.7 ? "bg-warn" : "bg-bull";

  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs">
        <span className="text-muted-foreground">{label}</span>
        <div className="flex items-center gap-2">
          <span className="text-muted-foreground/60">{limit}</span>
          <span className={`tabular-nums font-medium ${danger ? "text-bear" : "text-foreground"}`}>
            {value}
          </span>
        </div>
      </div>
      <div className="h-1 w-full rounded-full bg-muted overflow-hidden">
        <div
          className={`h-full rounded-full transition-all ${barColor}`}
          style={{ width: `${clampedPct * 100}%` }}
        />
      </div>
    </div>
  );
}
