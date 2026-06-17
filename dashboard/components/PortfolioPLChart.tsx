"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchDailyPnLHistory, type DailyPnlRecord } from "@/lib/api";
import { LightweightSeriesChart, type SeriesPoint } from "@/components/charts/LightweightSeriesChart";

const REFRESH_MS = 60_000;
const LOOKBACK_DAYS = 45;

export function PortfolioPLChart() {
  const [rows, setRows] = useState<DailyPnlRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Data wiring unchanged — same endpoint, same 45-day lookback.
  const load = useCallback(async () => {
    try {
      const res = await fetchDailyPnLHistory({ days: LOOKBACK_DAYS });
      const list = res.daily_pnl ?? [];
      setRows(list);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load P&L");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => clearInterval(id);
  }, [load]);

  const totalPnl = rows.reduce((a, d) => a + (Number(d.realized_pnl) || 0), 0);
  const positive = totalPnl >= 0;

  // Same realized_pnl values, handed to the TradingView renderer as an area series.
  const series: SeriesPoint[] = useMemo(
    () => rows.map((d) => ({ time: d.date, value: Number(d.realized_pnl) || 0 })),
    [rows],
  );

  return (
    <Card className="border-zinc-800 bg-zinc-950/60">
      <CardHeader className="flex flex-row items-center justify-between space-y-0 py-3">
        <CardTitle className="text-sm font-medium text-zinc-300">Paper daily P&amp;L</CardTitle>
        {!loading && rows.length > 0 && (
          <Badge variant={positive ? "bull" : "bear"} className="font-mono text-[10px]">
            {positive ? "+" : ""}
            {totalPnl.toFixed(0)}
          </Badge>
        )}
      </CardHeader>
      <CardContent className="pb-3">
        {loading ? (
          <div className="h-[120px] animate-pulse rounded bg-zinc-800/80" />
        ) : error ? (
          <p className="text-xs text-red-400/90">{error}</p>
        ) : rows.length === 0 ? (
          <div className="flex h-[120px] items-center justify-center text-xs text-zinc-600">
            No daily P&amp;L rows yet
          </div>
        ) : (
          <LightweightSeriesChart
            data={series}
            type="area"
            color={positive ? "#22c55e" : "#ef4444"}
            height={120}
            valueFormat="dollar"
          />
        )}
        {!loading && rows.length > 0 && (
          <p className="mt-1 text-[10px] text-zinc-600">{rows.length} days in window</p>
        )}
      </CardContent>
    </Card>
  );
}
