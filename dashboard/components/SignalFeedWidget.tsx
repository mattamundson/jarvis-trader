"use client";

import type { JSX } from "react";
import { useState } from "react";
import useSWR from "swr";
import { fetchEngine } from "@/lib/api";

// ── Types ───────────────────────────────────────────────────────────────────

interface PipelineDecision {
  id: number;
  symbol: string;
  direction: "LONG" | "SHORT" | "HOLD";
  conviction: number;
  entry_price?: number;
  stop_price?: number;
  target_price?: number;
  risk_reward?: number;
  timestamp: string;
  regime?: string;
  // The trader's real "why" text (or pipeline summary fallback) — populated by
  // signal_scanner.py at write time; already present in /decisions/recent rows.
  reasoning?: string;
}

// Stage-by-stage drill-down shape from GET /decisions/{id}/detail
// (engine/routers/decisions_router.py:47-185). Only the reasoning-bearing
// fields this widget surfaces are typed here.
interface StageAnalyst {
  signal?: string | null;
  confidence?: number | null;
  summary?: string | null;
  regime?: string | null;
  trend?: string | null;
}

interface DecisionDetail {
  id: number;
  symbol: string;
  timestamp: string;
  action?: string | null;
  summary?: string | null;
  final_action?: string | null;
  // Present only on pre-migration-019 rows (no full_pipeline stored).
  reasoning?: string | null;
  note?: string | null;
  stage1_analysts?: Record<string, StageAnalyst>;
  stage2_debate?: {
    verdict?: string | null;
    debate_score?: number | null;
    summary?: string | null;
  };
  stage3_trader?: { action?: string | null; reasoning?: string | null };
  stage4_risk?: { approved?: boolean | null; reasoning?: string | null };
  stage5_fund?: { approved?: boolean | null; reasoning?: string | null } | null;
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

function convictionBar(score: number | null | undefined): JSX.Element {
  if (score == null) {
    return (
      <span className="font-mono text-[10px] text-zinc-500 min-w-[72px]">—</span>
    );
  }
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

// ── Stage-by-stage drill-down ─────────────────────────────────────────────────

function StageLine({ label, text }: { label: string; text?: string | null }) {
  if (!text || !text.trim()) return null;
  return (
    <div className="flex gap-2">
      <span className="font-mono text-[9px] uppercase tracking-wider text-zinc-600 shrink-0 w-14 pt-0.5">
        {label}
      </span>
      <span className="text-[11px] leading-relaxed text-zinc-300">{text}</span>
    </div>
  );
}

function DecisionDetailPanel({ id }: { id: number }) {
  const { data, error, isLoading } = useSWR<DecisionDetail>(
    `/decisions/${id}/detail`,
    (path: string) => fetchEngine<DecisionDetail>(path),
    { revalidateOnFocus: false, shouldRetryOnError: false }
  );

  if (isLoading) {
    return (
      <div className="px-4 py-3 bg-zinc-950/60 border-b border-zinc-800/60">
        <span className="font-mono text-[10px] text-zinc-500 tracking-wider animate-pulse">
          Loading breakdown&hellip;
        </span>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="px-4 py-3 bg-zinc-950/60 border-b border-zinc-800/60">
        <span className="font-mono text-[10px] text-red-400/70 tracking-wider">
          Breakdown unavailable
        </span>
      </div>
    );
  }

  // Pre-migration-019 rows have no stage data — surface the stored reasoning/note.
  const analysts = data.stage1_analysts
    ? Object.entries(data.stage1_analysts)
    : [];

  return (
    <div className="px-4 py-3 bg-zinc-950/60 border-b border-zinc-800/60 space-y-1.5">
      {analysts.map(([name, a]) => (
        <StageLine
          key={name}
          label={name.slice(0, 4)}
          text={a.summary ?? undefined}
        />
      ))}
      <StageLine label="Debate" text={data.stage2_debate?.summary} />
      <StageLine label="Trader" text={data.stage3_trader?.reasoning} />
      <StageLine label="Risk" text={data.stage4_risk?.reasoning} />
      <StageLine label="Fund" text={data.stage5_fund?.reasoning} />
      {analysts.length === 0 &&
        !data.stage3_trader?.reasoning &&
        !data.stage4_risk?.reasoning && (
          <StageLine
            label="Why"
            text={data.reasoning ?? data.summary ?? data.note}
          />
        )}
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

  const [expandedId, setExpandedId] = useState<number | null>(null);

  const isConnected = !error && !isLoading;
<<<<<<< HEAD
  const decisions = data?.slice(0, 10) ?? [];
=======
  const decisions = Array.isArray(data) ? data.slice(0, 10) : [];
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2

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
              /decisions/recent
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
            const isExpanded = expandedId === d.id;
            const why = d.reasoning?.trim();

            return (
              <div key={d.id}>
                <button
                  type="button"
                  onClick={() => setExpandedId(isExpanded ? null : d.id)}
                  className="w-full text-left px-3 py-2 hover:bg-zinc-800/30 transition-colors"
                  aria-expanded={isExpanded}
                >
                  <div className="grid grid-cols-[64px_56px_80px_80px_64px] gap-3 items-center">
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

                  {/* Plain-English "why" preview (from /decisions/recent reasoning) */}
                  {why && (
                    <p
                      className={`mt-1 text-[11px] leading-snug text-zinc-400 ${
                        isExpanded ? "" : "line-clamp-1"
                      }`}
                    >
                      {why}
                    </p>
                  )}
                </button>

                {/* Stage-by-stage drill-down (GET /decisions/{id}/detail) */}
                {isExpanded && <DecisionDetailPanel id={d.id} />}
              </div>
            );
          })}
      </div>

      {/* Footer */}
      <div className="px-3 py-1.5 border-t border-zinc-800/60 bg-zinc-900/60">
        <span className="font-mono text-[9px] text-zinc-700 tracking-wider">
          POLL 30s &middot; GET /decisions/recent
        </span>
      </div>
    </div>
  );
}
