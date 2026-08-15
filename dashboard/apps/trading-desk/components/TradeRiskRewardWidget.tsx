"use client";

import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  type HonestTradeSet,
  dedupCaveat,
} from "@/lib/honestTrades";
import { useHonestTrades } from "@/lib/useHonestTrades";

// ── Metric derivation ─────────────────────────────────────────────────────────

interface RRMetrics {
  avgWin: number;
  avgLoss: number;
  riskReward: number | null;
  totalTrades: number;
  profitFactor: number | null;
  expectancy: number;
  winRate: number; // 0..1
}

function deriveMetrics(set: HonestTradeSet): RRMetrics {
  const { trades, winRate, profitFactor, net } = set;

  const winners = trades.filter((t) => t.pnl > 0);
  const losers = trades.filter((t) => t.pnl < 0);

  const avgWin =
    winners.length > 0
      ? winners.reduce((s, t) => s + t.pnl, 0) / winners.length
      : 0;

  const avgLoss =
    losers.length > 0
      ? Math.abs(losers.reduce((s, t) => s + t.pnl, 0) / losers.length)
      : 0;

  // R:R = avgWin / |avgLoss|; null when no losses to ratio against
  const riskReward: number | null =
    avgLoss < 0.01 ? null : avgWin === 0 ? 0 : avgWin / avgLoss;

  // expectancy = net / n  (equivalent to winRate*avgWin - lossRate*avgLoss)
  const totalTrades = trades.length;
  const expectancy = totalTrades > 0 ? net / totalTrades : 0;

  return {
    avgWin,
    avgLoss,
    riskReward,
    totalTrades,
    profitFactor,
    expectancy,
    winRate,
  };
}

// ── Badge helpers ─────────────────────────────────────────────────────────────

function rrBadgeVariant(rr: number | null): "bull" | "warn" | "bear" | "neutral" {
  if (rr === null) return "neutral";
  if (rr >= 2.0) return "bull";
  if (rr >= 1.0) return "warn";
  return "bear";
}

// ── Sub-components ────────────────────────────────────────────────────────────

interface StatCellProps {
  label: string;
  value: string;
  valueClass?: string;
}

function StatCell({ label, value, valueClass = "text-foreground" }: StatCellProps) {
  return (
    <div className="rounded-lg border border-border/50 bg-background/20 px-4 py-3 flex flex-col gap-1">
      <p className="text-xs text-muted-foreground uppercase tracking-wider">{label}</p>
      <p className={`text-sm font-semibold font-mono tabular-nums ${valueClass}`}>{value}</p>
    </div>
  );
}

// ── Widget ────────────────────────────────────────────────────────────────────

export function TradeRiskRewardWidget() {
  const { honest: set, isLoading: loading, error: loadError } = useHonestTrades(300_000);
  const error = loadError ? (loadError instanceof Error ? loadError.message : String(loadError)) : null;

  const metrics = set ? deriveMetrics(set) : null;
  const rrDisplay =
    metrics?.riskReward === null || metrics?.riskReward === undefined
      ? "—"
      : `${metrics.riskReward.toFixed(2)}:1`;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>Risk:Reward Analysis</CardTitle>
          {metrics && !loading && !error && (
            <Badge variant={rrBadgeVariant(metrics.riskReward)}>
              {rrDisplay}
            </Badge>
          )}
        </div>
      </CardHeader>
      <CardContent>
        {loading && (
          <p className="text-xs text-muted-foreground animate-pulse">
            Loading trade history&hellip;
          </p>
        )}

        {!loading && error && (
          <p className="text-xs text-red-400">Error: {error}</p>
        )}

        {!loading && !error && metrics && metrics.totalTrades === 0 && (
          <p className="text-xs text-muted-foreground">
            No closed trades with P&amp;L data found.
          </p>
        )}

        {!loading && !error && metrics && metrics.totalTrades > 0 && (
          <div className="space-y-4">
            {/* Big R:R metric */}
            <div className="flex flex-col items-center justify-center rounded-xl border border-border/50 bg-background/30 py-5 gap-1">
              <p className="text-xs text-muted-foreground uppercase tracking-widest">
                R:R Ratio
              </p>
              <p className="text-4xl font-bold font-mono tabular-nums text-foreground leading-none">
                {rrDisplay}
              </p>
              <Badge variant={rrBadgeVariant(metrics.riskReward)} className="mt-1">
                {metrics.riskReward === null
                  ? "No Loss Data"
                  : metrics.riskReward >= 2.0
                  ? "Excellent"
                  : metrics.riskReward >= 1.0
                  ? "Acceptable"
                  : "Below Target"}
              </Badge>
            </div>

            {/* Row of 4 stats */}
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
              <StatCell
                label="Avg Win"
                value={`$${metrics.avgWin.toFixed(2)}`}
                valueClass="text-green-400"
              />
              <StatCell
                label="Avg Loss"
                value={`$${metrics.avgLoss.toFixed(2)}`}
                valueClass="text-red-400"
              />
              <StatCell
                label="Profit Factor"
                value={
                  metrics.profitFactor === null
                    ? "—"
                    : metrics.profitFactor === Infinity
                    ? "&#8734;"
                    : `${metrics.profitFactor.toFixed(2)}x`
                }
                valueClass={
                  metrics.profitFactor !== null && metrics.profitFactor >= 2.0
                    ? "text-green-400"
                    : metrics.profitFactor !== null && metrics.profitFactor >= 1.0
                    ? "text-yellow-400"
                    : "text-red-400"
                }
              />
              <StatCell
                label="Expectancy"
                value={`${metrics.expectancy >= 0 ? "+" : ""}$${metrics.expectancy.toFixed(2)}/trade`}
                valueClass={metrics.expectancy >= 0 ? "text-green-400" : "text-red-400"}
              />
            </div>

            {/* Footer */}
            <div className="flex items-center justify-between pt-1 border-t border-border/50 text-xs text-muted-foreground">
              <span>
                {set ? dedupCaveat(set) : `${metrics.totalTrades} trades`}
                {" • "}
                {(metrics.winRate * 100).toFixed(1)}% win rate
              </span>
              <span className="text-muted-foreground/60 italic">
                Backtest target: 2.14:1
              </span>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default TradeRiskRewardWidget;
