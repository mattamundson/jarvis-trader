"use client";

import React, { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchEngine } from "@/lib/api";
import { fetchHonestTrades } from "@/lib/honestTrades";
import {
  type BacktestBaselineRow,
  fmtBaselineNum,
  pickApprovedBacktestBaseline,
  type ScorecardBacktestBaseline,
} from "@/lib/scorecardBaseline";
import { PREFERRED_BASELINE_LABEL } from "@/lib/approvedSymbols";

// ── Types ─────────────────────────────────────────────────────────────────────

type BadgeVariant = "bull" | "bear" | "warn" | "info" | "neutral";

interface PaperMetrics {
  profit_factor?: number;
  sharpe_ratio?: number;
  win_rate?: number;
  total_trades?: number;
}

// ── Badge logic ───────────────────────────────────────────────────────────────

function pfVariant(pf: number): BadgeVariant {
  if (pf >= 2.0) return "bull";
  if (pf >= 1.5) return "warn";
  return "bear";
}

function wrVariant(wr: number): BadgeVariant {
  if (wr >= 55) return "bull";
  if (wr >= 45) return "warn";
  return "bear";
}

function tradesVariant(t: number): BadgeVariant {
  if (t >= 30) return "bull";
  if (t >= 10) return "warn";
  return "info";
}

function normalizeWinRate(raw: number): number {
  return raw > 1 ? raw : raw * 100;
}

function fmtBacktestCell(
  loadingBt: boolean,
  n: number | null,
  decimals = 2
): string {
  if (loadingBt) return "…";
  return fmtBaselineNum(n, decimals);
}

// ── Component ─────────────────────────────────────────────────────────────────

export function BacktestVsPaperWidget() {
  const [paper, setPaper] = useState<PaperMetrics | null>(null);
  const [baseline, setBaseline] = useState<ScorecardBacktestBaseline | null>(null);
  const [loadingBt, setLoadingBt] = useState(true);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function fetchMetrics() {
    try {
      // Paper column from the honest deduped record (was /analytics/performance,
      // which over-counts re-logged winners -> fabricated PF 2.95 / 19 trades).
      //
      // fetchHonestTrades() -> masterApi's fetchRealizedPnl() carries its own
      // 15s AbortController timeout (see lib/masterApi.ts), so a stalled
      // master-api rejects into the catch block below within a bounded time
      // instead of leaving `loading` true forever -- the "renders
      // placeholders forever" symptom this widget must never reproduce.
      const [honest, btRows] = await Promise.all([
        fetchHonestTrades(),
        fetchEngine<BacktestBaselineRow[]>(`/backtest/results`).catch(() => [] as BacktestBaselineRow[]),
      ]);
      setPaper({
        profit_factor: honest.profitFactor ?? undefined,
        sharpe_ratio: undefined, // annualized Sharpe not in the deduped record
        win_rate: honest.winRate * 100,
        total_trades: honest.trades.length,
      });
      setBaseline(pickApprovedBacktestBaseline(btRows));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch");
    } finally {
      setLoading(false);
      setLoadingBt(false);
    }
  }

  useEffect(() => {
    fetchMetrics();
    const id = setInterval(fetchMetrics, 300_000);
    return () => clearInterval(id);
  }, []);

  const pf = paper?.profit_factor ?? null;
  const wr = paper?.win_rate != null ? normalizeWinRate(paper.win_rate) : null;
  const trades = paper?.total_trades ?? null;

  const btPf = baseline?.profitFactor ?? null;
  const btSr = baseline?.sharpeRatio ?? null;
  const btWr = baseline?.winRatePct ?? null;
  const btTrades = baseline?.totalTrades ?? null;

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-2">
          <div>
            <CardTitle className="text-sm font-semibold uppercase tracking-widest text-accent">
              Backtest vs Paper Reality
            </CardTitle>
            <p className="text-[11px] text-muted-foreground mt-0.5">
              Backtest column from saved engine results ({PREFERRED_BASELINE_LABEL} preferred)
            </p>
          </div>
          {loading && (
            <Badge variant="neutral" className="text-[10px] font-mono">
              LOADING
            </Badge>
          )}
          {error && !loading && (
            <Badge variant="bear" className="text-[10px] font-mono">
              ERROR
            </Badge>
          )}
          {!loading && !error && (
            <Badge variant="info" className="text-[10px] font-mono">
              LIVE
            </Badge>
          )}
        </div>
      </CardHeader>

      <CardContent className="pb-5">
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border">
                <th className="pb-2 pr-4 text-left font-semibold text-muted-foreground uppercase tracking-wider">
                  Metric
                </th>
                <th className="pb-2 pr-4 text-right font-semibold text-muted-foreground uppercase tracking-wider">
                  Backtest
                </th>
                <th className="pb-2 pr-4 text-right font-semibold text-muted-foreground uppercase tracking-wider">
                  Paper (Live)
                </th>
                <th className="pb-2 text-center font-semibold text-muted-foreground uppercase tracking-wider">
                  Status
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/50">
              <tr className="hover:bg-muted/20 transition-colors">
                <td className="py-2.5 pr-4 font-medium text-foreground">Profit Factor</td>
                <td className="py-2.5 pr-4 text-right font-mono tabular-nums text-muted-foreground">
                  {fmtBacktestCell(loadingBt, btPf)}
                </td>
                <td className="py-2.5 pr-4 text-right font-mono tabular-nums font-semibold text-foreground">
                  {loading ? (
                    <span className="text-muted-foreground">—</span>
                  ) : error || pf == null ? (
                    <span className="text-muted-foreground">N/A</span>
                  ) : (
                    pf.toFixed(2)
                  )}
                </td>
                <td className="py-2.5 text-center">
                  {!loading && !error && pf != null ? (
                    <Badge variant={pfVariant(pf)} className="text-[10px]">
                      {pfVariant(pf) === "bull" ? "ON TRACK" : pfVariant(pf) === "warn" ? "MARGINAL" : "BELOW"}
                    </Badge>
                  ) : (
                    <span className="text-muted-foreground text-xs">—</span>
                  )}
                </td>
              </tr>

              <tr className="hover:bg-muted/20 transition-colors">
                <td className="py-2.5 pr-4 font-medium text-foreground">Sharpe Ratio</td>
                <td className="py-2.5 pr-4 text-right font-mono tabular-nums text-muted-foreground">
                  {fmtBacktestCell(loadingBt, btSr)}
                </td>
                <td
                  className="py-2.5 pr-4 text-right font-mono tabular-nums text-muted-foreground"
                  title="Annualized Sharpe is not derivable from the deduped trade record"
                >
                  —
                </td>
                <td className="py-2.5 text-center">
                  <span className="text-muted-foreground text-xs">not computed</span>
                </td>
              </tr>

              <tr className="hover:bg-muted/20 transition-colors">
                <td className="py-2.5 pr-4 font-medium text-foreground">Win Rate</td>
                <td className="py-2.5 pr-4 text-right font-mono tabular-nums text-muted-foreground">
                  {loadingBt ? (
                    "…"
                  ) : btWr != null ? (
                    `${btWr.toFixed(1)}%`
                  ) : (
                    "—"
                  )}
                </td>
                <td className="py-2.5 pr-4 text-right font-mono tabular-nums font-semibold text-foreground">
                  {loading ? (
                    <span className="text-muted-foreground">—</span>
                  ) : error || wr == null ? (
                    <span className="text-muted-foreground">N/A</span>
                  ) : (
                    `${wr.toFixed(1)}%`
                  )}
                </td>
                <td className="py-2.5 text-center">
                  {!loading && !error && wr != null ? (
                    <Badge variant={wrVariant(wr)} className="text-[10px]">
                      {wrVariant(wr) === "bull" ? "ON TRACK" : wrVariant(wr) === "warn" ? "MARGINAL" : "BELOW"}
                    </Badge>
                  ) : (
                    <span className="text-muted-foreground text-xs">—</span>
                  )}
                </td>
              </tr>

              <tr className="hover:bg-muted/20 transition-colors">
                <td className="py-2.5 pr-4 font-medium text-foreground">Total Trades</td>
                <td className="py-2.5 pr-4 text-right font-mono tabular-nums text-muted-foreground">
                  {loadingBt ? (
                    "…"
                  ) : btTrades != null ? (
                    btTrades.toLocaleString()
                  ) : (
                    "—"
                  )}
                </td>
                <td className="py-2.5 pr-4 text-right font-mono tabular-nums font-semibold text-foreground">
                  {loading ? (
                    <span className="text-muted-foreground">—</span>
                  ) : error || trades == null ? (
                    <span className="text-muted-foreground">N/A</span>
                  ) : (
                    trades.toLocaleString()
                  )}
                </td>
                <td className="py-2.5 text-center">
                  {!loading && !error && trades != null ? (
                    <Badge variant={tradesVariant(trades)} className="text-[10px]">
                      {tradesVariant(trades) === "bull"
                        ? "SUFFICIENT"
                        : tradesVariant(trades) === "warn"
                          ? "BUILDING"
                          : "TOO FEW"}
                    </Badge>
                  ) : (
                    <span className="text-muted-foreground text-xs">—</span>
                  )}
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <p className="mt-3 text-[11px] text-muted-foreground italic">
          Paper column from the honest deduped trade record (read-time deduped); backtest column
          from saved engine results. Paper targets set at 38% of backtest thresholds.
        </p>

        {error && (
          <div className="mt-3 rounded-lg border border-bear/20 bg-bear/5 px-3 py-2 text-[11px] text-bear">
            Could not reach engine: {error}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
