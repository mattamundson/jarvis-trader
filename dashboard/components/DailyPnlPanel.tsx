"use client";

import { useMemo } from "react";
import useSWR from "swr";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ReferenceLine,
  ResponsiveContainer,
} from "recharts";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { fetchDailyPnlHistoryNormalized } from "@/lib/api";
import { formatCurrency } from "@/lib/utils";
import type { DailyPnlRecord } from "@/lib/api";

const REFRESH_MS = 30_000;

async function dailyPnlFetcher(): Promise<DailyPnlRecord[]> {
  return fetchDailyPnlHistoryNormalized({ days: 30 });
}

function formatShortDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

export function DailyPnlPanel() {
  const { data: records, isLoading, error } = useSWR<DailyPnlRecord[]>(
    "portfolio/history/daily-pnl-normalized-30",
    dailyPnlFetcher,
    { refreshInterval: REFRESH_MS }
  );

  const rows = records ?? [];

  // Determine chart gradient direction based on final cumulative P&L
  const finalCumulative = rows.length > 0 ? rows[rows.length - 1].cumulative_pnl : 0;
  const gradientColor = finalCumulative >= 0 ? "#22c55e" : "#ef4444";

  // Summary stats
  const totalRealized = rows.reduce((sum, r) => sum + r.realized_pnl, 0);
  const profitDays = rows.filter((r) => r.realized_pnl > 0).length;
  const lossDays = rows.filter((r) => r.realized_pnl < 0).length;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>Daily P&amp;L — 30 Days</CardTitle>
          {rows.length > 0 && (
            <span
              className={`tabular-nums text-sm font-bold ${
                totalRealized >= 0 ? "text-bull" : "text-bear"
              }`}
            >
              {formatCurrency(totalRealized)}
            </span>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {isLoading && (
          <div className="flex items-center justify-center py-8">
            <div className="h-4 w-4 rounded-full border-2 border-accent border-t-transparent animate-spin mr-2" />
            <span className="text-xs text-muted-foreground">Loading…</span>
          </div>
        )}

        {error && !isLoading && (
          <p className="text-center text-xs text-bear py-6">
            Failed to load P&L history — engine may be offline.
          </p>
        )}

        {!isLoading && !error && rows.length === 0 && (
          <p className="text-center text-sm text-muted-foreground py-8">
            No P&L history yet
          </p>
        )}

        {!isLoading && !error && rows.length > 0 && (
          <>
            {/* Summary stat strip */}
            <div className="grid grid-cols-3 gap-3">
              <StatPill
                label="30-Day P&L"
                value={formatCurrency(totalRealized)}
                color={totalRealized >= 0 ? "text-bull" : "text-bear"}
              />
              <StatPill
                label="Profit Days"
                value={String(profitDays)}
                color="text-bull"
              />
              <StatPill
                label="Loss Days"
                value={String(lossDays)}
                color={lossDays > 0 ? "text-bear" : "text-muted-foreground"}
              />
            </div>

            {/* Cumulative equity area chart */}
            {rows.length > 1 && (
              <div className="h-36">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart
                    data={rows}
                    margin={{ top: 4, right: 4, bottom: 0, left: 0 }}
                  >
                    <defs>
                      <linearGradient id="dailyPnlGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor={gradientColor} stopOpacity={0.3} />
                        <stop offset="95%" stopColor={gradientColor} stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <XAxis
                      dataKey="date"
                      hide
                      tickFormatter={formatShortDate}
                    />
                    <YAxis domain={["auto", "auto"]} hide />
                    <ReferenceLine y={0} stroke="hsl(222 47% 14%)" strokeDasharray="3 3" />
                    <Tooltip
                      contentStyle={{
                        backgroundColor: "hsl(222 47% 9%)",
                        border: "1px solid hsl(222 47% 14%)",
                        borderRadius: "8px",
                        fontSize: "12px",
                      }}
                      labelFormatter={(label: string) => formatShortDate(label)}
                      formatter={(value: number, name: string) => [
                        formatCurrency(value),
                        name === "cumulative_pnl" ? "Cumulative" : "Daily",
                      ]}
                    />
                    <Area
                      type="monotone"
                      dataKey="cumulative_pnl"
                      stroke={gradientColor}
                      strokeWidth={1.5}
                      fill="url(#dailyPnlGrad)"
                      dot={false}
                    />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            )}

            {/* Daily breakdown table */}
            <TableRows rows={rows} />
          </>
        )}
      </CardContent>
    </Card>
  );
}

function TableRows({ rows }: { rows: DailyPnlRecord[] }) {
  const reversedRows = useMemo(() => [...rows].reverse(), [rows]);

  return (
    <div className="overflow-x-auto -mx-1 max-h-48 overflow-y-auto">
      <table className="w-full text-xs">
        <caption className="sr-only">Daily P&L breakdown with realized and cumulative values</caption>
        <thead className="sticky top-0 bg-card">
          <tr className="border-b border-border">
            <th className="pb-2 pr-3 text-left font-semibold text-muted-foreground uppercase tracking-wider">
              Date
            </th>
            <th className="pb-2 pr-3 text-right font-semibold text-muted-foreground uppercase tracking-wider whitespace-nowrap">
              Daily P&L
            </th>
            <th className="pb-2 pr-3 text-right font-semibold text-muted-foreground uppercase tracking-wider whitespace-nowrap">
              Cumulative
            </th>
            <th className="pb-2 text-right font-semibold text-muted-foreground uppercase tracking-wider">
              Trades
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border/50">
          {reversedRows.map((row) => (
            <tr key={row.date} className="hover:bg-muted/20 transition-colors">
              <td className="py-1.5 pr-3 font-mono text-muted-foreground whitespace-nowrap">
                {formatShortDate(row.date)}
              </td>
              <td
                className={`py-1.5 pr-3 text-right tabular-nums font-medium ${
                  row.realized_pnl > 0
                    ? "text-bull"
                    : row.realized_pnl < 0
                    ? "text-bear"
                    : "text-muted-foreground"
                }`}
              >
                <span aria-label={`Daily P&L: ${row.realized_pnl >= 0 ? "+" : ""}${formatCurrency(row.realized_pnl)}`}>
                  {row.realized_pnl >= 0 ? "+" : ""}{formatCurrency(row.realized_pnl)}
                </span>
              </td>
              <td
                className={`py-1.5 pr-3 text-right tabular-nums ${
                  row.cumulative_pnl >= 0 ? "text-bull" : "text-bear"
                }`}
              >
                <span aria-label={`Cumulative P&L: ${row.cumulative_pnl >= 0 ? "+" : ""}${formatCurrency(row.cumulative_pnl)}`}>
                  {row.cumulative_pnl >= 0 ? "+" : ""}{formatCurrency(row.cumulative_pnl)}
                </span>
              </td>
              <td className="py-1.5 text-right tabular-nums text-muted-foreground">
                {row.num_trades}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function StatPill({
  label,
  value,
  color,
}: {
  label: string;
  value: string;
  color: string;
}) {
  return (
    <div className="rounded-lg bg-muted/40 px-3 py-2 text-center">
      <p className="text-xs text-muted-foreground uppercase tracking-wider mb-0.5">
        {label}
      </p>
      <p className={`tabular-nums text-sm font-bold ${color}`}>{value}</p>
    </div>
  );
}
