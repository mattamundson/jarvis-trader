"use client";

// URL-driven, summary-first workspace shell for /performance.
//
// Only the section matching the resolved `?section=` id mounts -- the other
// four never render their (heavy, data-fetching) component tree. Chrome
// (header/nav, page title, and the frozen-backtest-snapshot banner) is
// unchanged from the former app/performance/page.tsx.
//
// See docs/superpowers/specs/2026-08-13-dashboard-hardening-design.md section 3.

import React from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Activity, ArrowLeft } from "lucide-react";
import { ResultLabel } from "@/components/ResultLabel";
import { resolveWorkspaceSection } from "@/lib/workspaceSections";
import { PERFORMANCE_SECTIONS } from "@/components/performance/performanceSections";

function SectionLoadingFallback() {
  return (
    <div
      className="rounded-lg p-4 text-sm"
      style={{ backgroundColor: "#0a0a0a", border: "1px solid #1a1a2e", color: "#555" }}
    >
      Loading…
    </div>
  );
}

// Built once at module scope (not per-render) so next/dynamic's own component
// identity stays stable across re-renders of the workspace.
const SECTION_COMPONENTS: Record<string, React.ComponentType> = Object.fromEntries(
  PERFORMANCE_SECTIONS.map((section) => [
    section.id,
    dynamic(section.loadComponent, { ssr: false, loading: SectionLoadingFallback }),
  ]),
);

function WorkspaceSectionNav({ activeId }: { activeId: string }) {
  return (
    <nav className="flex flex-wrap items-center gap-2" aria-label="Performance sections">
      {PERFORMANCE_SECTIONS.map((section) => {
        const isActive = section.id === activeId;
        return (
          <Link
            key={section.id}
            href={section.id === "summary" ? "/performance" : `/performance?section=${section.id}`}
            data-testid={`performance-section-tab-${section.id}`}
            aria-current={isActive ? "page" : undefined}
            className="rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-wider transition-colors"
            style={
              isActive
                ? { backgroundColor: "#00ff8818", border: "1px solid #00ff8840", color: "#00ff88" }
                : { border: "1px solid #1a1a2e", color: "#888" }
            }
          >
            {section.label}
          </Link>
        );
      })}
    </nav>
  );
}

export default function PerformanceWorkspace() {
  const searchParams = useSearchParams();
  const activeId = resolveWorkspaceSection(PERFORMANCE_SECTIONS, searchParams.get("section"));
  const ActiveSection = SECTION_COMPONENTS[activeId];

  return (
    <div className="min-h-screen" style={{ backgroundColor: "#050505" }}>
      {/* Header */}
      <header
        className="sticky top-0 z-50 backdrop-blur"
        style={{ backgroundColor: "rgba(5,5,5,0.95)", borderBottom: "1px solid #1a1a2e" }}
      >
        <div className="mx-auto max-w-[1920px] 2xl:max-w-[2400px] flex items-center justify-between px-6 py-3">
          <div className="flex items-center gap-3">
            <div
              className="flex h-8 w-8 items-center justify-center rounded-lg"
              style={{ backgroundColor: "#00ff8815" }}
            >
              <Activity className="h-5 w-5" style={{ color: "#00ff88" }} />
            </div>
            <div>
              <h1 className="font-bold tracking-tight" style={{ color: "#e0e0e0" }}>
                JARVIS TRADER
              </h1>
              <p className="text-xs" style={{ color: "#555" }}>
                IBKR Futures + Schwab Options
              </p>
            </div>
            <nav className="hidden lg:flex items-center gap-4 ml-6">
              <Link href="/" className="text-xs transition-colors" style={{ color: "#888" }}>
                Dashboard
              </Link>
              <Link href="/analysis" className="text-xs transition-colors" style={{ color: "#888" }}>
                Analysis
              </Link>
              <Link href="/backtest" className="text-xs transition-colors" style={{ color: "#888" }}>
                Backtest
              </Link>
              <Link
                href="/performance"
                className="text-xs font-semibold pb-0.5"
                style={{ color: "#e0e0e0", borderBottom: "1px solid #00ff88" }}
              >
                Performance
              </Link>
              <Link href="/validation" className="text-xs transition-colors" style={{ color: "#888" }}>
                Validation
              </Link>
              <Link href="/journal" className="text-xs transition-colors" style={{ color: "#888" }}>
                Journal
              </Link>
              <Link href="/paper" className="text-xs font-semibold transition-colors" style={{ color: "#00ff88" }}>
                Paper Trading
              </Link>
              <Link href="/watchlist" className="text-xs transition-colors" style={{ color: "#888" }}>
                Watchlist
              </Link>
              <Link href="/scorecard" className="text-xs transition-colors" style={{ color: "#888" }}>
                Scorecard
              </Link>
              <Link href="/settings" className="text-xs transition-colors" style={{ color: "#888" }}>
                Settings
              </Link>
              <Link href="/health" className="text-xs transition-colors" style={{ color: "#888" }}>
                Health
              </Link>
            </nav>
          </div>
          <div className="flex items-center gap-3">
            <Link
              href="/"
              className="flex items-center gap-1.5 text-xs transition-colors"
              style={{ color: "#888" }}
            >
              <ArrowLeft className="h-3.5 w-3.5" />
              Back to Dashboard
            </Link>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1920px] 2xl:max-w-[2400px] px-6 py-6 space-y-6">
        {/* Page title */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <div>
            <h2
              className="text-2xl font-bold tracking-tight font-mono flex items-center gap-2"
              style={{ color: "#e0e0e0" }}
            >
              Backtest Performance Analytics
              <ResultLabel kind="backtest" />
            </h2>
            <p className="text-sm mt-1 font-mono" style={{ color: "#555" }}>
              JARVIS TRADER v2.7 | STC (Schaff Trend Cycle) + ATR Stops/Targets + Regime Filter
            </p>
          </div>
          <div className="flex items-center gap-3">
            <Link
              href="/strategy-ledger"
              className="font-mono text-[10px] font-bold tracking-wider px-3 py-1.5 rounded hover:opacity-80 transition-opacity"
              style={{ backgroundColor: "#ffcc0018", border: "1px solid #ffcc0040", color: "#ffcc00" }}
            >
              2026-03-30 SNAPSHOT (historical) — see live gate-v2 verdicts in Strategy Ledger →
            </Link>
            <span
              className="font-mono text-[10px] tracking-wider px-2 py-1 rounded"
              style={{ backgroundColor: "#00d4ff10", border: "1px solid #00d4ff33", color: "#00d4ff" }}
            >
              Updated 2026-03-30
            </span>
          </div>
        </div>

        <WorkspaceSectionNav activeId={activeId} />

        <div data-testid={`performance-section-${activeId}`}>
          <ActiveSection />
        </div>
      </main>
    </div>
  );
}
