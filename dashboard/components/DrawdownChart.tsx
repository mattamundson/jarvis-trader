"use client";

import { useEffect, useState } from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

const ENGINE_URL = process.env.NEXT_PUBLIC_ENGINE_URL || "http://localhost:8010";

interface DailyPnlRecord {
  date: string;
  realized_pnl: number;
  num_trades: number;
  cumulative_pnl: number;
}

interface DrawdownPoint {
  date: string;
  drawdown: number;
}

function formatCurrency(value: number): string {
  const abs = Math.abs(value);
  const formatted = abs.toFixed(0);
  return value < 0 ? `-$${formatted}` : `$${formatted}`;
}

function formatDate(dateStr: string): string {
  const d = new Date(dateStr);
  const month = d.getMonth() + 1;
  const day = d.getDate();
  return `${month}/${day}`;
}

export function DrawdownChart() {
  const [records, setRecords] = useState<DailyPnlRecord[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = () => {
      fetch(`${ENGINE_URL}/portfolio/history/daily-pnl?limit=90`)
        .then((r) => r.json())
        .then((d) => {
          const rows: DailyPnlRecord[] = d.records ?? [];
          setRecords(rows);
          setLoading(false);
        })
        .catch(() => setLoading(false));
    };
    load();
    const id = setInterval(load, 60_000);
    return () => clearInterval(id);
  }, []);

  // Determine if there is any trade data
  const hasData =
    records.length > 0 && records.some((r) => r.num_trades > 0);

  // Calculate drawdown series from cumulative_pnl
  const drawdownPoints: DrawdownPoint[] = [];
  let runningMax = -Infinity;

  for (const rec of records) {
    if (runningMax === -Infinity) {
      runningMax = rec.cumulative_pnl;
    } else {
      runningMax = Math.max(runningMax, rec.cumulative_pnl);
    }
    const dd = Math.min(0, rec.cumulative_pnl - runningMax);
    drawdownPoints.push({ date: rec.date, drawdown: dd });
  }

  // Max drawdown = most negative value
  const maxDrawdown =
    drawdownPoints.length > 0
      ? Math.min(...drawdownPoints.map((p) => p.drawdown))
      : 0;

  const maxDrawdownVariant =
    maxDrawdown < -10 ? "bear" : maxDrawdown < 0 ? "warn" : "bull";

  // SVG chart computations
  const W = 400;
  const H = 120;
  const BASELINE_Y = 4; // baseline at top (0 drawdown = top of chart)
  const BOTTOM_Y = H - 16; // bottom of chart area (for labels)
  const chartH = BOTTOM_Y - BASELINE_Y;

  const minDD = drawdownPoints.length > 0 ? Math.min(...drawdownPoints.map((p) => p.drawdown)) : 0;
  // If no drawdown at all, flat line at top
  const ddRange = minDD < 0 ? Math.abs(minDD) : 1;

  const toX = (i: number): number => {
    const n = drawdownPoints.length;
    if (n <= 1) return W / 2;
    return (i / (n - 1)) * W;
  };

  const toY = (dd: number): number => {
    // dd is 0 or negative; 0 maps to BASELINE_Y, minDD maps to BOTTOM_Y
    return BASELINE_Y + (Math.abs(dd) / ddRange) * chartH;
  };

  // Build SVG path: area from baseline down to drawdown values
  let areaPath = "";
  if (drawdownPoints.length > 0) {
    const points = drawdownPoints.map((p, i) => `${toX(i).toFixed(1)},${toY(p.drawdown).toFixed(1)}`);
    // Start at first point at baseline
    const firstX = toX(0).toFixed(1);
    const lastX = toX(drawdownPoints.length - 1).toFixed(1);
    areaPath =
      `M ${firstX},${BASELINE_Y} ` +
      `L ${points.join(" L ")} ` +
      `L ${lastX},${BASELINE_Y} Z`;
  }

  // Build stroke-only line path
  let linePath = "";
  if (drawdownPoints.length > 0) {
    const points = drawdownPoints.map(
      (p, i) => `${toX(i).toFixed(1)},${toY(p.drawdown).toFixed(1)}`
    );
    linePath = `M ${points.join(" L ")}`;
  }

  const firstDate = drawdownPoints.length > 0 ? formatDate(drawdownPoints[0].date) : "";
  const lastDate =
    drawdownPoints.length > 1
      ? formatDate(drawdownPoints[drawdownPoints.length - 1].date)
      : "";

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle>Drawdown</CardTitle>
        <Badge variant={maxDrawdownVariant}>
          Max: {formatCurrency(maxDrawdown)}
        </Badge>
      </CardHeader>
      <CardContent>
        {loading ? (
          <div className="h-[120px] rounded bg-muted animate-pulse" />
        ) : !hasData ? (
          <div className="h-[120px] flex items-center justify-center text-xs text-muted-foreground">
            No trade data available
          </div>
        ) : (
          <div className="relative">
            <svg
              viewBox="0 0 400 120"
              className="w-full h-[120px]"
              preserveAspectRatio="none"
            >
              {/* Baseline (zero drawdown) */}
              <line
                x1="0"
                y1={BASELINE_Y}
                x2="400"
                y2={BASELINE_Y}
                stroke="currentColor"
                strokeOpacity={0.2}
              />

              {/* Drawdown area fill */}
              {areaPath && (
                <path
                  d={areaPath}
                  stroke="#ef4444"
                  strokeWidth={1.5}
                  fill="rgba(239,68,68,0.15)"
                />
              )}

              {/* Drawdown line */}
              {linePath && (
                <path
                  d={linePath}
                  fill="none"
                  stroke="#ef4444"
                  strokeWidth={1.5}
                  strokeLinejoin="round"
                />
              )}

              {/* X-axis date labels */}
              {firstDate && (
                <text
                  x="2"
                  y={H - 2}
                  fontSize={8}
                  fill="currentColor"
                  fillOpacity={0.5}
                >
                  {firstDate}
                </text>
              )}
              {lastDate && (
                <text
                  x={W - 2}
                  y={H - 2}
                  fontSize={8}
                  textAnchor="end"
                  fill="currentColor"
                  fillOpacity={0.5}
                >
                  {lastDate}
                </text>
              )}

              {/* Y-axis: max drawdown value at bottom */}
              {minDD < 0 && (
                <text
                  x="2"
                  y={BOTTOM_Y - 2}
                  fontSize={8}
                  fill="currentColor"
                  fillOpacity={0.5}
                >
                  {formatCurrency(minDD)}
                </text>
              )}
            </svg>
          </div>
        )}
        <p className="text-xs text-muted-foreground mt-1">
          Last 90 days • Refreshes every 60s
        </p>
      </CardContent>
    </Card>
  );
}
