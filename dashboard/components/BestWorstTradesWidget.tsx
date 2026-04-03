"use client";

import { useEffect, useState, useCallback } from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { fetchEngine } from "@/lib/api";


interface TradeRecord {
  id: string | number;
  symbol: string;
  action: string;
  entry_price: number;
  exit_price: number | null;
  quantity: number;
  entry_time: string;
  exit_time: string | null;
  pnl: number | null;
  commission: number | null;
  status: string;
}

interface TradesResponse {
  trades: TradeRecord[];
}

function TradeRow({ trade }: { trade: TradeRecord }) {
  const pnl = trade.pnl as number;
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
  const [best5, setBest5] = useState<TradeRecord[]>([]);
  const [worst5, setWorst5] = useState<TradeRecord[]>([]);
  const [insufficient, setInsufficient] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchTrades = useCallback(async () => {
    try {
      const raw: unknown = await fetchEngine<unknown>(
        `/portfolio/history/trades?limit=500&status=CLOSED`
      );
      const rows: TradeRecord[] = Array.isArray(raw)
        ? raw
        : ((raw as { trades?: TradeRecord[] }).trades ?? []);

      const closed = rows.filter(
        (t) => t.status === "CLOSED" && t.pnl !== null && t.pnl !== undefined
      );

      if (closed.length < 2) {
        setInsufficient(true);
        setBest5([]);
        setWorst5([]);
      } else {
        setInsufficient(false);
        const sorted = [...closed].sort((a, b) => (b.pnl as number) - (a.pnl as number));
        setBest5(sorted.slice(0, 5));
        setWorst5([...sorted].reverse().slice(0, 5));
      }
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load trades");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchTrades();
    const interval = setInterval(fetchTrades, 5 * 60 * 1000);
    return () => clearInterval(interval);
  }, [fetchTrades]);

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
              From last 500 closed trades &bull; Refreshes every 5m
            </p>
          </>
        )}
      </CardContent>
    </Card>
  );
}
