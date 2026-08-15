"use client";

import React from "react";
import useSWR from "swr";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
} from "@/components/ui/card";
import {
  equityCurve,
  type HonestTradeSet,
  type EquityPoint,
  dedupCaveat,
} from "@/lib/honestTrades";
import { useHonestTrades } from "@/lib/useHonestTrades";
import { fetchEngine } from "@/lib/api";

// ── Types ─────────────────────────────────────────────────────────────────────

interface PaperPhaseSummary {
  starting_balance: number;
}

// ── Fetcher ───────────────────────────────────────────────────────────────────

const fetchPaperPhaseSummary = () =>
  fetchEngine<PaperPhaseSummary>("/portfolio/stats/paper-phase-summary");

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtCurrency(value: number): string {
  const abs = Math.abs(value);
  const formatted = abs.toLocaleString("en-US", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  });
  return `${value < 0 ? "-" : ""}$${formatted}`;
}

function fmtCurrencyFull(value: number): string {
  const abs = Math.abs(value);
  const formatted = abs.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return `${value < 0 ? "-" : ""}$${formatted}`;
}

// ── Chart constants ───────────────────────────────────────────────────────────

const VB_W = 600;
const VB_H = 200;
const PAD_LEFT = 50;
const PAD_RIGHT = 20;
const PAD_TOP = 20;
const PAD_BOTTOM = 30;

const PLOT_W = VB_W - PAD_LEFT - PAD_RIGHT;
const PLOT_H = VB_H - PAD_TOP - PAD_BOTTOM;

// ── Component ─────────────────────────────────────────────────────────────────

export function EquityCurveWidget() {
  const { honest: honestSet, isLoading: loading, error: loadError } = useHonestTrades(120_000);
  const error = loadError ? (loadError instanceof Error ? loadError.message : String(loadError)) : null;
  const curve: EquityPoint[] = honestSet ? equityCurve(honestSet.trades) : [];

  const { data: phaseSummary } = useSWR<PaperPhaseSummary>(
    "portfolio/stats/paper-phase-summary",
    fetchPaperPhaseSummary,
    { refreshInterval: 120_000 }
  );
  const startingCapital =
    phaseSummary && phaseSummary.starting_balance > 0
      ? phaseSummary.starting_balance
      : 10_000.0;

  // ── Derived data ──────────────────────────────────────────────────────────

  // Equity values for chart (cumulative P&L per close)
  const cumulative: number[] = curve.map((p) => p.equity);

  const totalPnl = curve.length > 0 ? curve[curve.length - 1].equity : 0;
  const peakPnl = curve.length > 0 ? Math.max(...cumulative) : 0;
  const fromPeak = totalPnl - peakPnl;

  const minCum = cumulative.length > 0 ? Math.min(0, ...cumulative) : 0;
  const maxCum = cumulative.length > 0 ? Math.max(0, ...cumulative) : 0;

  // Badge
  let badgeVariant: "bull" | "bear" | "neutral";
  let badgeLabel: string;
  if (totalPnl > 0) {
    badgeVariant = "bull";
    badgeLabel = "PROFITABLE";
  } else if (totalPnl < 0) {
    badgeVariant = "bear";
    badgeLabel = "IN DRAWDOWN";
  } else {
    badgeVariant = "neutral";
    badgeLabel = "FLAT";
  }

  // Colors
  const isPositive = totalPnl >= 0;
  const strokeColor = isPositive ? "#22c55e" : "#ef4444";
  const fillColor = isPositive
    ? "rgba(34,197,94,0.15)"
    : "rgba(239,68,68,0.15)";
  const endDotColor = isPositive ? "#22c55e" : "#ef4444";

  // ── SVG coordinate helpers ────────────────────────────────────────────────

  function toX(index: number, total: number): number {
    if (total <= 1) return PAD_LEFT + PLOT_W / 2;
    return PAD_LEFT + (index / (total - 1)) * PLOT_W;
  }

  function toY(val: number): number {
    const range = maxCum - minCum || 1;
    return PAD_TOP + PLOT_H - ((val - minCum) / range) * PLOT_H;
  }

  // Zero-line Y
  const zeroY = toY(0);

  // Build chart SVG contents
  function buildChart(): React.ReactNode {
    const n = cumulative.length;
    if (n === 0) return null;

    // For single trade, just draw a dot
    if (n === 1) {
      const cx = toX(0, 1);
      const cy = toY(cumulative[0]);
      return (
        <>
          {/* Zero baseline */}
          <line
            x1={PAD_LEFT}
            y1={zeroY}
            x2={VB_W - PAD_RIGHT}
            y2={zeroY}
            stroke="#666"
            strokeDasharray="4,4"
            strokeWidth="1"
          />
          <circle cx={cx} cy={cy} r={5} fill={endDotColor} />
        </>
      );
    }

    // Build point array
    const points = cumulative.map((v, i) => ({
      x: toX(i, n),
      y: toY(v),
    }));

    // Line path
    const linePath = points
      .map((p, i) => `${i === 0 ? "M" : "L"} ${p.x.toFixed(2)} ${p.y.toFixed(2)}`)
      .join(" ");

    // Area path: line + close bottom
    const areaPath =
      linePath +
      ` L ${points[n - 1].x.toFixed(2)} ${(PAD_TOP + PLOT_H).toFixed(2)}` +
      ` L ${points[0].x.toFixed(2)} ${(PAD_TOP + PLOT_H).toFixed(2)}` +
      " Z";

    // Local maxima (highest point)
    const maxVal = Math.max(...cumulative);
    const maxIdx = cumulative.indexOf(maxVal);
    const maxPt = points[maxIdx];

    // Endpoint
    const endPt = points[n - 1];

    return (
      <>
        {/* Zero baseline */}
        <line
          x1={PAD_LEFT}
          y1={zeroY}
          x2={VB_W - PAD_RIGHT}
          y2={zeroY}
          stroke="#666"
          strokeDasharray="4,4"
          strokeWidth="1"
        />
        {/* Area fill */}
        <path d={areaPath} fill={fillColor} stroke="none" />
        {/* Line */}
        <path
          d={linePath}
          fill="none"
          stroke={strokeColor}
          strokeWidth={2}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        {/* Local maxima dot */}
        {maxIdx !== n - 1 && (
          <circle cx={maxPt.x} cy={maxPt.y} r={3} fill="#22c55e" />
        )}
        {/* Endpoint dot */}
        <circle cx={endPt.x} cy={endPt.y} r={4} fill={endDotColor} />
      </>
    );
  }

  // ── Y-axis labels ─────────────────────────────────────────────────────────

  function buildYAxis(): React.ReactNode {
    if (cumulative.length === 0) return null;
    const labelX = PAD_LEFT - 4;
    const labels: { val: number; y: number }[] = [];

    labels.push({ val: maxCum, y: toY(maxCum) });
    if (minCum !== 0 && maxCum !== 0) {
      labels.push({ val: 0, y: toY(0) });
    }
    if (minCum !== maxCum) {
      labels.push({ val: minCum, y: toY(minCum) });
    }

    return labels.map(({ val, y }, i) => (
      <text
        key={i}
        x={labelX}
        y={y}
        textAnchor="end"
        dominantBaseline="middle"
        fontSize="9"
        fill="#888"
      >
        {fmtCurrency(val)}
      </text>
    ));
  }

  // ── X-axis labels ─────────────────────────────────────────────────────────

  function buildXAxis(): React.ReactNode {
    if (cumulative.length === 0) return null;
    const n = cumulative.length;
    const yPos = PAD_TOP + PLOT_H + 18;
    return (
      <>
        <text
          x={toX(0, n)}
          y={yPos}
          textAnchor="middle"
          fontSize="9"
          fill="#888"
        >
          Trade 1
        </text>
        <text
          x={toX(n - 1, n)}
          y={yPos}
          textAnchor="middle"
          fontSize="9"
          fill="#888"
        >
          Trade {n}
        </text>
      </>
    );
  }

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle>Equity Curve</CardTitle>
        <Badge variant={badgeVariant}>{badgeLabel}</Badge>
      </CardHeader>

      <CardContent>
        {loading ? (
          <div className="w-full h-[200px] bg-muted rounded animate-pulse" />
        ) : error ? (
          <div className="h-[200px] flex items-center justify-center text-sm text-muted-foreground">
            Equity curve unavailable
          </div>
        ) : curve.length === 0 ? (
          <div className="h-[200px] flex items-center justify-center text-sm text-muted-foreground text-center px-4">
            No closed trades yet — equity curve will appear here
          </div>
        ) : (
          <svg
            viewBox={`0 0 ${VB_W} ${VB_H}`}
            width="100%"
            preserveAspectRatio="none"
            style={{ display: "block" }}
          >
            {buildYAxis()}
            {buildXAxis()}
            {buildChart()}
          </svg>
        )}

        {/* Stats row */}
        {!loading && !error && (
          <div className="mt-4 pt-4 border-t border-border space-y-3">
            <div className="grid grid-cols-4 gap-4">
              <div className="space-y-1">
                <p className="text-[10px] text-muted-foreground uppercase tracking-wide font-medium">
                  Starting Capital
                </p>
                <p className="text-sm font-bold font-mono text-foreground">
                  {fmtCurrency(startingCapital)}
                </p>
              </div>
              <div className="space-y-1">
                <p className="text-[10px] text-muted-foreground uppercase tracking-wide font-medium">
                  Current P&amp;L
                </p>
                <p
                  className={`text-sm font-bold font-mono ${
                    totalPnl > 0
                      ? "text-green-500"
                      : totalPnl < 0
                      ? "text-red-500"
                      : "text-muted-foreground"
                  }`}
                >
                  {totalPnl >= 0 ? "+" : ""}
                  {fmtCurrencyFull(totalPnl)}
                </p>
              </div>
              <div className="space-y-1">
                <p className="text-[10px] text-muted-foreground uppercase tracking-wide font-medium">
                  Peak P&amp;L
                </p>
                <p className="text-sm font-bold font-mono text-foreground">
                  {peakPnl >= 0 ? "+" : ""}
                  {fmtCurrencyFull(peakPnl)}
                </p>
              </div>
              <div className="space-y-1">
                <p className="text-[10px] text-muted-foreground uppercase tracking-wide font-medium">
                  From Peak
                </p>
                <p
                  className={`text-sm font-bold font-mono ${
                    fromPeak < 0 ? "text-red-500" : "text-muted-foreground"
                  }`}
                >
                  {fromPeak > 0 ? "+" : ""}
                  {fmtCurrencyFull(fromPeak)}
                </p>
              </div>
            </div>
            {honestSet && (
              <p className="text-[10px] text-muted-foreground">
                {dedupCaveat(honestSet)}
              </p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
