"use client";

// Performance workspace — "summary" (account truth) section.
// Extracted verbatim from the former app/performance/page.tsx's tearsheet,
// account ROI, weekly P&L, daily P&L calendar, equity curve, and extended
// performance-summary widgets (PRB dashboard-hardening Task 3) — no
// calculation, label, or error-handling behavior changed, only relocated.

import { QuantStatsPanel } from "@/components/QuantStatsPanel";
import { AccountROIWidget } from "@/components/AccountROIWidget";
import { WeeklyPnLCard } from "@/components/WeeklyPnLCard";
import { DailyPnLCalendarWidget } from "@/components/DailyPnLCalendarWidget";
import { EquityCurveWidget } from "@/components/EquityCurveWidget";
import { PerformanceSummaryWidget } from "@/components/PerformanceSummaryWidget";
import { WidgetErrorBoundary } from "@/components/WidgetErrorBoundary";

export default function SummarySection() {
  return (
    <div className="space-y-6">
      {/* Portfolio Tearsheet — QuantStats institutional metrics */}
      <WidgetErrorBoundary name="Tearsheet">
        <QuantStatsPanel />
      </WidgetErrorBoundary>

      {/* Account ROI */}
      <WidgetErrorBoundary name="Account ROI">
        <AccountROIWidget />
      </WidgetErrorBoundary>

      {/* Weekly P&L */}
      <WidgetErrorBoundary name="Weekly P&L">
        <WeeklyPnLCard />
      </WidgetErrorBoundary>

      {/* Daily P&L Calendar */}
      <WidgetErrorBoundary name="Daily P&L Calendar">
        <DailyPnLCalendarWidget />
      </WidgetErrorBoundary>

      {/* Equity Curve */}
      <WidgetErrorBoundary name="Equity Curve">
        <EquityCurveWidget />
      </WidgetErrorBoundary>

      {/* Extended Analytics summary (folded in from the retired /stats page, P2.3 IA) */}
      <WidgetErrorBoundary name="Performance Summary">
        <PerformanceSummaryWidget />
      </WidgetErrorBoundary>
    </div>
  );
}
