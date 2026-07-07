"use client";

import { useState, useEffect, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { GitCompare } from "lucide-react";
import { fetchEngine } from "@/lib/api";
import {
  fetchHonestTrades,
  dedupCaveat,
  exitDate,
  type HonestTradeSet,
} from "@/lib/honestTrades";

// ── Types ─────────────────────────────────────────────────────────────────────

/** Backtest-reference side of /analytics/performance/compare (engine key: "backtest"). */
interface BacktestRef {
  profit_factor: number;
  sharpe_ratio: number;
  win_rate: number;
}

/** Each gate the engine reports as { required, met, current? }. */
interface ThresholdGate {
  required: number;
  met?: boolean;
  current?: number;
}

/**
 * Engine's compare_to_backtest() validation_thresholds — nested gates, NOT flat
 * min_* numbers. The engine gates PF, Sharpe, and trading DAYS; there is no
 * win-rate or trade-count gate here.
 */
interface ValidationThresholds {
  profit_factor?: ThresholdGate;
  sharpe_ratio?: ThresholdGate;
  min_trading_days?: ThresholdGate;
}

interface CompareResponse {
  backtest: BacktestRef;
  validation_thresholds: ValidationThresholds;
  degradation_factor?: {
    profit_factor: number | null;
    sharpe_ratio: number | null;
    note?: string;
  };
}

// ── Constants ─────────────────────────────────────────────────────────────────

const REFRESH_INTERVAL_MS = 2 * 60 * 1000; // 2 minutes

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmt(v: number | null | undefined, decimals = 2): string {
  return v != null ? v.toFixed(decimals) : "—";
}

// ── Sub-components ────────────────────────────────────────────────────────────

function SkeletonRow() {
  return (
    <tr className="border-b border-border">
      {[0, 1, 2].map((i) => (
        <td key={i} className="px-4 py-3">
          <div className="h-4 rounded bg-muted animate-pulse" />
        </td>
      ))}
    </tr>
  );
}

// ── Main Component ────────────────────────────────────────────────────────────

export function BacktestComparisonCard() {
  const [ref, setRef] = useState<CompareResponse | null>(null);
  const [honest, setHonest] = useState<HonestTradeSet | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      // Fetch both sources concurrently; honest trades is the paper side
      const [refData, honestData] = await Promise.all([
        fetchEngine<CompareResponse>(`/analytics/performance/compare`, {
          cache: "no-store",
        }),
        fetchHonestTrades(),
      ]);
      setRef(refData);
      setHonest(honestData);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const interval = setInterval(load, REFRESH_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [load]);

  // ── Derived pass/fail (honest paper vs backtest thresholds) ───────────────

  // The engine gates on PF, Sharpe, and trading DAYS — there is no win-rate or
  // trade-count gate here. Win rate is shown as an informational paper-vs-
  // backtest reference only.
  const thresholds = ref?.validation_thresholds;
  const minPf = thresholds?.profit_factor?.required ?? null;
  const minSharpe = thresholds?.sharpe_ratio?.required ?? null;
  const minDays = thresholds?.min_trading_days?.required ?? null;

  // Paper-side values come from the honest deduped record
  const paperPf = honest?.profitFactor ?? null;
  const paperWr = honest != null ? honest.winRate * 100 : null; // 0..100
  // Trading days = distinct local close-dates in the deduped record (matches the
  // engine's min_trading_days gate, not raw trade count).
  const paperTradingDays = honest
    ? new Set(honest.trades.map((t) => exitDate(t)).filter(Boolean)).size
    : null;

  const pfPass = paperPf != null && minPf != null && paperPf >= minPf;
  // Sharpe is not computable from the deduped record (no annualised Sharpe) —
  // surfaced as "—"/N/A and excluded from the pass tally.
  const daysPass =
    paperTradingDays != null && minDays != null && paperTradingDays >= minDays;

  // Only the gates the engine defines AND we can honestly evaluate.
  const allPass = pfPass && daysPass;

  interface MetricRowDef {
    label: string;
    paperValue: string;
    targetValue: string;
    badgeVariant: "bull" | "bear" | "warn" | "info" | "neutral";
    badgeLabel: string;
  }

  // Backtest win rate may arrive as a fraction (0..1) or a percent (0..100);
  // normalize to percent for the reference display.
  const backtestWrPct =
    ref?.backtest?.win_rate != null
      ? ref.backtest.win_rate <= 1
        ? ref.backtest.win_rate * 100
        : ref.backtest.win_rate
      : null;

  const metricRows: MetricRowDef[] =
    honest != null
      ? [
          {
            label: "Profit Factor",
            paperValue: fmt(paperPf),
            targetValue: minPf != null ? `≥ ${fmt(minPf)}` : "—",
            badgeVariant: pfPass ? "bull" : "bear",
            badgeLabel: pfPass ? "PASS" : "FAIL",
          },
          {
            label: "Sharpe Ratio",
            paperValue: "—",
            targetValue: minSharpe != null ? `≥ ${fmt(minSharpe)}` : "—",
            // Sharpe not computable from deduped record — neutral, not FAIL
            badgeVariant: "neutral",
            badgeLabel: "N/A",
          },
          {
            label: "Win Rate %",
            paperValue: paperWr != null ? `${paperWr.toFixed(1)}%` : "—",
            // No engine win-rate gate — show the backtest win rate as a reference.
            targetValue:
              backtestWrPct != null ? `bt ${backtestWrPct.toFixed(1)}%` : "—",
            badgeVariant: "neutral",
            badgeLabel: "REF",
          },
          {
            label: "Trading Days",
            paperValue:
              paperTradingDays != null ? String(paperTradingDays) : "—",
            targetValue: minDays != null ? `≥ ${minDays}` : "—",
            badgeVariant: daysPass ? "bull" : "warn",
            badgeLabel: daysPass ? "PASS" : "IN PROGRESS",
          },
        ]
      : [];

  // Degradation: honest PF vs backtest PF
  const backtestPf = ref?.backtest?.profit_factor ?? null;
  const degradationPct =
    backtestPf != null && backtestPf > 0 && paperPf != null
      ? ((paperPf / backtestPf) * 100).toFixed(1)
      : null;

  const caveat = honest ? dedupCaveat(honest) : null;

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2 text-sm">
            <GitCompare className="h-4 w-4" />
            Backtest vs. Paper Trading
          </CardTitle>
          {!loading && honest && (
            <Badge variant={allPass ? "bull" : "neutral"}>
              {allPass ? "VALIDATION PASS" : "NOT YET"}
            </Badge>
          )}
        </div>
      </CardHeader>

      <CardContent>
        {error && (
          <p className="text-sm text-red-400 mb-3">
            Engine offline — {error}
          </p>
        )}

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border">
                <th className="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground">
                  Metric
                </th>
                <th className="px-4 py-2 text-center text-xs font-medium uppercase tracking-wider text-muted-foreground">
                  Paper Trading
                </th>
                <th className="px-4 py-2 text-center text-xs font-medium uppercase tracking-wider text-muted-foreground">
                  Target
                </th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <>
                  <SkeletonRow />
                  <SkeletonRow />
                  <SkeletonRow />
                  <SkeletonRow />
                </>
              ) : !honest ? (
                <tr>
                  <td
                    colSpan={3}
                    className="px-4 py-6 text-center text-sm text-muted-foreground"
                  >
                    No comparison data available
                  </td>
                </tr>
              ) : (
                metricRows.map((row) => (
                  <tr
                    key={row.label}
                    className="border-b border-border last:border-0"
                  >
                    <td className="px-4 py-3 text-muted-foreground">
                      {row.label}
                    </td>
                    <td className="px-4 py-3 text-center font-mono font-medium tabular-nums text-foreground">
                      {row.paperValue}
                    </td>
                    <td className="px-4 py-3 text-center">
                      <div className="flex flex-col items-center gap-1">
                        <span className="font-mono text-xs text-muted-foreground">
                          {row.targetValue}
                        </span>
                        <Badge variant={row.badgeVariant}>
                          {row.badgeLabel}
                        </Badge>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Footer — degradation factor + dedup caveat + overall status */}
        {!loading && honest && (
          <div className="mt-3 pt-3 border-t border-border space-y-2">
            <div className="flex items-center justify-between gap-2 flex-wrap">
              <p className="text-xs text-muted-foreground">
                Degradation factor:{" "}
                <span className="font-mono font-medium text-foreground">
                  {degradationPct ?? "—"}{degradationPct != null ? "%" : ""}
                </span>{" "}
                of backtest PF achieved in live paper trading
              </p>
              <Badge variant={allPass ? "bull" : "neutral"}>
                {allPass ? "VALIDATION PASS" : "NOT YET"}
              </Badge>
            </div>
            {caveat && (
              <p className="text-xs text-muted-foreground font-mono">
                {caveat}
              </p>
            )}
            {honest.caveats.length > 0 && (
              <ul className="text-xs text-muted-foreground space-y-0.5 list-disc list-inside">
                {honest.caveats.map((c, i) => (
                  <li key={i}>{c}</li>
                ))}
              </ul>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
