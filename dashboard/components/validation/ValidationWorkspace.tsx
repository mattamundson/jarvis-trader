"use client";

// URL-driven, summary-first workspace shell for /validation.
//
// Only the section matching the resolved `?section=` id mounts -- the other
// five never render their (heavy, data-fetching) component tree, so the page
// stops shipping and mounting all 18 of the former page's sections on every
// load. Chrome (header/nav, the always-on trust widgets, and the section
// switcher) is unchanged from the former app/validation/page.tsx.
//
// See docs/superpowers/specs/2026-08-13-dashboard-hardening-design.md section 3.

import React from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Activity, ArrowLeft, TrendingUp } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { ResultLabel } from "@/components/ResultLabel";
import { WidgetErrorBoundary } from "@/components/WidgetErrorBoundary";
import { ValidationChecklist } from "@/components/ValidationChecklist";
import { TradingDaysCountdownCard } from "@/components/TradingDaysCountdownCard";
import { BacktestVsPaperWidget } from "@/components/BacktestVsPaperWidget";
import { resolveWorkspaceSection } from "@/lib/workspaceSections";
import { VALIDATION_SECTIONS } from "@/components/validation/validationSections";

function SectionLoadingFallback() {
  return (
    <div className="rounded-lg border border-border bg-muted/40 p-4 text-sm text-muted-foreground">
      Loading…
    </div>
  );
}

// Built once at module scope (not per-render) so next/dynamic's own component
// identity stays stable across re-renders of the workspace.
const SECTION_COMPONENTS: Record<string, React.ComponentType> = Object.fromEntries(
  VALIDATION_SECTIONS.map((section) => [
    section.id,
    dynamic(section.loadComponent, { ssr: false, loading: SectionLoadingFallback }),
  ]),
);

function WorkspaceSectionNav({ activeId }: { activeId: string }) {
  return (
    <nav className="flex flex-wrap items-center gap-2" aria-label="Validation sections">
      {VALIDATION_SECTIONS.map((section) => {
        const isActive = section.id === activeId;
        return (
          <Link
            key={section.id}
            href={section.id === "summary" ? "/validation" : `/validation?section=${section.id}`}
            data-testid={`validation-section-tab-${section.id}`}
            aria-current={isActive ? "page" : undefined}
            className={`rounded-full border px-3 py-1 text-xs font-semibold uppercase tracking-wider transition-colors ${
              isActive
                ? "border-accent bg-accent/10 text-accent"
                : "border-border text-muted-foreground hover:text-foreground hover:border-accent/40"
            }`}
          >
            {section.label}
          </Link>
        );
      })}
    </nav>
  );
}

export default function ValidationWorkspace() {
  const searchParams = useSearchParams();
  const activeId = resolveWorkspaceSection(VALIDATION_SECTIONS, searchParams.get("section"));
  const ActiveSection = SECTION_COMPONENTS[activeId];

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
              <p className="text-xs text-muted-foreground">IBKR Futures + Schwab Options</p>
            </div>
            <nav className="hidden lg:flex items-center gap-4 ml-6">
              <a
                href="/"
                className="text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                Dashboard
              </a>
              <a
                href="/analysis"
                className="text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                Analysis
              </a>
              <a
                href="/backtest"
                className="text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                Backtest
              </a>
              <a
                href="/performance"
                className="text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                Performance
              </a>
              <a
                href="/validation"
                className="text-xs text-foreground font-semibold border-b border-accent pb-0.5 transition-colors"
              >
                Validation
              </a>
              <a
                href="/journal"
                className="text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                Journal
              </a>
              <a
                href="/paper"
                className="text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                Paper Trading
              </a>
              <a
                href="/watchlist"
                className="text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                Watchlist
              </a>
              <a
                href="/scorecard"
                className="text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                Scorecard
              </a>
              <a
                href="/settings"
                className="text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                Settings
              </a>
              <a
                href="/health"
                className="text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                Health
              </a>
            </nav>
          </div>

          <div className="flex items-center gap-3">
            <a
              href="/"
              className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
            >
              <ArrowLeft className="h-3.5 w-3.5" />
              Back to Dashboard
            </a>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1920px] 2xl:max-w-[2400px] px-6 py-6 space-y-6">
        <ValidationChecklist />
        <TradingDaysCountdownCard />
        <WidgetErrorBoundary name="Backtest vs Paper">
          <BacktestVsPaperWidget />
        </WidgetErrorBoundary>

        {/* Page title */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <div>
            <h2 className="text-2xl font-bold text-foreground tracking-tight flex items-center gap-2">
              <TrendingUp className="h-6 w-6 text-accent" />
              Strategy Validation Dashboard
              <ResultLabel kind="backtest" />
            </h2>
            <p className="text-sm text-muted-foreground mt-0.5">
              Walk-forward results, statistical significance, and parameter robustness
            </p>
          </div>
          <Badge variant="info" className="text-xs px-3 py-1 font-mono tracking-wider self-start sm:self-auto">
            PAPER PHASE — ONGOING
          </Badge>
        </div>

        <WorkspaceSectionNav activeId={activeId} />

        <div data-testid={`validation-section-${activeId}`}>
          <ActiveSection />
        </div>
      </main>
    </div>
  );
}
