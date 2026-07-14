"use client";

import { useEffect, useRef, type MutableRefObject } from "react";
import {
  createChart,
  createSeriesMarkers,
  ColorType,
  CrosshairMode,
  LineStyle,
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  type IChartApi,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type SeriesMarker,
  type SeriesType,
  type Time,
} from "lightweight-charts";
import type { OHLCVBar, TechnicalAnalysisResult } from "@/lib/api";

interface CandlestickChartProps {
  bars?: OHLCVBar[];
  technical?: TechnicalAnalysisResult | null;
  height?: number;
  livePrice?: number | null;
  /** Optional trade/signal markers overlaid on the candle series. */
  markers?: SeriesMarker<Time>[];
  /** Optional horizontal price lines (e.g. stop / target) drawn on the candle series. */
  priceLines?: Array<{ price: number; color: string; title: string }>;
}

export function CandlestickChart({
  bars,
  technical,
  height = 420,
  livePrice,
  markers,
  priceLines,
}: CandlestickChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  // EMA overlay ribbon — full historical time-series
  const ema8Ref = useRef<ISeriesApi<"Line"> | null>(null);
  const ema21Ref = useRef<ISeriesApi<"Line"> | null>(null);
  const ema34Ref = useRef<ISeriesApi<"Line"> | null>(null);
  // VWAP overlay and STC subpanel
  const vwapSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const stcSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  // Trade/signal markers plugin (v5: createSeriesMarkers on the candle series)
  const markersPluginRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  // Trade price lines (stop/target) overlaid on the candle series
  const priceLineRefs = useRef<ReturnType<ISeriesApi<"Candlestick">["createPriceLine"]>[]>([]);

  // ── Initialize chart on mount ─────────────────────────────────────────────
  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height: height,
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
      rightPriceScale: {
        borderColor: "rgba(0, 212, 255, 0.1)",
        textColor: "#64748b",
      },
      timeScale: {
        borderColor: "rgba(0, 212, 255, 0.1)",
        timeVisible: true,
        secondsVisible: false,
      },
    });

    // Candlestick series (v5: chart.addSeries(SeriesDefinition, options))
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: "#00ff88",
      downColor: "#ff4466",
      borderUpColor: "#00ff88",
      borderDownColor: "#ff4466",
      wickUpColor: "#00ff88",
      wickDownColor: "#ff4466",
    });

    // Volume histogram on a separate price scale
    const volumeSeries = chart.addSeries(HistogramSeries, {
      color: "rgba(0, 212, 255, 0.2)",
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
    });
    chart.priceScale("volume").applyOptions({
      scaleMargins: { top: 0.8, bottom: 0 },
    });

    // EMA ribbon — full historical overlay series
    const ema8Series = chart.addSeries(LineSeries, {
      color: "rgba(0, 255, 136, 0.85)",
      lineWidth: 1,
      title: "EMA8",
      priceLineVisible: false,
      lastValueVisible: true,
      crosshairMarkerVisible: false,
    });
    const ema21Series = chart.addSeries(LineSeries, {
      color: "rgba(255, 204, 0, 0.85)",
      lineWidth: 1,
      title: "EMA21",
      priceLineVisible: false,
      lastValueVisible: true,
      crosshairMarkerVisible: false,
    });
    const ema34Series = chart.addSeries(LineSeries, {
      color: "rgba(255, 68, 102, 0.85)",
      lineWidth: 1,
      title: "EMA34",
      priceLineVisible: false,
      lastValueVisible: true,
      crosshairMarkerVisible: false,
    });

    // VWAP overlay — orange dashed, daily-anchored
    const vwapSeries = chart.addSeries(LineSeries, {
      color: '#FF9500',
      lineWidth: 2,
      lineStyle: LineStyle.Dashed,
      title: 'VWAP',
      lastValueVisible: true,
      priceLineVisible: false,
      crosshairMarkerVisible: true,
    });

    // STC histogram subpanel — occupies bottom 22% of chart
    const stcSeries = chart.addSeries(HistogramSeries, {
      color: 'rgba(0, 212, 255, 0.5)',
      priceScaleId: 'stc_pane',
      lastValueVisible: true,
      title: 'STC',
    });
    chart.priceScale('stc_pane').applyOptions({
      scaleMargins: { top: 0.78, bottom: 0.02 },
      autoScale: true,
    });

    // OS / OB reference lines on STC pane
    stcSeries.createPriceLine({
      price: 15,
      color: '#00ff88',
      lineStyle: LineStyle.Dotted,
      lineWidth: 1 as 1,
      title: 'OS',
      axisLabelVisible: true,
    });
    stcSeries.createPriceLine({
      price: 83,
      color: '#ff4444',
      lineStyle: LineStyle.Dotted,
      lineWidth: 1 as 1,
      title: 'OB',
      axisLabelVisible: true,
    });

    // Markers plugin bound to the candle series (updated in the markers effect)
    markersPluginRef.current = createSeriesMarkers(candleSeries, []);

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    volumeSeriesRef.current = volumeSeries;
    ema8Ref.current = ema8Series;
    ema21Ref.current = ema21Series;
    ema34Ref.current = ema34Series;
    vwapSeriesRef.current = vwapSeries;
    stcSeriesRef.current = stcSeries;

    // Responsive resize observer
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        chart.applyOptions({ width: entry.contentRect.width });
      }
    });
    ro.observe(containerRef.current);

    return () => {
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      volumeSeriesRef.current = null;
      ema8Ref.current = null;
      ema21Ref.current = null;
      ema34Ref.current = null;
      vwapSeriesRef.current = null;
      stcSeriesRef.current = null;
      markersPluginRef.current = null;
      priceLineRefs.current = [];
    };
  }, [height]);

  // ── Update trade/signal markers when they change ─────────────────────────
  useEffect(() => {
    if (!markersPluginRef.current) return;
    markersPluginRef.current.setMarkers(markers ?? []);
  }, [markers]);

  // ── Update candle + volume data when bars change ──────────────────────────
  useEffect(() => {
    if (!candleSeriesRef.current || !bars?.length) return;

    const candleData = bars.map((b) => ({
      time: b.time as Time,
      open: b.open,
      high: b.high,
      low: b.low,
      close: b.close,
    }));

    const volumeData = bars
      .filter((b) => b.volume != null)
      .map((b) => ({
        time: b.time as Time,
        value: b.volume!,
        color:
          b.close >= b.open
            ? "rgba(0, 255, 136, 0.2)"
            : "rgba(255, 68, 102, 0.2)",
      }));

    candleSeriesRef.current.setData(candleData);
    if (volumeSeriesRef.current && volumeData.length) {
      volumeSeriesRef.current.setData(volumeData);
    }

    // EMA ribbon — full historical time-series overlays
    const emaMap: Array<[MutableRefObject<ISeriesApi<"Line"> | null>, "ema_8" | "ema_21" | "ema_34"]> = [
      [ema8Ref, "ema_8"],
      [ema21Ref, "ema_21"],
      [ema34Ref, "ema_34"],
    ];
    for (const [ref, field] of emaMap) {
      if (ref.current) {
        const emaData = bars
          .filter((b) => b[field] != null && !isNaN(b[field] as number))
          .map((b) => ({ time: b.time as Time, value: b[field] as number }));
        if (emaData.length > 0) ref.current.setData(emaData);
      }
    }

    // VWAP overlay
    if (vwapSeriesRef.current) {
      const vwapData = bars
        .filter((b) => b.vwap != null && !isNaN(b.vwap as number))
        .map((b) => ({ time: b.time as Time, value: b.vwap as number }));
      if (vwapData.length > 0) {
        vwapSeriesRef.current.setData(vwapData);
      }
    }

    // STC histogram subpanel
    if (stcSeriesRef.current) {
      const stcData = bars
        .filter((b) => b.stc != null && !isNaN(b.stc as number))
        .map((b) => ({
          time: b.time as Time,
          value: b.stc as number,
          color: (b.stc as number) <= 15
            ? 'rgba(0, 255, 136, 0.8)'
            : (b.stc as number) >= 83
            ? 'rgba(255, 68, 68, 0.8)'
            : 'rgba(0, 212, 255, 0.5)',
        }));
      if (stcData.length > 0) {
        stcSeriesRef.current.setData(stcData);
      }
    }

    chartRef.current?.timeScale().fitContent();
  }, [bars]);

  // ── Apply trade price lines (stop / target) ───────────────────────────────
  useEffect(() => {
    const series = candleSeriesRef.current;
    if (!series) return;
    // clear previous lines
    for (const pl of priceLineRefs.current) {
      try {
        series.removePriceLine(pl);
      } catch {
        /* series may already be disposed */
      }
    }
    priceLineRefs.current = [];
    for (const pl of priceLines ?? []) {
      if (pl.price == null || !Number.isFinite(pl.price)) continue;
      priceLineRefs.current.push(
        series.createPriceLine({
          price: pl.price,
          color: pl.color,
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title: pl.title,
        })
      );
    }
  }, [priceLines, bars]);

  // ── Update indicator price lines when technical data changes ─────────────
  useEffect(() => {
    const series = candleSeriesRef.current;
    if (!series || !technical) return;

    // Remove old price lines before adding new ones
    for (const pl of series.priceLines()) {
      series.removePriceLine(pl);
    }

    const addLine = (
      price: number | null | undefined,
      color: string,
      title: string,
      lineStyle: LineStyle = LineStyle.Solid,
      lineWidth: 1 | 2 | 3 | 4 = 1,
      axisLabelVisible = true
    ) => {
      if (price == null || price === 0) return;
      series.createPriceLine({
        price,
        color,
        lineWidth,
        lineStyle,
        axisLabelVisible,
        title,
      });
    };

    // EMA ribbon is rendered as historical time-series overlays (see bars useEffect above)
    // Keltner channels
    addLine(
      technical.kelt_inner_upper,
      "rgba(0, 212, 255, 0.6)",
      "KC+",
      LineStyle.Dashed,
      1,
      false
    );
    addLine(
      technical.kelt_inner_lower,
      "rgba(0, 212, 255, 0.6)",
      "KC-",
      LineStyle.Dashed,
      1,
      false
    );

    // Trade levels
    addLine(technical.entry_price, "#00ff88", "ENTRY", LineStyle.Dotted, 2);
    addLine(technical.stop_level, "#ff4466", "STOP", LineStyle.LargeDashed);
    addLine(technical.target_1, "#00d4ff", "T1", LineStyle.Dotted);
  }, [technical]);

  // ── Live price tick from WebSocket ───────────────────────────────────────
  useEffect(() => {
    if (livePrice == null || !candleSeriesRef.current || !bars?.length) return;
    const last = bars[bars.length - 1];
    candleSeriesRef.current.update({
      time: last.time as Time,
      open: last.open,
      high: Math.max(last.high, livePrice),
      low: Math.min(last.low, livePrice),
      close: livePrice,
    });
  }, [livePrice, bars]);

  // ── Loading / empty states ────────────────────────────────────────────────
  if (!bars?.length) {
    return (
      <div
        className="flex flex-col items-center justify-center text-slate-500 text-sm font-mono gap-2"
        style={{ height, background: "rgba(6,13,26,0.6)" }}
      >
        <span className="text-cyan-700 tracking-widest text-xs">
          CHART ENGINE
        </span>
        <span className="text-slate-600 text-xs">
          {bars === null
            ? "Engine offline — no chart data"
            : "Loading bars..."}
        </span>
      </div>
    );
  }

  return <div ref={containerRef} style={{ height }} className="w-full" />;
}
