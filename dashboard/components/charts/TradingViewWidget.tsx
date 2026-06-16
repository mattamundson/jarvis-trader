"use client";

import { useEffect, useRef } from "react";
import type { ChartSymbol } from "@/hooks/useChartData";

/**
 * Maps internal futures symbols to TradingView ticker symbols (front-month
 * continuous). These feed TV's free embeddable Advanced Real-Time Chart widget,
 * which renders TV-hosted data — distinct from the JARVIS chart (our own bars).
 */
const TV_SYMBOL: Record<ChartSymbol, string> = {
  MES: "CME_MINI:MES1!",
  MNQ: "CME_MINI:MNQ1!",
  MGC: "COMEX:MGC1!",
  MCL: "NYMEX:MCL1!",
};

const TV_INTERVAL: Record<string, string> = {
  "5m": "5",
  "15m": "15",
  "1h": "60",
  "4h": "240",
  "1d": "D",
};

interface TradingViewWidgetProps {
  symbol: ChartSymbol;
  timeframe?: string;
  height?: number;
}

/**
 * TradingView free "Advanced Real-Time Chart" embed. Injects TV's widget script
 * into a per-instance container; re-injects when symbol/timeframe change. No API
 * key, no data plumbing — TV hosts the data. Cannot overlay our own markers
 * (that's what the JARVIS chart is for).
 */
export function TradingViewWidget({
  symbol,
  timeframe = "1h",
  height = 460,
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
      symbol: TV_SYMBOL[symbol],
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
  }, [symbol, timeframe]);

  return (
    <div style={{ height }} className="w-full overflow-hidden rounded-lg">
      <div ref={containerRef} className="tradingview-widget-container h-full w-full" />
    </div>
  );
}
