"use client";

// Reusable TradingView-quality renderer (lightweight-charts v5) for OUR OWN
// time-series data. This is the open-source TradingView library plotting the
// exact same data the previous custom-SVG/recharts charts consumed — only the
// renderer changes, never the data. Used to upgrade the P&L / drawdown / equity
// mini-charts to the TradingView look without any TV-hosted feed.

import { useEffect, useRef } from "react";
import {
  createChart,
  ColorType,
  CrosshairMode,
  LineStyle,
  AreaSeries,
  LineSeries,
  HistogramSeries,
  type IChartApi,
  type ISeriesApi,
  type SeriesType,
  type Time,
} from "lightweight-charts";

export interface SeriesPoint {
  time: Time;
  value: number;
  /** Per-bar color (histogram only — e.g. green for +P&L, red for −P&L). */
  color?: string;
}

interface LightweightSeriesChartProps {
  data: SeriesPoint[];
  type?: "area" | "line" | "histogram";
  color?: string;
  /** Area gradient stops (default derived from `color`). */
  topColor?: string;
  bottomColor?: string;
  height?: number;
  /** Dollar = whole-number $ price format; price = 2dp. */
  valueFormat?: "dollar" | "price";
  /** Enable pan/zoom. Off by default for compact card widgets. */
  interactive?: boolean;
  /** Hide the time axis (for index-based curves with synthetic time values). */
  hideTimeAxis?: boolean;
}

export function LightweightSeriesChart({
  data,
  type = "area",
  color = "#00d4ff",
  topColor,
  bottomColor,
  height = 140,
  valueFormat = "dollar",
  interactive = false,
  hideTimeAxis = false,
}: LightweightSeriesChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<SeriesType> | null>(null);

  // ── Create chart + series once per visual config ──────────────────────────
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const chart = createChart(el, {
      width: el.clientWidth,
      height,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#64748b",
        fontFamily: "JetBrains Mono, monospace",
        fontSize: 10,
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
      rightPriceScale: { borderColor: "rgba(0, 212, 255, 0.1)" },
      timeScale: {
        borderColor: "rgba(0, 212, 255, 0.1)",
        timeVisible: false,
        secondsVisible: false,
        visible: !hideTimeAxis,
      },
      handleScroll: interactive,
      handleScale: interactive,
    });
    chartRef.current = chart;

    const priceFormat =
      valueFormat === "dollar"
        ? ({ type: "price", precision: 0, minMove: 1 } as const)
        : ({ type: "price", precision: 2, minMove: 0.01 } as const);

    let series: ISeriesApi<SeriesType>;
    if (type === "line") {
      series = chart.addSeries(LineSeries, { color, lineWidth: 2, priceFormat });
    } else if (type === "histogram") {
      series = chart.addSeries(HistogramSeries, { color, priceFormat, base: 0 });
    } else {
      series = chart.addSeries(AreaSeries, {
        lineColor: color,
        topColor: topColor ?? `${color}55`,
        bottomColor: bottomColor ?? `${color}08`,
        lineWidth: 2,
        priceFormat,
      });
    }
    seriesRef.current = series;

    const ro = new ResizeObserver(() => {
      if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth });
    });
    ro.observe(el);

    return () => {
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, [type, color, topColor, bottomColor, height, valueFormat, interactive, hideTimeAxis]);

  // ── Push data on change (renderer only — data is passed through verbatim) ──
  useEffect(() => {
    const series = seriesRef.current;
    if (!series) return;
    series.setData(data);
    chartRef.current?.timeScale().fitContent();
  }, [data]);

  return <div ref={containerRef} style={{ height }} className="w-full" />;
}
