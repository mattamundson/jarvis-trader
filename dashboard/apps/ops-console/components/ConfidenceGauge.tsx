"use client";

import useSWR from "swr";
import { fetchCalibration, type CalibrationDiagnostics } from "@/lib/api";

/**
 * JARVIS calibration gauge — surfaces how well-calibrated the analyst ensemble
 * has been (Brier + IC over the rolling window) rather than just the signal.
 *
 * Honest-first: until enough graded outcomes accrue, it shows a clear
 * "not yet calibrated" state instead of a fabricated confidence number
 * (brier_30d_rolling is null on a fresh book).
 */
export function ConfidenceGauge() {
  const { data, error } = useSWR<CalibrationDiagnostics>(
    "/analytics/calibration",
    fetchCalibration,
    { refreshInterval: 60_000, shouldRetryOnError: false }
  );

  const readyAgents = data
    ? data.agents.filter((a) => data.per_agent[a]?.ready)
    : [];

  // Aggregate calibration quality over READY agents only: 1.0 = perfectly
  // calibrated (Brier 0), 0 = at/above the neutral sentinel. Never invented
  // when there is no ready agent.
  let quality: number | null = null;
  if (data && readyAgents.length > 0 && data.neutral_sentinel > 0) {
    const mean =
      readyAgents.reduce(
        (acc, a) => acc + (data.per_agent[a]?.brier_score ?? data.neutral_sentinel),
        0
      ) / readyAgents.length;
    quality = Math.max(0, Math.min(1, 1 - mean / data.neutral_sentinel));
  }

  const calibrated = quality !== null;
  const pct = calibrated ? Math.round((quality as number) * 100) : 0;
  const barColor =
    pct >= 70 ? "bg-emerald-400" : pct >= 40 ? "bg-amber-400" : "bg-red-400";

  return (
    <div className="rounded-xl border border-[#1a1a2e] bg-[#0a0a0a] p-4">
      <div className="mb-3 flex items-center justify-between">
        <span className="font-mono text-[10px] font-bold uppercase tracking-[0.2em] text-cyan-400">
          JARVIS Calibration
        </span>
        {data && (
          <span
            className={`font-mono text-[9px] rounded border px-1.5 py-0.5 ${
              data.brier_enabled
                ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-400"
                : "border-gray-600/40 bg-gray-600/10 text-gray-400"
            }`}
            title="Reflects BRIER_CALIBRATION_ENABLED on the engine"
          >
            {data.brier_enabled ? "ENABLED" : "SHADOW"}
          </span>
        )}
      </div>

      {error && (
        <p className="py-2 text-xs text-red-400">Calibration API unreachable.</p>
      )}

      {!error && !data && (
        <p className="py-2 text-xs text-gray-500">Loading calibration…</p>
      )}

      {data && !calibrated && (
        <div className="space-y-1 py-1">
          <p className="text-sm font-semibold text-amber-400">NOT YET CALIBRATED</p>
          <p className="text-xs text-gray-500">
            {data.total_outcomes} graded outcome{data.total_outcomes === 1 ? "" : "s"} ·
            need {data.min_trades_threshold}/agent over {data.window_days}d. No
            confidence number is shown until the floor is met.
          </p>
        </div>
      )}

      {data && calibrated && (
        <div className="space-y-2">
          <div className="flex items-end justify-between">
            <span className="font-mono text-3xl font-bold tabular-nums text-gray-100">
              {pct}
              <span className="text-base text-gray-500">%</span>
            </span>
            <span className="text-[11px] text-gray-500">
              {readyAgents.length}/{data.agents.length} agents ready
            </span>
          </div>
          <div className="h-2 w-full overflow-hidden rounded-full bg-[#1a1a2e]">
            <div
              className={`h-full rounded-full ${barColor}`}
              style={{ width: `${pct}%` }}
            />
          </div>
          {data.blocked_by.length > 0 && (
            <p className="text-[10px] text-gray-500">
              below floor: {data.blocked_by.join(", ")}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
