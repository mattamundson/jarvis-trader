"use client";

import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";

const ENGINE_URL = process.env.NEXT_PUBLIC_ENGINE_URL || "http://localhost:8010";

interface Position {
  trade_id?: string;
  symbol: string;
  action: string;
  quantity: number;
  entry_price?: number;
  current_price?: number;
  unrealized_pnl?: number;
  entry_time?: string;
}

interface PositionsResponse {
  positions?: Position[];
  total_unrealized_pnl?: number;
  count?: number;
}

export function OpenPositionsWidget() {
  const [data, setData] = useState<PositionsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fetchPositions = async () => {
    try {
      const res = await fetch(`${ENGINE_URL}/portfolio/paper/positions`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json: PositionsResponse = await res.json();
      setData(json);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch");
    }
  };

  useEffect(() => {
    fetchPositions();
    const interval = setInterval(fetchPositions, 30_000);
    return () => clearInterval(interval);
  }, []);

  const positions = data?.positions ?? [];
  const count = data?.count ?? positions.length;
  const totalUnrealizedPnl =
    data?.total_unrealized_pnl ??
    positions.reduce((sum, p) => sum + (p.unrealized_pnl ?? 0), 0);

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3">
        <CardTitle className="text-base font-semibold">Open Positions</CardTitle>
        <div className="flex gap-2">
          {count > 0 && (
            <Badge variant={totalUnrealizedPnl >= 0 ? "bull" : "bear"}>
              {totalUnrealizedPnl >= 0 ? "+" : ""}${totalUnrealizedPnl.toFixed(2)} Unrealized
            </Badge>
          )}
          <Badge variant={count > 0 ? "warn" : "neutral"}>{count} Open</Badge>
        </div>
      </CardHeader>
      <CardContent>
        {error && (
          <p className="text-sm text-red-400 mb-2">Engine error: {error}</p>
        )}
        {count === 0 ? (
          <p className="text-sm text-muted-foreground text-center py-6">
            No open positions
          </p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-muted-foreground uppercase">
                <th className="text-left pb-2">Symbol</th>
                <th className="text-left pb-2">Side</th>
                <th className="text-right pb-2">Qty</th>
                <th className="text-right pb-2">Entry</th>
                <th className="text-right pb-2">Current</th>
                <th className="text-right pb-2">Unreal. P&amp;L</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((pos) => (
                <tr
                  key={pos.trade_id ?? pos.symbol}
                  className="border-t border-border"
                >
                  <td className="py-2 font-mono">{pos.symbol}</td>
                  <td className="py-2">
                    <Badge variant={pos.action.toUpperCase() === "LONG" || pos.action.toLowerCase() === "buy" ? "bull" : "bear"}>
                      {pos.action.toUpperCase()}
                    </Badge>
                  </td>
                  <td className="py-2 text-right font-mono">{pos.quantity}</td>
                  <td className="py-2 text-right font-mono">
                    {pos.entry_price?.toFixed(2) ?? "—"}
                  </td>
                  <td className="py-2 text-right font-mono">
                    {pos.current_price?.toFixed(2) ?? "—"}
                  </td>
                  <td
                    className={cn(
                      "py-2 text-right font-mono font-medium",
                      pos.unrealized_pnl != null && pos.unrealized_pnl > 0
                        ? "text-green-400"
                        : pos.unrealized_pnl != null && pos.unrealized_pnl < 0
                        ? "text-red-400"
                        : ""
                    )}
                  >
                    {pos.unrealized_pnl != null
                      ? `${pos.unrealized_pnl >= 0 ? "+" : ""}$${Math.abs(pos.unrealized_pnl).toFixed(2)}`
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="text-xs text-muted-foreground mt-2">Refreshes every 30s</p>
      </CardContent>
    </Card>
  );
}
