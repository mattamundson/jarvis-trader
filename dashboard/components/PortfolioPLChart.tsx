"use client";

import { useCallback, useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchDailyPnLHistory, type DailyPnlRecord } from "@/lib/api";

const REFRESH_MS = 60_000;
const LOOKBACK_DAYS = 45;

export function PortfolioPLChart() {
  const [rows, setRows] = useState<DailyPnlRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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

  const W = 400;
  const H = 120;
  const PAD = { top: 10, right: 10, bottom: 20, left: 44 };
  const innerW = W - PAD.left - PAD.right;
  const innerH = H - PAD.top - PAD.bottom;

  const pnls = rows.map((d) => Number(d.realized_pnl) || 0);
  const minVal = pnls.length ? Math.min(0, ...pnls) : -10;
  const maxVal = pnls.length ? Math.max(0, ...pnls) : 10;
  const range = maxVal - minVal || 1;
  const toX = (i: number) => PAD.left + (i / Math.max(pnls.length - 1, 1)) * innerW;
  const toY = (v: number) => PAD.top + (1 - (v - minVal) / range) * innerH;
  const zeroY = toY(0);
  const totalPnl = pnls.reduce((a, b) => a + b, 0);
  const polyPoints = pnls.map((v, i) => `${toX(i)},${toY(v)}`).join(" ");
  const areaPoints = pnls.length
    ? `${PAD.left},${zeroY} ${pnls.map((v, i) => `${toX(i)},${toY(v)}`).join(" ")} ${toX(pnls.length - 1)},${zeroY}`
    : "";

  return (
    <Card className="border-zinc-800 bg-zinc-950/60">
      <CardHeader className="flex flex-row items-center justify-between space-y-0 py-3">
        <CardTitle className="text-sm font-medium text-zinc-300">Paper daily P&amp;L</CardTitle>
        {!loading && rows.length > 0 && (
          <Badge variant={totalPnl >= 0 ? "bull" : "bear"} className="font-mono text-[10px]">
            {totalPnl >= 0 ? "+" : ""}
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
          <svg viewBox={`0 0 ${W} ${H}`} className="h-[120px] w-full" preserveAspectRatio="none">
            <line
              x1={PAD.left}
              y1={zeroY}
              x2={W - PAD.right}
              y2={zeroY}
              stroke="currentColor"
              strokeOpacity={0.12}
              strokeWidth={1}
            />
            {areaPoints && (
              <polygon
                points={areaPoints}
                fill={totalPnl >= 0 ? "#22c55e" : "#ef4444"}
                fillOpacity={0.12}
              />
            )}
            {pnls.length > 1 && (
              <polyline
                fill="none"
                points={polyPoints}
                stroke={totalPnl >= 0 ? "#4ade80" : "#f87171"}
                strokeWidth={1.5}
              />
            )}
          </svg>
        )}
        {!loading && rows.length > 0 && (
          <p className="mt-1 text-[10px] text-zinc-600">{rows.length} days in window</p>
        )}
      </CardContent>
    </Card>
  );
}
