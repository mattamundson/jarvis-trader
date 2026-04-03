"use client";

import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Sun } from "lucide-react";
import { fetchEngine } from "@/lib/api";

interface SessionToday {
  date: string;
  session: string;
  closed_trades: number;
  open_trades: number;
  gross_pnl: number;
  wins: number;
  losses: number;
  win_rate: number | null;
  best_trade: number | null;
  worst_trade: number | null;
  avg_pnl: number | null;
  symbols_traded: string[];
  last_updated: string;
}

export function SessionTodayWidget() {
  const [data, setData] = useState<SessionToday | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = async () => {
      try {
        const payload = await fetchEngine("/portfolio/stats/session-today");
        setData(payload);
      } catch {
        setData(null);
      } finally {
        setLoading(false);
      }
    };
    load();
    const id = setInterval(load, 30_000); // refresh every 30s
    return () => clearInterval(id);
  }, []);

  if (loading) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-2">
            <Sun className="h-4 w-4" />Today&apos;s Session
          </CardTitle>
        </CardHeader>
        <CardContent><div className="animate-pulse h-12 bg-muted rounded" /></CardContent>
      </Card>
    );
  }

  if (!data) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-2">
            <Sun className="h-4 w-4" />Today&apos;s Session
          </CardTitle>
        </CardHeader>
        <CardContent><p className="text-sm text-muted-foreground">No session data</p></CardContent>
      </Card>
    );
  }

  const pnlVariant: "bull" | "bear" = data.gross_pnl >= 0 ? "bull" : "bear";

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm flex items-center gap-2">
            <Sun className="h-4 w-4" />Today&apos;s Session
          </CardTitle>
          <Badge variant={pnlVariant}>
            {data.gross_pnl >= 0 ? "+" : ""}${data.gross_pnl.toFixed(2)}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-2">
        {data.closed_trades === 0 && data.open_trades === 0 ? (
          <p className="text-sm text-muted-foreground">No trades today</p>
        ) : (
          <>
            <div className="grid grid-cols-3 gap-2 text-xs">
              <div>
                <div className="text-muted-foreground">Trades</div>
                <div className="font-mono font-medium">{data.closed_trades}</div>
              </div>
              <div>
                <div className="text-muted-foreground">W / L</div>
                <div className="font-mono">
                  <span className="text-green-500">{data.wins}</span>
                  <span className="text-muted-foreground"> / </span>
                  <span className="text-red-400">{data.losses}</span>
                </div>
              </div>
              <div>
                <div className="text-muted-foreground">Win Rate</div>
                <div className="font-mono">
                  {data.win_rate !== null ? `${(data.win_rate * 100).toFixed(0)}%` : "N/A"}
                </div>
              </div>
            </div>
            {data.open_trades > 0 && (
              <div className="text-xs">
                <Badge variant="info">{data.open_trades} open</Badge>
              </div>
            )}
            {data.symbols_traded.length > 0 && (
              <div className="flex gap-1 flex-wrap">
                {data.symbols_traded.map((s) => (
                  <span key={s} className="text-xs bg-muted rounded px-1.5 py-0.5">{s}</span>
                ))}
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
