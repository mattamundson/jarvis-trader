"use client";

import { Radar } from "lucide-react";
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
import { DrawdownProjectionCard } from "@/components/DrawdownProjectionCard";
import { OptionsChainCard } from "@/components/OptionsChainCard";
import { PnLAttributionCard } from "@/components/PnLAttributionCard";
import { TradeRecommendationsCard } from "@/components/TradeRecommendationsCard";
import { OperatorScoreboard } from "./components/OperatorScoreboard";

/**
 * Local operator view. Order entry is not mounted here.
 * Dollar panels stay on this module and are not imported by the Vercel page.
 */
export function MissionControlLocal() {
  return (
    <div className="min-h-screen bg-background">
      <header className="sticky top-0 z-40 border-b border-border bg-background/95 backdrop-blur">
        <div className="mx-auto max-w-[1600px] 2xl:max-w-[2000px] flex items-center gap-3 px-6 py-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent/10">
            <Radar className="h-5 w-5 text-accent" />
          </div>
          <div>
            <h1 className="font-bold text-foreground tracking-tight">MISSION CONTROL</h1>
            <p className="text-xs text-muted-foreground">
              Trading + environment fused view — auto-refreshes every 15s
            </p>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1600px] 2xl:max-w-[2000px] px-6 py-6 space-y-6">
        <WidgetErrorBoundary name="Operator Scoreboard">
          <OperatorScoreboard />
        </WidgetErrorBoundary>

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
