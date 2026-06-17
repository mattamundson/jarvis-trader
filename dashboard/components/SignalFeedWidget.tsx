"use client";
import { OfflineFallback } from "@/components/OfflineFallback";

import type { JSX } from "react";
import useSWR from "swr";
import { fetchEngine } from "@/lib/api";

// ── Types ───────────────────────────────────────────────────────────────────

interface PipelineDecision {
  id: string;
  symbol: string;
  direction: "LONG" | "SHORT" | "HOLD";
  conviction: number;
  entry_price?: number;
  stop_price?: number;
  target_price?: number;
  risk_reward?: number;
  timestamp: string;
  regime?: string;
}

// ── Helpers ─────────────────────────────────────────────────────────────────

function fetcher(path: string): Promise<PipelineDecision[]> {
  return fetchEngine<PipelineDecision[]>(path);
}

function relativeTime(isoString: string): string {
  const now = Date.now();
  const then = new Date(isoString).getTime();
  const diffSec = Math.floor((now - then) / 1000);

  if (diffSec < 60) return `${diffSec}s ago`;
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDay = Math.floor(diffHr / 24);
  return `${diffDay}d ago`;
}

function convictionBar(score: number): JSX.Element {
  const pct = Math.min(100, Math.max(0, (score / 10) * 100));
  const color =
    score >= 7
      ? "bg-green-500"
      : score >= 4
      ? "bg-yellow-500"
      : "bg-red-500";

  return (
    <div className="flex items-center gap-1.5 min-w-[72px]">
      <div className="flex-1 h-1 bg-zinc-800 rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full transition-all ${color}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="font-mono text-[10px] tabular-nums text-zinc-300 w-5 text-right">
        {score.toFixed(1)}
      </span>
    </div>
  );
}

function DirectionBadge({ direction }: { direction: "LONG" | "SHORT" | "HOLD" }) {
  const styles: Record<string, string> = {
    LONG: "text-green-400 border-green-500/30 bg-green-950/20",
    SHORT: "text-red-400 border-red-500/30 bg-red-950/20",
    HOLD: "text-zinc-400 border-zinc-700 bg-zinc-900/20",
  };

  return (
    <span
      className={`inline-flex items-center justify-center font-mono text-[10px] font-bold tracking-wider px-2 py-0.5 rounded border ${styles[direction] ?? styles.HOLD}`}
    >
      {direction}
    </span>
  );
}

// ── Skeleton row ─────────────────────────────────────────────────────────────

function SkeletonRow() {
  return (
    <div className="grid grid-cols-[64px_56px_80px_80px_64px] gap-3 items-center px-3 py-2 border-b border-zinc-800/60 animate-pulse">
      <div className="h-3 bg-zinc-800 rounded w-10" />
      <div className="h-5 bg-zinc-800 rounded w-12" />
      <div className="h-3 bg-zinc-800 rounded w-16" />
      <div className="h-3 bg-zinc-800 rounded w-14" />
      <div className="h-3 bg-zinc-800 rounded w-10" />
    </div>
  );
}

// ── Main Component ────────────────────────────────────────────────────────────

export function SignalFeedWidget() {
  const { data, error, isLoading } = useSWR<PipelineDecision[]>(
    "/decisions/recent",
    fetcher,
    {
      refreshInterval: 30_000,
      shouldRetryOnError: false,
      revalidateOnFocus: false,
    }
  );

  const isConnected = !error && !isLoading;
  const decisions = data?.slice(0, 10) ?? [];

  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-zinc-800 bg-zinc-900/80">
        <div className="flex items-center gap-2">
          {/* Pulsing dot — green when connected, zinc when loading/error */}
          <span className="relative flex h-2 w-2">
            {isConnected ? (
              <>
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75" />
                <span className="relative inline-flex rounded-full h-2 w-2 bg-green-500" />
              </>
            ) : (
              <span className="relative inline-flex rounded-full h-2 w-2 bg-zinc-600" />
            )}
          </span>
          <span className="font-mono text-[11px] font-bold tracking-[0.18em] uppercase text-zinc-100">
            SIGNAL FEED
          </span>
        </div>
        <span className="font-mono text-[9px] text-zinc-600 tracking-wider uppercase">
          last 10 decisions
        </span>
      </div>

      {/* Column headers */}
      <div className="grid grid-cols-[64px_56px_80px_80px_64px] gap-3 items-center px-3 py-1.5 border-b border-zinc-800/60">
        <span className="font-mono text-[9px] uppercase tracking-wider text-zinc-600">Symbol</span>
        <span className="font-mono text-[9px] uppercase tracking-wider text-zinc-600">Dir</span>
        <span className="font-mono text-[9px] uppercase tracking-wider text-zinc-600">Conviction</span>
        <span className="font-mono text-[9px] uppercase tracking-wider text-zinc-600">R:R</span>
        <span className="font-mono text-[9px] uppercase tracking-wider text-zinc-600 text-right">Time</span>
      </div>

      {/* Content */}
      <div className="divide-y divide-zinc-800/40 min-h-[200px]">
        {/* Loading state */}
        {isLoading && (
          <>
            {Array.from({ length: 5 }).map((_, i) => (
              <SkeletonRow key={i} />
            ))}
          </>
        )}

        {/* Error state */}
        {!isLoading && error && (
          <div className="flex flex-col items-center justify-center py-10 gap-2">
            <span className="font-mono text-[10px] text-red-400/70 tracking-wider">
              ENGINE UNREACHABLE
            </span>
            <span className="font-mono text-[9px] text-zinc-700">
              engine offline
            </span>
          </div>
        )}

        {/* Empty state */}
        {!isLoading && !error && decisions.length === 0 && (
          <div className="flex items-center justify-center py-10">
            <span className="font-mono text-[10px] text-zinc-600 tracking-wider uppercase">
              No signals yet
            </span>
          </div>
        )}

        {/* Data rows */}
        {!isLoading &&
          !error &&
          decisions.map((d) => {
            const rrDisplay =
              d.risk_reward != null
                ? `${d.risk_reward.toFixed(1)}:1`
                : "\u2014";

            return (
              <div
                key={d.id}
                className="grid grid-cols-[64px_56px_80px_80px_64px] gap-3 items-center px-3 py-2 hover:bg-zinc-800/30 transition-colors"
              >
                {/* Symbol */}
                <span className="font-mono text-xs font-semibold text-zinc-100 truncate">
                  {d.symbol}
                </span>

                {/* Direction */}
                <DirectionBadge direction={d.direction} />

                {/* Conviction bar + score */}
                {convictionBar(d.conviction)}

                {/* R:R */}
                <span
                  className={`font-mono text-[11px] tabular-nums ${
                    d.risk_reward != null && d.risk_reward >= 2
                      ? "text-green-400"
                      : d.risk_reward != null && d.risk_reward >= 1
                      ? "text-yellow-400"
                      : "text-zinc-500"
                  }`}
                >
                  {rrDisplay}
                </span>

                {/* Timestamp */}
                <span className="font-mono text-[10px] text-zinc-500 text-right tabular-nums">
                  {relativeTime(d.timestamp)}
                </span>
              </div>
            );
          })}
      </div>

      {/* Footer */}
      <div className="px-3 py-1.5 border-t border-zinc-800/60 bg-zinc-900/60">
        <span className="font-mono text-[9px] text-zinc-700 tracking-wider">
          POLL 30s
        </span>
      </div>
    </div>
  );
}
