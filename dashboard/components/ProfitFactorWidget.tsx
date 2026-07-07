"use client";

import React, { useState, useEffect } from "react";
import { BarChart3, RefreshCw, TrendingUp, TrendingDown, Hash, Trophy } from "lucide-react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchRealizedPnl, type RealizedPnl } from "@/lib/masterApi";

// Honest trade-record source: GET /master/trading/realized (read-time deduped).
// The raw /analytics/performance endpoint over-counts re-logged winners
// (fabricated PF 2.95 / +$3,899 vs the deduplicated reality PF 0.66 / -$8,188),
// so this widget reads profit factor / win-rate / avg win-loss / trade count
// from the honest engine_sim record. See lib/honestMetrics.ts.

// ── Badge helpers ──────────────────────────────────────────────────────────────

type BadgeVariant = "bull" | "bear" | "warn" | "info" | "neutral";

function pfBadgeVariant(pf: number | null): BadgeVariant {
  if (pf === null) return "neutral";
  if (pf < 1.0) return "bear";
  if (pf < 2.0) return "warn";
  return "bull";
}

function pfBadgeLabel(pf: number | null): string {
  if (pf === null) return "No Data";
  if (pf < 1.0) return "Losing";
  if (pf < 1.5) return "Below Target";
  if (pf < 2.0) return "Getting Close";
  return "Target Met ✓";
}

// ── Gauge bar colour ───────────────────────────────────────────────────────────

function gaugeColor(pf: number): string {
  if (pf >= 2.0) return "var(--bull)";
  if (pf >= 1.5) return "var(--warn)";
  return "var(--bear)";
}

// ── Currency formatter ─────────────────────────────────────────────────────────

function fmtCurrency(n: number): string {
  const abs = Math.abs(n);
  const formatted = abs.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return `${n < 0 ? "-" : ""}$${formatted}`;
}

// ── Component ──────────────────────────────────────────────────────────────────

export function ProfitFactorWidget() {
  const [data, setData] = useState<RealizedPnl | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);

  async function fetchData() {
    try {
      setLoading(true);
      const payload = await fetchRealizedPnl();
      if (!payload.engine_sim?.ok) {
        throw new Error(payload.engine_sim?.error || "honest trade record unavailable");
      }
      setData(payload);
      setError(null);
      setLastRefresh(new Date());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 30_000);
    return () => clearInterval(interval);
  }, []);

  const es = data?.engine_sim;
  const pf: number | null = es?.profit_factor ?? null;
  const avgWin: number = es && es.wins > 0 ? es.gross_win / es.wins : 0;
  const avgLoss: number = es && es.losses > 0 ? -(es.gross_loss / es.losses) : 0;
  const winRate: number = (es?.win_rate ?? 0) * 100;
  const totalTrades: number = es?.trades ?? 0;
  const recommendation: string = data?.headline ?? "";
  const trimmedRec = recommendation.length > 100 ? recommendation.slice(0, 100) + "…" : recommendation;

  const badgeVariant = pfBadgeVariant(pf);
  const badgeLabel = pfBadgeLabel(pf);

  const gaugeWidth = pf !== null ? Math.min(100, (pf / 3.0) * 100) : 0;
  const pfDisplay = pf !== null ? pf.toFixed(2) : "—";

  // Tick positions as percentages of 3.0
  const ticks: { value: number; label: string; isTarget?: boolean }[] = [
    { value: 0, label: "0" },
    { value: 1.0, label: "1.0" },
    { value: 1.5, label: "1.5" },
    { value: 2.0, label: "2.0", isTarget: true },
    { value: 3.0, label: "3.0" },
  ];

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <BarChart3 className="h-4 w-4 text-muted-foreground" />
            <CardTitle>Profit Factor</CardTitle>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant={badgeVariant}>{badgeLabel}</Badge>
            <button
              onClick={fetchData}
              disabled={loading}
              className="flex items-center rounded p-1 text-muted-foreground hover:text-foreground transition-colors disabled:opacity-40"
              aria-label="Refresh"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
            </button>
          </div>
        </div>
      </CardHeader>

      <CardContent className="space-y-5">
        {/* Large PF number */}
        <div className="flex flex-col items-center py-2">
          <span
            className="text-4xl font-bold font-mono"
            style={{ color: pf !== null ? gaugeColor(pf) : undefined }}
          >
            {pfDisplay}
          </span>
          <span className="text-xs text-muted-foreground mt-1">Profit Factor</span>
        </div>

        {/* Gauge bar */}
        <div className="space-y-1.5">
          <div className="relative h-3 bg-muted rounded-full overflow-hidden">
            <div
              className="h-full rounded-full transition-all duration-500"
              style={{
                width: `${gaugeWidth}%`,
                backgroundColor: pf !== null ? gaugeColor(pf) : "var(--muted)",
              }}
            />
          </div>

          {/* Tick labels */}
          <div className="relative h-5">
            {ticks.map((tick) => {
              const leftPct = (tick.value / 3.0) * 100;
              return (
                <span
                  key={tick.value}
                  className={`absolute -translate-x-1/2 text-[10px] leading-none whitespace-nowrap ${
                    tick.isTarget
                      ? "text-accent font-semibold"
                      : "text-muted-foreground"
                  }`}
                  style={{ left: `${leftPct}%` }}
                >
                  {tick.isTarget ? `${tick.label} TARGET` : tick.label}
                </span>
              );
            })}
          </div>
        </div>

        {/* Stats grid */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 pt-1">
          {/* Avg Win */}
          <div className="rounded-lg bg-muted/40 p-3 flex flex-col gap-1">
            <div className="flex items-center gap-1 text-[10px] text-muted-foreground uppercase tracking-wide font-medium">
              <TrendingUp className="h-3 w-3" />
              Avg Win
            </div>
            <span className="text-sm font-mono font-bold text-bull">
              {loading ? "…" : fmtCurrency(avgWin)}
            </span>
          </div>

          {/* Avg Loss */}
          <div className="rounded-lg bg-muted/40 p-3 flex flex-col gap-1">
            <div className="flex items-center gap-1 text-[10px] text-muted-foreground uppercase tracking-wide font-medium">
              <TrendingDown className="h-3 w-3" />
              Avg Loss
            </div>
            <span className="text-sm font-mono font-bold text-bear">
              {loading ? "…" : fmtCurrency(avgLoss)}
            </span>
          </div>

          {/* Win Rate */}
          <div className="rounded-lg bg-muted/40 p-3 flex flex-col gap-1">
            <div className="flex items-center gap-1 text-[10px] text-muted-foreground uppercase tracking-wide font-medium">
              <Trophy className="h-3 w-3" />
              Win Rate
            </div>
            <span className="text-sm font-mono font-bold text-foreground">
              {loading ? "…" : `${winRate.toFixed(1)}%`}
            </span>
          </div>

          {/* Total Trades */}
          <div className="rounded-lg bg-muted/40 p-3 flex flex-col gap-1">
            <div className="flex items-center gap-1 text-[10px] text-muted-foreground uppercase tracking-wide font-medium">
              <Hash className="h-3 w-3" />
              Total Trades
            </div>
            <span className="text-sm font-mono font-bold text-foreground">
              {loading ? "…" : String(totalTrades)}
            </span>
          </div>
        </div>

        {/* Target note */}
        <p className="text-xs text-muted-foreground text-center">
          Target: &ge; 2.0 for live trading approval
        </p>

        {/* Recommendation */}
        {trimmedRec && (
          <p className="text-xs text-muted-foreground border-t border-border pt-3 leading-relaxed">
            {trimmedRec}
          </p>
        )}

        {/* Error */}
        {error && (
          <p className="text-xs text-bear text-center border border-bear/20 rounded-lg px-3 py-2">
            Error: {error}
          </p>
        )}

        {/* Last refresh */}
        <p className="text-[10px] text-muted-foreground text-right">
          {lastRefresh
            ? `Last refresh: ${lastRefresh.toLocaleTimeString()}`
            : loading
            ? "Loading…"
            : "Not yet loaded"}
        </p>
      </CardContent>
    </Card>
  );
}
