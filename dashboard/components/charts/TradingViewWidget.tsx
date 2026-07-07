"use client";

import { useEffect, useRef } from "react";

const TV_INTERVAL: Record<string, string> = {
  "5m": "5",
  "15m": "15",
  "1h": "60",
  "4h": "240",
  "1d": "D",
};

interface TradingViewWidgetProps {
  /**
   * Fully-resolved TradingView ticker (e.g. "AMEX:SPY", "CME_MINI:MES1!").
   * Use `tvTickerFor()` from `@/lib/chart-class` to resolve an internal symbol.
   */
  tvSymbol: string;
  timeframe?: string;
  height?: number;
  /** Render a small "data may be delayed" note (TV's free tier delays CME futures). */
  showDelayedNote?: boolean;
}

/**
 * TradingView free "Advanced Real-Time Chart" embed. Injects TV's widget script
 * into a per-instance container; re-injects when symbol/timeframe change. No API
 * key, no data plumbing — TV hosts the data. Cannot overlay our own markers (that
 * is what the JARVIS chart is for).
 *
 * IMPORTANT: never feed this a futures symbol for a "live" chart — TV delays CME
 * futures 15–30 min on the free tier. Route via `MarketChart`, which sends futures
 * to our own real-time bars and only equities/indices/macro/crypto here.
 */
export function TradingViewWidget({
  tvSymbol,
  timeframe = "1h",
  height = 460,
  showDelayedNote = false,
}: TradingViewWidgetProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    // Clear any previous embed (symbol/timeframe change re-injects).
    container.innerHTML = "";

    const script = document.createElement("script");
    script.src =
      "https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js";
    script.type = "text/javascript";
    script.async = true;
    script.innerHTML = JSON.stringify({
      autosize: true,
      symbol: tvSymbol,
      interval: TV_INTERVAL[timeframe] ?? "60",
      timezone: "America/Chicago",
      theme: "dark",
      style: "1",
      locale: "en",
      backgroundColor: "rgba(6, 13, 26, 1)",
      gridColor: "rgba(0, 212, 255, 0.06)",
      hide_side_toolbar: false,
      allow_symbol_change: true,
      studies: ["STD;EMA", "STD;VWAP"],
      support_host: "https://www.tradingview.com",
    });
    container.appendChild(script);

    return () => {
      container.innerHTML = "";
    };
  }, [tvSymbol, timeframe]);

  return (
    <div style={{ height }} className="relative w-full overflow-hidden rounded-lg">
      <div ref={containerRef} className="tradingview-widget-container h-full w-full" />
      {showDelayedNote && (
        <span className="pointer-events-none absolute right-1.5 top-1.5 z-10 rounded bg-background/70 px-1.5 py-0.5 text-[10px] font-mono text-muted-foreground/80">
          TradingView · may be delayed
        </span>
      )}
    </div>
  );
}
