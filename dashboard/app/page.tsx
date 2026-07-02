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
import { PaperTradingPanel } from "@/components/PaperTradingPanel";
import { TradeHistory } from "@/components/TradeHistory";
import { DailyPnlPanel } from "@/components/DailyPnlPanel";
import { RegimeDisplay } from "@/components/RegimeDisplay";
import { MTFConfirmationWidget } from "@/components/MTFConfirmationWidget";
import { DualTFWidget } from "@/components/DualTFWidget";
import { SignalHistory } from "@/components/SignalHistory";
import { CircuitBreakerPanel } from "@/components/CircuitBreakerPanel";
import { IBGatewayStatus } from "@/components/IBGatewayStatus";
import { SchwabStatusWidget } from "@/components/SchwabStatusWidget";
import { BrokerPositionsWidget } from "@/components/BrokerPositionsWidget";
import { StrategyParamsPanel } from "@/components/StrategyParamsPanel";
import { SessionTodayWidget } from "@/components/SessionTodayWidget";
import { RollingWFEWidget } from "@/components/RollingWFEWidget";
import { TradeJournalWidget } from "@/components/TradeJournalWidget";
import { EODSummaryWidget } from "@/components/EODSummaryWidget";
import { EventsFeedWidget } from '@/components/EventsFeedWidget';
import UnrealizedPnLWidget from "@/components/UnrealizedPnLWidget";
import { ProactiveValidationWidget } from "@/components/ProactiveValidationWidget";
import { ForwardTestPanel } from "@/components/ForwardTestPanel";
import { ExecutionCockpitWidget } from "@/components/ExecutionCockpitWidget";
import { AlertHistoryWidget } from "@/components/AlertHistoryWidget";
import LiveTradeReasoningWidget from "@/components/LiveTradeReasoningWidget";
import { DiscordIntelligenceWidget } from "@/components/DiscordIntelligenceWidget";
import { BookmarkThemesPanel } from "@/components/BookmarkThemesPanel";
import { BookmarkFeedPanel } from "@/components/BookmarkFeedPanel";
import { StrategyResearchPanel } from "@/components/StrategyResearchPanel";
import { SignalFlowWidget } from "@/components/widgets/SignalFlowWidget";
import { SuperEngineStatusWidget } from "@/components/SuperEngineStatusWidget";
import { EngineHealthWidget } from "@/components/EngineHealthWidget";
import { ConfidenceGauge } from "@/components/ConfidenceGauge";
import { HonestPnlCard } from "@/components/HonestPnlCard";
import { SameDayPnLBadge } from "@/components/SameDayPnLBadge";
import ShadowPerformanceWidget from "@/components/ShadowPerformanceWidget";
import { InstitutionalProfileWidget } from "@/components/InstitutionalProfileWidget";
import { Pm2StabilityWidget } from "@/components/Pm2StabilityWidget";
import { MESSprintGate } from "@/components/MESSprintGate";
import PendingApprovals from "@/components/PendingApprovals";
import { WidgetErrorBoundary } from "@/components/WidgetErrorBoundary";
import { PriceChartPanel } from "@/components/charts/PriceChartPanel";
import type { ChartSymbol, ChartTimeframe } from "@/hooks/useChartData";
import { Badge } from "@/components/ui/badge";
import { fetchEngine, getPendingApprovals } from "@/lib/api";
import type {
  HealthResponse,
  SafetyStatus,
  PortfolioSnapshot,
  AgentDecision,
  SentimentData,
  WatchlistItem,
  MacroSnapshot,
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

  // Macro snapshot for VIX header — poll every 60s (FRED data doesn't change faster)
  const { data: macro } = useSWR<MacroSnapshot>(
    "/macro/snapshot",
    fetcher,
    { refreshInterval: 60_000, shouldRetryOnError: false }
  );

  const engineReachable = !healthErr && !!health;
  const engineHealthy =
    health?.status === "ok" || health?.status === "healthy";
  const engineDegraded = engineReachable && !engineHealthy;

  const { data: pendingApprovals } = useSWR(
    engineReachable ? "pending-approvals-count" : null,
    () => getPendingApprovals(50),
    { refreshInterval: 25_000, shouldRetryOnError: false }
  );
  const pendingCount = pendingApprovals?.count ?? 0;

  const [analysisSymbol, setAnalysisSymbol] = React.useState("SPY");
  const [isRunning, setIsRunning] = React.useState(false);
  const [lastResult, setLastResult] = React.useState<Record<string, unknown> | null>(null);
  // Cockpit live chart — our own real-time futures bars (never TradingView's delayed embed).
  const [chartSymbol, setChartSymbol] = React.useState<ChartSymbol>("MES");
  const [chartTimeframe, setChartTimeframe] = React.useState<ChartTimeframe>("1h");

  const runAnalysis = useCallback(async () => {
    if (!engineReachable || isRunning) return;
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
  }, [engineReachable, isRunning, analysisSymbol]);

  const onKillSwitchToggle = useCallback(() => {
    mutateSafety();
    mutateHealth();
  }, [mutateSafety, mutateHealth]);

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="sticky top-0 z-50 border-b border-border bg-background/95 backdrop-blur">
        <div className="mx-auto max-w-[1920px] 2xl:max-w-[2400px] flex items-center justify-between px-6 2xl:px-10 py-3">
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
            {/* IB Gateway compact status card */}
            <IBGatewayStatus />

            {/* Engine connection status */}
            {engineReachable ? (
              <div className="flex items-center gap-1.5 text-xs text-bull">
                <Wifi className="h-3.5 w-3.5" />
                <span>
                  {engineDegraded ? "Engine connected (degraded)" : "Engine connected"}
                </span>
                {health?.schwab_connected && <Badge variant="info">Schwab</Badge>}
              </div>
            ) : (
              <div className="flex items-center gap-1.5 text-xs text-bear">
                <WifiOff className="h-3.5 w-3.5" />
                <span>Engine offline</span>
              </div>
            )}

            {/* Mode badges */}
            {health?.live_trading && <Badge variant="bull">LIVE</Badge>}
            {health?.paper_mode && <Badge variant="info">PAPER MODE</Badge>}
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

      <main className="mx-auto max-w-[1920px] 2xl:max-w-[2400px] px-6 2xl:px-10 py-4 space-y-4">
        {/* Macro / VIX header bar */}
        <WidgetErrorBoundary name="Macro Bar">
          <MacroBar macro={macro ?? null} />
        </WidgetErrorBoundary>

        {/* Watchlist ticker bar — live price feed */}
        <WidgetErrorBoundary name="Watchlist">
          <WatchlistBar items={watchlist ?? []} />
        </WidgetErrorBoundary>

        {/* EOD Summary — daily P&L and validation gates */}
        <WidgetErrorBoundary name="EOD Summary">
          <EODSummaryWidget />
        </WidgetErrorBoundary>

        {/* Circuit breaker safety panel — safety-critical, shown before trading panels */}
        <WidgetErrorBoundary name="Circuit Breaker">
          <CircuitBreakerPanel />
        </WidgetErrorBoundary>

        {/* Proactive Validation Suite — 8-check MCL + MNQ validation */}
        <WidgetErrorBoundary name="Proactive Validation">
          <ProactiveValidationWidget />
        </WidgetErrorBoundary>

        {/* Forward-Test loop — per-candidate OOS record + graduation verdict
            (honest-edge spine: registry -> forward-test -> graduation) */}
        <WidgetErrorBoundary name="Forward Test">
          <ForwardTestPanel />
        </WidgetErrorBoundary>

        {/* Execution Cockpit — live fills, fidelity, slippage, pending approvals */}
        <WidgetErrorBoundary name="Execution Cockpit">
          <ExecutionCockpitWidget />
        </WidgetErrorBoundary>

        {/* Live market chart — our own real-time futures bars (TradingView's free
            embed delays CME futures, so futures are charted from our data here). */}
        <WidgetErrorBoundary name="Price Chart">
          <PriceChartPanel
            symbol={chartSymbol}
            timeframe={chartTimeframe}
            onSymbolChange={setChartSymbol}
            onTimeframeChange={setChartTimeframe}
            height={360}
          />
        </WidgetErrorBoundary>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {/* Signal Flow — per-instrument STC values and pipeline block stage */}
          <WidgetErrorBoundary name="Signal Flow">
            <SignalFlowWidget />
          </WidgetErrorBoundary>

          {/* Super-Engine Infrastructure Status */}
          <WidgetErrorBoundary name="Super Engine Status">
            <SuperEngineStatusWidget />
          </WidgetErrorBoundary>

          {/* Engine Health — live /health subsystem checks (TV MCP, LLM, IBKR) */}
          <WidgetErrorBoundary name="Engine Health">
            <EngineHealthWidget />
          </WidgetErrorBoundary>

          {/* JARVIS Calibration — Brier/IC ensemble calibration (honest empty state) */}
          <WidgetErrorBoundary name="Confidence Gauge">
            <ConfidenceGauge />
          </WidgetErrorBoundary>

          {/* Deduped realized record via the honest-metrics layer (not raw tables) */}
          <WidgetErrorBoundary name="Honest PnL">
            <HonestPnlCard />
          </WidgetErrorBoundary>

          {/* Same-day P&L reconciliation (C3): aggregate vs independent snapshot */}
          <WidgetErrorBoundary name="Same Day PnL">
            <SameDayPnLBadge />
          </WidgetErrorBoundary>

          {/* PM2 Stability Monitor — OU-1 watchdog, positions + STP coverage */}
          <WidgetErrorBoundary name="PM2 Stability">
            <Pm2StabilityWidget />
          </WidgetErrorBoundary>

          {/* MES Sprint Gate — April 30 live-flip prerequisite aggregator */}
          <WidgetErrorBoundary name="MES Sprint Gate">
            <MESSprintGate />
          </WidgetErrorBoundary>
        </div>

        {/* Walk-Forward / Paper Trading Status */}
        <WidgetErrorBoundary name="WFE Status">
          <WFEStatusCard />
        </WidgetErrorBoundary>

        {/* Rolling WFE Monitoring */}
        <WidgetErrorBoundary name="Rolling WFE">
          <RollingWFEWidget />
        </WidgetErrorBoundary>

        {/* Main grid */}
        <div className="grid grid-cols-12 gap-4">
          {/* Left column — positions + performance + regime */}
          <div className="col-span-12 lg:col-span-3 space-y-4">
            <WidgetErrorBoundary name="Session Today">
              <SessionTodayWidget />
            </WidgetErrorBoundary>
            <WidgetErrorBoundary name="Institutional Profile">
              <InstitutionalProfileWidget defaultSymbol="MES" />
            </WidgetErrorBoundary>
            <WidgetErrorBoundary name="Positions">
              <PositionsPanel
                positions={portfolio?.positions ?? []}
                totalEquity={portfolio?.total_equity ?? 0}
                dailyPnl={portfolio?.daily_pnl ?? 0}
                unrealizedPnl={portfolio?.unrealized_pnl ?? 0}
              />
            </WidgetErrorBoundary>
            <WidgetErrorBoundary name="Performance">
              <PerformancePanel
                metrics={null}
                equityCurve={[]}
              />
            </WidgetErrorBoundary>
            <WidgetErrorBoundary name="Regime">
              <RegimeDisplay />
            </WidgetErrorBoundary>
            <WidgetErrorBoundary name="Shadow Performance">
              <ShadowPerformanceWidget />
            </WidgetErrorBoundary>
            <WidgetErrorBoundary name="MTF Confirmation">
              <MTFConfirmationWidget symbol="MES" />
            </WidgetErrorBoundary>
            <WidgetErrorBoundary name="Dual TF">
              <DualTFWidget />
            </WidgetErrorBoundary>
          </div>

          {/* Center column — agent activity feed */}
          <div className="col-span-12 lg:col-span-6">
            <WidgetErrorBoundary name="Agent Feed">
              <AgentFeed decisions={agentDecisions ?? []} />
            </WidgetErrorBoundary>
          </div>

          {/* Right column — safety + sentiment */}
          <div className="col-span-12 lg:col-span-4 space-y-6">
            <WidgetErrorBoundary name="Pending Approvals">
              <PendingApprovals />
            </WidgetErrorBoundary>
            <WidgetErrorBoundary name="Kill Switch">
              <KillSwitch

                isActive={safety?.kill_switch_active ?? false}
                reason={safety?.kill_switch_reason}
                onToggle={onKillSwitchToggle}
              />
            </WidgetErrorBoundary>

            {/* Schwab connection status */}
            <WidgetErrorBoundary name="Schwab Status">
              <SchwabStatusWidget />
            </WidgetErrorBoundary>

            {/* Broker position reconciliation */}
            <WidgetErrorBoundary name="Broker Positions">
              <BrokerPositionsWidget />
            </WidgetErrorBoundary>

            {/* Unrealized P&L — live paper positions with mark-to-market */}
            <WidgetErrorBoundary name="Unrealized PnL">
              <UnrealizedPnLWidget />
            </WidgetErrorBoundary>

            {/* Safety metrics */}
            {safety && (
              <div className="rounded-xl border border-border bg-card p-4 space-y-2">
                <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3">
                  Risk Monitor
                </p>
                <RiskRow
                  label="Daily P&L"
                  value={`$${(safety.daily_pnl ?? 0).toFixed(0)}`}
                  limit={`limit: $${Math.abs(safety.max_daily_loss ?? 0).toFixed(0)}`}
                  pct={Math.abs(safety.daily_pnl ?? 0) / Math.abs(safety.max_daily_loss || 1)}
                  danger={(safety.daily_pnl ?? 0) < (safety.max_daily_loss ?? 0)}
                />
                <RiskRow
                  label="Drawdown"
                  value={`${((safety.current_drawdown ?? 0) * 100).toFixed(1)}%`}
                  limit="limit: 10%"
                  pct={(safety.current_drawdown ?? 0) / 0.10}
                  danger={(safety.current_drawdown ?? 0) > 0.08}
                />
                <RiskRow
                  label="Orders Today"
                  value={String(safety.orders_today ?? 0)}
                  limit="limit: 50"
                  pct={(safety.orders_today ?? 0) / 50}
                  danger={(safety.orders_today ?? 0) > 40}
                />
              </div>
            )}

            <WidgetErrorBoundary name="Sentiment">
              <SentimentPanel sentiments={sentiments ?? []} />
            </WidgetErrorBoundary>

            {/* Alert History — fired P&L threshold alerts */}
            <WidgetErrorBoundary name="Alert History">
              <AlertHistoryWidget />
            </WidgetErrorBoundary>

            {/* Discord Intelligence — Corey Auction Tools signal context */}
            <WidgetErrorBoundary name="Discord Intelligence">
              <DiscordIntelligenceWidget />
            </WidgetErrorBoundary>

            {/* Bookmark Themes — Claude-clustered weekly themes from Discord bookmarks */}
            <WidgetErrorBoundary name="Bookmark Themes">
              <BookmarkThemesPanel />
            </WidgetErrorBoundary>

            {/* Bookmark Feed — recent and searchable Discord bookmark rows */}
            <WidgetErrorBoundary name="Bookmark Feed">
              <BookmarkFeedPanel />
            </WidgetErrorBoundary>

            {/* Strategy Research — X-bookmark edge-scan candidates + research gate-v2 verdicts */}
            <WidgetErrorBoundary name="Strategy Research">
              <StrategyResearchPanel />
            </WidgetErrorBoundary>

            {/* Strategy Parameters */}
            <WidgetErrorBoundary name="Strategy Params">
              <StrategyParamsPanel />
            </WidgetErrorBoundary>

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
                  disabled={!engineReachable || isRunning}
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

        {/* Paper trading positions panel — full width below main grid */}
        <WidgetErrorBoundary name="Paper Trading">
          <PaperTradingPanel />
        </WidgetErrorBoundary>

        {/* Live pipeline reasoning — full 5-stage breakdown for each trade decision */}
        <WidgetErrorBoundary name="Live Trade Reasoning">
          <LiveTradeReasoningWidget />
        </WidgetErrorBoundary>

        {/* Trade journal with full signal provenance (US-1404) */}
        <WidgetErrorBoundary name="Trade Journal">
          <TradeJournalWidget />
        </WidgetErrorBoundary>

        {/* Persisted history — full width, three-column on large screens */}
        <div className="grid grid-cols-12 gap-4">
          <div className="col-span-12 lg:col-span-6">
            <WidgetErrorBoundary name="Trade History">
              <TradeHistory />
            </WidgetErrorBoundary>
          </div>
          <div className="col-span-12 lg:col-span-3">
            <WidgetErrorBoundary name="Signal History">
              <SignalHistory />
            </WidgetErrorBoundary>
          </div>
          <div className="col-span-12 lg:col-span-3">
            <WidgetErrorBoundary name="Daily PnL">
              <DailyPnlPanel />
            </WidgetErrorBoundary>
          </div>
        </div>

      <div className="mt-8">
        <WidgetErrorBoundary name="Events Feed">
          <EventsFeedWidget />
        </WidgetErrorBoundary>
      </div>
    
</main>
    </div>
  );
}

// ── Macro Bar ────────────────────────────────────────────────────────────

function MacroBar({ macro }: { macro: MacroSnapshot | null }) {
  if (!macro) return null;

  const vix = typeof macro.vix === "number" ? macro.vix : null;
  const fedFunds = typeof macro.fed_funds_rate === "number" ? macro.fed_funds_rate : null;
  const tenYear = typeof macro.ten_year_yield === "number" ? macro.ten_year_yield : null;

  // Determine VIX regime color
  function vixColor(v: number): string {
    if (v >= 30) return "text-bear";
    if (v >= 20) return "text-warn";
    return "text-bull";
  }

  const hasAnyData = vix != null || fedFunds != null || tenYear != null;
  if (!hasAnyData) return null;

  return (
    <div className="flex items-center gap-5 rounded-lg border border-border bg-card/60 px-4 py-2 overflow-x-auto scrollbar-none">
      <span className="font-mono text-[10px] font-bold text-muted-foreground tracking-widest shrink-0 uppercase">
        Macro
      </span>
      <div className="h-4 w-px bg-border shrink-0" />

      {vix != null && (
        <MacroStat
          label="VIX"
          value={vix.toFixed(2)}
          colorClass={vixColor(vix)}
          tag={vix >= 30 ? "HIGH FEAR" : vix >= 20 ? "ELEVATED" : "LOW"}
          tagColor={vixColor(vix)}
        />
      )}

      {fedFunds != null && (
        <MacroStat
          label="FED FUNDS"
          value={`${fedFunds.toFixed(2)}%`}
          colorClass="text-foreground/80"
        />
      )}

      {tenYear != null && (
        <MacroStat
          label="10Y YIELD"
          value={`${tenYear.toFixed(2)}%`}
          colorClass={tenYear >= 5 ? "text-bear" : tenYear >= 4 ? "text-warn" : "text-foreground/80"}
        />
      )}
    </div>
  );
}

function MacroStat({
  label,
  value,
  colorClass,
  tag,
  tagColor,
}: {
  label: string;
  value: string;
  colorClass: string;
  tag?: string;
  tagColor?: string;
}) {
  return (
    <div className="flex items-center gap-2 shrink-0">
      <span className="font-mono text-[10px] text-muted-foreground tracking-wider">{label}</span>
      <span className={`font-mono text-xs font-bold tabular-nums ${colorClass}`}>{value}</span>
      {tag && (
        <span
          className={`font-mono text-[9px] font-semibold tracking-widest px-1.5 py-0.5 rounded border ${
            tagColor === "text-bear"
              ? "border-bear/30 bg-bear/10 text-bear"
              : tagColor === "text-warn"
              ? "border-warn/30 bg-warn/10 text-warn"
              : "border-bull/30 bg-bull/10 text-bull"
          }`}
        >
          {tag}
        </span>
      )}
    </div>
  );
}


// ── WFE / Paper Trading Status Card ──────────────────────────────────────

interface PaperStatusEntry {
  status: string;
  wfe: number;
  wfe_label: string;
  cleared_date?: string;
  risk_per_trade?: string;
  config?: string;
  target_wfe?: number;
}

interface RegimeStatusEntry {
  current_regime: string;
  regime_breakdown_30d?: Record<string, number>;
  adaptive_stc_os?: number;
  adaptive_stc_ob?: number;
}

// Fallback mirrors the live gate-v2 reality (see /backtest/paper-status):
// MES/MGC trend = PASS (active forward-proving book); MCL/MNQ = DO_NOT_TRADE.
const FALLBACK_PAPER: Record<string, PaperStatusEntry> = {
  "MES_1h": {
    status: "ACTIVE",
    wfe: 1.0,
    wfe_label: "PASS via alt",
    cleared_date: "2026-05-31",
    config: "gate-v2 trend rank11",
  },
  "MGC_1d": {
    status: "ACTIVE",
    wfe: 1.0,
    wfe_label: "PASS via alt",
    cleared_date: "2026-05-31",
    config: "gate-v2 trend rank4",
  },
  "MCL_1h": {
    status: "NO-TRADE",
    wfe: 0.0,
    wfe_label: "DO-NOT-TRADE (routing-blocked)",
  },
  "MNQ_1h": {
    status: "NO-TRADE",
    wfe: 0.0,
    wfe_label: "DO-NOT-TRADE (routing-blocked)",
  },
};

const FALLBACK_REGIME: Record<string, RegimeStatusEntry> = {
  "MGC_1d": { current_regime: "TRENDING" },
  "MNQ_1h": { current_regime: "RANGING" },
  "MCL_1h": { current_regime: "\u2014" },
};

function WFEStatusCard() {
  const {
    data: paperData,
    error: paperErr,
    isLoading: paperLoading,
  } = useSWR<Record<string, PaperStatusEntry>>(
    "/backtest/paper-status",
    fetcher,
    { refreshInterval: 30_000, shouldRetryOnError: false }
  );
  const { data: regimeData } = useSWR<Record<string, RegimeStatusEntry>>(
    "/backtest/regime-status",
    fetcher,
    { refreshInterval: 30_000, shouldRetryOnError: false }
  );

  // When the engine is unreachable SWR has no live data. The fallback snapshot
  // is frozen at 2026-05-31, so it must only render behind a loud STALE badge —
  // never as if it were live status (the bug this card used to have).
  const isStale = !!paperErr || (!paperLoading && paperData === undefined);
  const paper = paperData ?? FALLBACK_PAPER;
  const regime = regimeData ?? FALLBACK_REGIME;

  const symbols = Object.keys(paper);

  function statusColor(status: string): string {
    if (status === "ACTIVE") return "#00ff88";
    if (status === "RESEARCH") return "#ffcc00";
    return "#ff4444";
  }

  function statusDot(status: string): string {
    if (status === "ACTIVE") return "\uD83D\uDFE2";
    if (status === "RESEARCH") return "\uD83D\uDFE1";
    return "\uD83D\uDD34";
  }

  function wfeColor(wfe: number): string {
    if (wfe >= 0.70) return "#00ff88";
    if (wfe >= 0.30) return "#ffcc00";
    return "#ff4444";
  }

  return (
    <div className="rounded-xl border border-[#1a1a2e] bg-[#0a0a0a] p-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="font-mono text-[10px] font-bold tracking-[0.2em] uppercase" style={{ color: isStale ? "#f59e0b" : "#00ff88" }}>
            PAPER TRADING STATUS
          </span>
          <span className="font-mono text-[9px] px-1.5 py-0.5 rounded border" style={{ borderColor: "#00d4ff33", backgroundColor: "#00d4ff10", color: "#00d4ff" }}>
            WFE
          </span>
          {isStale && (
            <span className="font-mono text-[9px] font-bold px-1.5 py-0.5 rounded border animate-pulse" style={{ borderColor: "#f59e0b66", backgroundColor: "#f59e0b1a", color: "#f59e0b" }}>
              STALE · ENGINE UNREACHABLE
            </span>
          )}
        </div>
        <span className="font-mono text-[9px]" style={{ color: isStale ? "#f59e0b" : "#555" }}>
          {isStale ? "Last known 2026-05-31 — not live" : "Walk-Forward Efficiency"}
        </span>
      </div>

      {/* Table */}
      <div className="font-mono text-xs" style={{ opacity: isStale ? 0.5 : 1 }}>
        {/* Header row */}
        <div className="grid grid-cols-4 gap-2 pb-2 mb-2" style={{ borderBottom: "1px solid #1a1a2e" }}>
          <span className="text-[10px] uppercase tracking-wider" style={{ color: "#555" }}>Symbol</span>
          <span className="text-[10px] uppercase tracking-wider text-center" style={{ color: "#555" }}>WFE</span>
          <span className="text-[10px] uppercase tracking-wider text-center" style={{ color: "#555" }}>Status</span>
          <span className="text-[10px] uppercase tracking-wider text-center" style={{ color: "#555" }}>Regime</span>
        </div>

        {/* Data rows */}
        {symbols.map((key) => {
          const entry = paper[key];
          const reg = regime[key];
          const displayName = key.replace("_", " ");
          const currentRegime = reg?.current_regime ?? "\u2014";

          return (
            <div
              key={key}
              className="grid grid-cols-4 gap-2 py-1.5 items-center"
              style={{ borderBottom: "1px solid #111" }}
            >
              {/* Symbol */}
              <span className="font-semibold" style={{ color: "#e0e0e0" }}>
                {displayName}
              </span>

              {/* WFE */}
              <span className="text-center tabular-nums font-bold" style={{ color: wfeColor(entry.wfe) }}>
                {entry.wfe.toFixed(2)}
              </span>

              {/* Status */}
              <span className="text-center" style={{ color: statusColor(entry.status) }}>
                {statusDot(entry.status)} {entry.status}
              </span>

              {/* Regime */}
              <span className="text-center" style={{ color: currentRegime === "\u2014" ? "#555" : "#00d4ff" }}>
                {currentRegime !== "\u2014" ? `${currentRegime} (NOW)` : "\u2014"}
              </span>
            </div>
          );
        })}
      </div>

      {/* Footer — show config for ACTIVE symbols */}
      {symbols.some((k) => paper[k].status === "ACTIVE") && (
        <div className="mt-3 pt-2" style={{ borderTop: "1px solid #1a1a2e" }}>
          {symbols
            .filter((k) => paper[k].status === "ACTIVE")
            .map((k) => {
              const entry = paper[k];
              return (
                <div key={k} className="flex items-center gap-3 font-mono text-[10px]" style={{ color: "#555" }}>
                  <span style={{ color: "#00ff88" }}>{k.replace("_", " ")}</span>
                  <span>cleared: {entry.cleared_date ?? "\u2014"}</span>
                  <span>risk: {entry.risk_per_trade ?? "\u2014"}</span>
                  <span style={{ color: "#00d4ff" }}>{entry.config ?? ""}</span>
                </div>
              );
            })}
        </div>
      )}
    </div>
  );
}

// ── Risk Row ──────────────────────────────────────────────────────────────

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
  const clampedPct = Math.min(pct, 1);
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-xs">
        <span className="text-muted-foreground">{label}</span>
        <div className="flex items-center gap-2">
          <span className="font-mono font-semibold" style={{ color: danger ? "#ff4444" : "#e0e0e0" }}>
            {value}
          </span>
          <span className="font-mono" style={{ color: "#555" }}>/ {limit}</span>
        </div>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full" style={{ backgroundColor: "#1a1a2e" }}>
        <div
          className="h-full rounded-full transition-all"
          style={{
            width: `${clampedPct * 100}%`,
            backgroundColor: danger ? "#ff4444" : clampedPct > 0.7 ? "#ffcc00" : "#00ff88",
          }}
        />
      </div>
      <p className="font-mono text-[10px]" style={{ color: "#555" }}>{limit}</p>
    </div>
  );
}