"use client";

import { POLL_INTERVAL } from "@/lib/polling-config";

import useSWR from "swr";
import { fetchEngine } from "@/lib/api";

interface PortfolioSummary {
  total_daily_pnl: number;
  daily_target: number;
  target_progress_pct: number;
  markets: Record<string, { daily_pnl: number; open_positions: number; status: string }>;
}

interface DailyTargetProgressWidgetProps {
  compact?: boolean;
}

function fetcher<T = unknown>(url: string): Promise<T> {
  return fetchEngine<T>(url);
}

const MARKET_COLORS: Record<string, string> = {
  futures: "#00ff88",
  options: "#00d4ff",
  crypto: "#ff9500",
  polymarket: "#ff6bff",
};
const MARKET_ORDER = ["futures", "options", "crypto", "polymarket"];

// SVG ring — radius 40, circumference ≈ 251.3
const R = 40;
const CIRC = 2 * Math.PI * R;

export function DailyTargetProgressWidget({ compact = false }: DailyTargetProgressWidgetProps) {
  const { data } = useSWR<PortfolioSummary>(
    "/portfolio/summary",
    fetcher,
    { refreshInterval: POLL_INTERVAL.FAST, shouldRetryOnError: false }
  );

  const target = data?.daily_target ?? 500;
  const total = data?.total_daily_pnl ?? 0;
  const pct = Math.min(1, Math.max(0, target > 0 ? total / target : 0));
  const isPositive = total >= 0;
  const ringColor = pct >= 1 ? "#00ff88" : pct >= 0.5 ? "#ffcc00" : isPositive ? "#00d4ff" : "#ff4444";
  const strokeDash = `${(pct * CIRC).toFixed(2)} ${CIRC.toFixed(2)}`;

  if (compact) {
    return (
      <div className="flex items-center gap-3">
        <div className="h-2 flex-1 rounded-full bg-muted overflow-hidden">
          <div
            className="h-full rounded-full transition-all duration-500"
            style={{ width: `${pct * 100}%`, backgroundColor: ringColor }}
          />
        </div>
        <span
          className="font-mono text-xs font-bold tabular-nums shrink-0"
          style={{ color: ringColor }}
        >
          ${total.toFixed(0)} / ${target.toFixed(0)}
        </span>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-border bg-card p-4 flex flex-col items-center gap-4">
      <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground self-start">
        Daily Target Progress
      </p>

      {/* Circular SVG progress ring */}
      <div className="relative flex items-center justify-center">
        <svg width="100" height="100" viewBox="0 0 100 100" style={{ transform: "rotate(-90deg)" }}>
          {/* Background ring */}
          <circle
            cx="50" cy="50" r={R}
            fill="none"
            stroke="hsl(var(--muted))"
            strokeWidth="8"
          />
          {/* Progress ring */}
          <circle
            cx="50" cy="50" r={R}
            fill="none"
            stroke={ringColor}
            strokeWidth="8"
            strokeLinecap="round"
            strokeDasharray={strokeDash}
            style={{ transition: "stroke-dasharray 0.5s ease" }}
          />
        </svg>
        {/* Center text */}
        <div className="absolute flex flex-col items-center">
          <span
            className="font-mono text-base font-bold tabular-nums leading-none"
            style={{ color: ringColor }}
          >
            {(pct * 100).toFixed(0)}%
          </span>
          <span className="font-mono text-[9px] text-muted-foreground mt-0.5">
            {isPositive ? "+" : ""}${total.toFixed(0)}
          </span>
        </div>
      </div>

      <p className="font-mono text-[10px] text-muted-foreground -mt-2">
        ${target.toFixed(0)} daily target
      </p>

      {/* Per-market contribution bars */}
      <div className="w-full space-y-1.5">
        {MARKET_ORDER.map((market) => {
          const m = data?.markets?.[market];
          if (!m) return null;
          const mPct = Math.min(1, target > 0 ? Math.abs(m.daily_pnl) / target : 0);
          const color = MARKET_COLORS[market] ?? "#888";
          return (
            <div key={market} className="flex items-center gap-2">
              <span className="font-mono text-[10px] text-muted-foreground uppercase w-20 shrink-0">
                {market}
              </span>
              <div className="flex-1 h-1.5 rounded-full bg-muted overflow-hidden">
                <div
                  className="h-full rounded-full transition-all duration-500"
                  style={{ width: `${mPct * 100}%`, backgroundColor: color }}
                />
              </div>
              <span
                className="font-mono text-[10px] tabular-nums w-16 text-right shrink-0"
                style={{ color: m.daily_pnl >= 0 ? color : "#ff4444" }}
              >
                {m.daily_pnl >= 0 ? "+" : ""}${m.daily_pnl.toFixed(0)}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
