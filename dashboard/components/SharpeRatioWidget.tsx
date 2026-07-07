"use client";

import React from "react";
import { TrendingUp, RefreshCw, AlertTriangle, Info } from "lucide-react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { perTradeSharpe } from "@/lib/honestTrades";
import { useHonestTrades } from "@/lib/useHonestTrades";


// ── Helpers ────────────────────────────────────────────────────────────────────

/**
 * Interpret per-trade Sharpe (mean/stdev of trade P&L).
 * Thresholds are intentionally relaxed vs an annualized Sharpe — this is a
 * trade-dispersion ratio, not a time-normalised risk metric.
 */
function getSharpeInterpretation(sharpe: number | null): {
  label: string;
  variant: "bull" | "bear" | "warn" | "info" | "neutral";
  description: string;
} {
  if (sharpe === null) {
    return {
      label: "N/A",
      variant: "neutral",
      description: "Insufficient trades to compute dispersion ratio (need ≥2 trades with non-zero variance).",
    };
  }
  if (sharpe < 0) {
    return {
      label: "Negative",
      variant: "bear",
      description: "Average trade P&L is negative — losses outweigh wins in expectancy.",
    };
  }
  if (sharpe < 0.3) {
    return {
      label: "Poor",
      variant: "bear",
      description: "Low consistency relative to trade-to-trade dispersion.",
    };
  }
  if (sharpe < 0.6) {
    return {
      label: "Below Target",
      variant: "warn",
      description: "Moderate trade-level consistency. Variance is high relative to mean.",
    };
  }
  if (sharpe < 1.0) {
    return {
      label: "Acceptable",
      variant: "warn",
      description: "Reasonable trade consistency. Mean P&L outpacing dispersion.",
    };
  }
  return {
    label: "Strong",
    variant: "bull",
    description: "Strong trade-level consistency — mean P&L well above standard deviation.",
  };
}

function formatCurrency(value: number): string {
  const abs = Math.abs(value);
  const formatted =
    abs >= 1000
      ? `$${(abs / 1000).toFixed(1)}k`
      : `$${abs.toFixed(2)}`;
  return value < 0 ? `-${formatted}` : `+${formatted}`;
}

function formatPercent(fraction: number): string {
  return `${(fraction * 100).toFixed(1)}%`;
}

// ── Stat Cell ─────────────────────────────────────────────────────────────────

function StatCell({
  label,
  value,
  colorClass = "text-foreground",
}: {
  label: string;
  value: string;
  colorClass?: string;
}) {
  return (
    <div className="rounded-lg bg-muted/40 px-3 py-2 text-center min-w-0">
      <p className="text-[10px] text-muted-foreground uppercase tracking-wider mb-0.5 truncate">
        {label}
      </p>
      <p className={`tabular-nums text-sm font-bold font-mono truncate ${colorClass}`}>{value}</p>
    </div>
  );
}

// ── Main Widget ────────────────────────────────────────────────────────────────

export function SharpeRatioWidget() {
  const { honest: set, isLoading: loading, error: loadError } = useHonestTrades(30_000);
  const error = loadError ? (loadError instanceof Error ? loadError.message : String(loadError)) : null;
  const sharpe = set ? perTradeSharpe(set.trades) : null;
  const lastRefresh = set ? new Date() : null;

  const interpretation = getSharpeInterpretation(sharpe);
  const GAUGE_MAX = 1.5;
  const gaugeWidth = sharpe !== null ? Math.min(100, Math.max(0, (sharpe / GAUGE_MAX) * 100)) : 0;
  const gaugeColor =
    sharpe === null
      ? "var(--muted)"
      : sharpe >= 1.0
      ? "var(--bull)"
      : sharpe >= 0.6
      ? "var(--warn)"
      : "var(--bear)";

  const tradeCount = set?.trades.length ?? 0;
  const winRate = set?.winRate ?? 0;
  const net = set?.net ?? 0;

  return (
    <Card className="border-accent/20">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <div className="flex h-7 w-7 items-center justify-center rounded-md bg-accent/10">
              <TrendingUp className="h-4 w-4 text-accent" />
            </div>
            <CardTitle>Sharpe Ratio</CardTitle>
          </div>
          {!loading && !error && (
            <Badge variant={interpretation.variant}>{interpretation.label}</Badge>
          )}
          {!loading && error && (
            <Badge variant="bear">Offline</Badge>
          )}
          {loading && (
            <Badge variant="neutral">Loading...</Badge>
          )}
        </div>
      </CardHeader>

      <CardContent>
        {/* Loading state */}
        {loading && (
          <div className="flex items-center justify-center py-10 gap-3">
            <div className="h-4 w-4 rounded-full border-2 border-accent border-t-transparent animate-spin" />
            <span className="text-sm text-muted-foreground">Fetching deduped trade record...</span>
          </div>
        )}

        {/* Error state */}
        {!loading && error && (
          <div className="rounded-lg border border-bear/20 bg-bear/5 p-4 flex items-start gap-3">
            <AlertTriangle className="h-4 w-4 text-bear shrink-0 mt-0.5" />
            <div>
              <p className="text-sm font-semibold text-bear">Engine unavailable</p>
              <p className="text-xs text-muted-foreground mt-0.5">{error}</p>
              <p className="text-xs text-muted-foreground mt-1">
                Ensure the JARVIS engine is running and reachable through the dashboard proxy. Retrying every 30s.
              </p>
            </div>
          </div>
        )}

        {/* Data state */}
        {!loading && !error && set && (
          <div className="space-y-5">
            {/* Caveat banner */}
            <div className="flex items-start gap-2 rounded-md border border-muted bg-muted/20 px-3 py-2">
              <Info className="h-3.5 w-3.5 text-muted-foreground shrink-0 mt-0.5" />
              <p className="text-[11px] text-muted-foreground leading-snug">
                <span className="font-semibold text-foreground">Per-trade Sharpe (deduped, n={tradeCount})</span>
                {" "}— mean &divide; sample&nbsp;std of trade P&amp;L. This is a trade-level dispersion ratio,
                not an annualized Sharpe. It is not comparable to the broker&apos;s reported Sharpe.
              </p>
            </div>

            {/* Large Sharpe number */}
            <div className="text-center py-2">
              <p
                className="text-4xl font-bold tabular-nums font-mono"
                style={{ color: gaugeColor }}
              >
                {sharpe !== null ? sharpe.toFixed(3) : "—"}
              </p>
              <p className="text-xs text-muted-foreground mt-1">
                {interpretation.description}
              </p>
            </div>

            {/* Gauge bar */}
            {sharpe !== null && (
              <div>
                <div className="h-3 bg-muted rounded-full overflow-hidden">
                  <div
                    className="h-full rounded-full transition-all duration-500"
                    style={{
                      width: `${gaugeWidth}%`,
                      backgroundColor: gaugeColor,
                    }}
                  />
                </div>
                <div className="flex justify-between mt-1">
                  <span className="text-[9px] font-mono text-muted-foreground">0</span>
                  <span className="text-[9px] font-mono text-muted-foreground">0.5</span>
                  <span className="text-[9px] font-mono text-muted-foreground">1.0</span>
                  <span className="text-[9px] font-mono text-muted-foreground">{GAUGE_MAX.toFixed(1)}</span>
                </div>
              </div>
            )}

            {/* Supporting stats from deduped record */}
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 pt-1">
              <StatCell
                label="Win Rate"
                value={formatPercent(winRate)}
                colorClass={winRate >= 0.55 ? "text-bull" : winRate >= 0.45 ? "text-warn" : "text-bear"}
              />
              <StatCell
                label="Net P&L (deduped)"
                value={formatCurrency(net)}
                colorClass={net >= 0 ? "text-bull" : "text-bear"}
              />
              <StatCell
                label="Trade Count"
                value={String(tradeCount)}
                colorClass="text-foreground"
              />
            </div>

            {/* Last refresh */}
            {lastRefresh && (
              <div className="flex items-center gap-1.5 pt-1">
                <RefreshCw className="h-3 w-3 text-muted-foreground" />
                <span className="text-[10px] text-muted-foreground">
                  Last updated {lastRefresh.toLocaleTimeString()} — auto-refresh every 30s
                </span>
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
