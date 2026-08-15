"use client";

import useSWR from "swr";
import { fetchEngine } from "@/lib/api";
import type { HourlyStatsResponse, HourlyStatItem } from "@/lib/api";

const fetcher = (path: string) => fetchEngine<HourlyStatsResponse>(path);

function barColor(winRate: number): string {
  if (winRate >= 0.55) return "#00ff88";
  if (winRate >= 0.40) return "#ffcc00";
  return "#ff4444";
}

function HourBar({ stat }: { stat: HourlyStatItem }) {
  const pct = Math.round(stat.win_rate * 100);
  const color = barColor(stat.win_rate);
  return (
    <div className="flex flex-col gap-1">
      <div
        className="relative rounded font-mono text-[9px] font-bold flex items-center"
        style={{ height: "20px", backgroundColor: "#0f0f0f", border: "1px solid #1a1a2e" }}
      >
        <div
          className="absolute left-0 top-0 h-full rounded"
          style={{
            width: `${pct}%`,
            backgroundColor: color,
            opacity: 0.25,
            transition: "width 0.4s ease",
          }}
        />
        <span
          className="absolute left-0 right-0 text-center font-mono text-[9px] font-bold"
          style={{ color }}
        >
          {pct}%
        </span>
      </div>
      <div className="text-center">
        <span className="font-mono text-[8px]" style={{ color: "#555" }}>
          {stat.hour_label}
        </span>
      </div>
      <div className="text-center">
        <span className="font-mono text-[8px]" style={{ color: "#444" }}>
          {stat.trade_count}t
        </span>
      </div>
    </div>
  );
}

export function WinRateByHourWidget() {
  const { data, error, isLoading } = useSWR(
    "/portfolio/paper/hourly-stats",
    fetcher,
    { refreshInterval: 60000 }
  );

  return (
    <section
      className="rounded-xl p-5"
      style={{ backgroundColor: "#0a0a0a", border: "1px solid #1a1a2e" }}
    >
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3
            className="font-mono text-sm font-bold tracking-[0.15em] uppercase"
            style={{ color: "#00ff88" }}
          >
            Win Rate by Hour of Day
          </h3>
          <p className="font-mono text-[10px] mt-0.5" style={{ color: "#555" }}>
            Central Time (CT) — closed paper trades only
          </p>
        </div>
        {data?.best_hour && (
          <div className="flex gap-3">
            <div
              className="rounded px-2 py-1 font-mono text-[10px]"
              style={{ backgroundColor: "#00ff8812", border: "1px solid #00ff8830", color: "#00ff88" }}
            >
              BEST {data.best_hour.hour_label} — {Math.round(data.best_hour.win_rate * 100)}%
            </div>
            {data.worst_hour && (
              <div
                className="rounded px-2 py-1 font-mono text-[10px]"
                style={{ backgroundColor: "#ff444412", border: "1px solid #ff444430", color: "#ff4444" }}
              >
                WORST {data.worst_hour.hour_label} — {Math.round(data.worst_hour.win_rate * 100)}%
              </div>
            )}
          </div>
        )}
      </div>

      {isLoading && (
        <div className="font-mono text-[11px] text-center py-6" style={{ color: "#555" }}>
          Loading hourly stats...
        </div>
      )}

      {error && (
        <div className="font-mono text-[11px] text-center py-6" style={{ color: "#ff4444" }}>
          Engine offline — no hourly data
        </div>
      )}

      {!isLoading && !error && (!data?.hourly_stats || data.hourly_stats.length === 0) && (
        <div className="font-mono text-[11px] text-center py-6" style={{ color: "#555" }}>
          No closed trades yet — hourly breakdown will appear here
        </div>
      )}

      {!isLoading && !error && data?.hourly_stats && data.hourly_stats.length > 0 && (
        <div className="overflow-x-auto">
          <div
            className="grid gap-2"
            style={{
              gridTemplateColumns: `repeat(${data.hourly_stats.length}, minmax(44px, 1fr))`,
              minWidth: `${data.hourly_stats.length * 52}px`,
            }}
          >
            {data.hourly_stats.map((stat: HourlyStatItem) => (
              <HourBar key={stat.hour} stat={stat} />
            ))}
          </div>
          <div className="flex items-center gap-4 mt-4 pt-3" style={{ borderTop: "1px solid #1a1a2e" }}>
            <span className="font-mono text-[9px]" style={{ color: "#555" }}>WIN RATE THRESHOLDS:</span>
            <span className="font-mono text-[9px]" style={{ color: "#00ff88" }}>&ge;55% STRONG</span>
            <span className="font-mono text-[9px]" style={{ color: "#ffcc00" }}>40-55% ACCEPTABLE</span>
            <span className="font-mono text-[9px]" style={{ color: "#ff4444" }}>&lt;40% WEAK</span>
          </div>
        </div>
      )}
    </section>
  );
}
