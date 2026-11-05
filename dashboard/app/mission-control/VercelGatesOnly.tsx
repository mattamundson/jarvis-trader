"use client";

import useSWR from "swr";
import { Radar } from "lucide-react";
import { fetcher, localFetcher } from "./components/shared";
import { GatesBlock, LockoutBlock } from "./components/OperatorScoreboard";
import type { HermesGatesReport } from "@/lib/hermesGates";
import { RiskSafetyPanel } from "./components/RiskSafetyPanel";
import { PositionsPerformancePanel } from "./components/PositionsPerformancePanel";
import { SignalsPipelinePanel } from "./components/SignalsPipelinePanel";
import { ValidationGatesPanel } from "./components/ValidationGatesPanel";
import { EngineDataPanel } from "./components/EngineDataPanel";
import { EnvironmentFleetPanel } from "./components/EnvironmentFleetPanel";
import { RuntimeSnapshotPanel } from "./components/RuntimeSnapshotPanel";
import { TradingStatusReconciliation } from "@/components/TradingStatusReconciliation";
import { WidgetErrorBoundary } from "@/components/WidgetErrorBoundary";
import { SpxIntradayAnalysisCard } from "@/components/SpxIntradayAnalysisCard";
import { MarketBriefCard } from "@/components/MarketBriefCard";
import { PaperTradeAuditCard } from "@/components/PaperTradeAuditCard";
import { TOSLiveQuotesCard } from "@/components/TOSLiveQuotesCard";
import { TOSIndicatorCard } from "@/components/TOSIndicatorCard";
import { GatewayWatchdogCard } from "@/components/GatewayWatchdogCard";
import { TradeExecutionCard } from "@/components/TradeExecutionCard";
import { DrawdownProjectionCard } from "@/components/DrawdownProjectionCard";
import { OptionsChainCard } from "@/components/OptionsChainCard";
import { PnLAttributionCard } from "@/components/PnLAttributionCard";
import { TradeRecommendationsCard } from "@/components/TradeRecommendationsCard";

interface LossTrackerStatus {
  is_halted?: boolean;
  halt_until?: string | null;
}

/**
 * Public Vercel audience. All master panels PLUS gates and lockout.
 * Addition-only: every panel master had is rendered here.
 */
export function VercelGatesOnly() {
  const { data: lockout, error: lockoutError } = useSWR<LossTrackerStatus>(
    "/safety/loss-tracker/status",
    fetcher,
    { refreshInterval: 15_000 },
  );
  const { data: gates, error: gatesError } = useSWR<HermesGatesReport>(
    "/api/operator/gates",
    localFetcher,
    { refreshInterval: 15_000 },
  );

  return (
    <div className="min-h-screen bg-background">
      <header className="sticky top-0 z-40 border-b border-border bg-background/95 backdrop-blur">
        <div className="mx-auto flex max-w-[1600px] items-center gap-3 px-6 py-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent/10">
            <Radar className="h-5 w-5 text-accent" />
          </div>
          <div>
            <h1 className="font-bold tracking-tight text-foreground">MISSION CONTROL</h1>
            <p className="text-xs text-muted-foreground">Gates and lockout only</p>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-[1600px] 2xl:max-w-[2000px] px-6 py-6 space-y-6">
        {/* ADDITION: Gates and lockout block (not in master) */}
        <section className="rounded-xl border border-border bg-card p-4">
          <LockoutBlock lockout={lockout} error={lockoutError} />
          <div className="mt-4">
            <GatesBlock gates={gates} error={gatesError} />
          </div>
        </section>

        {/* All panels from master's mission-control page follow */}
        <WidgetErrorBoundary name="Risk & Safety">
          <RiskSafetyPanel />
        </WidgetErrorBoundary>

        <WidgetErrorBoundary name="Drawdown Projection">
          <DrawdownProjectionCard />
        </WidgetErrorBoundary>

        <WidgetErrorBoundary name="Trading Status Reconciliation">
          <TradingStatusReconciliation />
        </WidgetErrorBoundary>

        <WidgetErrorBoundary name="Runtime Snapshot">
          <RuntimeSnapshotPanel />
        </WidgetErrorBoundary>

        <WidgetErrorBoundary name="Market Brief Machine Score">
          <MarketBriefCard />
        </WidgetErrorBoundary>

        <WidgetErrorBoundary name="SPX Intraday Decision">
          <SpxIntradayAnalysisCard />
        </WidgetErrorBoundary>

        <WidgetErrorBoundary name="Paper Trade Audit">
          <PaperTradeAuditCard />
        </WidgetErrorBoundary>

        <WidgetErrorBoundary name="Gateway Watchdog">
          <GatewayWatchdogCard />
        </WidgetErrorBoundary>

        <WidgetErrorBoundary name="Trade Execution">
          <TradeExecutionCard />
        </WidgetErrorBoundary>

        <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
          <WidgetErrorBoundary name="Positions & Performance">
            <PositionsPerformancePanel />
          </WidgetErrorBoundary>

          <WidgetErrorBoundary name="Signals & Pipeline">
            <SignalsPipelinePanel />
          </WidgetErrorBoundary>

          <WidgetErrorBoundary name="Validation & Gates">
            <ValidationGatesPanel />
          </WidgetErrorBoundary>

          <WidgetErrorBoundary name="Engine & Data">
            <EngineDataPanel />
          </WidgetErrorBoundary>
        </div>

        <WidgetErrorBoundary name="Environment Fleet">
          <EnvironmentFleetPanel />
        </WidgetErrorBoundary>

        <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
          <WidgetErrorBoundary name="TOS Live Quotes">
            <TOSLiveQuotesCard />
          </WidgetErrorBoundary>

          <WidgetErrorBoundary name="Trade Recommendations">
            <TradeRecommendationsCard />
          </WidgetErrorBoundary>
        </div>

        <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
          <WidgetErrorBoundary name="TOS Indicators">
            <TOSIndicatorCard />
          </WidgetErrorBoundary>
        </div>

        <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
          <WidgetErrorBoundary name="Options Chain">
            <OptionsChainCard />
          </WidgetErrorBoundary>

          <WidgetErrorBoundary name="P&L Attribution">
            <PnLAttributionCard />
          </WidgetErrorBoundary>
        </div>
      </main>
    </div>
  );
}
