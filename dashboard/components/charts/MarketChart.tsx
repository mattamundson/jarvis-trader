"use client";

import type { SeriesMarker, Time } from "lightweight-charts";
import { CandlestickChart } from "@/components/command-center/charts/CandlestickChart";
import { TradingViewWidget } from "@/components/charts/TradingViewWidget";
import {
  useChartData,
  type ChartSymbol,
  type ChartTimeframe,
} from "@/hooks/useChartData";
import { useLiveLastPrice } from "@/hooks/useLiveLastPrice";
import { chartClassFor, tvTickerFor } from "@/lib/chart-class";

interface MarketChartProps {
  /** Any symbol. Futures route to our real-time bars; everything else to TradingView. */
  symbol: string;
  timeframe?: ChartTimeframe;
  height?: number;
  /** Trade/signal markers overlaid on the candle series (futures path only). */
  markers?: SeriesMarker<Time>[];
  /** Subscribe to live WS price ticks (futures path). Default true. */
  live?: boolean;
  className?: string;
}

/**
 * Symbol-class-aware chart. The single entry point that enforces "futures use our
 * own real-time bars, never TradingView's delayed embed." See `lib/chart-class.ts`.
 */
export function MarketChart({
  symbol,
  timeframe = "1h",
  height = 420,
  markers,
  live = true,
  className,
}: MarketChartProps) {
  if (chartClassFor(symbol) === "tv") {
    return (
      <div className={className}>
        <TradingViewWidget
          tvSymbol={tvTickerFor(symbol)}
          timeframe={timeframe}
          height={height}
          showDelayedNote
        />
      </div>
    );
  }

  return (
    <FuturesMarketChart
      symbol={symbol}
      timeframe={timeframe}
      height={height}
      markers={markers}
      live={live}
      className={className}
    />
  );
}

/**
 * Futures branch — kept as its own component so its data/WS hooks run only when a
 * futures symbol is actually being rendered (no conditional hook calls).
 */
function FuturesMarketChart({
  symbol,
  timeframe,
  height,
  markers,
  live,
  className,
}: Required<Omit<MarketChartProps, "markers" | "className">> & {
  markers?: SeriesMarker<Time>[];
  className?: string;
}) {
  const { bars, technical, barsError } = useChartData(symbol as ChartSymbol, timeframe);
  const livePrice = useLiveLastPrice(live ? symbol : null);

  if (barsError) {
    return (
      <div
        className={`flex items-center justify-center text-sm text-red-400 font-mono ${className ?? ""}`}
        style={{ height }}
      >
        Failed to load bars for {symbol}
      </div>
    );
  }

  return (
    <div className={className}>
      {bars.length ? (
        // Mount only once bars exist — CandlestickChart inits its chart in a
        // mount effect, so mounting with empty bars yields a dead container that
        // never re-inits when bars arrive (matches the command-center gate).
        <CandlestickChart
          bars={bars}
          technical={technical}
          markers={markers}
          livePrice={livePrice}
          height={height}
        />
      ) : (
        <div
          className="flex items-center justify-center text-sm text-muted-foreground font-mono"
          style={{ height }}
        >
          Loading {symbol} bars…
        </div>
      )}
    </div>
  );
}
