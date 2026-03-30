"use client";

import React, { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

const ENGINE_URL = process.env.NEXT_PUBLIC_ENGINE_URL || "http://localhost:8010";

// ── Static backtest reference values ─────────────────────────────────────────

const BACKTEST = {
  profitFactor: 5.27,
  sharpeRatio: 4.16,
  winRate: 67.3,
  totalTrades: 847,
  avgRR: 2.14,
  totalReturn: 47.2,
} as const;

// ── Types ─────────────────────────────────────────────────────────────────────

type BadgeVariant = "bull" | "bear" | "warn" | "info" | "neutral";

interface PaperMetrics {
  profit_factor?: number;
  sharpe_ratio?: number;
  win_rate?: number;
  total_trades?: number;
  avg_rr?: number;
  total_return?: number;
}

// ── Badge logic ───────────────────────────────────────────────────────────────

function pfVariant(pf: number): BadgeVariant {
  if (pf >= 2.0) return "bull";
  if (pf >= 1.5) return "warn";
  return "bear";
}

function sharpeVariant(s: number): BadgeVariant {
  if (s >= 1.5) return "bull";
  if (s >= 1.0) return "warn";
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

// ── Helper to normalize win rate ──────────────────────────────────────────────

function normalizeWinRate(raw: number): number {
  // API may return 0.673 (fraction) or 67.3 (percent)
  return raw > 1 ? raw : raw * 100;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function BacktestVsPaperWidget() {
  const [paper, setPaper] = useState<PaperMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function fetchMetrics() {
    try {
      const res = await fetch(`${ENGINE_URL}/analytics/performance`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setPaper(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchMetrics();
    const id = setInterval(fetchMetrics, 300_000);
    return () => clearInterval(id);
  }, []);

  // Resolved paper values
  const pf = paper?.profit_factor ?? null;
  const sharpe = paper?.sharpe_ratio ?? null;
  const wr = paper?.win_rate != null ? normalizeWinRate(paper.win_rate) : null;
  const trades = paper?.total_trades ?? null;

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-2">
          <div>
            <CardTitle className="text-sm font-semibold uppercase tracking-widest text-accent">
              Backtest vs Paper Reality
            </CardTitle>
            <p className="text-[11px] text-muted-foreground mt-0.5">
              STC Strategy — Target Validation
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
              {/* Profit Factor */}
              <tr className="hover:bg-muted/20 transition-colors">
                <td className="py-2.5 pr-4 font-medium text-foreground">Profit Factor</td>
                <td className="py-2.5 pr-4 text-right font-mono tabular-nums text-muted-foreground">
                  {BACKTEST.profitFactor.toFixed(2)}
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

              {/* Sharpe Ratio */}
              <tr className="hover:bg-muted/20 transition-colors">
                <td className="py-2.5 pr-4 font-medium text-foreground">Sharpe Ratio</td>
                <td className="py-2.5 pr-4 text-right font-mono tabular-nums text-muted-foreground">
                  {BACKTEST.sharpeRatio.toFixed(2)}
                </td>
                <td className="py-2.5 pr-4 text-right font-mono tabular-nums font-semibold text-foreground">
                  {loading ? (
                    <span className="text-muted-foreground">—</span>
                  ) : error || sharpe == null ? (
                    <span className="text-muted-foreground">N/A</span>
                  ) : (
                    sharpe.toFixed(2)
                  )}
                </td>
                <td className="py-2.5 text-center">
                  {!loading && !error && sharpe != null ? (
                    <Badge variant={sharpeVariant(sharpe)} className="text-[10px]">
                      {sharpeVariant(sharpe) === "bull" ? "ON TRACK" : sharpeVariant(sharpe) === "warn" ? "MARGINAL" : "BELOW"}
                    </Badge>
                  ) : (
                    <span className="text-muted-foreground text-xs">—</span>
                  )}
                </td>
              </tr>

              {/* Win Rate */}
              <tr className="hover:bg-muted/20 transition-colors">
                <td className="py-2.5 pr-4 font-medium text-foreground">Win Rate</td>
                <td className="py-2.5 pr-4 text-right font-mono tabular-nums text-muted-foreground">
                  {BACKTEST.winRate.toFixed(1)}%
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

              {/* Total Trades */}
              <tr className="hover:bg-muted/20 transition-colors">
                <td className="py-2.5 pr-4 font-medium text-foreground">Total Trades</td>
                <td className="py-2.5 pr-4 text-right font-mono tabular-nums text-muted-foreground">
                  {BACKTEST.totalTrades.toLocaleString()}
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
          Paper targets set at 38% of backtest thresholds to account for real market conditions
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
