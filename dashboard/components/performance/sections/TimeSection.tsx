"use client";

// Performance workspace — "time" (time analysis) section.
// Extracted verbatim from the former app/performance/page.tsx's hold-time,
// win-rate-by-hour, weekly/monthly breakdown, trade-duration, and
// trade-hourly-breakdown widgets (PRB dashboard-hardening Task 3) — no
// calculation, label, or error-handling behavior changed, only relocated.

import { WeeklyStatsWidget } from "@/components/WeeklyStatsWidget";
import { TradeDurationWidget } from "@/components/TradeDurationWidget";
import { MonthlyBreakdownWidget } from "@/components/MonthlyBreakdownWidget";
import AvgTradeTimeWidget from "@/components/AvgTradeTimeWidget";
import HoldTimeWidget from "@/components/HoldTimeWidget";
import { WinRateByHourWidget } from "@/components/WinRateByHourWidget";
import { TradeHourlyBreakdownWidget } from "@/components/TradeHourlyBreakdownWidget";
import { WidgetErrorBoundary } from "@/components/WidgetErrorBoundary";

export default function TimeSection() {
  return (
    <div className="space-y-6">
      {/* Win Rate by Hour of Day */}
      <WidgetErrorBoundary name="Win Rate by Hour">
        <WinRateByHourWidget />
      </WidgetErrorBoundary>

      {/* Hold time analytics */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <WidgetErrorBoundary name="Hold Time">
          <HoldTimeWidget />
        </WidgetErrorBoundary>
      </div>

      {/* Weekly live performance summary */}
      <WidgetErrorBoundary name="Weekly Stats">
        <WeeklyStatsWidget />
      </WidgetErrorBoundary>

      {/* Trade duration analysis */}
      <WidgetErrorBoundary name="Trade Duration">
        <TradeDurationWidget />
      </WidgetErrorBoundary>

      {/* Monthly Breakdown */}
      <WidgetErrorBoundary name="Monthly Breakdown">
        <MonthlyBreakdownWidget />
      </WidgetErrorBoundary>

      {/* Avg Trade Hold Time */}
      <WidgetErrorBoundary name="Avg Trade Time">
        <AvgTradeTimeWidget />
      </WidgetErrorBoundary>

      {/* Trade Hourly Breakdown */}
      <WidgetErrorBoundary name="Trade Hourly Breakdown">
        <TradeHourlyBreakdownWidget />
      </WidgetErrorBoundary>
    </div>
  );
}
