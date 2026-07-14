"use client";
import { useEffect, useMemo, useState } from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchDailyPnLHistory, type DailyPnlRecord } from "@/lib/api";
import { LightweightSeriesChart, type SeriesPoint } from "@/components/charts/LightweightSeriesChart";

export function DailyPnLChart({ days = 30 }: { days?: number }) {
  const [data, setData] = useState<DailyPnlRecord[]>([]);
  const [loading, setLoading] = useState(true);

  // Data wiring unchanged — same endpoint, same rows, same order.
  useEffect(() => {
    const load = () => {
      fetchDailyPnLHistory({ days })
        .then((d) => {
          const rows: DailyPnlRecord[] = d.daily_pnl ?? [];
          // Endpoint returns oldest-first; keep that order for the chart
          setData(rows.slice(-days));
          setLoading(false);
        })
        .catch(() => setLoading(false));
    };
    load();
    const id = setInterval(load, 30_000);
    return () => clearInterval(id);
  }, [days]);

  const pnls = data.map((d) => d.realized_pnl);
  const totalPnl = pnls.reduce((a, b) => a + b, 0);
  const wins = pnls.filter((p) => p > 0).length;
  const losses = pnls.filter((p) => p < 0).length;

  // Same data, shaped for the TradingView renderer: one bar per trading day,
  // colored by sign. No values altered.
  const series: SeriesPoint[] = useMemo(
    () =>
      data.map((d) => ({
        time: d.date,
        value: d.realized_pnl,
        color: d.realized_pnl >= 0 ? "#22c55e" : "#ef4444",
      })),
    [data],
  );

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>Daily P&amp;L ({days}d)</CardTitle>
          <Badge variant={totalPnl >= 0 ? "bull" : "bear"}>
            {totalPnl >= 0 ? "+" : ""}${totalPnl.toFixed(0)}
          </Badge>
        </div>
        <p className="text-xs text-muted-foreground">
          {wins}W / {losses}L &mdash; {data.length} trading days
        </p>
      </CardHeader>
      <CardContent>
        {loading ? (
          <div className="h-[120px] rounded bg-muted animate-pulse" />
        ) : data.length === 0 ? (
          <div className="h-[120px] flex items-center justify-center text-xs text-muted-foreground">
            No daily P&amp;L data yet
          </div>
        ) : (
          <LightweightSeriesChart data={series} type="histogram" height={120} valueFormat="dollar" />
        )}
      </CardContent>
    </Card>
  );
}
