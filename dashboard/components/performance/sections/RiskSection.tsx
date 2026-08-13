"use client";

// Performance workspace — "risk" (risk/return) section.
// Extracted verbatim from the former app/performance/page.tsx's streak,
// regime-attribution, drawdown, profit-factor, Sharpe, P&L-streak, and
// rolling-performance widgets (PRB dashboard-hardening Task 3) — no
// calculation, label, or error-handling behavior changed, only relocated.

import { DrawdownChart } from "@/components/DrawdownChart";
import { StreakTrackerWidget } from "@/components/StreakTrackerWidget";
import { RegimeAttributionWidget } from "@/components/RegimeAttributionWidget";
import { ProfitFactorWidget } from "@/components/ProfitFactorWidget";
import { SharpeRatioWidget } from "@/components/SharpeRatioWidget";
import { PnLStreakWidget } from "@/components/PnLStreakWidget";
import { RollingPerformanceWidget } from "@/components/RollingPerformanceWidget";
import { DrawdownChartWidget } from "@/components/DrawdownChartWidget";
import { WidgetErrorBoundary } from "@/components/WidgetErrorBoundary";

export default function RiskSection() {
  return (
    <div className="space-y-6">
      {/* Streak Tracker */}
      <WidgetErrorBoundary name="Streak Tracker">
        <StreakTrackerWidget />
      </WidgetErrorBoundary>

      {/* Regime Attribution */}
      <WidgetErrorBoundary name="Regime Attribution">
        <RegimeAttributionWidget />
      </WidgetErrorBoundary>

      {/* Drawdown Chart */}
      <WidgetErrorBoundary name="Drawdown Chart">
        <DrawdownChart />
      </WidgetErrorBoundary>

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        <WidgetErrorBoundary name="Profit Factor">
          <ProfitFactorWidget />
        </WidgetErrorBoundary>
        <WidgetErrorBoundary name="Sharpe Ratio">
          <SharpeRatioWidget />
        </WidgetErrorBoundary>
        <WidgetErrorBoundary name="P&L Streak">
          <PnLStreakWidget />
        </WidgetErrorBoundary>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <WidgetErrorBoundary name="Rolling Performance">
          <RollingPerformanceWidget />
        </WidgetErrorBoundary>
        <WidgetErrorBoundary name="Drawdown Chart">
          <DrawdownChartWidget />
        </WidgetErrorBoundary>
      </div>
    </div>
  );
}
