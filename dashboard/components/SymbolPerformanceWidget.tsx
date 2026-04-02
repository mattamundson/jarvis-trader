"use client";

import { useEffect, useState } from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { RefreshCw } from "lucide-react";
import { fetchEngine } from "@/lib/api";


interface SymbolStat {
  symbol: string;
  count: number;
  wins: number;
  losses: number;
  win_rate: number;
  total_pnl: number;
  avg_pnl: number;
  best_trade: number;
  worst_trade: number;
}

interface BySymbolResponse {
  symbols: SymbolStat[];
  total_symbols: number;
}

function pnlVariant(value: number): "bull" | "bear" | "neutral" {
  if (value > 0) return "bull";
  if (value < 0) return "bear";
  return "neutral";
}

function formatPnl(value: number): string {
  const abs = Math.abs(value).toFixed(2);
  return value >= 0 ? `+$${abs}` : `-$${abs}`;
}

function winRateClass(rate: number): string {
  if (rate >= 55) return "text-green-500";
  if (rate < 45) return "text-red-500";
  return "text-muted-foreground";
}

export function SymbolPerformanceWidget() {
  const [data, setData] = useState<BySymbolResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);

  const fetchData = () => {
    setLoading(true);
    fetchEngine(`/analytics/trades/by-symbol`)
      .then((r) => r.json())
      .then((d: BySymbolResponse) => {
        // Sort by total_pnl descending
        const sorted = {
          ...d,
          symbols: [...d.symbols].sort((a, b) => b.total_pnl - a.total_pnl),
        };
        setData(sorted);
        setLastUpdated(
          new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
        );
        setLoading(false);
      })
      .catch(() => setLoading(false));
  };

  useEffect(() => {
    fetchData();
    const id = setInterval(fetchData, 300_000); // refresh every 5 min
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const hasSymbols = data && data.symbols.length > 0;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>Symbol Performance</CardTitle>
          <div className="flex items-center gap-2">
            {data && (
              <span className="text-xs text-muted-foreground">
                {data.total_symbols} symbol{data.total_symbols !== 1 ? "s" : ""}
              </span>
            )}
            <button
              onClick={fetchData}
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
        {!data ? (
          /* Skeleton */
          <div className="px-4 pb-4 space-y-2">
            {[...Array(3)].map((_, i) => (
              <div key={i} className="h-10 rounded bg-muted animate-pulse" />
            ))}
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
                {data.symbols.map((s) => (
                  <tr key={s.symbol} className="hover:bg-muted/20 transition-colors">
                    <td className="px-4 py-2.5 font-mono font-semibold">{s.symbol}</td>
                    <td className="px-4 py-2.5 text-right tabular-nums">{s.count}</td>
                    <td className="px-4 py-2.5 text-right tabular-nums">
                      <span className="text-green-500">{s.wins}</span>
                      <span className="text-muted-foreground mx-0.5">/</span>
                      <span className="text-red-500">{s.losses}</span>
                    </td>
                    <td className={`px-4 py-2.5 text-right tabular-nums ${winRateClass(s.win_rate)}`}>
                      {s.win_rate.toFixed(1)}%
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      <Badge variant={pnlVariant(s.total_pnl)}>
                        {formatPnl(s.total_pnl)}
                      </Badge>
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      <Badge variant={pnlVariant(s.avg_pnl)}>
                        {formatPnl(s.avg_pnl)}
                      </Badge>
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      <Badge variant="bull">{formatPnl(s.best_trade)}</Badge>
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      <Badge variant="bear">{formatPnl(s.worst_trade)}</Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
