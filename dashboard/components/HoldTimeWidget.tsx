"use client";

import useSWR from "swr";
import { fetchEngine } from "@/lib/api";

interface DirectionStats { avg_minutes: number; trade_count: number; median_minutes: number; }
interface BucketStats { bucket: string; count: number; pct: number; }
interface HoldTimeData {
  overall_avg_minutes: number;
  by_direction: Record<string, DirectionStats>;
  by_symbol: Record<string, { avg_minutes: number; trade_count: number }>;
  hold_time_distribution: BucketStats[];
}

function fmtMins(m: number): string {
  if (m < 60) return `${Math.round(m)}m`;
  const h = Math.floor(m / 60), rem = Math.round(m % 60);
  return rem > 0 ? `${h}h ${rem}m` : `${h}h`;
}

const BAR_COLOR_CLASSES = ["bg-[#00d4ff]", "bg-[#00ff88]", "bg-[#ffcc00]", "bg-[#ff8800]", "bg-[#ff4444]"];

export default function HoldTimeWidget() {
  const { data, isLoading } = useSWR<HoldTimeData>(
    "/portfolio/paper/hold-time-stats",
    () => fetchEngine("/portfolio/paper/hold-time-stats"),
    { refreshInterval: 60_000, revalidateOnFocus: false }
  );

  const long = data?.by_direction?.["LONG"];
  const short = data?.by_direction?.["SHORT"];
  const dist = data?.hold_time_distribution ?? [];
  const maxPct = Math.max(...dist.map((b) => b.pct), 0.01);

  return (
    <div className="rounded-xl p-4 flex flex-col gap-3 bg-[#09090b] border border-[#27272a]">
      <span className="font-mono text-[10px] uppercase tracking-[0.15em] text-[#52525b]">
        AVG HOLD TIME
      </span>

      <div className="flex items-end gap-2">
        <span className="font-mono text-3xl font-bold tabular-nums leading-none text-[#e4e4e7]">
          {isLoading ? "--" : fmtMins(data?.overall_avg_minutes ?? 0)}
        </span>
        <span className="font-mono text-[10px] mb-1 text-[#52525b]">overall</span>
      </div>

      <div className="grid grid-cols-2 gap-2">
        {([{ label: "LONG", stats: long, colorClass: "text-[#00ff88]" }, { label: "SHORT", stats: short, colorClass: "text-[#ff4444]" }] as
          { label: string; stats: DirectionStats | undefined; colorClass: string }[]).map(({ label, stats, colorClass }) => (
          <div key={label} className="rounded-lg p-2.5 bg-[#111113] border border-[#1c1c1e]">
            <span className={`font-mono text-[9px] tracking-wider ${colorClass}`}>{label}</span>
            <div className="font-mono text-base font-bold tabular-nums mt-0.5 text-[#e4e4e7]">
              {stats ? fmtMins(stats.avg_minutes) : "--"}
            </div>
            <div className="font-mono text-[9px] mt-0.5 text-[#52525b]">
              {stats ? `${stats.trade_count} trades` : "no data"}
            </div>
          </div>
        ))}
      </div>

      <div className="flex flex-col gap-1">
        {dist.map((b, i) => (
          <div key={b.bucket} className="flex items-center gap-2">
            <span className="font-mono text-[9px] w-11 text-right tabular-nums text-[#52525b]">
              {b.bucket}
            </span>
            <div className="flex-1 h-2 rounded-full overflow-hidden bg-[#1c1c1e]">
              <div
                className={`h-full rounded-full transition-all duration-500 opacity-80 ${BAR_COLOR_CLASSES[i] ?? "bg-[#888]"}`}
                style={{ width: `${(b.pct / maxPct) * 100}%` }}
              />
            </div>
            <span className="font-mono text-[9px] w-8 tabular-nums text-[#71717a]">{b.count}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
