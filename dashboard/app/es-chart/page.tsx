"use client";

import { useEffect, useRef, useState } from "react";
import {
  createChart,
  ColorType,
  CrosshairMode,
  LineStyle,
  CandlestickSeries,
  LineSeries,
  type IChartApi,
  type ISeriesApi,
  type Time,
} from "lightweight-charts";
import useSWR from "swr";
import { fetchBars, type OHLCVBar } from "@/lib/api";
import { calculateAllLevels, type ESChartLevels } from "@/lib/esChartLevels";
import { Badge } from "@/components/ui/badge";
import { ExploratoryBanner } from "@/components/ExploratoryBanner";

interface OverlayToggles {
  atr: boolean;
  ib: boolean;
  tpo: boolean;
  priorTPO: boolean;
  gapFill: boolean;
  vwap: boolean;
  overnight: boolean;
}

export default function ESChartPage() {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const priceLineRefs = useRef<Map<string, ReturnType<ISeriesApi<"Candlestick">["createPriceLine"]>>>(new Map());
  
  const [overlays, setOverlays] = useState<OverlayToggles>({
    atr: true,
    ib: true,
    tpo: true,
    priorTPO: true,
    gapFill: true,
    vwap: true,
    overnight: true,
  });

  const { data: bars = [], error, isLoading } = useSWR<OHLCVBar[]>(
    ["/analyze/bars/MES", "5m", 3],
    () => fetchBars("MES", { timeframe: "5m", days: 3 }),
    { refreshInterval: 60_000, revalidateOnFocus: false }
  );

  const levels = calculateAllLevels(bars);

  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height: Math.min(600, window.innerHeight - 200),
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

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: "#00ff88",
      downColor: "#ff4466",
      borderUpColor: "#00ff88",
      borderDownColor: "#ff4466",
      wickUpColor: "#00ff88",
      wickDownColor: "#ff4466",
    });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;

    const handleResize = () => {
      if (containerRef.current && chartRef.current) {
        chartRef.current.applyOptions({
          width: containerRef.current.clientWidth,
          height: Math.min(600, window.innerHeight - 200),
        });
      }
    };

    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);
      chart.remove();
    };
  }, []);

  useEffect(() => {
    if (!candleSeriesRef.current || bars.length === 0) return;

    const candleData = bars.map((bar) => ({
      time: bar.time as Time,
      open: bar.open,
      high: bar.high,
      low: bar.low,
      close: bar.close,
    }));

    candleSeriesRef.current.setData(candleData);

    if (chartRef.current) {
      chartRef.current.timeScale().fitContent();
    }
  }, [bars]);

  useEffect(() => {
    if (!candleSeriesRef.current) return;

    priceLineRefs.current.forEach((line) => {
      candleSeriesRef.current?.removePriceLine(line);
    });
    priceLineRefs.current.clear();

    if (overlays.atr && levels.atrLevels) {
      const upper = candleSeriesRef.current.createPriceLine({
        price: levels.atrLevels.upperLevel,
        color: "#22d3ee",
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: "+ATR",
      });
      const lower = candleSeriesRef.current.createPriceLine({
        price: levels.atrLevels.lowerLevel,
        color: "#22d3ee",
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: "-ATR",
      });
      priceLineRefs.current.set("atr_upper", upper);
      priceLineRefs.current.set("atr_lower", lower);
    }

    if (overlays.ib && levels.initialBalance) {
      const ibHigh = candleSeriesRef.current.createPriceLine({
        price: levels.initialBalance.high,
        color: "#a855f7",
        lineWidth: 2,
        lineStyle: LineStyle.Solid,
        axisLabelVisible: true,
        title: "IB High",
      });
      const ibLow = candleSeriesRef.current.createPriceLine({
        price: levels.initialBalance.low,
        color: "#a855f7",
        lineWidth: 2,
        lineStyle: LineStyle.Solid,
        axisLabelVisible: true,
        title: "IB Low",
      });
      priceLineRefs.current.set("ib_high", ibHigh);
      priceLineRefs.current.set("ib_low", ibLow);
    }

    if (overlays.tpo && levels.tpoValueArea) {
      const vah = candleSeriesRef.current.createPriceLine({
        price: levels.tpoValueArea.vah,
        color: "#facc15",
        lineWidth: 1,
        lineStyle: LineStyle.Solid,
        axisLabelVisible: true,
        title: "VAH",
      });
      const val = candleSeriesRef.current.createPriceLine({
        price: levels.tpoValueArea.val,
        color: "#facc15",
        lineWidth: 1,
        lineStyle: LineStyle.Solid,
        axisLabelVisible: true,
        title: "VAL",
      });
      const poc = candleSeriesRef.current.createPriceLine({
        price: levels.tpoValueArea.poc,
        color: "#f97316",
        lineWidth: 2,
        lineStyle: LineStyle.Solid,
        axisLabelVisible: true,
        title: "POC",
      });
      priceLineRefs.current.set("vah", vah);
      priceLineRefs.current.set("val", val);
      priceLineRefs.current.set("poc", poc);
    }

    if (overlays.priorTPO && levels.priorTPO) {
      const pVah = candleSeriesRef.current.createPriceLine({
        price: levels.priorTPO.vah,
        color: "#facc15",
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: "Prior VAH",
      });
      const pVal = candleSeriesRef.current.createPriceLine({
        price: levels.priorTPO.val,
        color: "#facc15",
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: "Prior VAL",
      });
      const pPoc = candleSeriesRef.current.createPriceLine({
        price: levels.priorTPO.poc,
        color: "#f97316",
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: "Prior POC",
      });
      priceLineRefs.current.set("prior_vah", pVah);
      priceLineRefs.current.set("prior_val", pVal);
      priceLineRefs.current.set("prior_poc", pPoc);
    }

    if (overlays.gapFill && levels.gapFillLevel) {
      const gapFill = candleSeriesRef.current.createPriceLine({
        price: levels.gapFillLevel,
        color: "#3b82f6",
        lineWidth: 2,
        lineStyle: LineStyle.Dotted,
        axisLabelVisible: true,
        title: "Gap Fill",
      });
      priceLineRefs.current.set("gap_fill", gapFill);
    }

    if (overlays.vwap && levels.sessionVWAP) {
      const vwap = candleSeriesRef.current.createPriceLine({
        price: levels.sessionVWAP,
        color: "#10b981",
        lineWidth: 2,
        lineStyle: LineStyle.Solid,
        axisLabelVisible: true,
        title: "VWAP",
      });
      priceLineRefs.current.set("vwap", vwap);
    }

    if (overlays.overnight && levels.overnightHighLow) {
      const onHigh = candleSeriesRef.current.createPriceLine({
        price: levels.overnightHighLow.high,
        color: "#6366f1",
        lineWidth: 1,
        lineStyle: LineStyle.Dotted,
        axisLabelVisible: true,
        title: "ON High",
      });
      const onLow = candleSeriesRef.current.createPriceLine({
        price: levels.overnightHighLow.low,
        color: "#6366f1",
        lineWidth: 1,
        lineStyle: LineStyle.Dotted,
        axisLabelVisible: true,
        title: "ON Low",
      });
      priceLineRefs.current.set("on_high", onHigh);
      priceLineRefs.current.set("on_low", onLow);
    }
  }, [overlays, levels]);

  const toggleOverlay = (key: keyof OverlayToggles) => {
    setOverlays((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  return (
    <div className="min-h-screen bg-background p-4 md:p-6">
      <div className="max-w-7xl mx-auto space-y-4">
        <ExploratoryBanner what="ES candlestick overlays are a research visualization" />
        <div>
          <h1 className="text-2xl md:text-3xl font-bold text-foreground">ES Candlestick Chart</h1>
          <p className="text-sm text-muted-foreground mt-1">
            5-minute bars with technical overlays. Toggle levels from the legend below.
          </p>
        </div>

        {error && (
          <div className="bg-destructive/10 border border-destructive/20 rounded-lg p-4">
            <p className="text-sm text-destructive">Failed to load chart data</p>
          </div>
        )}

        {isLoading && (
          <div className="bg-card border border-border rounded-lg p-8 text-center">
            <p className="text-muted-foreground">Loading bars...</p>
          </div>
        )}

        {!isLoading && !error && (
          <>
            <div className="bg-card border border-border rounded-lg p-2 md:p-4 overflow-x-auto">
              <div ref={containerRef} className="w-full min-w-[320px]" />
            </div>

            <div className="bg-card border border-border rounded-lg p-4 space-y-4">
              <h2 className="text-lg font-semibold text-foreground">Legend & Toggles</h2>
              
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                <button
                  onClick={() => toggleOverlay("atr")}
                  className="flex items-center justify-between p-3 rounded border border-border hover:bg-accent/50 transition-colors"
                >
                  <div className="flex items-center gap-2">
                    <div className={`w-3 h-3 rounded-full ${overlays.atr ? "bg-cyan-400" : "bg-muted"}`} />
                    <span className="text-sm font-medium">ATR Levels</span>
                  </div>
                  {levels.atrLevels && (
                    <Badge variant="info" className="text-xs">
                      {levels.atrLevels.rangeUsedPct.toFixed(0)}% used
                    </Badge>
                  )}
                </button>

                <button
                  onClick={() => toggleOverlay("ib")}
                  className="flex items-center justify-between p-3 rounded border border-border hover:bg-accent/50 transition-colors"
                >
                  <div className="flex items-center gap-2">
                    <div className={`w-3 h-3 rounded-full ${overlays.ib ? "bg-purple-500" : "bg-muted"}`} />
                    <span className="text-sm font-medium">Initial Balance</span>
                  </div>
                </button>

                <button
                  onClick={() => toggleOverlay("tpo")}
                  className="flex items-center justify-between p-3 rounded border border-border hover:bg-accent/50 transition-colors"
                >
                  <div className="flex items-center gap-2">
                    <div className={`w-3 h-3 rounded-full ${overlays.tpo ? "bg-yellow-400" : "bg-muted"}`} />
                    <span className="text-sm font-medium">TPO Value Area (Today)</span>
                  </div>
                </button>

                <button
                  onClick={() => toggleOverlay("priorTPO")}
                  className="flex items-center justify-between p-3 rounded border border-border hover:bg-accent/50 transition-colors"
                >
                  <div className="flex items-center gap-2">
                    <div className={`w-3 h-3 rounded-full ${overlays.priorTPO ? "bg-yellow-400 opacity-50" : "bg-muted"}`} />
                    <span className="text-sm font-medium">TPO Value Area (Prior)</span>
                  </div>
                </button>

                <button
                  onClick={() => toggleOverlay("gapFill")}
                  className="flex items-center justify-between p-3 rounded border border-border hover:bg-accent/50 transition-colors"
                >
                  <div className="flex items-center gap-2">
                    <div className={`w-3 h-3 rounded-full ${overlays.gapFill ? "bg-blue-500" : "bg-muted"}`} />
                    <span className="text-sm font-medium">Gap Fill Level</span>
                  </div>
                </button>

                <button
                  onClick={() => toggleOverlay("vwap")}
                  className="flex items-center justify-between p-3 rounded border border-border hover:bg-accent/50 transition-colors"
                >
                  <div className="flex items-center gap-2">
                    <div className={`w-3 h-3 rounded-full ${overlays.vwap ? "bg-green-500" : "bg-muted"}`} />
                    <span className="text-sm font-medium">Session VWAP</span>
                  </div>
                </button>

                <button
                  onClick={() => toggleOverlay("overnight")}
                  className="flex items-center justify-between p-3 rounded border border-border hover:bg-accent/50 transition-colors"
                >
                  <div className="flex items-center gap-2">
                    <div className={`w-3 h-3 rounded-full ${overlays.overnight ? "bg-indigo-500" : "bg-muted"}`} />
                    <span className="text-sm font-medium">Overnight High/Low</span>
                  </div>
                </button>
              </div>

              <div className="pt-3 border-t border-border space-y-2">
                <p className="text-xs text-muted-foreground">
                  <span className="font-semibold">ATR:</span> Prior RTH close ± 14-period Wilders daily ATR
                </p>
                <p className="text-xs text-muted-foreground">
                  <span className="font-semibold">IB:</span> First RTH hour high/low (8:30-9:30 CT)
                </p>
                <p className="text-xs text-muted-foreground">
                  <span className="font-semibold">TPO Value Area:</span> VAH/VAL/POC from 70% volume distribution
                </p>
                <p className="text-xs text-muted-foreground">
                  <span className="font-semibold">Gap Fill:</span> Prior RTH close
                </p>
                <p className="text-xs text-muted-foreground">
                  <span className="font-semibold">VWAP:</span> Volume-weighted average price for current session
                </p>
                <p className="text-xs text-muted-foreground">
                  <span className="font-semibold">Overnight:</span> High/low from non-RTH bars
                </p>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
