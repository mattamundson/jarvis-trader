"use client";
import { useEffect, useState } from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchDailyPnLHistory, type DailyPnlRecord } from "@/lib/api";

export function DailyPnLChart({ days = 30 }: { days?: number }) {
  const [data, setData] = useState<DailyPnlRecord[]>([]);
  const [loading, setLoading] = useState(true);

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

  // Chart dimensions
  const W = 400;
  const H = 120;
  const PAD = { top: 10, right: 10, bottom: 20, left: 50 };
  const innerW = W - PAD.left - PAD.right;
  const innerH = H - PAD.top - PAD.bottom;

  const pnls = data.map((d) => d.realized_pnl);
  const minVal = pnls.length ? Math.min(0, ...pnls) : -10;
  const maxVal = pnls.length ? Math.max(0, ...pnls) : 10;
  const range = maxVal - minVal || 1;

  const toX = (i: number) =>
    PAD.left + (i / Math.max(pnls.length - 1, 1)) * innerW;
  const toY = (v: number) => PAD.top + (1 - (v - minVal) / range) * innerH;
  const zeroY = toY(0);

  const polyPoints = pnls.map((v, i) => `${toX(i)},${toY(v)}`).join(" ");

  const areaPoints = pnls.length
    ? `${PAD.left},${zeroY} ` +
      pnls.map((v, i) => `${toX(i)},${toY(v)}`).join(" ") +
      ` ${toX(pnls.length - 1)},${zeroY}`
    : "";

  const totalPnl = pnls.reduce((a, b) => a + b, 0);
  const wins = pnls.filter((p) => p > 0).length;
  const losses = pnls.filter((p) => p < 0).length;

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
          <svg
            viewBox={`0 0 ${W} ${H}`}
            className="w-full h-[120px]"
            preserveAspectRatio="none"
          >
            {/* Zero line */}
            <line
              x1={PAD.left}
              y1={zeroY}
              x2={W - PAD.right}
              y2={zeroY}
              stroke="currentColor"
              strokeOpacity={0.15}
              strokeWidth={1}
            />
            {/* Area fill */}
            {areaPoints && (
              <polygon
                points={areaPoints}
                fill={totalPnl >= 0 ? "#22c55e" : "#ef4444"}
                fillOpacity={0.12}
              />
            )}
            {/* Line */}
            {pnls.length > 1 && (
              <polyline
                points={polyPoints}
                fill="none"
                stroke={totalPnl >= 0 ? "#22c55e" : "#ef4444"}
                strokeWidth={1.5}
                strokeLinejoin="round"
              />
            )}
            {/* Dots for each day */}
            {pnls.map((v, i) => (
              <circle
                key={i}
                cx={toX(i)}
                cy={toY(v)}
                r={2}
                fill={v >= 0 ? "#22c55e" : "#ef4444"}
              />
            ))}
            {/* Y-axis labels */}
            <text
              x={PAD.left - 4}
              y={PAD.top + 4}
              fontSize={8}
              textAnchor="end"
              fill="currentColor"
              fillOpacity={0.5}
            >
              +${Math.round(maxVal)}
            </text>
            <text
              x={PAD.left - 4}
              y={H - PAD.bottom}
              fontSize={8}
              textAnchor="end"
              fill="currentColor"
              fillOpacity={0.5}
            >
              ${Math.round(minVal)}
            </text>
          </svg>
        )}
      </CardContent>
    </Card>
  );
}
