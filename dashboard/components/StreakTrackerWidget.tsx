"use client";

import useSWR from "swr";
import { fetchEngine } from "@/lib/api";
import type { StreaksResponse, StreakRecord } from "@/lib/api";

const fetcher = (path: string) => fetchEngine<StreaksResponse>(path);

function StreakBadge({ type, count }: { type: string; count: number }) {
  const isWin = type === "WIN";
  const isNone = type === "NONE" || count === 0;
  const colorClass = isNone ? "text-[#555]" : isWin ? "text-[#00ff88]" : "text-[#ff4444]";
  const panelClass = isNone
    ? "bg-[#11111180] border-[#2a2a2a]"
    : isWin
      ? "bg-[#00ff8812] border-[#00ff8830]"
      : "bg-[#ff444412] border-[#ff444430]";
  const label = isNone ? "NO TRADES" : isWin ? `WIN STREAK: ${count}` : `LOSS STREAK: ${count}`;

  return (
    <div
      className={`rounded-xl px-5 py-4 flex flex-col items-center justify-center gap-1 border ${panelClass}`}
    >
      <span className="font-mono text-[10px] uppercase tracking-widest text-[#555]">
        Current Streak
      </span>
      <span className={`font-mono text-2xl font-bold tracking-tight ${colorClass}`}>
        {label}
      </span>
    </div>
  );
}

function STREAK_ROW_CLASSES(color: "#00ff88" | "#ff4444") {
  return color === "#00ff88"
    ? { text: "text-[#00ff88]", chip: "text-[#00ff88] bg-[#00ff8818] border-[#00ff8830]", tint: "bg-[#00ff8808]" }
    : { text: "text-[#ff4444]", chip: "text-[#ff4444] bg-[#ff444418] border-[#ff444430]", tint: "bg-[#ff444408]" };
}

function StreakHistoryRow({ streak, index }: { streak: StreakRecord; index: number }) {
  const isWin = streak.type === "WIN";
  const c = STREAK_ROW_CLASSES(isWin ? "#00ff88" : "#ff4444");

  return (
    <div
      className={`flex items-center justify-between px-3 py-1.5 rounded ${index % 2 === 0 ? c.tint : "bg-transparent"}`}
    >
      <div className="flex items-center gap-2">
        <span
          className={`font-mono text-[10px] font-bold tracking-wider w-12 text-center rounded px-1 border ${c.chip}`}
        >
          {streak.type}
        </span>
        <span className={`font-mono text-xs font-bold tabular-nums ${c.text}`}>
          x{streak.count}
        </span>
      </div>
      <span className="font-mono text-[10px] text-[#555]">
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
    { refreshInterval: 60000 }
  );

  return (
    <section className="rounded-xl p-5 bg-panel border border-panel-border">
      <div className="mb-4">
        <h3 className="font-mono text-sm font-bold tracking-[0.15em] uppercase text-[#00ff88]">
          Consecutive Win / Loss Streaks
        </h3>
        <p className="font-mono text-[10px] mt-0.5 text-[#555]">
          Ordered by exit time — closed paper trades
        </p>
      </div>

      {isLoading && (
        <div className="font-mono text-[11px] text-center py-6 text-[#555]">
          Loading streak data...
        </div>
      )}

      {error && (
        <div className="font-mono text-[11px] text-center py-6 text-[#ff4444]">
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
            <div className="rounded-xl px-4 py-4 flex flex-col items-center justify-center gap-1 bg-[#00ff8808] border border-[#00ff8820]">
              <span className="font-mono text-[10px] uppercase tracking-widest text-[#555]">
                Max Win Streak
              </span>
              <span className="font-mono text-2xl font-bold text-[#00ff88]">
                {data.max_win_streak}
              </span>
            </div>
            <div className="rounded-xl px-4 py-4 flex flex-col items-center justify-center gap-1 bg-[#ff444408] border border-[#ff444420]">
              <span className="font-mono text-[10px] uppercase tracking-widest text-[#555]">
                Max Loss Streak
              </span>
              <span className="font-mono text-2xl font-bold text-[#ff4444]">
                {data.max_loss_streak}
              </span>
            </div>
          </div>

          {/* Streak history */}
          {(data.streak_history ?? []).length > 0 && (
            <div>
              <span className="font-mono text-[9px] uppercase tracking-widest block mb-2 text-[#444]">
                Recent Streak History (last {(data.streak_history ?? []).length})
              </span>
              <div className="rounded-lg overflow-hidden border border-panel-border">
                {[...(data.streak_history ?? [])].reverse().map((s, i) => (
                  <StreakHistoryRow key={i} streak={s} index={i} />
                ))}
              </div>
            </div>
          )}

          {(data.streak_history ?? []).length === 0 && (
            <div className="font-mono text-[11px] text-center py-4 text-[#555]">
              No streak history yet — close some trades first
            </div>
          )}
        </div>
      )}
    </section>
  );
}
