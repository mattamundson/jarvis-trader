// Section registry for the /performance summary-first workspace.
// See docs/superpowers/specs/2026-08-13-dashboard-hardening-design.md section 3
// ("account truth, risk/return, time analysis, execution quality, and research
// comparisons"). Only the section matching the resolved `?section=` id mounts
// -- see components/performance/PerformanceWorkspace.tsx.

import type { WorkspaceSectionDef } from "@/lib/workspaceSections";

export const PERFORMANCE_SECTIONS: WorkspaceSectionDef[] = [
  {
    id: "summary",
    label: "Account Truth",
    summary: "Tearsheet, account ROI, weekly/daily realized P&L, and the equity curve.",
    loadComponent: () => import("@/components/performance/sections/SummarySection"),
  },
  {
    id: "risk",
    label: "Risk / Return",
    summary: "Drawdown, profit factor, Sharpe, streaks, and regime attribution.",
    loadComponent: () => import("@/components/performance/sections/RiskSection"),
  },
  {
    id: "time",
    label: "Time Analysis",
    summary: "Hold time, win rate by hour, and weekly/monthly breakdowns.",
    loadComponent: () => import("@/components/performance/sections/TimeSection"),
  },
  {
    id: "execution",
    label: "Execution Quality",
    summary: "Commissions, entry quality, and per-symbol/per-trade execution detail.",
    loadComponent: () => import("@/components/performance/sections/ExecutionSection"),
  },
  {
    id: "research",
    label: "Research Comparisons",
    summary: "Frozen 2026-03-30 backtest matrix, walk-forward study, and the live price chart.",
    loadComponent: () => import("@/components/performance/sections/ResearchSection"),
  },
];
