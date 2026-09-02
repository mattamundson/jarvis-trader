"use client";

import React from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  dedupCaveat,
  maxDrawdownPct,
  type HonestTradeSet,
} from "@/lib/honestTrades";
import { useHonestTrades } from "@/lib/useHonestTrades";
import {
  annualizedSharpe,
  recordTradesPerYear,
} from "@/lib/honestAnnualized";


// ── Backtest benchmarks (static saved-backtest reference — NOT live) ──────────
// Source: MES 1h gate-v2 backtest run (historical). These are fixed constants
// from the best historical backtest; they do NOT update with live data.
//
// C3 metric-honesty pass (2026-08-18): the as-run Sharpe (4.16) was annualized
// at a fixed 252. The honest reference is deflated to the backtest's OWN
// observed frequency — 312 trades over the 2019-05-05 → 2026-08-14 window
// (7.27y → 42.9 trades/yr): 4.16 × sqrt(42.9/252) ≈ 1.72. Both the deflated
// display value and its derivation are shown so the number is independently
// re-verifiable against the saved backtest JSON (see
// lib/honestAnnualized.backtestAnnualization).

const BACKTEST_SHARPE_AS_RUN_252 = 4.16;
const BACKTEST_TRADES = 312;
const BACKTEST_WINDOW_DAYS = 2658; // 2019-05-05 → 2026-08-14
const BACKTEST_TRADES_PER_YEAR = BACKTEST_TRADES / (BACKTEST_WINDOW_DAYS / 365.25); // ≈ 42.88
const BACKTEST_SHARPE_HONEST =
  BACKTEST_SHARPE_AS_RUN_252 * Math.sqrt(BACKTEST_TRADES_PER_YEAR / 252); // ≈ 1.72

const BACKTEST = {
  profit_factor: 5.27,
  sharpe_ratio: BACKTEST_SHARPE_HONEST,
  win_rate: 0.72,
  total_trades: 312,
  max_drawdown: -0.031,
  total_pnl: 47200.0,
  avg_trade_pnl: 151.28,
  label: "MES 1h Backtest (Best) — static reference",
  period: "Historical",
};

// ── Types ─────────────────────────────────────────────────────────────────────

/** Live/paper column — derived from the honest deduped trade set. */
interface LiveData {
  profit_factor: number | null;
  /** Sharpe is not computable from the deduped record (no timestamps for annualisation). */
  sharpe_ratio: null;
  win_rate: number;
  total_trades: number;
  max_drawdown: number;
  total_pnl: number;
  avg_trade_pnl: number;
}

type RowColor = "green" | "orange" | "red" | "neutral";

function liveFromHonest(set: HonestTradeSet): LiveData {
  const avgTrade = set.trades.length > 0 ? set.net / set.trades.length : 0;
  // Negative fraction of peak (matches the BACKTEST.max_drawdown sign). The
  // shared helper sorts by close time before accumulating, so this no longer
  // depends on set.trades arriving in chronological order.
  const maxDDFrac = -maxDrawdownPct(set.trades);
  return {
    profit_factor: set.profitFactor,
    sharpe_ratio: null,
    win_rate: set.winRate,
    total_trades: set.trades.length,
    max_drawdown: maxDDFrac,
    total_pnl: set.net,
    avg_trade_pnl: avgTrade,
  };
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function colorClass(c: RowColor): string {
  if (c === "green") return "text-bull";
  if (c === "orange") return "text-warn";
  if (c === "red") return "text-bear";
  return "text-muted-foreground";
}

/** For positive metrics (higher = better): green >= 70%, orange >= 40%, red < 40% */
function positiveColor(live: number, backtest: number): RowColor {
  if (backtest === 0) return "neutral";
  const ratio = live / backtest;
  if (ratio >= 0.7) return "green";
  if (ratio >= 0.4) return "orange";
  return "red";
}

/** For drawdown (lower abs = better) */
function drawdownColor(liveDD: number, backtestDD: number): RowColor {
  const liveAbs = Math.abs(liveDD);
  const btAbs = Math.abs(backtestDD);
  if (btAbs === 0) return "neutral";
  const ratio = liveAbs / btAbs;
  if (ratio <= 1.5) return "green";
  if (ratio <= 3) return "orange";
  return "red";
}

function fmtPct(n: number): string {
  return `${(n * 100).toFixed(1)}%`;
}

function fmtCurrency(n: number): string {
  return n.toLocaleString("en-US", { style: "currency", currency: "USD" });
}

function fmtDD(n: number): string {
  return `${(Math.abs(n) * 100).toFixed(1)}%`;
}

function isAllZeros(data: LiveData): boolean {
  return (
    (data.profit_factor ?? 0) === 0 &&
    data.win_rate === 0 &&
    data.total_trades === 0 &&
    data.total_pnl === 0
  );
}

// ── Skeleton ──────────────────────────────────────────────────────────────────

function Skeleton() {
  return (
    <div className="animate-pulse space-y-3 p-4">
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="flex items-center justify-between">
          <div className="h-3 w-28 bg-muted rounded" />
          <div className="h-3 w-16 bg-muted rounded" />
          <div className="h-3 w-16 bg-muted rounded" />
        </div>
      ))}
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export function BacktestCompareWidget() {
  const { honest: set, isLoading: loading, error: loadError } = useHonestTrades(60_000);
  const error = loadError != null;
  const data: LiveData | null = set ? liveFromHonest(set) : null;
  const caveat: string = set ? dedupCaveat(set) : "";

  // ── Overall badge ──────────────────────────────────────────────────────────

  type BadgeVariant = "bull" | "bear" | "warn" | "info" | "neutral";

  function overallBadge(): { variant: BadgeVariant; label: string } {
    if (!data || isAllZeros(data)) return { variant: "neutral", label: "NO DATA" };
    const pf = data.profit_factor ?? 0;
    // Sharpe is not computable from the deduped record; gate on PF only
    if (pf >= 2.0) return { variant: "bull", label: "ON TARGET" };
    if (pf >= 1.5) return { variant: "info", label: "PROGRESSING" };
    if (pf >= 1.0) return { variant: "warn", label: "BELOW TARGET" };
    return { variant: "bear", label: "BELOW BREAKEVEN" };
  }

  const badge = overallBadge();

  // ── Row data ───────────────────────────────────────────────────────────────

  type Row = {
    metric: string;
    live: string;
    backtest: string;
    color: RowColor;
  };

  function buildRows(): Row[] {
    if (!data) return [];
    // Honest annualized Sharpe from the deduped record: per-trade Sharpe ×
    // sqrt(observed trades/yr). Null when the record spans < 90 days or has
    // < 2 trades — never falls back to the 252-scaled number.
    const liveSharpe = annualizedSharpe(set!.trades);
    return [
      {
        metric: "Profit Factor",
        live: data.profit_factor != null ? data.profit_factor.toFixed(2) : "—",
        backtest: BACKTEST.profit_factor.toFixed(2),
        color: data.profit_factor != null
          ? positiveColor(data.profit_factor, BACKTEST.profit_factor)
          : "neutral",
      },
      {
        metric: "Sharpe Ratio (annualized)",
        live: liveSharpe !== null ? liveSharpe.toFixed(2) : "—",
        backtest: BACKTEST.sharpe_ratio.toFixed(2),
        color: "neutral",
      },
      {
        metric: "Win Rate",
        live: fmtPct(data.win_rate),
        backtest: fmtPct(BACKTEST.win_rate),
        color: positiveColor(data.win_rate, BACKTEST.win_rate),
      },
      {
        metric: "Max Drawdown",
        live: fmtDD(data.max_drawdown),
        backtest: fmtDD(BACKTEST.max_drawdown),
        color: drawdownColor(data.max_drawdown, BACKTEST.max_drawdown),
      },
      {
        metric: "Avg Trade P&L",
        live: fmtCurrency(data.avg_trade_pnl),
        backtest: fmtCurrency(BACKTEST.avg_trade_pnl),
        color: positiveColor(data.avg_trade_pnl, BACKTEST.avg_trade_pnl),
      },
      {
        metric: "Total P&L",
        live: fmtCurrency(data.total_pnl),
        backtest: fmtCurrency(BACKTEST.total_pnl),
        color: "neutral",
      },
    ];
  }

  const rows = buildRows();

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle>Live vs Backtest Comparison</CardTitle>
            <p className="text-xs text-muted-foreground mt-1">
              Static backtest ref: MES 1h &nbsp;|&nbsp; PF 5.27 &nbsp;|&nbsp; Sharpe {BACKTEST.sharpe_ratio.toFixed(2)} (deflated, {BACKTEST_TRADES_PER_YEAR.toFixed(0)} trades/yr) &nbsp;|&nbsp; +47.2%
            </p>
          </div>
          <Badge variant={badge.variant}>{badge.label}</Badge>
        </div>
      </CardHeader>

      <CardContent>
        {loading ? (
          <Skeleton />
        ) : error ? (
          <div className="py-6 text-center text-sm text-muted-foreground">
            Performance data unavailable
          </div>
        ) : data && isAllZeros(data) ? (
          <div className="py-6 text-center text-sm text-muted-foreground">
            Accumulating live data...
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border bg-muted/30">
                  <th className="text-left px-4 py-2.5 text-muted-foreground font-semibold uppercase tracking-wide">
                    Metric
                  </th>
                  <th className="text-right px-4 py-2.5 text-muted-foreground font-semibold uppercase tracking-wide">
                    Live Paper
                  </th>
                  <th className="text-right px-4 py-2.5 text-muted-foreground font-semibold uppercase tracking-wide">
                    Backtest
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {rows.map((row) => (
                  <tr key={row.metric} className="hover:bg-muted/20 transition-colors">
                    <td className="px-4 py-3 font-medium text-foreground">
                      {row.metric}
                    </td>
                    <td
                      className={`px-4 py-3 text-right font-mono font-bold ${colorClass(row.color)}`}
                    >
                      {row.live}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-muted-foreground">
                      {row.backtest}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            <p className="mt-4 text-[11px] text-muted-foreground leading-relaxed border-t border-border pt-3">
              Live: {caveat || "deduped trades"}. Annualized Sharpe = per-trade Sharpe × √(observed
              trades/yr), never the fixed-252 figure (C3 honesty pass). Backtest Sharpe deflated the
              same way from its own 312 trades over 7.27y (4.16 as-run @252 → {BACKTEST.sharpe_ratio.toFixed(2)}).
              Backtest column = saved static reference, not live. Targets: PF &ge; 2.0.
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
