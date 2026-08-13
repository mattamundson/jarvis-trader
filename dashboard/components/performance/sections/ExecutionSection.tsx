"use client";

// Performance workspace — "execution" (execution quality) section.
// Extracted verbatim from the former app/performance/page.tsx's commission,
// top-symbols, entry-quality, recent-trades, win-rate-by-symbol, P&L
// histogram, best/worst-trades, and symbol-performance widgets (PRB
// dashboard-hardening Task 3) — no calculation, label, or error-handling
// behavior changed, only relocated.

import { CommissionTrackerWidget } from "@/components/CommissionTrackerWidget";
import { TopSymbolsWidget } from "@/components/TopSymbolsWidget";
import { EntryQualityWidget } from "@/components/EntryQualityWidget";
import { RecentTradesTableWidget } from "@/components/RecentTradesTableWidget";
import { WinRateBySymbolWidget } from "@/components/WinRateBySymbolWidget";
import { TradePnLHistogram } from "@/components/TradePnLHistogram";
import { BestWorstTradesWidget } from "@/components/BestWorstTradesWidget";
import { SymbolPerformanceWidget } from "@/components/SymbolPerformanceWidget";
import { WidgetErrorBoundary } from "@/components/WidgetErrorBoundary";

export default function ExecutionSection() {
  return (
    <div className="space-y-6">
      {/* Commission cost tracker */}
      <WidgetErrorBoundary name="Commission Tracker">
        <CommissionTrackerWidget />
      </WidgetErrorBoundary>

      {/* Top Symbols by P&L */}
      <WidgetErrorBoundary name="Top Symbols">
        <TopSymbolsWidget />
      </WidgetErrorBoundary>

      {/* Entry Quality */}
      <WidgetErrorBoundary name="Entry Quality">
        <EntryQualityWidget />
      </WidgetErrorBoundary>

      {/* Recent Closed Trades */}
      <WidgetErrorBoundary name="Recent Closed Trades">
        <RecentTradesTableWidget />
      </WidgetErrorBoundary>

      {/* Win Rate by Symbol */}
      <WidgetErrorBoundary name="Win Rate by Symbol">
        <WinRateBySymbolWidget />
      </WidgetErrorBoundary>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <WidgetErrorBoundary name="Trade P&L Histogram">
          <TradePnLHistogram />
        </WidgetErrorBoundary>
        <WidgetErrorBoundary name="Best/Worst Trades">
          <BestWorstTradesWidget />
        </WidgetErrorBoundary>
        <WidgetErrorBoundary name="Symbol Performance">
          <SymbolPerformanceWidget />
        </WidgetErrorBoundary>
      </div>
    </div>
  );
}
