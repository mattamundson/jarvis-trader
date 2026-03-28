"use client";

import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { formatCurrency, formatPercent, formatNumber } from "@/lib/utils";

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

interface PerformancePanelProps {
  metrics: PerformanceMetrics | null;
  equityCurve: EquityPoint[];
}

export function PerformancePanel({ metrics, equityCurve }: PerformancePanelProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Performance</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Equity curve */}
        {equityCurve.length > 1 && (
          <div className="h-32">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={equityCurve} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
                <defs>
                  <linearGradient id="equityGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#22c55e" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#22c55e" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <XAxis dataKey="date" hide />
                <YAxis domain={["auto", "auto"]} hide />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "hsl(222 47% 9%)",
                    border: "1px solid hsl(222 47% 14%)",
                    borderRadius: "8px",
                    fontSize: "12px",
                  }}
                  formatter={(v: number) => [formatCurrency(v), "Equity"]}
                />
                <Area
                  type="monotone"
                  dataKey="equity"
                  stroke="#22c55e"
                  strokeWidth={1.5}
                  fill="url(#equityGrad)"
                  dot={false}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
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
          <p className="text-center text-sm text-muted-foreground py-2">
            No trade history yet
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
