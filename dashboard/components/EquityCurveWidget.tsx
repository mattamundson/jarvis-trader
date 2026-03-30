"use client";

import React, { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";

const ENGINE_URL = process.env.NEXT_PUBLIC_ENGINE_URL || "http://localhost:8010";

interface DailyPnlRecord {
  date: string;
  realized_pnl: number;
  num_trades: number;
  cumulative_pnl: number;
}

interface DailyPnlResponse {
  records: DailyPnlRecord[];
}

function formatCurrencyLocal(value: number): string {
  const abs = Math.abs(value);
  const formatted = abs.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return `${value < 0 ? "-" : ""}$${formatted}`;
}

export function EquityCurveWidget() {
  const [records, setRecords] = useState<DailyPnlRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function fetchHistory() {
      try {
        const res = await fetch(
          `${ENGINE_URL}/portfolio/history/daily-pnl?limit=90`
        );
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data: DailyPnlResponse = await res.json();
        setRecords(data.records ?? []);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load");
      } finally {
        setLoading(false);
      }
    }
    fetchHistory();
  }, []);

  const totalPnL = records.length > 0
    ? records[records.length - 1].cumulative_pnl
    : 0;

  const badgeVariant =
    totalPnL > 0 ? "bull" : totalPnL < 0 ? "bear" : "neutral";
  const badgeLabel =
    totalPnL > 0 ? "PROFIT" : totalPnL < 0 ? "LOSS" : "FLAT";
  const pnlColor =
    totalPnL > 0
      ? "text-bull"
      : totalPnL < 0
      ? "text-bear"
      : "text-muted-foreground";

  const firstDate = records.length > 0 ? records[0].date : "";
  const lastDate = records.length > 0 ? records[records.length - 1].date : "";

  // Build SVG chart
  const svgWidth = 400;
  const svgHeight = 140;
  const yPadTop = 10;
  const yPadBot = 10;
  const yRange = svgHeight - yPadTop - yPadBot; // 120

  function buildChart(recs: DailyPnlRecord[]): React.ReactNode {
    if (recs.length === 0) return null;

    const values = recs.map((r) => r.cumulative_pnl);
    const minVal = Math.min(...values);
    const maxVal = Math.max(...values);
    const allZero = minVal === 0 && maxVal === 0;

    // Map value to y coordinate (inverted — top = high)
    function toY(val: number): number {
      if (allZero) return svgHeight / 2;
      const span = maxVal - minVal || 1;
      return yPadTop + yRange - ((val - minVal) / span) * yRange;
    }

    // Map index to x coordinate
    function toX(i: number): number {
      if (recs.length === 1) return svgWidth / 2;
      return (i / (recs.length - 1)) * svgWidth;
    }

    // Zero line y position
    const zeroY = toY(0);

    // Line/fill color
    const endVal = values[values.length - 1];
    let stroke: string;
    let fill: string;
    if (allZero || endVal === 0) {
      stroke = "currentColor";
      fill = "rgba(100,100,100,0.1)";
    } else if (endVal > 0) {
      stroke = "#22c55e";
      fill = "rgba(34,197,94,0.1)";
    } else {
      stroke = "#ef4444";
      fill = "rgba(239,68,68,0.1)";
    }

    // Build path points
    const points = recs.map((r, i) => ({
      x: toX(i),
      y: toY(r.cumulative_pnl),
    }));

    // Line path
    const linePath = points
      .map((p, i) => `${i === 0 ? "M" : "L"} ${p.x.toFixed(2)} ${p.y.toFixed(2)}`)
      .join(" ");

    // Area fill path: line + close to bottom
    const areaPath =
      linePath +
      ` L ${points[points.length - 1].x.toFixed(2)} ${svgHeight}` +
      ` L ${points[0].x.toFixed(2)} ${svgHeight}` +
      " Z";

    return (
      <>
        {/* Zero baseline */}
        <line
          x1="0"
          y1={zeroY}
          x2={svgWidth}
          y2={zeroY}
          stroke="currentColor"
          strokeOpacity="0.3"
          strokeDasharray="4,2"
          strokeWidth="1"
        />
        {/* Area fill */}
        <path d={areaPath} fill={fill} stroke="none" />
        {/* Line */}
        <path
          d={linePath}
          fill="none"
          stroke={stroke}
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </>
    );
  }

  return (
    <Card>
      <CardHeader
        className={cn(
          "flex flex-row items-center justify-between space-y-0 pb-2"
        )}
      >
        <CardTitle>Equity Curve</CardTitle>
        <div className="flex items-center gap-2">
          {!loading && (
            <>
              <span
                className={cn(
                  "text-lg font-mono font-bold",
                  pnlColor
                )}
              >
                {formatCurrencyLocal(totalPnL)}
              </span>
              <Badge variant={badgeVariant}>{badgeLabel}</Badge>
            </>
          )}
          {loading && (
            <span className="text-sm text-muted-foreground">Loading…</span>
          )}
        </div>
      </CardHeader>

      <CardContent>
        {loading ? (
          <div className="h-[140px] flex items-center justify-center">
            <div className="h-[140px] w-full bg-muted rounded animate-pulse" />
          </div>
        ) : error ? (
          <div className="h-[140px] flex items-center justify-center text-xs text-muted-foreground">
            Failed to load history: {error}
          </div>
        ) : records.length === 0 ? (
          <div className="h-[140px] flex items-center justify-center text-sm text-muted-foreground">
            No trade history yet
          </div>
        ) : (
          <svg
            viewBox={`0 0 ${svgWidth} ${svgHeight}`}
            preserveAspectRatio="none"
            className="w-full"
            style={{ height: "140px" }}
          >
            {buildChart(records)}
          </svg>
        )}

        <div className="flex justify-between text-xs text-muted-foreground mt-1">
          <span>{firstDate}</span>
          <span>Last 90 days</span>
          <span>{lastDate}</span>
        </div>
      </CardContent>
    </Card>
  );
}
