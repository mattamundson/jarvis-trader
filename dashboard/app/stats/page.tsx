"use client";

import { RefreshCw, BarChart3 } from "lucide-react";
import { PerformanceSummaryWidget } from "@/components/PerformanceSummaryWidget";
import { WinRateBySymbolWidget } from "@/components/WinRateBySymbolWidget";
import { ProfitFactorWidget } from "@/components/ProfitFactorWidget";
import { SharpeRatioWidget } from "@/components/SharpeRatioWidget";
import { WeeklyStatsWidget } from "@/components/WeeklyStatsWidget";
import { MonthlyBreakdownWidget } from "@/components/MonthlyBreakdownWidget";
import { TradeHourlyBreakdownWidget } from "@/components/TradeHourlyBreakdownWidget";
import { TradeDurationWidget } from "@/components/TradeDurationWidget";
import { DailyPnLCalendarWidget } from "@/components/DailyPnLCalendarWidget";
import { TradePnLHistogram } from "@/components/TradePnLHistogram";
import { BestWorstTradesWidget } from "@/components/BestWorstTradesWidget";
import { SymbolPerformanceWidget } from "@/components/SymbolPerformanceWidget";
import { RollingPerformanceWidget } from "@/components/RollingPerformanceWidget";
import { DrawdownChartWidget } from "@/components/DrawdownChartWidget";
import { CommissionTrackerWidget } from "@/components/CommissionTrackerWidget";
import { PnLStreakWidget } from "@/components/PnLStreakWidget";
import { WidgetErrorBoundary } from "@/components/WidgetErrorBoundary";

function SectionDivider({ title }: { title: string }) {
  return (
    <div className="flex items-center gap-3 mt-2">
      <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground whitespace-nowrap">
        {title}
      </p>
      <div className="flex-1 h-px bg-border" />
    </div>
  );
}

export default function StatsPage() {
  return (
    <div className="min-h-screen bg-background">
      {/* Sticky header */}
      <header className="sticky top-0 z-50 border-b border-border bg-background/95 backdrop-blur">
        <div className="mx-auto max-w-[1920px] 2xl:max-w-[2400px] flex items-center justify-between px-6 py-3">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent/10">
              <BarChart3 className="h-5 w-5 text-accent" />
            </div>
            <div>
              <h1 className="font-bold text-foreground tracking-tight">
                JARVIS TRADER — Statistics
              </h1>
              <p className="text-xs text-muted-foreground">
                Full trading performance analytics
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <span className="text-[10px] text-muted-foreground hidden sm:block">
              Auto-refresh per widget
            </span>
            <div className="flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1 text-xs text-muted-foreground">
              <RefreshCw className="h-3 w-3" />
              Live
            </div>
          </div>
        </div>
      </header>

      {/* Page content */}
      <main className="mx-auto max-w-[1920px] 2xl:max-w-[2400px] px-6 py-6 space-y-6">

        {/* Row 1 — full width summary */}
        <SectionDivider title="Performance Overview" />
        <div className="w-full">
          <WidgetErrorBoundary name="Performance Summary">
            <PerformanceSummaryWidget />
          </WidgetErrorBoundary>
        </div>

        {/* Row 2 — 3 cols: win rate, profit factor, sharpe */}
        <SectionDivider title="Core Metrics" />
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          <WidgetErrorBoundary name="Win Rate By Symbol">
            <WinRateBySymbolWidget />
          </WidgetErrorBoundary>
          <WidgetErrorBoundary name="Profit Factor">
            <ProfitFactorWidget />
          </WidgetErrorBoundary>
          <WidgetErrorBoundary name="Sharpe Ratio">
            <SharpeRatioWidget />
          </WidgetErrorBoundary>
        </div>

        {/* Row 3 — 2 cols: weekly stats, monthly breakdown */}
        <SectionDivider title="Periodic Breakdown" />
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <WidgetErrorBoundary name="Weekly Stats">
            <WeeklyStatsWidget />
          </WidgetErrorBoundary>
          <WidgetErrorBoundary name="Monthly Breakdown">
            <MonthlyBreakdownWidget />
          </WidgetErrorBoundary>
        </div>

        {/* Row 4 — 2 cols: hourly breakdown, trade duration */}
        <SectionDivider title="Trade Timing" />
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <WidgetErrorBoundary name="Trade Hourly Breakdown">
            <TradeHourlyBreakdownWidget />
          </WidgetErrorBoundary>
          <WidgetErrorBoundary name="Trade Duration">
            <TradeDurationWidget />
          </WidgetErrorBoundary>
        </div>

        {/* Row 5 — 2 cols: daily P&L calendar, P&L histogram */}
        <SectionDivider title="P&L Distribution" />
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <WidgetErrorBoundary name="Daily P&L Calendar">
            <DailyPnLCalendarWidget />
          </WidgetErrorBoundary>
          <TradePnLHistogram />
        </div>

        {/* Row 6 — 2 cols: best/worst trades, symbol performance */}
        <SectionDivider title="Trade Quality" />
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <WidgetErrorBoundary name="Best/Worst Trades">
            <BestWorstTradesWidget />
          </WidgetErrorBoundary>
          <WidgetErrorBoundary name="Symbol Performance">
            <SymbolPerformanceWidget />
          </WidgetErrorBoundary>
        </div>

        {/* Row 7 — 2 cols: rolling performance, drawdown chart */}
        <SectionDivider title="Risk & Drawdown" />
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <WidgetErrorBoundary name="Rolling Performance">
            <RollingPerformanceWidget />
          </WidgetErrorBoundary>
          <WidgetErrorBoundary name="Drawdown Chart">
            <DrawdownChartWidget />
          </WidgetErrorBoundary>
        </div>

        {/* Row 8 — 2 cols: commission tracker, P&L streak */}
        <SectionDivider title="Costs & Streaks" />
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <WidgetErrorBoundary name="Commission Tracker">
            <CommissionTrackerWidget />
          </WidgetErrorBoundary>
          <WidgetErrorBoundary name="P&L Streak">
            <PnLStreakWidget />
          </WidgetErrorBoundary>
        </div>

        {/* Footer */}
        <p className="text-[11px] text-muted-foreground text-center pb-4">
          JARVIS TRADER Statistics — All data from the paper trading engine via the dashboard proxy — Auto-refresh per widget
        </p>
      </main>
    </div>
  );
}
