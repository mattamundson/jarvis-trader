"use client";

import { useState, useEffect, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { GitCompare } from "lucide-react";
import { fetchEngine } from "@/lib/api";
import {
  fetchHonestTrades,
  dedupCaveat,
  type HonestTradeSet,
} from "@/lib/honestTrades";

// ── Types ─────────────────────────────────────────────────────────────────────

/** Shape of the backtest-reference side of /analytics/performance/compare */
interface BacktestRef {
  profit_factor: number;
  sharpe_ratio: number;
  win_rate: number;
}

interface ValidationThresholds {
  min_profit_factor: number;
  min_sharpe: number;
  min_win_rate: number;
  min_trades: number;
}

interface CompareResponse {
  backtested: BacktestRef;
  validation_thresholds: ValidationThresholds;
  /** kept for back-compat; not used for paper metrics any more */
  degradation_factor?: number;
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

  const thresholds = ref?.validation_thresholds;

  // Paper-side values come from the honest deduped record
  const paperPf = honest?.profitFactor ?? null;
  const paperWr = honest != null ? honest.winRate * 100 : null; // 0..100
  const paperTrades = honest?.trades.length ?? null;
  // Sharpe is not computable from the deduped record (no timestamps-per-trade
  // Sharpe vs annualised); surface "—"
  const paperSharpe: null = null;

  const pfPass =
    paperPf != null && thresholds != null && paperPf >= thresholds.min_profit_factor;
  const sharpePass = false; // always "—" / FAIL until real annualised Sharpe available
  const winRatePass =
    paperWr != null &&
    thresholds != null &&
    paperWr >= thresholds.min_win_rate;
  const tradesPass =
    paperTrades != null &&
    thresholds != null &&
    paperTrades >= thresholds.min_trades;

  const allPass = pfPass && winRatePass && tradesPass;
  // Note: sharpePass excluded from allPass because the metric is not available
  // from the deduped record — "NOT YET" is correct until that gap is filled.

  interface MetricRowDef {
    label: string;
    paperValue: string;
    targetValue: string;
    badgeVariant: "bull" | "bear" | "warn" | "info" | "neutral";
    badgeLabel: string;
  }

  const metricRows: MetricRowDef[] =
    honest != null && thresholds != null
      ? [
          {
            label: "Profit Factor",
            paperValue: fmt(paperPf),
            targetValue: `≥ ${fmt(thresholds.min_profit_factor)}`,
            badgeVariant: pfPass ? "bull" : "bear",
            badgeLabel: pfPass ? "PASS" : "FAIL",
          },
          {
            label: "Sharpe Ratio",
            paperValue: "—",
            targetValue: `≥ ${fmt(thresholds.min_sharpe)}`,
            // Sharpe not computable from deduped record — neutral, not FAIL
            badgeVariant: "neutral",
            badgeLabel: "N/A",
          },
          {
            label: "Win Rate %",
            paperValue: paperWr != null ? `${paperWr.toFixed(1)}%` : "—",
            targetValue: `≥ ${fmt(thresholds.min_win_rate, 1)}%`,
            badgeVariant: winRatePass ? "bull" : "bear",
            badgeLabel: winRatePass ? "PASS" : "FAIL",
          },
          {
            label: "Total Trades",
            paperValue: paperTrades != null ? String(paperTrades) : "—",
            targetValue: `≥ ${thresholds.min_trades ?? "—"}`,
            badgeVariant: tradesPass ? "bull" : "warn",
            badgeLabel: tradesPass ? "PASS" : "IN PROGRESS",
          },
        ]
      : [];

  // Degradation: honest PF vs backtest PF
  const backtestPf = ref?.backtested?.profit_factor ?? null;
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
