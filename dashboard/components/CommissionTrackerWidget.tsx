"use client";

import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { fetchEngine } from "@/lib/api";


interface CommissionStats {
  total_commissions: number;
  gross_pnl: number;
  net_pnl: number;
  by_symbol: Record<string, number>;
  trade_count: number;
  avg_commission_per_trade: number;
  rates: Record<string, number>;
}

export function CommissionTrackerWidget() {
  const [data, setData] = useState<CommissionStats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = async () => {
      try {
        const payload = await fetchEngine(`/portfolio/stats/commissions`);
        setData(payload);
      } catch {
        setData(null);
      } finally {
        setLoading(false);
      }
    };

    load();
    const id = setInterval(load, 300_000); // refresh every 5 minutes
    return () => clearInterval(id);
  }, []);

  if (loading) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Commission Tracker</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            <div className="animate-pulse h-8 bg-muted rounded" />
            <div className="animate-pulse h-8 bg-muted rounded" />
          </div>
        </CardContent>
      </Card>
    );
  }

  if (!data) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Commission Tracker</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">Unable to load commission data</p>
        </CardContent>
      </Card>
    );
  }

  const totalCommissions = data.total_commissions;
  const grossPnl = data.gross_pnl;
  const netPnl = data.net_pnl;
  const avgPerTrade = data.avg_commission_per_trade;
  const tradeCount = data.trade_count;
  const bySymbol = data.by_symbol;

  const headerBadgeVariant: "warn" | "neutral" =
    totalCommissions > 100 ? "warn" : "neutral";

  return (
    <Card>
      <CardHeader className="pb-2 flex flex-row items-center justify-between">
        <CardTitle className="text-sm">Commission Tracker</CardTitle>
        <Badge variant={headerBadgeVariant}>
          ${totalCommissions.toFixed(2)} Total
        </Badge>
      </CardHeader>
      <CardContent>
        {/* 3-column stats grid */}
        <div className="grid grid-cols-3 gap-3 text-center">
          <div className="rounded bg-muted p-3">
            <p className="text-xs text-muted-foreground">Gross P&L</p>
            <p
              className={cn(
                "text-lg font-mono font-bold",
                grossPnl >= 0 ? "text-green-500" : "text-red-500"
              )}
            >
              {grossPnl >= 0 ? "+" : ""}${grossPnl.toFixed(2)}
            </p>
          </div>
          <div className="rounded bg-muted p-3">
            <p className="text-xs text-muted-foreground">Net P&L</p>
            <p
              className={cn(
                "text-lg font-mono font-bold",
                netPnl >= 0 ? "text-green-500" : "text-red-500"
              )}
            >
              {netPnl >= 0 ? "+" : ""}${netPnl.toFixed(2)}
            </p>
          </div>
          <div className="rounded bg-muted p-3">
            <p className="text-xs text-muted-foreground">All Time</p>
            <p className="text-lg font-mono font-bold">${totalCommissions.toFixed(2)}</p>
          </div>
        </div>

        {/* Secondary stats */}
        <div className="flex justify-between mt-3 text-sm">
          <span className="text-muted-foreground">Avg per trade</span>
          <span className="font-mono">${avgPerTrade.toFixed(2)}</span>
        </div>
        <div className="flex justify-between text-sm">
          <span className="text-muted-foreground">Trade count</span>
          <span className="font-mono">{tradeCount}</span>
        </div>

        {/* Per-symbol breakdown */}
        {Object.keys(bySymbol).length > 0 && (
          <div className="mt-3 border-t border-border pt-2 space-y-1">
            <p className="text-xs text-muted-foreground mb-1">By symbol</p>
            {Object.entries(bySymbol).map(([sym, cost]) => (
              <div key={sym} className="flex justify-between text-xs">
                <span className="font-mono text-muted-foreground">{sym}</span>
                <span className="font-mono">${cost.toFixed(2)}</span>
              </div>
            ))}
          </div>
        )}

        {/* Commission impact note */}
        {totalCommissions > 0 && avgPerTrade > 0 && (
          <p className="text-xs text-muted-foreground mt-2 border-t border-border pt-2">
            Commission drag: ${totalCommissions.toFixed(2)} total cost reduces net P&L
          </p>
        )}

        <p className="text-xs text-muted-foreground mt-2">Refreshes every 5m</p>
      </CardContent>
    </Card>
  );
}
