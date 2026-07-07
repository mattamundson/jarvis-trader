"use client";

import React from "react";
import { RefreshCw, TrendingDown, AlertTriangle, ShieldCheck } from "lucide-react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  equityCurve,
  type HonestTradeSet,
  dedupCaveat,
} from "@/lib/honestTrades";
import { useHonestTrades } from "@/lib/useHonestTrades";


// Circuit breaker limit (from engine config / settings.MAX_DRAWDOWN_PCT default)
const CIRCUIT_BREAKER_LIMIT_PCT = 15;

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * Recovery gain % needed to return to peak from a drawdown.
 * Formula: recovery = drawdown / (1 - drawdown) * 100
 * where drawdown is the positive fraction (e.g. 0.082 for 8.2%).
 */
function calcRecoveryPct(drawdownPct: number): number {
  const d = drawdownPct / 100;
  if (d >= 1) return Infinity;
  return (d / (1 - d)) * 100;
}

type BadgeVariant = "bull" | "bear" | "warn" | "info" | "neutral";

function getDrawdownLevel(pct: number): {
  variant: BadgeVariant;
  label: string;
  fillColor: string;
  textColor: string;
} {
  if (pct < 5) {
    return {
      variant: "bull",
      label: "Safe",
      fillColor: "bg-bull",
      textColor: "text-bull",
    };
  }
  if (pct <= 10) {
    return {
      variant: "warn",
      label: "Caution",
      fillColor: "bg-warn",
      textColor: "text-warn",
    };
  }
  return {
    variant: "bear",
    label: "Danger",
    fillColor: "bg-bear",
    textColor: "text-bear",
  };
}

// ── Widget ────────────────────────────────────────────────────────────────────

export function MaxDrawdownTrackerWidget() {
  const { honest: honestSet, isLoading: loading, error: loadError, mutate: fetchData } = useHonestTrades(0);
  const error = loadError ? (loadError instanceof Error ? loadError.message : String(loadError)) : null;

  // Derive max drawdown (peak-to-trough in USD) from honest equity curve
  // The honest equity curve tracks drawdown as: equity - running_peak (always <= 0)
  const curve = honestSet ? equityCurve(honestSet.trades) : [];
  const peakEquity = curve.length > 0 ? Math.max(...curve.map((p) => p.equity)) : 0;
  // Max drawdown = worst (most negative) drawdown point
  const maxDrawdownUsd =
    curve.length > 0 ? Math.min(...curve.map((p) => p.drawdown)) : 0; // <= 0

  // Express as % of peak (avoid division by zero when peak <= 0)
  const drawdownPct =
    peakEquity > 0 ? (Math.abs(maxDrawdownUsd) / peakEquity) * 100 : 0;

  const recoveryPct = calcRecoveryPct(drawdownPct);
  const gaugeWidth = Math.min(100, (drawdownPct / CIRCUIT_BREAKER_LIMIT_PCT) * 100);

  const level = getDrawdownLevel(drawdownPct);

  // Determine status icon
  const StatusIcon =
    level.variant === "bull"
      ? ShieldCheck
      : level.variant === "warn"
      ? AlertTriangle
      : TrendingDown;

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <TrendingDown className="h-4 w-4 text-muted-foreground" />
            <CardTitle>Max Drawdown Tracker</CardTitle>
            <Badge variant={level.variant}>{level.label}</Badge>
          </div>
          <button
            onClick={() => fetchData()}
            disabled={loading}
            className="flex items-center gap-1 rounded border border-border px-2 py-1 text-xs text-muted-foreground hover:text-foreground transition-colors disabled:opacity-40"
          >
            <RefreshCw className={`h-3 w-3 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </button>
        </div>
        <p className="text-xs text-muted-foreground pt-0.5">
          Peak-to-trough equity drawdown — circuit breaker at {CIRCUIT_BREAKER_LIMIT_PCT}%
        </p>
      </CardHeader>

      <CardContent className="space-y-5">
        {loading ? (
          <div className="animate-pulse space-y-4">
            <div className="h-14 w-32 bg-muted rounded" />
            <div className="h-3 w-full bg-muted rounded-full" />
            <div className="grid grid-cols-3 gap-4">
              {[0, 1, 2].map((i) => (
                <div key={i} className="space-y-1.5">
                  <div className="h-2.5 w-16 bg-muted rounded" />
                  <div className="h-4 w-10 bg-muted rounded" />
                </div>
              ))}
            </div>
          </div>
        ) : error ? (
          <p className="text-sm text-bear">Error: {error}</p>
        ) : (
          <>
            {/* ── Large drawdown number ───────────────────────────────── */}
            <div className="flex items-end gap-3">
              <div>
                <p className="text-[10px] text-muted-foreground uppercase tracking-wide font-medium mb-0.5">
                  Current Max Drawdown
                </p>
                <p
                  className={`text-5xl font-bold font-mono leading-none ${level.textColor}`}
                >
                  {drawdownPct.toFixed(1)}%
                </p>
              </div>
              <div className="flex flex-col items-start gap-1 pb-1">
                <StatusIcon className={`h-5 w-5 ${level.textColor}`} />
                <Badge variant={level.variant} className="text-[10px]">
                  {level.label.toUpperCase()}
                </Badge>
              </div>
            </div>

            {/* ── Visual gauge ────────────────────────────────────────── */}
            <div className="space-y-1.5">
              <div className="flex items-center justify-between text-xs">
                <span className="font-medium text-foreground">Drawdown vs Limit</span>
                <span className="font-mono text-muted-foreground">
                  {drawdownPct.toFixed(1)}% of {CIRCUIT_BREAKER_LIMIT_PCT}% limit
                </span>
              </div>
              <div className="relative h-3 w-full rounded-full bg-muted overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all duration-500 ${level.fillColor}`}
                  style={{ width: `${gaugeWidth}%` }}
                />
              </div>
              {/* Tick marks at 5%, 10%, 15% */}
              <div className="relative h-2 w-full">
                {[5, 10, 15].map((tick) => {
                  const pos = (tick / CIRCUIT_BREAKER_LIMIT_PCT) * 100;
                  return (
                    <span
                      key={tick}
                      className="absolute text-[9px] text-muted-foreground -translate-x-1/2"
                      style={{ left: `${pos}%` }}
                    >
                      {tick}%
                    </span>
                  );
                })}
              </div>
            </div>

            {/* ── Stats grid ──────────────────────────────────────────── */}
            <div className="grid grid-cols-3 gap-4 pt-1 border-t border-border">
              {/* Circuit Breaker Limit */}
              <div className="space-y-0.5">
                <p className="text-[10px] text-muted-foreground uppercase tracking-wide font-medium">
                  CB Limit
                </p>
                <p className="text-sm font-mono font-bold text-foreground">
                  {CIRCUIT_BREAKER_LIMIT_PCT}%
                </p>
                <p className="text-[10px] text-muted-foreground">engine config</p>
              </div>

              {/* Headroom remaining */}
              <div className="space-y-0.5">
                <p className="text-[10px] text-muted-foreground uppercase tracking-wide font-medium">
                  Headroom
                </p>
                <p
                  className={`text-sm font-mono font-bold ${
                    CIRCUIT_BREAKER_LIMIT_PCT - drawdownPct > 5
                      ? "text-bull"
                      : CIRCUIT_BREAKER_LIMIT_PCT - drawdownPct > 2
                      ? "text-warn"
                      : "text-bear"
                  }`}
                >
                  {Math.max(0, CIRCUIT_BREAKER_LIMIT_PCT - drawdownPct).toFixed(1)}%
                </p>
                <p className="text-[10px] text-muted-foreground">to breaker</p>
              </div>

              {/* Recovery needed */}
              <div className="space-y-0.5">
                <p className="text-[10px] text-muted-foreground uppercase tracking-wide font-medium">
                  Recovery Needed
                </p>
                <p className={`text-sm font-mono font-bold ${level.textColor}`}>
                  {isFinite(recoveryPct) ? `+${recoveryPct.toFixed(1)}%` : "N/A"}
                </p>
                <p className="text-[10px] text-muted-foreground">to reach peak</p>
              </div>
            </div>

            {/* ── Context row ─────────────────────────────────────────── */}
            {honestSet && (
              <div className="rounded-lg border border-border bg-muted/30 px-4 py-3 grid grid-cols-2 gap-x-6 gap-y-2">
                <div className="flex justify-between text-xs">
                  <span className="text-muted-foreground">Total Trades</span>
                  <span className="font-mono font-medium text-foreground">
                    {honestSet.trades.length}
                  </span>
                </div>
                <div className="flex justify-between text-xs">
                  <span className="text-muted-foreground">Peak Equity</span>
                  <span className="font-mono font-medium text-foreground">
                    {peakEquity >= 0 ? "+" : ""}${peakEquity.toFixed(0)}
                  </span>
                </div>
                <div className="flex justify-between text-xs">
                  <span className="text-muted-foreground">Win Rate</span>
                  <span className="font-mono font-medium text-foreground">
                    {(honestSet.winRate * 100).toFixed(1)}%
                  </span>
                </div>
                <div className="flex justify-between text-xs">
                  <span className="text-muted-foreground">Max DD (USD)</span>
                  <span className="font-mono font-medium text-bear">
                    ${maxDrawdownUsd.toFixed(0)}
                  </span>
                </div>
              </div>
            )}

            {/* ── Recovery formula footnote ────────────────────────────── */}
            <p className="text-[10px] text-muted-foreground">
              Recovery formula: drawdown / (1 &minus; drawdown) &times; 100 &mdash; A{" "}
              {drawdownPct.toFixed(1)}% drawdown requires a{" "}
              {isFinite(recoveryPct) ? `${recoveryPct.toFixed(1)}%` : "—"} gain to recover.
              {honestSet && <> &middot; {dedupCaveat(honestSet)}</>}
            </p>
          </>
        )}
      </CardContent>
    </Card>
  );
}
