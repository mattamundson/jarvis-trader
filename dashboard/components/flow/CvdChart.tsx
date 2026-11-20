"use client";

import { useEffect, useRef } from "react";
import {
  createChart,
  ColorType,
  CandlestickSeries,
  LineSeries,
  type IChartApi,
  type ISeriesApi,
  type CandlestickData,
  type LineData,
} from "lightweight-charts";
import type { Bar1m, Gate } from "@/lib/flowTypes";

interface CvdChartProps {
  bars: Bar1m[];
  gates: Gate[];
  cvdLow: number;
  currentCvd: number;
}

export function CvdChart({ bars, gates, cvdLow, currentCvd }: CvdChartProps) {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const cvdSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);

  useEffect(() => {
    if (!chartContainerRef.current) return;

    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: "rgba(3, 7, 18, 0.6)" },
        textColor: "#94a3b8",
      },
      grid: {
        vertLines: { color: "rgba(148, 163, 184, 0.1)" },
        horzLines: { color: "rgba(148, 163, 184, 0.1)" },
      },
      width: chartContainerRef.current.clientWidth,
      height: 320,
      timeScale: {
        timeVisible: true,
        secondsVisible: false,
        borderColor: "#1e293b",
      },
      rightPriceScale: {
        borderColor: "#1e293b",
      },
    });

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: "#22c55e",
      downColor: "#ef4444",
      borderUpColor: "#22c55e",
      borderDownColor: "#ef4444",
      wickUpColor: "#22c55e",
      wickDownColor: "#ef4444",
    });

    const cvdSeries = chart.addSeries(LineSeries, {
      color: "#06b6d4",
      lineWidth: 2,
      priceScaleId: "cvd",
      title: "CVD",
    });

    chart.priceScale("cvd").applyOptions({
      scaleMargins: {
        top: 0.7,
        bottom: 0,
      },
      borderColor: "#1e293b",
    });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    cvdSeriesRef.current = cvdSeries;

    const handleResize = () => {
      if (chartContainerRef.current) {
        chart.applyOptions({ width: chartContainerRef.current.clientWidth });
      }
    };

    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);
      chart.remove();
    };
  }, []);

  useEffect(() => {
    if (!candleSeriesRef.current || !cvdSeriesRef.current || bars.length === 0) return;

    const candleData: CandlestickData[] = bars.map((bar) => ({
      time: Math.floor(new Date(bar.ts).getTime() / 1000) as any,
      open: bar.open,
      high: bar.high,
      low: bar.low,
      close: bar.close,
    }));

    const cvdStep = (currentCvd - cvdLow) / bars.length;
    const cvdData: LineData[] = bars.map((bar, i) => ({
      time: Math.floor(new Date(bar.ts).getTime() / 1000) as any,
      value: cvdLow + cvdStep * (i + 1),
    }));

    candleSeriesRef.current.setData(candleData);
    cvdSeriesRef.current.setData(cvdData);

    gates.forEach((gate) => {
      const color =
        gate.status === "broken"
          ? "#ef4444"
          : gate.status === "testing"
            ? "#eab308"
            : "#64748b";
      candleSeriesRef.current?.createPriceLine({
        price: gate.level,
        color,
        lineWidth: 1,
        lineStyle: 2,
        axisLabelVisible: true,
        title: `Gate ${gate.level}`,
      });
    });

    cvdSeriesRef.current.createPriceLine({
      price: cvdLow,
      color: "#dc2626",
      lineWidth: 1,
      lineStyle: 0,
      axisLabelVisible: true,
      title: "CVD Low",
    });

    chartRef.current?.timeScale().fitContent();
  }, [bars, gates, cvdLow, currentCvd]);

  return <div ref={chartContainerRef} className="w-full" />;
}
