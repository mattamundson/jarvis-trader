"use client";

import { useState } from "react";
import { Activity, Brain } from "lucide-react";
import { PatternCard } from "@/components/learning/PatternCard";
import { TradeGradeTable } from "@/components/learning/TradeGradeTable";
import { SuggestionPanel } from "@/components/learning/SuggestionPanel";
import { MemoryPanel } from "@/components/learning/MemoryPanel";
import { AgentWeightsPanel } from "@/components/learning/AgentWeightsPanel";
import { PostMortemPanel } from "@/components/learning/PostMortemPanel";

// ── Types ─────────────────────────────────────────────────────────────────────

type Tab = "patterns" | "grades" | "suggestions" | "memory" | "weights" | "postmortems";

const TABS: { id: Tab; label: string }[] = [
  { id: "patterns",     label: "Patterns" },
  { id: "grades",       label: "Trade Grades" },
  { id: "suggestions",  label: "Suggestions" },
  { id: "memory",       label: "Memory" },
  { id: "weights",      label: "Agent Weights" },
  { id: "postmortems",  label: "Post-Mortems" },
];

const SYMBOLS = ["MES", "MNQ", "MGC", "MCL"] as const;
type Symbol = (typeof SYMBOLS)[number];

// ── Nav links (keep in sync with other pages) ─────────────────────────────────

const NAV_LINKS: [string, string][] = [
  ["/", "Home"],
  ["/performance", "Performance"],
  ["/journal", "Journal"],
  ["/portfolio", "Portfolio"],
  ["/options", "Options"],
  ["/crypto", "Crypto"],
  ["/discord", "Discord Intel"],
  ["/learning", "Learning"],
  ["/health", "Health"],
];

// ── Page ──────────────────────────────────────────────────────────────────────

export default function LearningPage() {
  const [activeTab, setActiveTab] = useState<Tab>("patterns");
  const [symbol, setSymbol] = useState<Symbol>("MES");

  return (
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
              <p className="text-xs text-muted-foreground">Learning System</p>
            </div>
            <nav className="hidden lg:flex items-center gap-4 ml-6">
              {NAV_LINKS.map(([href, label]) => (
                <a
                  key={href}
                  href={href}
                  className={`text-xs transition-colors ${
                    href === "/learning"
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
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-accent/10">
              <Brain className="h-5 w-5 text-accent" />
            </div>
            <div>
              <h2 className="font-mono text-lg font-bold text-foreground tracking-tight">
                Learning System
              </h2>
              <p className="font-mono text-[11px] text-muted-foreground mt-0.5">
                Pattern recognition, trade grading &amp; strategy tuning
              </p>
            </div>
          </div>

          {/* Symbol selector — shown for tabs that are symbol-specific */}
          {(activeTab === "patterns" || activeTab === "suggestions") && (
            <div className="flex items-center gap-2">
              <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                Symbol
              </span>
              <div className="flex gap-1">
                {SYMBOLS.map((s) => (
                  <button
                    key={s}
                    onClick={() => setSymbol(s)}
                    className={`font-mono text-[11px] rounded px-3 py-1.5 border transition-colors ${
                      symbol === s
                        ? "border-accent/50 bg-accent/10 text-accent font-semibold"
                        : "border-border text-muted-foreground hover:text-foreground hover:border-border/80"
                    }`}
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}
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
        {activeTab === "patterns" && <PatternCard symbol={symbol} lookbackDays={30} />}
        {activeTab === "grades"   && <TradeGradeTable />}
        {activeTab === "suggestions" && <SuggestionPanel symbol={symbol} />}
        {activeTab === "memory"   && <MemoryPanel />}
        {activeTab === "weights"  && <AgentWeightsPanel />}
        {activeTab === "postmortems" && <PostMortemPanel />}

      </main>
    </div>
  );
}
