"use client";

import useSWR from "swr";
import { fetchEngine } from "@/lib/api";
import type { HourlyStatsResponse, HourlyStatItem } from "@/lib/api";

const fetcher = (path: string) => fetchEngine<HourlyStatsResponse>(path);

function barBgClass(winRate: number): string {
  if (winRate >= 0.55) return "bg-[#00ff88]";
  if (winRate >= 0.40) return "bg-[#ffcc00]";
  return "bg-[#ff4444]";
}

function barTextClass(winRate: number): string {
  if (winRate >= 0.55) return "text-[#00ff88]";
  if (winRate >= 0.40) return "text-[#ffcc00]";
  return "text-[#ff4444]";
}

function HourBar({ stat }: { stat: HourlyStatItem }) {
  const pct = Math.round(stat.win_rate * 100);
  return (
    <div className="flex flex-col gap-1">
      <div className="relative h-5 rounded font-mono text-[9px] font-bold flex items-center bg-[#0f0f0f] border border-panel-border">
        <div
          className={`absolute left-0 top-0 h-full rounded opacity-25 transition-all duration-500 ${barBgClass(stat.win_rate)}`}
          style={{ width: `${pct}%` }}
        />
        <span
          className={`absolute left-0 right-0 text-center font-mono text-[9px] font-bold ${barTextClass(stat.win_rate)}`}
        >
          {pct}%
        </span>
      </div>
      <div className="text-center">
        <span className="font-mono text-[8px] text-[#555]">
          {stat.label}
        </span>
      </div>
      <div className="text-center">
        <span className="font-mono text-[8px] text-[#444]">
          {stat.trades}t
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
    <section className="rounded-xl p-5 bg-panel border border-panel-border">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="font-mono text-sm font-bold tracking-[0.15em] uppercase text-[#00ff88]">
            Win Rate by Hour of Day
          </h3>
          <p className="font-mono text-[10px] mt-0.5 text-[#555]">
            Central Time (CT) — closed paper trades only
          </p>
        </div>
        {data?.best_hour && (
          <div className="flex gap-3">
            <div className="rounded px-2 py-1 font-mono text-[10px] bg-[#00ff8812] border border-[#00ff8830] text-[#00ff88]">
              BEST {data.best_hour.label} — {Math.round(data.best_hour.win_rate * 100)}%
            </div>
            {data.worst_hour && (
              <div className="rounded px-2 py-1 font-mono text-[10px] bg-[#ff444412] border border-[#ff444430] text-[#ff4444]">
                WORST {data.worst_hour.label} — {Math.round(data.worst_hour.win_rate * 100)}%
              </div>
            )}
          </div>
        )}
      </div>

      {isLoading && (
        <div className="font-mono text-[11px] text-center py-6 text-[#555]">
          Loading hourly stats...
        </div>
      )}

      {error && (
        <div className="font-mono text-[11px] text-center py-6 text-[#ff4444]">
          Engine offline — no hourly data
        </div>
      )}

      {!isLoading && !error && (!data?.hourly_stats || data.hourly_stats.length === 0) && (
        <div className="font-mono text-[11px] text-center py-6 text-[#555]">
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
          <div className="flex items-center gap-4 mt-4 pt-3 border-t border-panel-border">
            <span className="font-mono text-[9px] text-[#555]">WIN RATE THRESHOLDS:</span>
            <span className="font-mono text-[9px] text-[#00ff88]">&ge;55% STRONG</span>
            <span className="font-mono text-[9px] text-[#ffcc00]">40-55% ACCEPTABLE</span>
            <span className="font-mono text-[9px] text-[#ff4444]">&lt;40% WEAK</span>
          </div>
        </div>
      )}
    </section>
  );
}
