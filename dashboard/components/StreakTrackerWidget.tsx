"use client";

import { POLL_INTERVAL } from "@/lib/polling-config";

import useSWR from "swr";
import { fetchEngine } from "@/lib/api";
import type { StreaksResponse, StreakRecord } from "@/lib/api";

const fetcher = (path: string) => fetchEngine<StreaksResponse>(path);

function StreakBadge({ type, count }: { type: string; count: number }) {
  const isWin = type === "WIN";
  const isNone = type === "NONE" || count === 0;
  const color = isNone ? "#555" : isWin ? "#00ff88" : "#ff4444";
  const bg = isNone ? "#11111180" : isWin ? "#00ff8812" : "#ff444412";
  const border = isNone ? "#2a2a2a" : isWin ? "#00ff8830" : "#ff444430";
  const label = isNone ? "NO TRADES" : isWin ? `WIN STREAK: ${count}` : `LOSS STREAK: ${count}`;

  return (
    <div
      className="rounded-xl px-5 py-4 flex flex-col items-center justify-center gap-1"
      style={{ backgroundColor: bg, border: `1px solid ${border}` }}
    >
      <span className="font-mono text-[10px] uppercase tracking-widest" style={{ color: "#555" }}>
        Current Streak
      </span>
      <span className="font-mono text-2xl font-bold tracking-tight" style={{ color }}>
        {label}
      </span>
    </div>
  );
}

function StreakHistoryRow({ streak, index }: { streak: StreakRecord; index: number }) {
  const isWin = streak.type === "WIN";
  const color = isWin ? "#00ff88" : "#ff4444";
  const bg = isWin ? "#00ff8808" : "#ff444408";

  return (
    <div
      className="flex items-center justify-between px-3 py-1.5 rounded"
      style={{ backgroundColor: index % 2 === 0 ? bg : "transparent" }}
    >
      <div className="flex items-center gap-2">
        <span
          className="font-mono text-[10px] font-bold tracking-wider w-12 text-center rounded px-1"
          style={{ color, backgroundColor: `${color}18`, border: `1px solid ${color}30` }}
        >
          {streak.type}
        </span>
        <span className="font-mono text-xs font-bold tabular-nums" style={{ color }}>
          x{streak.count}
        </span>
      </div>
      <span className="font-mono text-[10px]" style={{ color: "#555" }}>
        {streak.start_date}
        {streak.start_date !== streak.end_date ? ` — ${streak.end_date}` : ""}
      </span>
    </div>
  );
}

export function StreakTrackerWidget() {
  const { data, error, isLoading } = useSWR(
    "/portfolio/paper/streaks",
    fetcher,
    { refreshInterval: POLL_INTERVAL.MINUTE }
  );

  return (
    <section
      className="rounded-xl p-5"
      style={{ backgroundColor: "#0a0a0a", border: "1px solid #1a1a2e" }}
    >
      <div className="mb-4">
        <h3
          className="font-mono text-sm font-bold tracking-[0.15em] uppercase"
          style={{ color: "#00ff88" }}
        >
          Consecutive Win / Loss Streaks
        </h3>
        <p className="font-mono text-[10px] mt-0.5" style={{ color: "#555" }}>
          Ordered by exit time — closed paper trades
        </p>
      </div>

      {isLoading && (
        <div className="font-mono text-[11px] text-center py-6" style={{ color: "#555" }}>
          Loading streak data...
        </div>
      )}

      {error && (
        <div className="font-mono text-[11px] text-center py-6" style={{ color: "#ff4444" }}>
          Engine offline — streak data unavailable
        </div>
      )}

      {!isLoading && !error && data != null && data.current_streak != null && (
        <div className="space-y-4">
          {/* Current streak + max stats */}
          <div className="grid grid-cols-3 gap-3">
            <div className="col-span-1">
              <StreakBadge
                type={data.current_streak.type}
                count={data.current_streak.count}
              />
            </div>
            <div
              className="rounded-xl px-4 py-4 flex flex-col items-center justify-center gap-1"
              style={{ backgroundColor: "#00ff8808", border: "1px solid #00ff8820" }}
            >
              <span className="font-mono text-[10px] uppercase tracking-widest" style={{ color: "#555" }}>
                Max Win Streak
              </span>
              <span className="font-mono text-2xl font-bold" style={{ color: "#00ff88" }}>
                {data.max_win_streak}
              </span>
            </div>
            <div
              className="rounded-xl px-4 py-4 flex flex-col items-center justify-center gap-1"
              style={{ backgroundColor: "#ff444408", border: "1px solid #ff444420" }}
            >
              <span className="font-mono text-[10px] uppercase tracking-widest" style={{ color: "#555" }}>
                Max Loss Streak
              </span>
              <span className="font-mono text-2xl font-bold" style={{ color: "#ff4444" }}>
                {data.max_loss_streak}
              </span>
            </div>
          </div>

          {/* Streak history */}
          {(data.streak_history ?? []).length > 0 && (
            <div>
              <span
                className="font-mono text-[9px] uppercase tracking-widest block mb-2"
                style={{ color: "#444" }}
              >
                Recent Streak History (last {(data.streak_history ?? []).length})
              </span>
              <div
                className="rounded-lg overflow-hidden"
                style={{ border: "1px solid #1a1a2e" }}
              >
                {[...(data.streak_history ?? [])].reverse().map((s, i) => (
                  <StreakHistoryRow key={i} streak={s} index={i} />
                ))}
              </div>
            </div>
          )}

          {(data.streak_history ?? []).length === 0 && (
            <div
              className="font-mono text-[11px] text-center py-4"
              style={{ color: "#555" }}
            >
              No streak history yet — close some trades first
            </div>
          )}
        </div>
      )}
    </section>
  );
}
