"use client";

import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { TrendingUp } from "lucide-react";
import { fetchEngine } from "@/lib/api";


interface WeeklyStats {
  period: string;
  total_trades: number;
  wins: number;
  losses: number;
  win_rate: number;
  total_pnl: number;
  avg_pnl: number;
  best_trade: number;
  worst_trade: number;
  trading_days: number;
}

function pnlVariant(value: number): "bull" | "bear" | "neutral" {
  if (value > 0) return "bull";
  if (value < 0) return "bear";
  return "neutral";
}

function formatPnl(value: number): string {
  const sign = value >= 0 ? "+" : "";
  return `${sign}$${value.toFixed(2)}`;
}

export function WeeklyStatsWidget() {
  const [data, setData] = useState<WeeklyStats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = async () => {
      try {
        const payload = await fetchEngine(`/portfolio/stats/weekly`);
        setData(payload);
      } catch {
        setData(null);
      } finally {
        setLoading(false);
      }
    };

    load();
    const id = setInterval(load, 120_000); // refresh every 2 minutes
    return () => clearInterval(id);
  }, []);

  if (loading) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-2">
            <TrendingUp className="h-4 w-4" />
            Weekly Performance
          </CardTitle>
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
          <CardTitle className="text-sm flex items-center gap-2">
            <TrendingUp className="h-4 w-4" />
            Weekly Performance
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">Unable to load weekly stats</p>
        </CardContent>
      </Card>
    );
  }

  const stats: Array<{ label: string; value: React.ReactNode }> = [
    {
      label: "Trades",
      value: (
        <span className="font-mono font-medium">{data.total_trades}</span>
      ),
    },
    {
      label: "Win Rate",
      value: (
        <span className="font-mono font-medium">
          {data.win_rate.toFixed(1)}%
        </span>
      ),
    },
    {
      label: "Total P&L",
      value: (
        <Badge variant={pnlVariant(data.total_pnl)}>
          {formatPnl(data.total_pnl)}
        </Badge>
      ),
    },
    {
      label: "Avg P&L",
      value: (
        <Badge variant={pnlVariant(data.avg_pnl)}>
          {formatPnl(data.avg_pnl)}
        </Badge>
      ),
    },
    {
      label: "Best Trade",
      value: (
        <Badge variant={pnlVariant(data.best_trade)}>
          {formatPnl(data.best_trade)}
        </Badge>
      ),
    },
    {
      label: "Worst Trade",
      value: (
        <Badge variant={pnlVariant(data.worst_trade)}>
          {formatPnl(data.worst_trade)}
        </Badge>
      ),
    },
  ];

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm flex items-center gap-2">
          <TrendingUp className="h-4 w-4" />
          Weekly Performance
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid grid-cols-3 gap-3">
          {stats.map((s) => (
            <div key={s.label} className="space-y-1">
              <div className="text-xs text-muted-foreground">{s.label}</div>
              <div>{s.value}</div>
            </div>
          ))}
        </div>
        <div
          className="pt-2 font-mono text-[10px] text-muted-foreground"
          style={{ borderTop: "1px solid hsl(var(--border))" }}
        >
          Trading days: {data.trading_days} &bull; Period: Last 7 days
        </div>
      </CardContent>
    </Card>
  );
}
