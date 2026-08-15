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

const BAR_COLORS = ["#00d4ff", "#00ff88", "#ffcc00", "#ff8800", "#ff4444"];

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
    <div className="rounded-xl p-4 flex flex-col gap-3"
      style={{ backgroundColor: "#09090b", border: "1px solid #27272a" }}>
      <span className="font-mono text-[10px] uppercase tracking-[0.15em]" style={{ color: "#52525b" }}>
        AVG HOLD TIME
      </span>

      <div className="flex items-end gap-2">
        <span className="font-mono text-3xl font-bold tabular-nums leading-none" style={{ color: "#e4e4e7" }}>
          {isLoading ? "--" : fmtMins(data?.overall_avg_minutes ?? 0)}
        </span>
        <span className="font-mono text-[10px] mb-1" style={{ color: "#52525b" }}>overall</span>
      </div>

      <div className="grid grid-cols-2 gap-2">
        {([{ label: "LONG", stats: long, color: "#00ff88" }, { label: "SHORT", stats: short, color: "#ff4444" }] as
          { label: string; stats: DirectionStats | undefined; color: string }[]).map(({ label, stats, color }) => (
          <div key={label} className="rounded-lg p-2.5" style={{ backgroundColor: "#111113", border: "1px solid #1c1c1e" }}>
            <span className="font-mono text-[9px] tracking-wider" style={{ color }}>{label}</span>
            <div className="font-mono text-base font-bold tabular-nums mt-0.5" style={{ color: "#e4e4e7" }}>
              {stats ? fmtMins(stats.avg_minutes) : "--"}
            </div>
            <div className="font-mono text-[9px] mt-0.5" style={{ color: "#52525b" }}>
              {stats ? `${stats.trade_count} trades` : "no data"}
            </div>
          </div>
        ))}
      </div>

      <div className="flex flex-col gap-1">
        {dist.map((b, i) => (
          <div key={b.bucket} className="flex items-center gap-2">
            <span className="font-mono text-[9px] w-11 text-right tabular-nums" style={{ color: "#52525b" }}>
              {b.bucket}
            </span>
            <div className="flex-1 h-2 rounded-full overflow-hidden" style={{ backgroundColor: "#1c1c1e" }}>
              <div className="h-full rounded-full transition-all duration-500" style={{
                width: `${(b.pct / maxPct) * 100}%`,
                backgroundColor: BAR_COLORS[i] ?? "#888",
                opacity: 0.8,
              }} />
            </div>
            <span className="font-mono text-[9px] w-8 tabular-nums" style={{ color: "#71717a" }}>{b.count}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
