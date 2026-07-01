"use client";

import useSWR from "swr";
import { fetchDurability, type DurabilityResponse } from "@/lib/api";

function fmtDuration(ms: number): string {
  if (ms < 60_000) return `${Math.round(ms / 1000)}s`;
  if (ms < 3_600_000) return `${(ms / 60_000).toFixed(1)}m`;
  if (ms < 86_400_000) return `${(ms / 3_600_000).toFixed(1)}h`;
  return `${(ms / 86_400_000).toFixed(2)}d`;
}

/**
 * Clean-run durability on the overview — the answer to "how many days straight
 * does the engine run as designed?" Reads GET /ops/durability, which derives the
 * number from the down-alert watchdog's outage ledger. The headline days-clean
 * figure only advances while the stack actually stays up (a restart can't game
 * it). Honest about absence: shows "no monitoring data" rather than a fake streak
 * when the watchdog hasn't run. See engine/routers/durability_router.py.
 */
export function DurabilityWidget() {
  const { data, error } = useSWR<DurabilityResponse>("ops-durability", fetchDurability, {
    refreshInterval: 60_000,
    shouldRetryOnError: false,
    errorRetryCount: 0,
  });

  return (
    <div className="rounded-xl border border-[#1a1a2e] bg-[#0a0a0a] p-4">
      <div className="mb-3 flex items-center justify-between">
        <span className="font-mono text-[10px] font-bold uppercase tracking-[0.2em] text-cyan-400">
          Clean-run durability
        </span>
        {data?.has_data && (
          <span
            className={`font-mono text-[9px] font-bold uppercase tracking-wider ${
              data.currently_down ? "text-red-400" : "text-emerald-400"
            }`}
          >
            {data.currently_down ? "IN OUTAGE" : "CLEAN"}
          </span>
        )}
      </div>

      {error && (
        <p className="py-2 text-xs text-gray-500">Engine unreachable — /ops/durability.</p>
      )}

      {!error && !data && <p className="py-2 text-xs text-gray-500">Loading…</p>}

      {data && !data.has_data && (
        <p className="py-2 text-xs text-gray-500">
          No monitoring data yet — wire up the down-alert watchdog (see
          ENGINE_DOWN_ALERTING runbook) and let it run.
        </p>
      )}

      {data && data.has_data && (
        <div className="space-y-2">
          <div className="flex items-end justify-between">
            <span
              className={`font-mono text-3xl font-bold tabular-nums ${
                data.currently_down ? "text-red-400" : "text-emerald-400"
              }`}
            >
              {data.currently_down
                ? "DOWN"
                : `${(data.current_streak_days ?? 0).toFixed(2)}d`}
            </span>
            <span className="text-[11px] text-gray-500">
              {data.currently_down ? (
                <>since {data.down_since?.slice(0, 16).replace("T", " ")}</>
              ) : (
                <>days clean</>
              )}
            </span>
          </div>
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-gray-500">
            <span>
              <span className="text-gray-600">outages</span> {data.outage_count}
            </span>
            {data.longest_streak_days != null && (
              <span>
                <span className="text-gray-600">longest</span>{" "}
                {data.longest_streak_days.toFixed(2)}d
              </span>
            )}
            {data.total_downtime_ms > 0 && (
              <span>
                <span className="text-gray-600">downtime</span>{" "}
                {fmtDuration(data.total_downtime_ms)}
              </span>
            )}
            {data.mtbf_ms != null && (
              <span>
                <span className="text-gray-600">MTBF</span> {fmtDuration(data.mtbf_ms)}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
