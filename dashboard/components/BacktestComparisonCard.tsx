"use client";

import { useState, useEffect, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { GitCompare } from "lucide-react";
import { fetchEngine } from "@/lib/api";

// ── Types ─────────────────────────────────────────────────────────────────────

interface PaperTrading {
  profit_factor: number;
  sharpe_ratio: number;
  win_rate: number;
  total_trades: number;
  total_pnl: number;
}

interface Backtested {
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
  paper_trading: PaperTrading;
  backtested: Backtested;
  degradation_factor: number;
  validation_thresholds: ValidationThresholds;
}

// ── Constants ─────────────────────────────────────────────────────────────────


const REFRESH_INTERVAL_MS = 2 * 60 * 1000; // 2 minutes

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmt(v: number, decimals = 2): string {
  return v.toFixed(decimals);
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
  const [data, setData] = useState<CompareResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await fetch(
        `/analytics/performance/compare`,
        { cache: "no-store" }
      );
      const json = (await res.json()) as CompareResponse;
      setData(json);
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

  // ── Derived pass/fail ──────────────────────────────────────────────────────

  const paper = data?.paper_trading;
  const thresholds = data?.validation_thresholds;

  const pfPass =
    paper !== undefined &&
    thresholds !== undefined &&
    paper.profit_factor >= thresholds.min_profit_factor;
  const sharpePass =
    paper !== undefined &&
    thresholds !== undefined &&
    paper.sharpe_ratio >= thresholds.min_sharpe;
  const winRatePass =
    paper !== undefined &&
    thresholds !== undefined &&
    paper.win_rate >= thresholds.min_win_rate;
  const tradesPass =
    paper !== undefined &&
    thresholds !== undefined &&
    paper.total_trades >= thresholds.min_trades;

  const allPass = pfPass && sharpePass && winRatePass && tradesPass;

  interface MetricRowDef {
    label: string;
    paperValue: string;
    targetValue: string;
    badgeVariant: "bull" | "bear" | "warn" | "info" | "neutral";
    badgeLabel: string;
  }

  const metricRows: MetricRowDef[] = data
    ? [
        {
          label: "Profit Factor",
          paperValue: fmt(paper!.profit_factor),
          targetValue: `≥ ${fmt(thresholds!.min_profit_factor)}`,
          badgeVariant: pfPass ? "bull" : "bear",
          badgeLabel: pfPass ? "PASS" : "FAIL",
        },
        {
          label: "Sharpe Ratio",
          paperValue: fmt(paper!.sharpe_ratio),
          targetValue: `≥ ${fmt(thresholds!.min_sharpe)}`,
          badgeVariant: sharpePass ? "bull" : "bear",
          badgeLabel: sharpePass ? "PASS" : "FAIL",
        },
        {
          label: "Win Rate %",
          paperValue: `${fmt(paper!.win_rate, 1)}%`,
          targetValue: `≥ ${fmt(thresholds!.min_win_rate, 1)}%`,
          badgeVariant: winRatePass ? "bull" : "bear",
          badgeLabel: winRatePass ? "PASS" : "FAIL",
        },
        {
          label: "Total Trades",
          paperValue: String(paper!.total_trades),
          targetValue: `≥ ${thresholds!.min_trades}`,
          badgeVariant: tradesPass ? "bull" : "warn",
          badgeLabel: tradesPass ? "PASS" : "IN PROGRESS",
        },
      ]
    : [];

  const degradationPct = data
    ? (data.degradation_factor * 100).toFixed(1)
    : null;

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2 text-sm">
            <GitCompare className="h-4 w-4" />
            Backtest vs. Paper Trading
          </CardTitle>
          {!loading && data && (
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
              ) : !data ? (
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

        {/* Footer — degradation factor + overall status */}
        {!loading && data && (
          <div className="mt-3 pt-3 border-t border-border flex items-center justify-between gap-2 flex-wrap">
            <p className="text-xs text-muted-foreground">
              Degradation factor:{" "}
              <span className="font-mono font-medium text-foreground">
                {degradationPct}%
              </span>{" "}
              of backtest performance achieved in live paper trading
            </p>
            <Badge variant={allPass ? "bull" : "neutral"}>
              {allPass ? "VALIDATION PASS" : "NOT YET"}
            </Badge>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
