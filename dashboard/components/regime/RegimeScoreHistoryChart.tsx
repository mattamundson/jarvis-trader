"use client";

import {
  Area,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { RegimeHistoryPoint } from "@/lib/regime";

const COLORS = {
  score: "#e2e8f0", // white-ish composite/price line
  shortEma: "#2dd4bf", // teal
  longEma: "#3b82f6", // blue
  extraEma: "#a855f7", // purple
  bullish: "#22c55e",
  neutral: "#f59e0b",
  bearish: "#ef4444",
};

interface TooltipPayloadItem {
  value: number;
  dataKey: string;
  color: string;
}

function ScoreTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: TooltipPayloadItem[];
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  const score = payload.find((p) => p.dataKey === "score");
  return (
    <div className="rounded-lg border border-border bg-card/95 px-3 py-2 font-mono text-[10px] shadow-lg backdrop-blur">
      <p className="font-bold text-foreground">{label}</p>
      {score && (
        <p style={{ color: score.value >= 0 ? COLORS.bullish : COLORS.bearish }}>
          Score: {score.value.toFixed(2)}
        </p>
      )}
    </div>
  );
}

interface RegimeScoreHistoryChartProps {
  data: RegimeHistoryPoint[];
  showEma: boolean;
  height?: number;
}

export function RegimeScoreHistoryChart({
  data,
  showEma,
  height = 300,
}: RegimeScoreHistoryChartProps) {
  if (data.length < 2) {
    return (
      <div
        className="flex items-center justify-center font-mono text-[11px] text-muted-foreground/50"
        style={{ height }}
      >
        No regime history
      </div>
    );
  }

  // Show ~13 evenly spaced time ticks across the session.
  const tickInterval = Math.max(1, Math.floor(data.length / 13));

  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id="regimeScoreFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={COLORS.bullish} stopOpacity={0.25} />
            <stop offset="45%" stopColor={COLORS.bullish} stopOpacity={0.04} />
            <stop offset="55%" stopColor={COLORS.bearish} stopOpacity={0.04} />
            <stop offset="100%" stopColor={COLORS.bearish} stopOpacity={0.28} />
          </linearGradient>
        </defs>

        <XAxis
          dataKey="time"
          interval={tickInterval}
          tick={{ fontSize: 9, fontFamily: "monospace", fill: "#64748b" }}
          axisLine={{ stroke: "rgba(148,163,184,0.15)" }}
          tickLine={false}
          minTickGap={8}
        />
        <YAxis
          domain={[-75, 55]}
          ticks={[-75, -60, -40, -20, 0, 20, 40, 55]}
          orientation="right"
          tick={{ fontSize: 9, fontFamily: "monospace", fill: "#64748b" }}
          axisLine={false}
          tickLine={false}
          width={36}
          tickFormatter={(v: number) => (v > 0 ? `+${v}` : `${v}`)}
        />
        <Tooltip content={<ScoreTooltip />} cursor={{ stroke: "rgba(148,163,184,0.3)" }} />

        <ReferenceLine y={0} stroke="rgba(148,163,184,0.35)" strokeDasharray="4 4" />

        <Area
          type="monotone"
          dataKey="score"
          stroke={COLORS.score}
          strokeWidth={1.5}
          fill="url(#regimeScoreFill)"
          dot={false}
          isAnimationActive={false}
        />

        {/* recharts v2 does not recurse into React Fragments when collecting
            chart series, so each Line must be a direct child of the chart.
            Wrapping these in a fragment silently drops them from the render. */}
        {showEma && (
          <Line
            type="monotone"
            dataKey="shortEma"
            stroke={COLORS.shortEma}
            strokeWidth={1.5}
            dot={false}
            isAnimationActive={false}
          />
        )}
        {showEma && (
          <Line
            type="monotone"
            dataKey="longEma"
            stroke={COLORS.longEma}
            strokeWidth={1.5}
            dot={false}
            isAnimationActive={false}
          />
        )}
        {showEma && (
          <Line
            type="monotone"
            dataKey="extraEma"
            stroke={COLORS.extraEma}
            strokeWidth={1.5}
            dot={false}
            isAnimationActive={false}
          />
        )}
      </ComposedChart>
    </ResponsiveContainer>
  );
}
