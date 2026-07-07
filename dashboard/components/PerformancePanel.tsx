"use client";

import { useMemo } from "react";
import useSWR from "swr";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { formatCurrency, formatPercent, formatNumber } from "@/lib/utils";
import { fetchEngine } from "@/lib/api";
import { LightweightSeriesChart, type SeriesPoint } from "@/components/charts/LightweightSeriesChart";

interface PerformanceMetrics {
  sharpe_ratio: number;
  max_drawdown: number;
  win_rate: number;
  profit_factor: number;
  total_trades: number;
  winning_trades: number;
  gross_pnl: number;
}

interface EquityPoint {
  date: string;
  equity: number;
}

interface EquityCurveData {
  points: EquityPoint[];
}

interface PerformancePanelProps {
  metrics?: PerformanceMetrics | null;
  equityCurve?: EquityPoint[];
}

function fetcher<T>(url: string): Promise<T> {
  return fetchEngine<T>(url);
}

export function PerformancePanel({ metrics, equityCurve }: PerformancePanelProps) {
  // Fetch equity curve from engine if not provided
  const { data: fetchedCurveData } = useSWR<EquityCurveData>(
    "/portfolio/history/equity-curve",
    fetcher,
    { refreshInterval: 30_000 }
  );

  const curve = useMemo(() => {
    if (equityCurve && equityCurve.length > 0) return equityCurve;
    return fetchedCurveData?.points ?? [];
  }, [equityCurve, fetchedCurveData]);

  // Same equity points, handed to the TradingView renderer as an area series.
  const series: SeriesPoint[] = useMemo(
    () => curve.map((p) => ({ time: p.date, value: p.equity })),
    [curve],
  );
  return (
    <Card>
      <CardHeader>
        <CardTitle>Performance</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Equity curve */}
        {curve.length > 1 && (
          <LightweightSeriesChart
            data={series}
            type="area"
            color="#22c55e"
            topColor="rgba(34,197,94,0.30)"
            bottomColor="rgba(34,197,94,0.00)"
            height={128}
            valueFormat="dollar"
          />
        )}

        {/* Metrics grid */}
        {metrics ? (
          <div className="grid grid-cols-2 gap-x-4 gap-y-3">
            <MetricRow
              label="Sharpe Ratio"
              value={metrics.sharpe_ratio.toFixed(2)}
              color={metrics.sharpe_ratio >= 1.5 ? "text-bull" : metrics.sharpe_ratio >= 1 ? "text-warn" : "text-bear"}
            />
            <MetricRow
              label="Max Drawdown"
              value={formatPercent(-Math.abs(metrics.max_drawdown * 100))}
              color={metrics.max_drawdown < 0.05 ? "text-bull" : metrics.max_drawdown < 0.10 ? "text-warn" : "text-bear"}
            />
            <MetricRow
              label="Win Rate"
              value={formatPercent(metrics.win_rate * 100)}
              color={metrics.win_rate >= 0.55 ? "text-bull" : metrics.win_rate >= 0.45 ? "text-warn" : "text-bear"}
            />
            <MetricRow
              label="Profit Factor"
              value={metrics.profit_factor.toFixed(2)}
              color={metrics.profit_factor >= 1.5 ? "text-bull" : metrics.profit_factor >= 1 ? "text-warn" : "text-bear"}
            />
            <MetricRow
              label="Total Trades"
              value={formatNumber(metrics.total_trades)}
              color="text-foreground"
            />
            <MetricRow
              label="Gross P&L"
              value={formatCurrency(metrics.gross_pnl)}
              color={metrics.gross_pnl >= 0 ? "text-bull" : "text-bear"}
            />
          </div>
        ) : (
          <p className="text-center text-sm text-muted-foreground py-4">
            No data yet
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function MetricRow({
  label,
  value,
  color,
}: {
  label: string;
  value: string;
  color: string;
}) {
  return (
    <div>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={`tabular-nums text-sm font-semibold ${color}`}>{value}</p>
    </div>
  );
}
