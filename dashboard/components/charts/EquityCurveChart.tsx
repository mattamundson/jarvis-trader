"use client";

import { useEffect, useRef } from "react";
import {
  createChart,
  ColorType,
  CrosshairMode,
  LineStyle,
  LineSeries,
  type IChartApi,
  type Time,
} from "lightweight-charts";

interface EquityCurveChartProps {
  /** Curve points; `time` = unix seconds, strictly ascending. */
  points: Array<{ time: number; value: number }>;
  height?: number;
  positive?: boolean;
}

/**
 * Equity curve rendered with TradingView's open-source Lightweight-Charts engine
 * (crosshair, zoom, pan) on OUR backtest data — the same series the recharts
 * sparkline showed, upgraded to an interactive TradingView-grade chart.
 */
export function EquityCurveChart({ points, height = 240, positive = true }: EquityCurveChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    if (!containerRef.current || points.length < 2) return;

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#64748b",
        fontFamily: "JetBrains Mono, monospace",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: "rgba(0, 212, 255, 0.05)" },
        horzLines: { color: "rgba(0, 212, 255, 0.05)" },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: "rgba(0, 212, 255, 0.4)", style: LineStyle.Dashed },
        horzLine: { color: "rgba(0, 212, 255, 0.4)", style: LineStyle.Dashed },
      },
      rightPriceScale: { borderColor: "rgba(0, 212, 255, 0.1)", textColor: "#64748b" },
      timeScale: { borderColor: "rgba(0, 212, 255, 0.1)", timeVisible: false },
    });

    const color = positive ? "#22c55e" : "#ef4444";
    const series = chart.addSeries(LineSeries, {
      color,
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: true,
      crosshairMarkerVisible: true,
    });
    series.setData(points.map((p) => ({ time: p.time as Time, value: p.value })));
    chart.timeScale().fitContent();
    chartRef.current = chart;

    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) chart.applyOptions({ width: entry.contentRect.width });
    });
    ro.observe(containerRef.current);

    return () => {
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
    };
  }, [points, height, positive]);

  if (!points || points.length < 2) {
    return (
      <div
        className="flex items-center justify-center text-xs text-muted-foreground"
        style={{ height }}
      >
        No curve data
      </div>
    );
  }

  return <div ref={containerRef} style={{ height }} className="w-full" />;
}
