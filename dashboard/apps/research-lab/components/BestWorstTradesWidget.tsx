"use client";

import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import {
  dedupCaveat,
  type HonestTrade,
  type HonestTradeSet,
} from "@/lib/honestTrades";
import { useHonestTrades } from "@/lib/useHonestTrades";


function TradeRow({ trade }: { trade: HonestTrade }) {
  const pnl = trade.pnl;
  return (
    <div className="flex items-center justify-between py-1.5 border-b border-border/40 last:border-0">
      <div className="flex items-center min-w-0">
        <span className="font-mono text-xs text-foreground truncate">{trade.symbol}</span>
        <Badge
          variant={trade.action === "LONG" ? "bull" : "bear"}
          className="ml-1 shrink-0"
        >
          {trade.action}
        </Badge>
      </div>
      <span
        className={cn(
          "font-mono text-xs font-medium ml-2 shrink-0",
          pnl >= 0 ? "text-green-400" : "text-red-400"
        )}
      >
        {pnl >= 0 ? "+" : ""}{pnl.toFixed(2)}
      </span>
    </div>
  );
}

export function BestWorstTradesWidget() {
  const { honest: tradeSet, isLoading: loading, error: loadError } = useHonestTrades(5 * 60 * 1000);
  const error = loadError ? (loadError instanceof Error ? loadError.message : String(loadError)) : null;
  const insufficient = tradeSet ? tradeSet.trades.length < 2 : false;
  const sorted = tradeSet && !insufficient ? [...tradeSet.trades].sort((a, b) => b.pnl - a.pnl) : [];
  const best5 = sorted.slice(0, 5);
  const worst5 = [...sorted].reverse().slice(0, 5);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Best &amp; Worst Trades</CardTitle>
      </CardHeader>
      <CardContent>
        {loading && (
          <p className="text-xs text-muted-foreground animate-pulse">Loading trade history…</p>
        )}

        {!loading && error && (
          <p className="text-xs text-red-400">Error: {error}</p>
        )}

        {!loading && !error && insufficient && (
          <p className="text-xs text-muted-foreground">Need more trade history</p>
        )}

        {!loading && !error && !insufficient && (
          <>
            <div className="grid grid-cols-2 gap-4">
              {/* Left: Top 5 best */}
              <div>
                <h4 className="text-xs font-semibold text-green-400 uppercase tracking-wider mb-2">
                  Top 5 Winners
                </h4>
                {best5.map((trade) => (
                  <TradeRow key={trade.id} trade={trade} />
                ))}
              </div>

              {/* Right: Top 5 worst */}
              <div>
                <h4 className="text-xs font-semibold text-red-400 uppercase tracking-wider mb-2">
                  Top 5 Losers
                </h4>
                {worst5.map((trade) => (
                  <TradeRow key={trade.id} trade={trade} />
                ))}
              </div>
            </div>

            <p className="text-xs text-muted-foreground mt-3">
              {tradeSet ? dedupCaveat(tradeSet) : "Deduped trade record"} &bull; Refreshes every 5m
            </p>
          </>
        )}
      </CardContent>
    </Card>
  );
}
