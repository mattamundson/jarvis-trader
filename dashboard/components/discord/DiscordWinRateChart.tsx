"use client";

import useSWR from "swr";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";
import { fetchEngine } from "@/lib/api";

const REFRESH_MS = 30_000;

function fetcher<T = unknown>(url: string): Promise<T> {
  return fetchEngine<T>(url);
}

interface SignalBySymbol {
  symbol: string;
  cnt: number;
  longs: number;
  shorts: number;
  avg_win_rate: number | null;
}

interface DiscordStatsResponse {
  signals_by_symbol: SignalBySymbol[];
}

const FOCUS_SYMBOLS = ["NQ", "ES", "GC", "YM", "RTY", "CL"];

function barColor(rate: number): string {
  if (rate >= 60) return "#00ff88";
  if (rate >= 40) return "#ffcc00";
  return "#ff4444";
}

interface TooltipPayload {
  value: number;
  payload: { symbol: string; cnt: number };
}

function CustomTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: TooltipPayload[];
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  const item = payload[0];
  return (
    <div className="rounded-lg border border-border bg-card px-3 py-2 font-mono text-xs shadow-lg">
      <p className="font-bold" style={{ color: "#00d4ff" }}>
        {label}
      </p>
      <p className="text-foreground">
        Win Rate:{" "}
        <span style={{ color: barColor(item.value) }}>
          {item.value.toFixed(1)}%
        </span>
      </p>
      <p className="text-muted-foreground">
        {item.payload.cnt.toLocaleString()} signals
      </p>
    </div>
  );
}

export function DiscordWinRateChart() {
  const { data, isLoading, error } = useSWR<DiscordStatsResponse>(
    "/discord/stats",
    fetcher,
    { refreshInterval: REFRESH_MS }
  );

  const rawSymbols = data?.signals_by_symbol ?? [];

  // Backend avg_win_rate is expected as a 0-1 fraction, but has been observed
  // returning out-of-range values (e.g. yielding >8000% after *100) for some
  // symbols. Clamp defensively so a bad upstream value can never blow out the
  // chart's 0-100 axis regardless of root cause on the backend.
  const toPct = (rate: number | null | undefined): number =>
    Math.max(0, Math.min(100, rate != null ? rate * 100 : 0));

  // Filter to focus symbols + convert win_rate to percent
  const chartData = FOCUS_SYMBOLS.map((sym) => {
    const found = rawSymbols.find((s) => s.symbol === sym);
    return {
      symbol: sym,
      win_rate_pct: toPct(found?.avg_win_rate),
      cnt: found?.cnt ?? 0,
    };
  }).filter((d) => d.cnt > 0);

  // Fallback: show all symbols if none of the focus symbols match
  const displayData =
    chartData.length > 0
      ? chartData
      : rawSymbols.slice(0, 8).map((s) => ({
          symbol: s.symbol,
          win_rate_pct: toPct(s.avg_win_rate),
          cnt: s.cnt,
        }));

  return (
    <div className="rounded-xl border border-border bg-card p-4 space-y-3">
      <div className="flex items-center justify-between">
        <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
          Win Rate by Symbol
        </p>
        <span className="font-mono text-[10px] text-muted-foreground">
          {isLoading ? "Loading…" : `${rawSymbols.length} symbols`}
        </span>
      </div>

      {error ? (
        <div className="h-40 flex items-center justify-center font-mono text-[11px] text-red-400/70 italic">
          Failed to load — engine may be offline
        </div>
      ) : isLoading ? (
        <div className="h-40 flex items-center justify-center">
          <span className="font-mono text-[11px] text-muted-foreground/50 animate-pulse">
            Loading chart…
          </span>
        </div>
      ) : displayData.length === 0 ? (
        <div className="h-40 flex items-center justify-center font-mono text-[11px] text-muted-foreground/50 italic">
          No symbol data available
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={180}>
          <BarChart
            data={displayData}
            layout="vertical"
            margin={{ top: 0, right: 48, left: 8, bottom: 0 }}
          >
            <XAxis
              type="number"
              domain={[0, 100]}
              tick={{ fontSize: 10, fontFamily: "monospace", fill: "#475569" }}
              tickFormatter={(v) => `${v}%`}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              type="category"
              dataKey="symbol"
              tick={{ fontSize: 11, fontFamily: "monospace", fill: "#94a3b8" }}
              axisLine={false}
              tickLine={false}
              width={32}
            />
            <Tooltip
              content={<CustomTooltip />}
              cursor={{ fill: "rgba(0,212,255,0.06)" }}
            />
            <Bar dataKey="win_rate_pct" radius={[0, 4, 4, 0]} maxBarSize={20}>
              {displayData.map((entry) => (
                <Cell
                  key={entry.symbol}
                  fill={barColor(entry.win_rate_pct)}
                  fillOpacity={0.85}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      )}

      {/* Legend */}
      <div className="flex items-center gap-4 font-mono text-[10px] text-muted-foreground">
        <span className="flex items-center gap-1">
          <span className="inline-block w-2 h-2 rounded-sm" style={{ backgroundColor: "#00ff88" }} />
          ≥60% strong
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block w-2 h-2 rounded-sm" style={{ backgroundColor: "#ffcc00" }} />
          40–60% neutral
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block w-2 h-2 rounded-sm" style={{ backgroundColor: "#ff4444" }} />
          &lt;40% weak
        </span>
      </div>
    </div>
  );
}
