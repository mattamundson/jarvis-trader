"use client";

import { useState } from "react";
import dynamic from "next/dynamic";
import { Activity, MessageSquare } from "lucide-react";
import { SWRConfig } from "swr";
import { WidgetErrorBoundary } from "@/components/WidgetErrorBoundary";

const DynamicDiscordStats = dynamic(
  () => import("@/components/discord/DiscordStats").then(mod => ({ default: mod.DiscordStats })),
  { ssr: false, loading: () => <DiscordPanelSkeleton label="Loading Discord stats..." /> }
);
const DynamicDiscordWinRateChart = dynamic(
  () => import("@/components/discord/DiscordWinRateChart").then(mod => ({ default: mod.DiscordWinRateChart })),
  { ssr: false, loading: () => <DiscordPanelSkeleton label="Loading win-rate chart..." /> }
);
const DynamicDiscordSignalTable = dynamic(
  () => import("@/components/discord/DiscordSignalTable").then(mod => ({ default: mod.DiscordSignalTable })),
  { ssr: false, loading: () => <DiscordPanelSkeleton label="Loading signal table..." /> }
);
const DynamicSignalFeed = dynamic(
  () => import("@/components/discord/signal-feed").then(mod => ({ default: mod.SignalFeed })),
  { ssr: false, loading: () => <DiscordPanelSkeleton label="Loading signal feed..." /> }
);
const DynamicIBReportCard = dynamic(
  () => import("@/components/discord/ib-report-card").then(mod => ({ default: mod.IBReportCard })),
  { ssr: false, loading: () => <DiscordPanelSkeleton label="Loading IB reports..." /> }
);
const DynamicCoreyFeed = dynamic(
  () => import("@/components/discord/corey-feed").then(mod => ({ default: mod.CoreyFeed })),
  { ssr: false, loading: () => <DiscordPanelSkeleton label="Loading Corey commentary..." /> }
);
const DynamicDiscordIntelligenceWidget = dynamic(
  () => import("@/components/DiscordIntelligenceWidget").then(mod => ({ default: mod.DiscordIntelligenceWidget })),
  { ssr: false, loading: () => <DiscordPanelSkeleton label="Loading Discord intelligence..." /> }
);
const DynamicKnowledgeContextWidget = dynamic(
  () => import("@/components/KnowledgeContextWidget").then(mod => ({ default: mod.KnowledgeContextWidget })),
  { ssr: false, loading: () => <DiscordPanelSkeleton label="Loading knowledge context..." /> }
);

type Tab = "overview" | "signals" | "ib-reports" | "commentary";

const TABS: { id: Tab; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "signals", label: "Signal Feed" },
  { id: "ib-reports", label: "IB Reports" },
  { id: "commentary", label: "Corey Commentary" },
];

// Page-level SWR config: disable retry on error so panels settle to an honest
// error/empty state instead of re-spinning after a failed /discord/* fetch.
// Sub-components that already set shouldRetryOnError:false are unaffected
// (their local config wins); this is the catch-all for components like
// signal-feed, ib-report-card, and corey-feed that don't set it.
const DISCORD_SWR_CONFIG = {
  shouldRetryOnError: false,
  errorRetryCount: 0,
} as const;

function DiscordPanelSkeleton({ label }: { label: string }) {
  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <div className="h-4 w-40 rounded bg-muted animate-pulse" />
      <div className="mt-4 h-28 rounded bg-muted/50 animate-pulse" />
      <p className="mt-3 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
        {label}
      </p>
    </div>
  );
}

export default function DiscordPage() {
  const [activeTab, setActiveTab] = useState<Tab>("overview");

  return (
    <SWRConfig value={DISCORD_SWR_CONFIG}>
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="sticky top-0 z-50 border-b border-border bg-background/95 backdrop-blur">
        <div className="mx-auto max-w-[1920px] 2xl:max-w-[2400px] flex items-center justify-between px-6 py-3">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent/10">
              <Activity className="h-5 w-5 text-accent" />
            </div>
            <div>
              <h1 className="font-bold text-foreground tracking-tight">JARVIS TRADER</h1>
              <p className="text-xs text-muted-foreground">Discord Intelligence</p>
            </div>
            <nav className="hidden lg:flex items-center gap-4 ml-6">
              {[
                ["/", "Home"],
                ["/performance", "Performance"],
                ["/journal", "Journal"],
                ["/portfolio", "Portfolio"],
                ["/options", "Options"],
                ["/crypto", "Crypto"],
                ["/discord", "Discord Intel"],
                ["/learning", "Learning"],
                ["/health", "Health"],
              ].map(([href, label]) => (
                <a
                  key={href}
                  href={href}
                  className={`text-xs transition-colors ${
                    href === "/discord"
                      ? "text-accent font-semibold"
                      : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {label}
                </a>
              ))}
            </nav>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1920px] 2xl:max-w-[2400px] px-6 py-6 space-y-6">

        {/* Page title */}
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[#5865F2]/10">
            <MessageSquare className="h-5 w-5" style={{ color: "#5865F2" }} />
          </div>
          <div>
            <h2 className="font-mono text-lg font-bold text-foreground tracking-tight">
              Discord Intelligence
            </h2>
            <p className="font-mono text-[11px] text-muted-foreground mt-0.5">
              Signals & commentary from the Corey Auction Tools server
            </p>
          </div>
        </div>

        {/* Tabs */}
        <div className="flex gap-1 border-b border-border">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`px-4 py-2 font-mono text-xs font-medium transition-colors border-b-2 -mb-px ${
                activeTab === tab.id
                  ? "border-accent text-accent"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Tab content */}
        {activeTab === "overview" && (
          <div className="space-y-6">
            {/* Row 1: Summary stats (full width) */}
            <DynamicDiscordStats />

            {/* Discord signal features (left) + curated knowledge brain (right) */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <WidgetErrorBoundary name="Discord Intelligence">
                <DynamicDiscordIntelligenceWidget />
              </WidgetErrorBoundary>
              <WidgetErrorBoundary name="Knowledge Context">
                <DynamicKnowledgeContextWidget symbol="MES" />
              </WidgetErrorBoundary>
            </div>

            {/* Row 2: Win rate chart (left) + commentary snippet (right) */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <DynamicDiscordWinRateChart />

              {/* Quick-info commentary card */}
              <div className="rounded-xl border border-border bg-card p-4 space-y-4">
                <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
                  About This Data
                </p>
                <div className="space-y-3 font-mono text-xs text-foreground/80 leading-relaxed">
                  <p>
                    <span style={{ color: "#00ff88" }} className="font-semibold">Bot Signals</span>{" "}
                    — Parsed from the Corey Auction Tools Discord bot. Each signal
                    includes symbol, direction (LONG/SHORT), entry, targets, stops,
                    and historical win-rate statistics.
                  </p>
                  <p>
                    <span style={{ color: "#00d4ff" }} className="font-semibold">IB Reports</span>{" "}
                    — Initial Balance reports posted each morning with IB High, IB
                    Low, and 50%/100% extension levels for each futures instrument.
                  </p>
                  <p>
                    <span style={{ color: "#ff9500" }} className="font-semibold">Commentary</span>{" "}
                    — Corey&apos;s market analysis posts from the general and
                    market-updates channels, covering context and daily trading plans.
                  </p>
                  <p>
                    <span style={{ color: "#ffcc00" }} className="font-semibold">Corey Alerts</span>{" "}
                    — Real-time trade alerts and level breaks called out during live
                    market sessions.
                  </p>
                </div>
                <div className="pt-2 border-t border-border">
                  <p className="font-mono text-[10px] text-muted-foreground">
                    Data spans Jul 2023 — Apr 2026 &bull; Imported from Discord export JSON
                  </p>
                </div>
              </div>
            </div>

            {/* Row 3: Recent signals table (full width) */}
            <DynamicDiscordSignalTable />
          </div>
        )}

        {activeTab === "signals" && <DynamicSignalFeed />}
        {activeTab === "ib-reports" && <DynamicIBReportCard />}
        {activeTab === "commentary" && <DynamicCoreyFeed />}

      </main>
    </div>
    </SWRConfig>
  );
}
