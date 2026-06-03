"use client";

import Link from "next/link";
import useSWR from "swr";
import {
  fetchHonestRealized,
  HONEST_REALIZED_KEY,
  type HonestPnlSummary,
} from "@/lib/honestMetrics";

function fmt(n: number): string {
  const s = new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(Math.abs(n));
  return n < 0 ? `−${s}` : `+${s}`;
}

/**
 * Deduplicated trade-record P&L on the main dashboard, sourced through the
 * honest-metrics layer (not the raw, over-counting engine tables). Surfaces the
 * real -$1,378 / PF 0.88 record so it is visible here, not only on /master.
 */
export function HonestPnlCard() {
  const { data, error } = useSWR<HonestPnlSummary>(
    HONEST_REALIZED_KEY,
    fetchHonestRealized,
    { refreshInterval: 60_000, shouldRetryOnError: false }
  );

  return (
    <div className="rounded-xl border border-[#1a1a2e] bg-[#0a0a0a] p-4">
      <div className="mb-3 flex items-center justify-between">
        <span className="font-mono text-[10px] font-bold uppercase tracking-[0.2em] text-cyan-400">
          Realized record (deduped)
        </span>
        <Link
          href="/master/trading"
          className="font-mono text-[9px] text-gray-500 transition-colors hover:text-gray-300"
        >
          detail →
        </Link>
      </div>

      {error && (
        <p className="py-2 text-xs text-gray-500">
          Honest-metrics source unavailable (master-api offline).
        </p>
      )}

      {!error && !data && (
        <p className="py-2 text-xs text-gray-500">Loading record…</p>
      )}

      {data && (
        <div className="space-y-2">
          <div className="flex items-end justify-between">
            <span
              className={`font-mono text-3xl font-bold tabular-nums ${
                data.netRealized < 0 ? "text-red-400" : "text-emerald-400"
              }`}
            >
              {fmt(data.netRealized)}
            </span>
            <span className="text-[11px] text-gray-500">
              {data.wins}W / {data.losses}L · PF{" "}
              <span className={data.profitFactor < 1 ? "text-red-400" : "text-emerald-400"}>
                {data.profitFactor.toFixed(2)}
              </span>
            </span>
          </div>
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-gray-500">
            <span>
              <span className="text-gray-600">trades</span> {data.trades}
            </span>
            <span>
              <span className="text-gray-600">win rate</span>{" "}
              {(data.winRate * 100).toFixed(0)}%
            </span>
          </div>
          {data.relogsCollapsed > 0 && (
            <p className="text-[10px] text-amber-400">
              {data.relogsCollapsed} re-logged row
              {data.relogsCollapsed === 1 ? "" : "s"} collapsed — the raw table
              over-counts to a false profit.
            </p>
          )}
          {!data.ok && (
            <p className="text-[10px] text-red-400">engine record unavailable</p>
          )}
        </div>
      )}
    </div>
  );
}
