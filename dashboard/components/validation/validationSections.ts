// Section registry for the /validation summary-first workspace.
// See docs/superpowers/specs/2026-08-13-dashboard-hardening-design.md section 3
// ("verdict, paper evidence, backtest comparison, WFE history, reconciliation,
// and export/audit"). Only the section matching the resolved `?section=` id
// mounts -- see components/validation/ValidationWorkspace.tsx.

import type { WorkspaceSectionDef } from "@/lib/workspaceSections";

export const VALIDATION_SECTIONS: WorkspaceSectionDef[] = [
  {
    id: "summary",
    label: "Verdict Summary",
    summary: "Live gate-v2 scorecards, MES re-validation, and trading-phase status.",
    loadComponent: () => import("@/components/validation/sections/SummarySection"),
  },
  {
    id: "paper",
    label: "Paper Evidence",
    summary: "Live paper-trading performance vs. validation thresholds and the P&L curve.",
    loadComponent: () => import("@/components/validation/sections/PaperSection"),
  },
  {
    id: "backtest",
    label: "Backtest Comparison",
    summary: "Saved backtest baseline and its side-by-side comparison to live paper results.",
    loadComponent: () => import("@/components/validation/sections/BacktestSection"),
  },
  {
    id: "wfe",
    label: "WFE History",
    summary: "Walk-forward efficiency monitor for the live strategy.",
    loadComponent: () => import("@/components/validation/sections/WfeSection"),
  },
  {
    id: "reconciliation",
    label: "Reconciliation",
    summary: "Broker position reconciliation status.",
    loadComponent: () => import("@/components/validation/sections/ReconciliationSection"),
  },
  {
    id: "audit",
    label: "Export / Audit",
    summary: "Pipeline run history and data export tools.",
    loadComponent: () => import("@/components/validation/sections/AuditSection"),
  },
];
