"use client";

import { POLL_INTERVAL } from "@/lib/polling-config";

import useSWR from "swr";
import { fetchEngine } from "@/lib/api";

interface MarketPnL {
  daily_pnl: number;
  open_positions: number;
  status: string;
}

interface PortfolioSummary {
  total_daily_pnl: number;
  daily_target: number;
  target_progress_pct: number;
  markets: Record<string, MarketPnL>;
}

interface MultiMarketPnLWidgetProps {
  summary?: PortfolioSummary | null;
  isLoading?: boolean;
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

export function MultiMarketPnLWidget({ summary: summaryProp, isLoading }: MultiMarketPnLWidgetProps) {
  const { data: fetched } = useSWR<PortfolioSummary>(
    summaryProp !== undefined ? null : "/portfolio/summary",
    fetcher,
    { refreshInterval: POLL_INTERVAL.FAST, shouldRetryOnError: false }
  );

  const summary = summaryProp ?? fetched;
  const target = summary?.daily_target ?? 500;
  const total = summary?.total_daily_pnl ?? 0;
  const pct = Math.min(100, Math.max(0, target > 0 ? (total / target) * 100 : 0));
  const isPositive = total >= 0;

  return (
    <div className="rounded-xl border border-border bg-card p-4 space-y-3">
      <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
        Multi-Market P&L
      </p>

      {/* Total P&L vs target */}
      <div className="flex items-end justify-between">
        <div>
          <span
            className="font-mono text-2xl font-bold tabular-nums"
            style={{ color: isPositive ? "#00ff88" : "#ff4444" }}
          >
            {isPositive ? "+" : ""}${total.toFixed(2)}
          </span>
          <span className="font-mono text-[10px] text-muted-foreground ml-2">
            / ${target.toFixed(0)} target
          </span>
        </div>
        <span
          className="font-mono text-xs font-semibold tabular-nums"
          style={{ color: pct >= 100 ? "#00ff88" : pct >= 50 ? "#ffcc00" : "#ff4444" }}
        >
          {pct.toFixed(1)}%
        </span>
      </div>

      {/* Progress bar */}
      <div className="h-2 w-full rounded-full bg-muted overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{
            width: `${pct}%`,
            backgroundColor: pct >= 100 ? "#00ff88" : pct >= 50 ? "#ffcc00" : isPositive ? "#00d4ff" : "#ff4444",
          }}
        />
      </div>

      {/* Per-market breakdown */}
      {isLoading ? (
        <p className="font-mono text-[10px] text-muted-foreground/50 text-center">Loading…</p>
      ) : (
        <div className="space-y-2 pt-1">
          {MARKET_ORDER.map((market) => {
            const m = summary?.markets?.[market];
            if (!m) return null;
            const mPct = target > 0 ? Math.abs(m.daily_pnl) / target * 100 : 0;
            const color = MARKET_COLORS[market] ?? "#888";
            const mPositive = m.daily_pnl >= 0;
            return (
              <div key={market} className="space-y-0.5">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span
                      className="inline-block h-2 w-2 rounded-full shrink-0"
                      style={{ backgroundColor: color }}
                    />
                    <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                      {market}
                    </span>
                    <span className="font-mono text-[10px] text-muted-foreground/50">
                      {m.open_positions} pos
                    </span>
                  </div>
                  <span
                    className="font-mono text-[11px] font-semibold tabular-nums"
                    style={{ color: mPositive ? "#00ff88" : "#ff4444" }}
                  >
                    {mPositive ? "+" : ""}${m.daily_pnl.toFixed(2)}
                  </span>
                </div>
                <div className="h-1 w-full rounded-full bg-muted overflow-hidden">
                  <div
                    className="h-full rounded-full transition-all duration-500"
                    style={{ width: `${Math.min(100, mPct)}%`, backgroundColor: color }}
                  />
                </div>
              </div>
            );
          })}

          {!summary?.markets && (
            <p className="font-mono text-[10px] text-muted-foreground/40 text-center">—</p>
          )}
        </div>
      )}
    </div>
  );
}
