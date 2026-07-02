"use client";

import React, { useState } from "react";
import Link from "next/link";
import {
  Activity,
  ArrowLeft,
  BookOpen,
  FlaskConical,
  ListChecks,
  ChevronDown,
  ChevronUp,
} from "lucide-react";
import { MarketSessionStatusCard } from "@/components/MarketSessionStatusCard";
import { RecentTradesTableWidget } from "@/components/RecentTradesTableWidget";
import { WidgetErrorBoundary } from "@/components/WidgetErrorBoundary";

// ── Category badge colors ────────────────────────────────────────────────────

type Category = "CRITICAL" | "FINDING" | "IMPROVEMENT" | "VERDICT" | "BREAKTHROUGH" | "BUG FIX";
type Status = "Resolved" | "Active" | "Superseded";
type HypothesisResult = "Pending" | "In Progress" | "FAILED" | "No improvement" | "Partial (0.34)" | "No (WFE same 0.27)";

const CATEGORY_STYLES: Record<Category, string> = {
  CRITICAL: "bg-red-500/15 text-red-400 border-red-500/30",
  FINDING: "bg-yellow-500/15 text-yellow-400 border-yellow-500/30",
  IMPROVEMENT: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  VERDICT: "bg-orange-500/15 text-orange-400 border-orange-500/30",
  BREAKTHROUGH: "bg-cyan-500/15 text-cyan-400 border-cyan-500/30",
  "BUG FIX": "bg-neutral-500/15 text-neutral-400 border-neutral-500/30",
};

const STATUS_STYLES: Record<Status, string> = {
  Resolved: "text-neutral-500",
  Active: "text-emerald-400",
  Superseded: "text-neutral-600 line-through",
};

// ── Static data ──────────────────────────────────────────────────────────────

interface ResearchEntry {
  date: string;
  entry: string;
  category: Category;
  status: Status;
}

const RESEARCH_LOG: ResearchEntry[] = [
  {
    date: "2026-03-29",
    entry: "MGC 1d adaptive WFE=0.88 (3-window) \u2014 small-sample bias exposed by 15-window",
    category: "CRITICAL",
    status: "Resolved",
  },
  {
    date: "2026-03-29",
    entry: "Regime classifier anti-predictive for gold daily (regime=ON loses money)",
    category: "FINDING",
    status: "Active",
  },
  {
    date: "2026-03-29",
    entry: "MES v2.5 PF 0.96\u21921.69 with regime_filter=OFF",
    category: "IMPROVEMENT",
    status: "Active",
  },
  {
    date: "2026-03-29",
    entry: "All static param sets fail 15-window WF \u2014 fundamental redesign needed",
    category: "VERDICT",
    status: "Active",
  },
  {
    date: "2026-03-28",
    entry: "MGC adaptive WFE surged 0.27\u21920.88",
    category: "BREAKTHROUGH",
    status: "Superseded",
  },
  {
    date: "2026-03-27",
    entry: "Walk-forward fails all 5 instruments (static params)",
    category: "VERDICT",
    status: "Resolved",
  },
  {
    date: "2026-03-26",
    entry: "8 critical backtesting bugs fixed",
    category: "BUG FIX",
    status: "Resolved",
  },
];

interface Hypothesis {
  hypothesis: string;
  prediction: string;
  tested: "Yes" | "No" | "Partial";
  result: HypothesisResult;
}

const HYPOTHESES: Hypothesis[] = [
  {
    hypothesis: "EMA trend gate prevents bear market losses",
    prediction: "WFE improvement",
    tested: "No",
    result: "Pending",
  },
  {
    hypothesis: "Regime_filter=OFF improves MGC daily WFE",
    prediction: "WFE >0.40",
    tested: "Partial",
    result: "In Progress",
  },
  {
    hypothesis: "Wider train window (12mo) improves MNQ WFE",
    prediction: "WFE >0.40",
    tested: "Yes",
    result: "No improvement",
  },
  {
    hypothesis: "Volume filter improves MNQ 1h",
    prediction: "WFE >0.40",
    tested: "Yes",
    result: "FAILED",
  },
  {
    hypothesis: "MTF filter improves MNQ 1h",
    prediction: "WFE >0.40",
    tested: "No",
    result: "Pending",
  },
  {
    hypothesis: "Adaptive regime improves MGC 1d",
    prediction: "WFE >0.50",
    tested: "Yes",
    result: "No (WFE same 0.27)",
  },
  {
    hypothesis: "Adaptive regime improves MNQ 1h",
    prediction: "WFE >0.40",
    tested: "Yes",
    result: "Partial (0.34)",
  },
];

interface Experiment {
  id: number;
  title: string;
  description: string;
}

const NEXT_EXPERIMENTS: Experiment[] = [
  {
    id: 1,
    title: "EMA 50/200 trend gate",
    description: "Prevent shorting during uptrend, longing during downtrend",
  },
  {
    id: 2,
    title: "MGC 1h vs 1d",
    description: "Intraday momentum may work better than daily macro",
  },
  {
    id: 3,
    title: "Multi-asset correlation",
    description: "Trade MNQ only when SPY trend aligns",
  },
  {
    id: 4,
    title: "Extend to 2020-2026 data",
    description: "COVID crash, full market cycles when data available",
  },
  {
    id: 5,
    title: "Different entry: RSI divergence vs STC crossover",
    description: "Compare RSI divergence signals against current STC-based entries",
  },
];

// ── Helper components ────────────────────────────────────────────────────────

function CategoryBadge({ category }: { category: Category }) {
  return (
    <span
      className={`inline-flex items-center rounded border px-2 py-0.5 font-mono text-[10px] font-semibold tracking-wider ${CATEGORY_STYLES[category]}`}
    >
      {category}
    </span>
  );
}

function StatusText({ status }: { status: Status }) {
  return (
    <span className={`font-mono text-xs ${STATUS_STYLES[status]}`}>
      {status}
    </span>
  );
}

function TestedBadge({ tested }: { tested: "Yes" | "No" | "Partial" }) {
  const styles = {
    Yes: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
    No: "bg-neutral-500/15 text-neutral-500 border-neutral-500/30",
    Partial: "bg-yellow-500/15 text-yellow-400 border-yellow-500/30",
  };
  return (
    <span
      className={`inline-flex items-center rounded border px-2 py-0.5 font-mono text-[10px] font-semibold ${styles[tested]}`}
    >
      {tested}
    </span>
  );
}

function ResultBadge({ result }: { result: HypothesisResult }) {
  let style = "text-neutral-500";
  if (result === "FAILED") style = "text-red-400 font-bold";
  else if (result === "In Progress") style = "text-cyan-400";
  else if (result === "Pending") style = "text-neutral-500";
  else if (result.startsWith("Partial")) style = "text-yellow-400";
  else if (result.startsWith("No")) style = "text-orange-400";

  return <span className={`font-mono text-xs ${style}`}>{result}</span>;
}

// ── Section wrapper ──────────────────────────────────────────────────────────

function Section({
  title,
  icon,
  accentColor,
  children,
  defaultOpen = true,
}: {
  title: string;
  icon: React.ReactNode;
  accentColor: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="rounded-xl border border-[#1a1a2e] bg-[#0a0a0a]">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between px-5 py-4 text-left"
      >
        <div className="flex items-center gap-3">
          <div
            className="flex h-7 w-7 items-center justify-center rounded-lg"
            style={{ backgroundColor: `${accentColor}15` }}
          >
            {icon}
          </div>
          <span
            className="font-mono text-xs font-bold tracking-[0.15em] uppercase"
            style={{ color: accentColor }}
          >
            {title}
          </span>
        </div>
        {open ? (
          <ChevronUp className="h-4 w-4 text-neutral-600" />
        ) : (
          <ChevronDown className="h-4 w-4 text-neutral-600" />
        )}
      </button>
      {open && (
        <div className="border-t border-[#1a1a2e] px-5 pb-5 pt-4">
          {children}
        </div>
      )}
    </div>
  );
}

// ── Main Page ────────────────────────────────────────────────────────────────

export default function JournalPage() {
  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="sticky top-0 z-50 border-b border-border bg-background/95 backdrop-blur">
        <div className="mx-auto max-w-[1920px] 2xl:max-w-[2400px] flex items-center justify-between px-6 py-3">
          <div className="flex items-center gap-3">
            <Link
              href="/"
              className="flex items-center gap-2 text-muted-foreground hover:text-foreground transition-colors"
            >
              <ArrowLeft className="h-4 w-4" />
              <span className="text-xs">Dashboard</span>
            </Link>
            <div className="h-5 w-px bg-border" />
            <div className="flex items-center gap-2">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent/10">
                <BookOpen className="h-5 w-5 text-accent" />
              </div>
              <div>
                <h1 className="font-bold text-foreground tracking-tight">
                  RESEARCH JOURNAL
                </h1>
                <p className="text-xs text-muted-foreground">
                  Signal research log, hypotheses, and experiment tracker
                </p>
              </div>
            </div>
          </div>

          <nav className="hidden lg:flex items-center gap-4">
            <Link href="/" className="text-xs text-muted-foreground hover:text-foreground transition-colors">
              Dashboard
            </Link>
            <Link href="/analysis" className="text-xs text-muted-foreground hover:text-foreground transition-colors">
              Analysis
            </Link>
            <Link href="/backtest" className="text-xs text-muted-foreground hover:text-foreground transition-colors">
              Backtest
            </Link>
            <Link href="/performance" className="text-xs text-muted-foreground hover:text-foreground transition-colors">
              Performance
            </Link>
            <Link href="/validation" className="text-xs text-muted-foreground hover:text-foreground transition-colors">
              Validation
            </Link>
            <Link href="/journal" className="text-xs text-accent font-semibold">
              Journal
            </Link>
            <Link href="/journal-review" className="text-xs text-muted-foreground hover:text-foreground transition-colors">
              Review
            </Link>
            <Link href="/paper" className="text-xs text-muted-foreground hover:text-foreground transition-colors">
              Paper Trading
            </Link>
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-[1920px] 2xl:max-w-[2400px] px-6 py-6 space-y-6">
        {/* ── Market Session Status ──────────────────────────────────────────── */}
        <MarketSessionStatusCard />

        {/* ── Recent Trades ──────────────────────────────────────────────────── */}
        <WidgetErrorBoundary name="Recent Trades">
          <RecentTradesTableWidget />
        </WidgetErrorBoundary>

        {/* ── Section 1: Research Log ────────────────────────────────────────── */}
        <Section
          title="Research Log"
          icon={<BookOpen className="h-4 w-4 text-cyan-400" />}
          accentColor="#00d4ff"
        >
          <div
            className="mb-4 flex items-center gap-2 rounded-md px-3 py-2 font-mono text-[11px] uppercase tracking-wider"
            style={{ backgroundColor: "#2a1f0a", border: "1px solid #6b5414", color: "#e0b94a" }}
          >
            <span style={{ fontWeight: 700 }}>Static log</span>
            <span style={{ color: "#9a8030" }}>
              frozen snapshot, last updated 2026-03-29 — &ldquo;active&rdquo; reflects status as of then, not today
            </span>
          </div>
          <div className="overflow-x-auto">
            {/* Table header */}
            <div
              className="grid gap-3 pb-3 mb-1 font-mono text-[10px] uppercase tracking-wider"
              style={{
                gridTemplateColumns: "90px 1fr 120px 90px",
                color: "#555",
                borderBottom: "1px solid #1a1a2e",
              }}
            >
              <span>Date</span>
              <span>Entry</span>
              <span className="text-center">Category</span>
              <span className="text-center">Status</span>
            </div>

            {/* Table rows */}
            {RESEARCH_LOG.map((row, i) => (
              <div
                key={i}
                className="grid gap-3 py-3 items-center font-mono text-xs"
                style={{
                  gridTemplateColumns: "90px 1fr 120px 90px",
                  borderBottom: "1px solid #111",
                }}
              >
                <span className="tabular-nums text-neutral-500">{row.date}</span>
                <span className="text-neutral-200 leading-relaxed">{row.entry}</span>
                <span className="text-center">
                  <CategoryBadge category={row.category} />
                </span>
                <span className="text-center">
                  <StatusText status={row.status} />
                </span>
              </div>
            ))}
          </div>

          {/* Summary stats */}
          <div className="mt-4 flex items-center gap-6 font-mono text-[10px] text-neutral-600">
            <span>
              {RESEARCH_LOG.filter((r) => r.status === "Active").length} active
            </span>
            <span>
              {RESEARCH_LOG.filter((r) => r.status === "Resolved").length} resolved
            </span>
            <span>{RESEARCH_LOG.length} total entries</span>
          </div>
        </Section>

        {/* ── Section 2: Hypothesis Tracker ──────────────────────────────────── */}
        <Section
          title="Hypothesis Tracker"
          icon={<FlaskConical className="h-4 w-4 text-yellow-400" />}
          accentColor="#ffcc00"
        >
          <div className="overflow-x-auto">
            {/* Table header */}
            <div
              className="grid gap-3 pb-3 mb-1 font-mono text-[10px] uppercase tracking-wider"
              style={{
                gridTemplateColumns: "1fr 140px 80px 160px",
                color: "#555",
                borderBottom: "1px solid #1a1a2e",
              }}
            >
              <span>Hypothesis</span>
              <span className="text-center">Prediction</span>
              <span className="text-center">Tested</span>
              <span className="text-center">Result</span>
            </div>

            {/* Table rows */}
            {HYPOTHESES.map((h, i) => (
              <div
                key={i}
                className="grid gap-3 py-3 items-center font-mono text-xs"
                style={{
                  gridTemplateColumns: "1fr 140px 80px 160px",
                  borderBottom: "1px solid #111",
                }}
              >
                <span className="text-neutral-200 leading-relaxed">{h.hypothesis}</span>
                <span className="text-center text-neutral-400 tabular-nums">{h.prediction}</span>
                <span className="text-center">
                  <TestedBadge tested={h.tested} />
                </span>
                <span className="text-center">
                  <ResultBadge result={h.result} />
                </span>
              </div>
            ))}
          </div>

          {/* Summary */}
          <div className="mt-4 flex items-center gap-6 font-mono text-[10px] text-neutral-600">
            <span>
              {HYPOTHESES.filter((h) => h.result === "Pending").length} pending
            </span>
            <span>
              {HYPOTHESES.filter((h) => h.tested === "Yes").length} tested
            </span>
            <span>
              {HYPOTHESES.filter((h) => h.result === "FAILED").length} failed
            </span>
          </div>
        </Section>

        {/* ── Section 3: Next Experiments ─────────────────────────────────────── */}
        <Section
          title="Next Experiments"
          icon={<ListChecks className="h-4 w-4 text-emerald-400" />}
          accentColor="#00ff88"
        >
          <div className="space-y-3">
            {NEXT_EXPERIMENTS.map((exp) => (
              <div
                key={exp.id}
                className="flex items-start gap-4 rounded-lg border border-[#1a1a2e] bg-[#0d0d0d] px-4 py-3"
              >
                <span
                  className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md font-mono text-[11px] font-bold tabular-nums"
                  style={{
                    backgroundColor: "#00ff8815",
                    color: "#00ff88",
                    border: "1px solid #00ff8830",
                  }}
                >
                  {exp.id}
                </span>
                <div>
                  <p className="font-mono text-xs font-semibold text-neutral-200">
                    {exp.title}
                  </p>
                  <p className="font-mono text-[11px] text-neutral-500 mt-0.5 leading-relaxed">
                    {exp.description}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </Section>

        {/* Footer timestamp */}
        <div className="text-center font-mono text-[10px] text-neutral-700 py-4">
          JARVIS TRADER RESEARCH JOURNAL &middot; Last updated 2026-03-29
        </div>
      </main>
    </div>
  );
}
