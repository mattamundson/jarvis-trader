"use client";

import { useMemo } from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { RefreshCw } from "lucide-react";
import {
  bySymbolStats,
  dedupCaveat,
  type SymbolStat,
} from "@/lib/honestTrades";
import { useHonestTrades } from "@/lib/useHonestTrades";

// ── Types ─────────────────────────────────────────────────────────────────────

/** Display shape — extends SymbolStat with derived avg and per-trade extremes. */
interface SymbolDisplay extends SymbolStat {
  /** avg P&L per trade */
  avg_pnl: number;
  /** best single trade P&L in this symbol (null if no trades) */
  best_trade: number | null;
  /** worst single trade P&L in this symbol (null if no trades) */
  worst_trade: number | null;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function pnlVariant(value: number): "bull" | "bear" | "neutral" {
  if (value > 0) return "bull";
  if (value < 0) return "bear";
  return "neutral";
}

function formatPnl(value: number | null): string {
  if (value === null) return "n/a";
  const abs = Math.abs(value).toFixed(2);
  return value >= 0 ? `+$${abs}` : `-$${abs}`;
}

function winRateClass(rate: number): string {
  // rate is 0..1 here
  if (rate >= 0.55) return "text-green-500";
  if (rate < 0.45) return "text-red-500";
  return "text-muted-foreground";
}

// ── Component ─────────────────────────────────────────────────────────────────

export function SymbolPerformanceWidget() {
  const { honest: tradeSet, isLoading: loading, error: loadError, mutate } = useHonestTrades(300_000);
  const error = !!loadError;

  // Derive display rows from the trade set
  const symbols = useMemo<SymbolDisplay[]>(() => {
    if (!tradeSet) return [];
    const perSymbolTrades = new Map<string, number[]>();
    for (const t of tradeSet.trades) {
      const arr = perSymbolTrades.get(t.symbol) ?? [];
      arr.push(t.pnl);
      perSymbolTrades.set(t.symbol, arr);
    }
    return bySymbolStats(tradeSet.trades).map((s) => {
      const pnls = perSymbolTrades.get(s.symbol) ?? [];
      return {
        ...s,
        avg_pnl: s.trades > 0 ? s.net / s.trades : 0,
        best_trade: pnls.length > 0 ? Math.max(...pnls) : null,
        worst_trade: pnls.length > 0 ? Math.min(...pnls) : null,
      };
    });
  }, [tradeSet]);

  const lastUpdated = tradeSet
    ? new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : null;

  const hasSymbols = symbols.length > 0;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>Symbol Performance</CardTitle>
          <div className="flex items-center gap-2">
            {hasSymbols && (
              <span className="text-xs text-muted-foreground">
                {symbols.length} symbol{symbols.length !== 1 ? "s" : ""}
              </span>
            )}
            <button
              onClick={() => mutate()}
              disabled={loading}
              className="text-muted-foreground hover:text-foreground transition-colors"
              title="Refresh"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
            </button>
          </div>
        </div>
        {lastUpdated && (
          <p className="text-xs text-muted-foreground">Updated: {lastUpdated}</p>
        )}
      </CardHeader>
      <CardContent className="p-0">
        {!hasSymbols && !error ? (
          /* Skeleton / loading */
          <div className="px-4 pb-4 space-y-2">
            {[...Array(3)].map((_, i) => (
              <div key={i} className="h-10 rounded bg-muted animate-pulse" />
            ))}
          </div>
        ) : error ? (
          /* Error state */
          <div className="px-4 pb-4 text-sm text-muted-foreground">
            Unable to load symbol data.
          </div>
        ) : !hasSymbols ? (
          /* Empty state */
          <div className="px-4 pb-4 text-sm text-muted-foreground">
            No symbol data yet.
          </div>
        ) : (
          /* Table */
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border bg-muted/30">
                  <th className="px-4 py-2 text-left font-medium text-muted-foreground">Symbol</th>
                  <th className="px-4 py-2 text-right font-medium text-muted-foreground">Trades</th>
                  <th className="px-4 py-2 text-right font-medium text-muted-foreground">W/L</th>
                  <th className="px-4 py-2 text-right font-medium text-muted-foreground">Win Rate</th>
                  <th className="px-4 py-2 text-right font-medium text-muted-foreground">Total P&amp;L</th>
                  <th className="px-4 py-2 text-right font-medium text-muted-foreground">Avg P&amp;L</th>
                  <th className="px-4 py-2 text-right font-medium text-muted-foreground">Best</th>
                  <th className="px-4 py-2 text-right font-medium text-muted-foreground">Worst</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {symbols.map((s) => (
                  <tr key={s.symbol} className="hover:bg-muted/20 transition-colors">
                    <td className="px-4 py-2.5 font-mono font-semibold">{s.symbol}</td>
                    <td className="px-4 py-2.5 text-right tabular-nums">{s.trades}</td>
                    <td className="px-4 py-2.5 text-right tabular-nums">
                      <span className="text-green-500">{s.wins}</span>
                      <span className="text-muted-foreground mx-0.5">/</span>
                      <span className="text-red-500">{s.losses}</span>
                    </td>
                    <td className={`px-4 py-2.5 text-right tabular-nums ${winRateClass(s.winRate)}`}>
                      {(s.winRate * 100).toFixed(1)}%
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      <Badge variant={pnlVariant(s.net)}>
                        {formatPnl(s.net)}
                      </Badge>
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      <Badge variant={pnlVariant(s.avg_pnl)}>
                        {formatPnl(s.avg_pnl)}
                      </Badge>
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      <Badge variant={s.best_trade !== null && s.best_trade > 0 ? "bull" : "neutral"}>
                        {formatPnl(s.best_trade)}
                      </Badge>
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      <Badge variant={s.worst_trade !== null && s.worst_trade < 0 ? "bear" : "neutral"}>
                        {formatPnl(s.worst_trade)}
                      </Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {/* Dedup caveat footer */}
            {tradeSet && (
              <p className="px-4 py-2 text-[10px] text-muted-foreground font-mono">
                {dedupCaveat(tradeSet)}
              </p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
