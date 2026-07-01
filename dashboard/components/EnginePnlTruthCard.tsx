"use client";

import useSWR from "swr";
import { fetchPnlTruth, type PnlTruthResponse } from "@/lib/api";

function fmt(n: number): string {
  const s = new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(Math.abs(n));
  return n < 0 ? `−${s}` : `+${s}`;
}

/**
 * Engine-native honest realized P&L, sourced from GET /pnl/truth.
 *
 * Distinct from HonestPnlCard (which reads the external master-api honest-metrics
 * layer and goes blank when :8030 is down): this card reads the engine's OWN
 * closed-trade ledger, so it stays truthful with no external dependency. Its
 * whole point is honesty about its own confidence — it renders an explicit
 * TRUSTED / DEGRADED verdict and shows "—" (never a fabricated $0) when the
 * ledger can't be read. See engine/routers/pnl_truth_router.py.
 */
export function EnginePnlTruthCard() {
  const { data, error } = useSWR<PnlTruthResponse>("pnl-truth", fetchPnlTruth, {
    refreshInterval: 60_000,
    shouldRetryOnError: false,
    errorRetryCount: 0,
  });

  const degraded = !!data && !data.trusted;
  const pnl = data?.realized_pnl ?? null;

  return (
    <div className="rounded-xl border border-[#1a1a2e] bg-[#0a0a0a] p-4">
      <div className="mb-3 flex items-center justify-between">
        <span className="font-mono text-[10px] font-bold uppercase tracking-[0.2em] text-cyan-400">
          Realized P&amp;L (engine ledger)
        </span>
        {data && (
          <span
            className={`font-mono text-[9px] font-bold uppercase tracking-wider ${
              data.trusted ? "text-emerald-400" : "text-amber-400"
            }`}
          >
            {data.status}
          </span>
        )}
      </div>

      {error && (
        <p className="py-2 text-xs text-gray-500">
          Engine unreachable — /pnl/truth did not respond.
        </p>
      )}

      {!error && !data && <p className="py-2 text-xs text-gray-500">Loading record…</p>}

      {data && (
        <div className="space-y-2">
          <div className="flex items-end justify-between">
            <span
              className={`font-mono text-3xl font-bold tabular-nums ${
                pnl == null
                  ? "text-amber-400"
                  : pnl < 0
                    ? "text-red-400"
                    : "text-emerald-400"
              }`}
            >
              {pnl == null ? "—" : fmt(pnl)}
            </span>
            <span className="text-[11px] text-gray-500">
              {data.closed_trades} closed
              {data.excluded_trades > 0 && (
                <>
                  {" · "}
                  <span className="text-amber-400">{data.excluded_trades} excluded</span>
                </>
              )}
            </span>
          </div>

          {degraded && (
            <p className="text-[10px] text-amber-400">
              Degraded — no fabricated number.{" "}
              {data.reasons.length > 0 ? data.reasons.join("; ") : "ledger source unavailable"}.
            </p>
          )}

          {!degraded && data.sources_present.length > 0 && (
            <p className="text-[10px] text-gray-600">
              source: {data.sources_present.join(", ")}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
