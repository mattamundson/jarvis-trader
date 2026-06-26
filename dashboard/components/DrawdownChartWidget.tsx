"use client";

import React from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  equityCurve,
  type EquityPoint,
} from "@/lib/honestTrades";
import { useHonestTrades } from "@/lib/useHonestTrades";


const REFRESH_INTERVAL_MS = 120_000;
const DD_LIMIT = 15; // percent — breach threshold
const DD_WARN = 10;  // percent — warning threshold
const DD_OK = 5;     // percent — healthy threshold

type LoadState = "loading" | "ok" | "error";

// ── SVG drawdown chart ─────────────────────────────────────────────────────

function DrawdownSVG({ series }: { series: number[] }) {
  const W = 600; // viewBox width (scales to 100%)
  const H = 120;
  const PAD_LEFT = 40;
  const PAD_RIGHT = 8;
  const PAD_TOP = 8;
  const PAD_BOTTOM = 20;

  const chartW = W - PAD_LEFT - PAD_RIGHT;
  const chartH = H - PAD_TOP - PAD_BOTTOM;

  const maxDD = Math.max(...series, DD_LIMIT + 2, 1);

  // Map value: 0 at top, maxDD at bottom
  const xOf = (i: number) =>
    PAD_LEFT + (series.length > 1 ? (i / (series.length - 1)) * chartW : chartW / 2);
  const yOf = (dd: number) =>
    PAD_TOP + (dd / maxDD) * chartH;

  const limitY = yOf(DD_LIMIT);

  // Build polyline points
  const points = series.map((dd, i) => `${xOf(i)},${yOf(dd)}`).join(" ");

  // Build filled area path
  const firstX = xOf(0);
  const lastX = xOf(series.length - 1);
  const bottomY = PAD_TOP + chartH;

  const areaPath =
    `M ${firstX},${yOf(series[0])} ` +
    series.map((dd, i) => `L ${xOf(i)},${yOf(dd)}`).join(" ") +
    ` L ${lastX},${bottomY} L ${firstX},${bottomY} Z`;

  const maxDDLabel = `${maxDD.toFixed(1)}%`;

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      width="100%"
      height={H}
      preserveAspectRatio="none"
      aria-label="Drawdown chart"
    >
      {/* Y-axis labels */}
      <text
        x={PAD_LEFT - 4}
        y={PAD_TOP + 4}
        textAnchor="end"
        fontSize={9}
        fill="currentColor"
        className="text-muted-foreground"
        style={{ fill: "rgba(120,120,130,0.8)" }}
      >
        {maxDDLabel}
      </text>
      <text
        x={PAD_LEFT - 4}
        y={PAD_TOP + chartH + 4}
        textAnchor="end"
        fontSize={9}
        fill="currentColor"
        style={{ fill: "rgba(120,120,130,0.8)" }}
      >
        0%
      </text>

      {/* Horizontal dashed line at 15% drawdown limit */}
      <line
        x1={PAD_LEFT}
        y1={limitY}
        x2={PAD_LEFT + chartW}
        y2={limitY}
        stroke="#ef4444"
        strokeWidth={1}
        strokeDasharray="4 3"
        opacity={0.5}
      />
      <text
        x={PAD_LEFT + chartW - 2}
        y={limitY - 3}
        textAnchor="end"
        fontSize={8}
        style={{ fill: "#ef4444", opacity: 0.7 }}
      >
        15% limit
      </text>

      {/* Filled area */}
      {series.length > 1 && (
        <path d={areaPath} fill="rgba(239,68,68,0.2)" stroke="none" />
      )}

      {/* Line */}
      {series.length === 1 ? (
        <circle
          cx={xOf(0)}
          cy={yOf(series[0])}
          r={3}
          fill="#ef4444"
        />
      ) : (
        <polyline
          points={points}
          fill="none"
          stroke="#ef4444"
          strokeWidth={1.5}
          strokeLinejoin="round"
          strokeLinecap="round"
        />
      )}

      {/* X-axis baseline */}
      <line
        x1={PAD_LEFT}
        y1={PAD_TOP + chartH}
        x2={PAD_LEFT + chartW}
        y2={PAD_TOP + chartH}
        stroke="rgba(120,120,130,0.3)"
        strokeWidth={1}
      />

      {/* Y-axis line */}
      <line
        x1={PAD_LEFT}
        y1={PAD_TOP}
        x2={PAD_LEFT}
        y2={PAD_TOP + chartH}
        stroke="rgba(120,120,130,0.3)"
        strokeWidth={1}
      />
    </svg>
  );
}

// ── Drawdown series from honest equity curve ──────────────────────────────────
// equityCurve returns { t, equity, drawdown } where drawdown <= 0 (distance
// below running peak). Convert to a positive percentage series for the chart.

function deriveSeries(curve: EquityPoint[]): number[] {
  return curve.map((pt) => {
    // peak = equity - drawdown (since drawdown <= 0)
    const peak = pt.equity - pt.drawdown;
    if (peak <= 0) return 0;
    return (Math.abs(pt.drawdown) / peak) * 100;
  });
}

// ── Main widget ────────────────────────────────────────────────────────────

export function DrawdownChartWidget() {
  const { honest: set, isLoading, error: loadError } = useHonestTrades(REFRESH_INTERVAL_MS);
  const loadState: LoadState = isLoading ? "loading" : loadError ? "error" : "ok";
  const series = set ? deriveSeries(equityCurve(set.trades)) : [];
  const tradeCount = set ? set.trades.filter((t) => t.exit_time).length : 0;

  const maxDrawdown = series.length > 0 ? Math.max(...series) : 0;

  // Badge and color logic
  type BadgeVariant = "bear" | "warn" | "bull" | "info";
  let badgeVariant: BadgeVariant;
  let badgeText: string;

  if (maxDrawdown > DD_LIMIT) {
    badgeVariant = "bear";
    badgeText = "BREACHED";
  } else if (maxDrawdown > DD_WARN) {
    badgeVariant = "warn";
    badgeText = "WARNING";
  } else if (maxDrawdown <= DD_OK) {
    badgeVariant = "bull";
    badgeText = "HEALTHY";
  } else {
    badgeVariant = "info";
    badgeText = "MODERATE";
  }

  const ddTextColor =
    maxDrawdown > DD_WARN
      ? "text-red-500"
      : maxDrawdown > DD_OK
      ? "text-orange-400"
      : "text-emerald-500";

  // ── Render states ──────────────────────────────────────────────────────

  if (loadState === "loading") {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Drawdown Chart</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="animate-pulse space-y-3">
            <div className="h-4 w-24 bg-muted rounded" />
            <div className="h-[120px] bg-muted rounded" />
          </div>
        </CardContent>
      </Card>
    );
  }

  if (loadState === "error") {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Drawdown Chart</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">Drawdown data unavailable</p>
        </CardContent>
      </Card>
    );
  }

  if (series.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Drawdown Chart</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">No closed trades yet</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>Drawdown Chart</CardTitle>
          <div className="flex items-center gap-2">
            <Badge variant="neutral" className="text-[10px]">Deduped</Badge>
            <Badge variant={badgeVariant}>{badgeText}</Badge>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {/* Large max drawdown display */}
        <div className="flex items-baseline gap-2 mb-3">
          <span className={`text-3xl font-bold font-mono ${ddTextColor}`}>
            {maxDrawdown.toFixed(1)}%
          </span>
          <span className="text-xs text-muted-foreground">
            max drawdown &mdash; {tradeCount} closed trades (deduped)
          </span>
        </div>

        {/* SVG chart */}
        <div className="w-full">
          <DrawdownSVG series={series} />
        </div>

        {/* Legend */}
        <div className="flex items-center gap-4 mt-2">
          <div className="flex items-center gap-1.5">
            <div className="w-4 h-0.5 bg-red-500 opacity-50 border-dashed border-t border-red-500" />
            <span className="text-[10px] text-muted-foreground">15% limit</span>
          </div>
          <div className="flex items-center gap-1.5">
            <div
              className="w-4 h-2 rounded-sm"
              style={{ background: "rgba(239,68,68,0.2)", border: "1px solid #ef4444" }}
            />
            <span className="text-[10px] text-muted-foreground">drawdown</span>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
