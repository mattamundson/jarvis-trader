"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { TrendingUp } from "lucide-react";
import {
  exitDate,
  dedupCaveat,
  type HonestTrade,
} from "@/lib/honestTrades";
import { useHonestTrades } from "@/lib/useHonestTrades";

// ── Types ─────────────────────────────────────────────────────────────────────

interface WeeklyStats {
  /** Label shown in footer: "Last 7 days" */
  period: string;
  total_trades: number;
  wins: number;
  losses: number;
  win_rate: number;
  total_pnl: number;
  avg_pnl: number;
  best_trade: number | null;
  worst_trade: number | null;
  /** distinct close-date count */
  trading_days: number;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function pnlVariant(value: number | null): "bull" | "bear" | "neutral" {
  if (value == null) return "neutral";
  if (value > 0) return "bull";
  if (value < 0) return "bear";
  return "neutral";
}

function formatPnl(value: number | null | undefined): string {
  if (value == null) return "—";
  const sign = value >= 0 ? "+" : "";
  return `${sign}$${value.toFixed(2)}`;
}

/**
 * Derive weekly stats from the honest trade list.
 * "This week" = trades whose exit_time is within the last 7 calendar days.
 */
function deriveWeeklyStats(trades: HonestTrade[]): WeeklyStats | null {
  const now = Date.now();
  const sevenDaysMs = 7 * 24 * 60 * 60 * 1000;
  const cutoff = now - sevenDaysMs;

  const recent = trades.filter((t) => {
    if (!t.exit_time) return false;
    const ms = Date.parse(t.exit_time);
    return !Number.isNaN(ms) && ms >= cutoff;
  });

  if (recent.length === 0) return null;

  const wins = recent.filter((t) => t.pnl > 0).length;
  const losses = recent.filter((t) => t.pnl < 0).length;
  const total_pnl = recent.reduce((s, t) => s + t.pnl, 0);
  const pnls = recent.map((t) => t.pnl);
  const tradingDates = new Set(recent.map((t) => exitDate(t)).filter(Boolean));

  return {
    period: "Last 7 days",
    total_trades: recent.length,
    wins,
    losses,
    win_rate: recent.length > 0 ? (wins / recent.length) * 100 : 0,
    total_pnl,
    avg_pnl: recent.length > 0 ? total_pnl / recent.length : 0,
    best_trade: pnls.length > 0 ? Math.max(...pnls) : null,
    worst_trade: pnls.length > 0 ? Math.min(...pnls) : null,
    trading_days: tradingDates.size,
  };
}

// ── Component ─────────────────────────────────────────────────────────────────

export function WeeklyStatsWidget() {
  const { honest: tradeSet, isLoading: loading, error: loadError } = useHonestTrades(120_000);
  const fetchError = !!loadError;
  const data = tradeSet ? deriveWeeklyStats(tradeSet.trades) : null;

  if (loading) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-2">
            <TrendingUp className="h-4 w-4" />
            Weekly Performance
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            <div className="animate-pulse h-8 bg-muted rounded" />
            <div className="animate-pulse h-8 bg-muted rounded" />
          </div>
        </CardContent>
      </Card>
    );
  }

  if (fetchError || !data) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-2">
            <TrendingUp className="h-4 w-4" />
            Weekly Performance
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            {fetchError ? "Unable to load weekly stats" : "No trades in the last 7 days"}
          </p>
        </CardContent>
      </Card>
    );
  }

  const stats: Array<{ label: string; value: React.ReactNode }> = [
    {
      label: "Trades",
      value: (
        <span className="font-mono font-medium">{data.total_trades}</span>
      ),
    },
    {
      label: "Win Rate",
      value: (
        <span className="font-mono font-medium">
          {data.win_rate != null ? data.win_rate.toFixed(1) : "—"}%
        </span>
      ),
    },
    {
      label: "Total P&L",
      value: (
        <Badge variant={pnlVariant(data.total_pnl)}>
          {formatPnl(data.total_pnl)}
        </Badge>
      ),
    },
    {
      label: "Avg P&L",
      value: (
        <Badge variant={pnlVariant(data.avg_pnl)}>
          {formatPnl(data.avg_pnl)}
        </Badge>
      ),
    },
    {
      label: "Best Trade",
      value: (
        <Badge variant={pnlVariant(data.best_trade)}>
          {formatPnl(data.best_trade)}
        </Badge>
      ),
    },
    {
      label: "Worst Trade",
      value: (
        <Badge variant={pnlVariant(data.worst_trade)}>
          {formatPnl(data.worst_trade)}
        </Badge>
      ),
    },
  ];

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm flex items-center gap-2">
          <TrendingUp className="h-4 w-4" />
          Weekly Performance
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid grid-cols-3 gap-3">
          {stats.map((s) => (
            <div key={s.label} className="space-y-1">
              <div className="text-xs text-muted-foreground">{s.label}</div>
              <div>{s.value}</div>
            </div>
          ))}
        </div>
        <div
          className="pt-2 font-mono text-[10px] text-muted-foreground"
          style={{ borderTop: "1px solid hsl(var(--border))" }}
        >
          Trading days: {data.trading_days} &bull; Period: {data.period}
          {tradeSet && (
            <span className="ml-2 opacity-70">&bull; {dedupCaveat(tradeSet)}</span>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
