"use client";

import { Radar } from "lucide-react";
import { RiskSafetyPanel } from "./components/RiskSafetyPanel";
import { PositionsPerformancePanel } from "./components/PositionsPerformancePanel";
import { SignalsPipelinePanel } from "./components/SignalsPipelinePanel";
import { ValidationGatesPanel } from "./components/ValidationGatesPanel";
import { EngineDataPanel } from "./components/EngineDataPanel";
import { EnvironmentFleetPanel } from "./components/EnvironmentFleetPanel";

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
              Owns infrastructure, provider health, and data-path operations — auto-refreshes every 15s
            </p>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1600px] 2xl:max-w-[2000px] px-6 py-6 space-y-6">
        {/* Panel 1 — Risk & Safety (full-width, most prominent) */}
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
      </main>
    </div>
  );
}
