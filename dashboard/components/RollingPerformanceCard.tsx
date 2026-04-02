"use client";

import { useState, useEffect } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { BarChart2 } from "lucide-react";
import { fetchEngine } from "@/lib/api";

interface RollingMetrics {
  days: number;
  trade_count: number;
  profit_factor: number | null;
  sharpe_ratio: number | null;
  win_rate: number | null;
  gross_pnl: number;
  max_drawdown: number;
  avg_pnl_per_trade: number | null;
  best_trade: number | null;
  worst_trade: number | null;
  window_start: string;
  window_end: string;
  error?: string;
}

const WINDOWS = [7, 14, 30] as const;

function fmt(v: number | null, decimals = 2): string {
  if (v === null || v === undefined) return "N/A";
  return v.toFixed(decimals);
}

function fmtPct(v: number | null): string {
  if (v === null || v === undefined) return "N/A";
  return `${(v * 100).toFixed(1)}%`;
}

function fmtUsd(v: number): string {
  return v >= 0 ? `+$${v.toFixed(2)}` : `-$${Math.abs(v).toFixed(2)}`;
}

export function RollingPerformanceCard() {
  const [window, setWindow] = useState<7 | 14 | 30>(30);
  const [data, setData] = useState<RollingMetrics | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      try {
        const payload = await fetchEngine(`/analytics/performance/rolling?days=${window}`);
        setData(payload);
      } catch {
        setData(null);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [window]);

  const pfPass = data?.profit_factor !== null && (data?.profit_factor ?? 0) >= 2.0;
  const sharpePass = data?.sharpe_ratio !== null && (data?.sharpe_ratio ?? 0) >= 1.5;

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm flex items-center gap-2">
            <BarChart2 className="h-4 w-4" />
            Rolling Performance
          </CardTitle>
          <div className="flex gap-1">
            {WINDOWS.map((w) => (
              <button
                key={w}
                onClick={() => setWindow(w)}
                className={`px-2 py-0.5 text-xs rounded ${
                  window === w
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                {w}d
              </button>
            ))}
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {loading ? (
          <div className="animate-pulse space-y-2">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="h-4 bg-muted rounded" />
            ))}
          </div>
        ) : !data || data.error ? (
          <p className="text-sm text-muted-foreground">No data available</p>
        ) : data.trade_count === 0 ? (
          <p className="text-sm text-muted-foreground">No trades in last {window} days</p>
        ) : (
          <div className="space-y-2 text-sm">
            <div className="grid grid-cols-2 gap-x-4 gap-y-1">
              <div className="flex justify-between">
                <span className="text-muted-foreground">Trades</span>
                <span className="font-mono">{data.trade_count}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Gross P&amp;L</span>
                <span className={`font-mono ${data.gross_pnl >= 0 ? "text-green-500" : "text-red-400"}`}>
                  {fmtUsd(data.gross_pnl)}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Win Rate</span>
                <span className="font-mono">{fmtPct(data.win_rate)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Avg/Trade</span>
                <span className={`font-mono ${(data.avg_pnl_per_trade ?? 0) >= 0 ? "text-green-500" : "text-red-400"}`}>
                  {data.avg_pnl_per_trade !== null ? fmtUsd(data.avg_pnl_per_trade) : "N/A"}
                </span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-muted-foreground">Prof. Factor</span>
                <div className="flex items-center gap-1">
                  <span className="font-mono">{fmt(data.profit_factor)}</span>
                  {data.profit_factor !== null && (
                    <Badge variant={pfPass ? "bull" : "bear"} className="text-xs py-0 h-4">
                      {pfPass ? "✓" : "✗"}
                    </Badge>
                  )}
                </div>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-muted-foreground">Sharpe</span>
                <div className="flex items-center gap-1">
                  <span className="font-mono">{fmt(data.sharpe_ratio)}</span>
                  {data.sharpe_ratio !== null && (
                    <Badge variant={sharpePass ? "bull" : "bear"} className="text-xs py-0 h-4">
                      {sharpePass ? "✓" : "✗"}
                    </Badge>
                  )}
                </div>
              </div>
            </div>
            <div className="pt-1 border-t text-xs text-muted-foreground">
              {data.window_start} &rarr; {data.window_end}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
