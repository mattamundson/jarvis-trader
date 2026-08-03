"use client";

import React, { useEffect, useState } from "react";
import { RefreshCw, Globe } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { fetchEngine } from "@/lib/api";
import { RawRecordBadge } from "@/components/RawRecordBadge";
import {
  parseTradesHistoryResponse,
  type RegimeTradeRecord as TradeRecord,
  type TradesHistoryPayload,
} from "@/lib/regimePnlTrades";


// ── Types ─────────────────────────────────────────────────────────────────────

interface RegimeStat {
  regime: string;
  tradeCount: number;
  winCount: number;
  winRate: number;
  totalPnL: number;
  avgPnL: number;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * Extract the regime label from a trade record.
 * Checks (in order):
 *   1. trade.regime          — top-level field (some execution paths)
 *   2. trade.strategy_params.regime
 *   3. trade.strategy_params.regime_type  (MGC paper tracker convention)
 * Returns null if none is found / all are blank/unknown.
 */
function extractRegime(trade: TradeRecord): string | null {
  const candidates: (string | undefined | null)[] = [
    trade.regime,
    trade.strategy_params?.regime,
    trade.strategy_params?.regime_type,
  ];

  for (const c of candidates) {
    if (c && typeof c === "string" && c.trim() !== "" && c.toUpperCase() !== "UNKNOWN") {
      return c.trim().toUpperCase();
    }
  }
  return null;
}

/**
 * Convert a snake_case / UPPER_SNAKE regime label to Title Case.
 * "TRENDING_BULL" → "Trending Bull", "RANGING" → "Ranging"
 */
function formatRegimeName(regime: string): string {
  return regime
    .replace(/_/g, " ")
    .toLowerCase()
    .replace(/\b\w/g, (ch) => ch.toUpperCase());
}

/**
 * Win-rate badge variant per spec:
 *   ≥55% → bull, ≥40% → warn, <40% → bear
 */
function winRateBadgeVariant(
  winRate: number
): "bull" | "warn" | "bear" {
  if (winRate >= 55) return "bull";
  if (winRate >= 40) return "warn";
  return "bear";
}

function pnlColor(value: number): string {
  if (value > 0) return "text-green-400";
  if (value < 0) return "text-red-400";
  return "text-muted-foreground";
}

function formatPnL(value: number): string {
  const sign = value >= 0 ? "+" : "";
  return `${sign}$${value.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function RegimePnLBreakdownWidget() {
  const [trades, setTrades] = useState<TradeRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastRefreshed, setLastRefreshed] = useState<Date | null>(null);

  const fetchTrades = async () => {
    setLoading(true);
    setError(null);
    try {
      const json = await fetchEngine<TradesHistoryPayload>(
        `/portfolio/history/trades?status=CLOSED&limit=500`
      );
      setTrades(parseTradesHistoryResponse(json));
      setLastRefreshed(new Date());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTrades();
  }, []);

  // ── Aggregate per-regime stats ──────────────────────────────────────────────

  const regimeStats: RegimeStat[] = (() => {
    const map = new Map<
      string,
      { tradeCount: number; winCount: number; totalPnL: number }
    >();

    for (const trade of trades) {
      const regime = extractRegime(trade);
      if (!regime) continue;

      const pnl = typeof trade.pnl === "number" ? trade.pnl : 0;
      const isWin = pnl > 0;

      const existing = map.get(regime) ?? { tradeCount: 0, winCount: 0, totalPnL: 0 };
      map.set(regime, {
        tradeCount: existing.tradeCount + 1,
        winCount: existing.winCount + (isWin ? 1 : 0),
        totalPnL: existing.totalPnL + pnl,
      });
    }

    return Array.from(map.entries())
      .map(([regime, stats]) => ({
        regime,
        tradeCount: stats.tradeCount,
        winCount: stats.winCount,
        winRate: stats.tradeCount > 0 ? (stats.winCount / stats.tradeCount) * 100 : 0,
        totalPnL: stats.totalPnL,
        avgPnL: stats.tradeCount > 0 ? stats.totalPnL / stats.tradeCount : 0,
      }))
      .sort((a, b) => b.tradeCount - a.tradeCount);
  })();

  const hasRegimeData = regimeStats.length > 0;

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="rounded-xl border border-border bg-card overflow-hidden">
      {/* Header */}
      <div className="px-5 py-3.5 border-b border-border flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-accent/10">
            <Globe className="h-3.5 w-3.5 text-accent" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Regime P&amp;L Breakdown
              </p>
              {/* Regime is sourced from strategy_params — absent in the deduped HonestTrade record.
                  P&L totals here reflect the raw (over-counted) trade log, not the deduplicated record. */}
              <RawRecordBadge className="text-[9px]" />
            </div>
            <p className="text-[10px] text-muted-foreground/60">
              Closed trades grouped by market regime
            </p>
          </div>
        </div>
        <button
          onClick={fetchTrades}
          disabled={loading}
          className="flex items-center gap-1.5 rounded-lg border border-border bg-background px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground hover:bg-accent/5 transition-colors disabled:opacity-50"
          aria-label="Refresh regime P&L breakdown"
        >
          <RefreshCw className={`h-3 w-3 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </button>
      </div>

      {/* Body */}
      <div className="p-5">
        {/* Loading */}
        {loading && (
          <div className="flex items-center gap-2 text-xs text-muted-foreground animate-pulse py-4">
            <RefreshCw className="h-3.5 w-3.5 animate-spin" />
            Loading trade history…
          </div>
        )}

        {/* Error */}
        {!loading && error && (
          <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-xs text-red-400">
            Failed to load trades: {error}
          </div>
        )}

        {/* No data yet / all null regimes */}
        {!loading && !error && !hasRegimeData && (
          <div className="rounded-lg border border-border bg-background/40 px-4 py-6 text-center">
            <Globe className="h-6 w-6 text-muted-foreground/40 mx-auto mb-2" />
            <p className="text-xs text-muted-foreground">
              Regime data not yet available — will populate as trades accumulate
            </p>
            {trades.length > 0 && (
              <p className="text-[10px] text-muted-foreground/60 mt-1">
                {trades.length} closed trade{trades.length !== 1 ? "s" : ""} found, but none carry a
                regime label yet.
              </p>
            )}
          </div>
        )}

        {/* Table */}
        {!loading && !error && hasRegimeData && (
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-border">
                  {["Regime", "Trades", "Win%", "Total P&L", "Avg P&L"].map((h) => (
                    <th
                      key={h}
                      className="pb-2 px-2 text-[10px] font-medium uppercase tracking-wider text-muted-foreground first:pl-0 last:pr-0"
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {regimeStats.map((row) => (
                  <tr
                    key={row.regime}
                    className="border-b border-border/40 last:border-0 hover:bg-white/[0.02] transition-colors"
                  >
                    {/* Regime name */}
                    <td className="py-2.5 px-2 first:pl-0">
                      <span className="text-xs font-medium text-foreground">
                        {formatRegimeName(row.regime)}
                      </span>
                    </td>

                    {/* Trade count */}
                    <td className="py-2.5 px-2 text-xs tabular-nums text-muted-foreground">
                      {row.tradeCount}
                    </td>

                    {/* Win rate with badge */}
                    <td className="py-2.5 px-2">
                      <Badge variant={winRateBadgeVariant(row.winRate)}>
                        {row.winRate.toFixed(0)}%
                      </Badge>
                    </td>

                    {/* Total P&L */}
                    <td className={`py-2.5 px-2 text-xs tabular-nums font-mono font-medium ${pnlColor(row.totalPnL)}`}>
                      {formatPnL(row.totalPnL)}
                    </td>

                    {/* Avg P&L */}
                    <td className={`py-2.5 px-2 last:pr-0 text-xs tabular-nums font-mono ${pnlColor(row.avgPnL)}`}>
                      {formatPnL(row.avgPnL)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            {/* Footer */}
            <div className="mt-3 pt-3 border-t border-border/40 space-y-1">
              <div className="flex items-center justify-between">
                <p className="text-[10px] text-muted-foreground/60">
                  {trades.length} closed trade{trades.length !== 1 ? "s" : ""} ·{" "}
                  {regimeStats.length} regime{regimeStats.length !== 1 ? "s" : ""}
                </p>
                {lastRefreshed && (
                  <p className="text-[10px] text-muted-foreground/60">
                    Updated {lastRefreshed.toLocaleTimeString()}
                  </p>
                )}
              </div>
              {/* Regime is extracted from strategy_params — a field absent in the deduped HonestTrade
                  record. These P&L figures come from the raw /portfolio/history/trades endpoint and
                  may include re-logged duplicate rows. Do not compare regime totals to the deduped
                  net P&L shown in other widgets. */}
              <p className="text-[10px] text-yellow-400/70">
                ⚠ P&amp;L figures are from the raw trade log (not deduped). Regime field is absent
                from the deduplicated record — an honest regime split cannot be derived.
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
