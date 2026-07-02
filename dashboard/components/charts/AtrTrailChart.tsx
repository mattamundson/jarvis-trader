"use client";

// ATR-trail price chart (lightweight-charts v5): price line + the dotted trail
// colored by state (green=long / red=short, via two whitespace-gapped series) +
// flip entry markers (^ long / v short, colored green win / red loss). The data
// is OUR backtest payload from GET /backtest/atr-trail/trades — same renderer
// the rest of the dashboard uses, no TV-hosted feed.

import { useEffect, useRef } from "react";
import {
  createChart,
  createSeriesMarkers,
  ColorType,
  CrosshairMode,
  LineStyle,
  LineSeries,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  type SeriesMarker,
  type Time,
  type WhitespaceData,
} from "lightweight-charts";
import type {
  AtrTrailLinePoint,
  AtrTrailPricePoint,
  AtrTrailTrade,
} from "@/lib/api";

interface AtrTrailChartProps {
  price: AtrTrailPricePoint[];
  trail: AtrTrailLinePoint[];
  trades: AtrTrailTrade[];
  height?: number;
}

export function AtrTrailChart({ price, trail, trades, height = 460 }: AtrTrailChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const priceRef = useRef<ISeriesApi<"Line"> | null>(null);
  const trailLongRef = useRef<ISeriesApi<"Line"> | null>(null);
  const trailShortRef = useRef<ISeriesApi<"Line"> | null>(null);

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
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: "rgba(0, 212, 255, 0.1)" },
      timeScale: {
        borderColor: "rgba(0, 212, 255, 0.1)",
        timeVisible: true,
        secondsVisible: false,
      },
      handleScroll: true,
      handleScale: true,
    });
    chartRef.current = chart;

    const priceFormat = { type: "price", precision: 2, minMove: 0.25 } as const;
    priceRef.current = chart.addSeries(LineSeries, {
      color: "#94a3b8",
      lineWidth: 1,
      priceFormat,
      lastValueVisible: false,
    });
    trailLongRef.current = chart.addSeries(LineSeries, {
      color: "#16c784",
      lineWidth: 2,
      lineStyle: LineStyle.Dotted,
      priceFormat,
      lastValueVisible: false,
    });
    trailShortRef.current = chart.addSeries(LineSeries, {
      color: "#ea3943",
      lineWidth: 2,
      lineStyle: LineStyle.Dotted,
      priceFormat,
      lastValueVisible: false,
    });

    const ro = new ResizeObserver(() => {
      if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth });
    });
    ro.observe(el);

    return () => {
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
      priceRef.current = null;
      trailLongRef.current = null;
      trailShortRef.current = null;
    };
  }, [height]);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || !priceRef.current || !trailLongRef.current || !trailShortRef.current) return;

    priceRef.current.setData(price.map((p) => ({ time: p.t as Time, value: p.c })));

    // Two gapped series so the dotted trail shows its long/short state in color.
    const long: (LineData | WhitespaceData)[] = trail.map((p) =>
      p.s === 1 ? { time: p.t as Time, value: p.v } : { time: p.t as Time },
    );
    const short: (LineData | WhitespaceData)[] = trail.map((p) =>
      p.s === -1 ? { time: p.t as Time, value: p.v } : { time: p.t as Time },
    );
    trailLongRef.current.setData(long);
    trailShortRef.current.setData(short);

    // Entry markers: ^ long / v short, green winner / red loser.
    const markers: SeriesMarker<Time>[] = trades.map((t) => ({
      time: t.entry_t as Time,
      position: t.dir === 1 ? "belowBar" : "aboveBar",
      shape: t.dir === 1 ? "arrowUp" : "arrowDown",
      color: t.pnl_usd > 0 ? "#16c784" : "#ea3943",
    }));
    createSeriesMarkers(priceRef.current, markers);

    chart.timeScale().fitContent();
  }, [price, trail, trades]);

  return <div ref={containerRef} style={{ height }} className="w-full" />;
}
