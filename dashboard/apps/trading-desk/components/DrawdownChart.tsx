"use client";

import { useEffect, useMemo, useState } from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchDailyPnlHistoryNormalized, type DailyPnlRecord } from "@/lib/api";
import { LightweightSeriesChart, type SeriesPoint } from "@/components/charts/LightweightSeriesChart";

interface DrawdownPoint {
  date: string;
  drawdown: number;
}

function formatCurrency(value: number): string {
  const abs = Math.abs(value);
  const formatted = abs.toFixed(0);
  return value < 0 ? `-$${formatted}` : `$${formatted}`;
}

export function DrawdownChart() {
  const [records, setRecords] = useState<DailyPnlRecord[]>([]);
  const [loading, setLoading] = useState(true);

  // Data wiring unchanged — same normalized endpoint, same 90-day window.
  useEffect(() => {
    const load = () => {
      fetchDailyPnlHistoryNormalized({ days: 90 })
        .then((rows) => {
          setRecords(rows);
          setLoading(false);
        })
        .catch(() => setLoading(false));
    };
    load();
    const id = setInterval(load, 60_000);
    return () => clearInterval(id);
  }, []);

  const hasData = records.length > 0 && records.some((r) => r.num_trades > 0);

  // Drawdown derived from cumulative_pnl (unchanged math — running max underwater).
  const drawdownPoints: DrawdownPoint[] = useMemo(() => {
    const pts: DrawdownPoint[] = [];
    let runningMax = -Infinity;
    for (const rec of records) {
      runningMax = runningMax === -Infinity ? rec.cumulative_pnl : Math.max(runningMax, rec.cumulative_pnl);
      pts.push({ date: rec.date, drawdown: Math.min(0, rec.cumulative_pnl - runningMax) });
    }
    return pts;
  }, [records]);

  const maxDrawdown =
    drawdownPoints.length > 0 ? Math.min(...drawdownPoints.map((p) => p.drawdown)) : null;
  const maxDrawdownVariant =
    maxDrawdown != null && maxDrawdown < -10
      ? "bear"
      : maxDrawdown != null && maxDrawdown < 0
        ? "warn"
        : maxDrawdown === 0
          ? "bull"
          : "neutral";

  // Same drawdown values, handed to the TradingView renderer as an area series.
  const series: SeriesPoint[] = useMemo(
    () => drawdownPoints.map((p) => ({ time: p.date, value: p.drawdown })),
    [drawdownPoints],
  );

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle>Drawdown</CardTitle>
        {/*
          maxDrawdown is null (not 0) when there's no data yet -- either still
          loading or the endpoint returned no rows. Previously this defaulted
          to 0 and rendered "Max: $0" regardless of loading/empty state, which
          reads as "confirmed zero drawdown" when the real figure (e.g. the
          engine's own -$1,981.70 max_dd) is simply not loaded. "—" makes the
          absence of data visible instead of silently asserting a healthy
          number.
        */}
        <Badge variant={maxDrawdownVariant}>
          Max: {maxDrawdown != null ? formatCurrency(maxDrawdown) : "—"}
        </Badge>
      </CardHeader>
      <CardContent>
        {loading ? (
          <div className="h-[120px] rounded bg-muted animate-pulse" />
        ) : !hasData ? (
          <div className="h-[120px] flex items-center justify-center text-xs text-muted-foreground">
            No trade data available
          </div>
        ) : (
          <LightweightSeriesChart
            data={series}
            type="area"
            color="#ef4444"
            topColor="rgba(239,68,68,0.05)"
            bottomColor="rgba(239,68,68,0.30)"
            height={120}
            valueFormat="dollar"
          />
        )}
        <p className="text-xs text-muted-foreground mt-1">Last 90 days • Refreshes every 60s</p>
      </CardContent>
    </Card>
  );
}
