"use client";

import { Radar } from "lucide-react";
import { RiskSafetyPanel } from "./components/RiskSafetyPanel";
import { PositionsPerformancePanel } from "./components/PositionsPerformancePanel";
import { SignalsPipelinePanel } from "./components/SignalsPipelinePanel";
import { ValidationGatesPanel } from "./components/ValidationGatesPanel";
import { EngineDataPanel } from "./components/EngineDataPanel";
import { EnvironmentFleetPanel } from "./components/EnvironmentFleetPanel";
<<<<<<< HEAD
=======
import { RuntimeSnapshotPanel } from "./components/RuntimeSnapshotPanel";
import { TradingStatusReconciliation } from "@/components/TradingStatusReconciliation";
import { WidgetErrorBoundary } from "@/components/WidgetErrorBoundary";
import { SpxIntradayAnalysisCard } from "@/components/SpxIntradayAnalysisCard";
import { MarketBriefCard } from "@/components/MarketBriefCard";
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2

/**
 * MISSION CONTROL — single command-center view fusing trading state
 * (safety, positions, signals, gates, engine health) with local
 * environment state (loop fleet + env-canary via /api/fleet).
 *
 * All engine data flows through the /api/engine proxy (server-side
 * X-API-Key injection); every panel degrades to an UNREACHABLE note
 * when its endpoint is down, so the page always renders.
 */
export default function MissionControlPage() {
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
        {/* Panel 1 — Risk & Safety (full-width, most prominent) */}
<<<<<<< HEAD
        <RiskSafetyPanel />

        <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
          {/* Panel 2 — Positions & Paper Performance */}
          <PositionsPerformancePanel />

          {/* Panel 3 — Signals & Pipeline */}
          <SignalsPipelinePanel />

          {/* Panel 4 — Validation & Gates */}
          <ValidationGatesPanel />

          {/* Panel 5 — Engine & Data */}
          <EngineDataPanel />
        </div>

        {/* Panel 6 — Environment Fleet (local fs via /api/fleet) */}
        <EnvironmentFleetPanel />
=======
        <WidgetErrorBoundary name="Risk & Safety">
          <RiskSafetyPanel />
        </WidgetErrorBoundary>

        {/* Panel 1b — Trading-status split-brain reconciliation (full-width,
            equally prominent: an unnoticed config disagreement here is how
            a symbol trades when it shouldn't, or fails to when it should). */}
        <WidgetErrorBoundary name="Trading Status Reconciliation">
          <TradingStatusReconciliation />
        </WidgetErrorBoundary>

        {/* Panel 1c — Read-only operator runtime snapshot. This remains useful
            when the engine is fully down because it reads a machine-local,
            redacted artifact rather than live engine routes. */}
        <WidgetErrorBoundary name="Runtime Snapshot">
          <RuntimeSnapshotPanel />
        </WidgetErrorBoundary>

        {/* Panel 1d — Broad morning market machine score. Dashboard-only,
            analysis-only; reads the generated brief artifact and never routes orders. */}
        <WidgetErrorBoundary name="Market Brief Machine Score">
          <MarketBriefCard />
        </WidgetErrorBoundary>

        {/* Panel 1e — SPX intraday decision intelligence. Dashboard-only,
            analysis-only; it never routes orders or mutates risk state. */}
        <WidgetErrorBoundary name="SPX Intraday Decision">
          <SpxIntradayAnalysisCard />
        </WidgetErrorBoundary>

        <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
          {/* Panel 2 — Positions & Paper Performance */}
          <WidgetErrorBoundary name="Positions & Performance">
            <PositionsPerformancePanel />
          </WidgetErrorBoundary>

          {/* Panel 3 — Signals & Pipeline */}
          <WidgetErrorBoundary name="Signals & Pipeline">
            <SignalsPipelinePanel />
          </WidgetErrorBoundary>

          {/* Panel 4 — Validation & Gates */}
          <WidgetErrorBoundary name="Validation & Gates">
            <ValidationGatesPanel />
          </WidgetErrorBoundary>

          {/* Panel 5 — Engine & Data */}
          <WidgetErrorBoundary name="Engine & Data">
            <EngineDataPanel />
          </WidgetErrorBoundary>
        </div>

        {/* Panel 6 — Environment Fleet (local fs via /api/fleet) */}
        <WidgetErrorBoundary name="Environment Fleet">
          <EnvironmentFleetPanel />
        </WidgetErrorBoundary>
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
      </main>
    </div>
  );
}
