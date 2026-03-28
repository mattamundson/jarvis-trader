"use client";

import { useCallback } from "react";
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

function fetcher(url: string) {
  return fetchEngine(url);
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

  const onKillSwitchToggle = useCallback(() => {
    mutateSafety();
    mutateHealth();
  }, [mutateSafety, mutateHealth]);

  const engineOnline = !healthErr && !!health;

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
