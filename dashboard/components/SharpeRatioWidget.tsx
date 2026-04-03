"use client";

import React, { useState, useEffect } from "react";
import { TrendingUp, RefreshCw, Target, AlertTriangle } from "lucide-react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchEngine } from "@/lib/api";


// ── Types ──────────────────────────────────────────────────────────────────────

interface PerformanceMetrics {
  profit_factor: number;
  sharpe_ratio: number;
  win_rate: number;
  total_trades: number;
  period_days: number;
  max_drawdown: number;
  total_pnl: number;
  avg_win: number;
  avg_loss: number;
  meets_paper_threshold: boolean;
}

interface PerformanceThresholds {
  min_profit_factor: number;
  min_sharpe: number;
  min_win_rate: number;
  min_trades: number;
  min_trading_days: number;
}

interface PerformanceResponse {
  status: string;
  metrics: PerformanceMetrics;
  thresholds: PerformanceThresholds;
  recommendation: string;
}

// ── Helpers ────────────────────────────────────────────────────────────────────

function getSharpeInterpretation(sharpe: number): {
  label: string;
  variant: "bull" | "bear" | "warn" | "info" | "neutral";
  description: string;
} {
  if (sharpe < 0.5) {
    return {
      label: "Poor",
      variant: "bear",
      description: "Strategy returns are not adequately compensating for risk taken.",
    };
  }
  if (sharpe < 1.0) {
    return {
      label: "Below Target",
      variant: "warn",
      description: "Moderate risk-adjusted returns. Significant improvement needed.",
    };
  }
  if (sharpe < 1.5) {
    return {
      label: "Getting Close",
      variant: "warn",
      description: "Acceptable risk-adjusted returns. Approaching the June 2026 target.",
    };
  }
  if (sharpe < 2.0) {
    return {
      label: "Target Met \u2713",
      variant: "bull",
      description: "Strong risk-adjusted returns. June 2026 live trading threshold cleared.",
    };
  }
  return {
    label: "Excellent",
    variant: "bull",
    description: "Exceptional risk-adjusted returns. Well above the live trading threshold.",
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

// ── Gauge Tick ─────────────────────────────────────────────────────────────────

function GaugeTick({
  value,
  label,
  isTarget,
  maxValue,
}: {
  value: number;
  label: string;
  isTarget: boolean;
  maxValue: number;
}) {
  const pct = (value / maxValue) * 100;
  return (
    <div
      className="absolute flex flex-col items-center"
      style={{ left: `${pct}%`, transform: "translateX(-50%)" }}
    >
      <div
        className={`w-px h-2 ${isTarget ? "bg-warn" : "bg-border"}`}
        style={{ marginTop: "-2px" }}
      />
      <span
        className={`text-[9px] font-mono mt-0.5 whitespace-nowrap ${
          isTarget ? "text-warn font-bold" : "text-muted-foreground"
        }`}
      >
        {isTarget ? `${label} TARGET` : label}
      </span>
    </div>
  );
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
  const [data, setData] = useState<PerformanceResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);

  async function fetchData() {
    try {
      const payload = await fetchEngine(`/analytics/performance`);
      setData(payload);
      setError(null);
      setLastRefresh(new Date());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch performance data");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 30000);
    return () => clearInterval(interval);
  }, []);

  const GAUGE_MAX = 3.0;
  const TARGET = 1.5;

  const sharpe = data?.metrics?.sharpe_ratio ?? 0;
  const interpretation = getSharpeInterpretation(sharpe);
  const gaugeWidth = Math.min(100, (sharpe / GAUGE_MAX) * 100);
  const gaugeColor =
    sharpe >= 1.5
      ? "var(--bull)"
      : sharpe >= 1.0
      ? "var(--warn)"
      : "var(--bear)";

  const winRate = data?.metrics?.win_rate ?? 0;
  const maxDrawdown = data?.metrics?.max_drawdown ?? 0;
  const totalPnl = data?.metrics?.total_pnl ?? 0;
  const periodDays = data?.metrics?.period_days ?? 0;

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
          {!loading && !error && data && (
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
            <span className="text-sm text-muted-foreground">Fetching performance data...</span>
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
                Ensure JARVIS engine is running on port 8010. Retrying every 30s.
              </p>
            </div>
          </div>
        )}

        {/* Data state */}
        {!loading && !error && data && (
          <div className="space-y-5">
            {/* Large Sharpe number */}
            <div className="text-center py-2">
              <p
                className="text-4xl font-bold tabular-nums font-mono"
                style={{ color: gaugeColor }}
              >
                {sharpe.toFixed(3)}
              </p>
              <p className="text-xs text-muted-foreground mt-1">
                {interpretation.description}
              </p>
              <div className="flex items-center justify-center gap-1.5 mt-2">
                <Target className="h-3 w-3 text-warn" />
                <span className="text-[11px] text-warn font-semibold">
                  Target: {TARGET.toFixed(1)} (June 2026 live trading requirement)
                </span>
              </div>
            </div>

            {/* Gauge bar */}
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
              {/* Tick marks */}
              <div className="relative mt-1 h-5" style={{ marginLeft: "0", marginRight: "0" }}>
                {[
                  { value: 0, label: "0" },
                  { value: 0.5, label: "0.5" },
                  { value: 1.0, label: "1.0" },
                  { value: 1.5, label: "1.5", isTarget: true },
                  { value: 2.0, label: "2.0" },
                  { value: 3.0, label: "3.0" },
                ].map((tick) => (
                  <GaugeTick
                    key={tick.value}
                    value={tick.value}
                    label={tick.label}
                    isTarget={tick.isTarget === true}
                    maxValue={GAUGE_MAX}
                  />
                ))}
              </div>
            </div>

            {/* Supporting stats */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 pt-1">
              <StatCell
                label="Win Rate"
                value={formatPercent(winRate)}
                colorClass={winRate >= 0.55 ? "text-bull" : winRate >= 0.45 ? "text-warn" : "text-bear"}
              />
              <StatCell
                label="Max Drawdown"
                value={`${(Math.abs(maxDrawdown) * 100).toFixed(2)}%`}
                colorClass={
                  Math.abs(maxDrawdown) < 0.05
                    ? "text-bull"
                    : Math.abs(maxDrawdown) < 0.10
                    ? "text-warn"
                    : "text-bear"
                }
              />
              <StatCell
                label="Total P&L"
                value={formatCurrency(totalPnl)}
                colorClass={totalPnl >= 0 ? "text-bull" : "text-bear"}
              />
              <StatCell
                label="Trading Days"
                value={String(periodDays)}
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
