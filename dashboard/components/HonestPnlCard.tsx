"use client";

import Link from "next/link";
import { useHonestTrades } from "@/lib/useHonestTrades";

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
 *
 * Reads through the shared `useHonestTrades()` subscription (SWR key
 * "honest-trades") rather than a private "honest-realized-pnl" key, so this card
 * dedupes with every other honest-metrics widget — one /master/trading/realized
 * request per refresh cycle for the whole page, and no cross-widget desync. The
 * HonestTradeSet already carries every field this summary needs.
 */
export function HonestPnlCard() {
  const { honest, error } = useHonestTrades(60_000);
  const pf = honest?.profitFactor ?? null;

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
      {/*
        Labeling for the two-scoreboard discrepancy (see PaperTradingPanel.tsx
        for the counterpart note): master-api's read-time dedup over all
        history/all symbols -- a different pipeline and trade universe than
        the engine's own trade_history DB shown in "Paper Trading". Neither
        number is wrong; they measure different things.
      */}
      <p className="mb-2 text-[9px] text-gray-500">
        master-api dedup, all-time · all symbols
      </p>

      {error && (
        <p className="py-2 text-xs text-gray-500">
          Honest-metrics source unavailable (master-api offline).
        </p>
      )}

      {!error && !honest && (
        <p className="py-2 text-xs text-gray-500">Loading record…</p>
      )}

      {honest && (
        <div className="space-y-2">
          <div className="flex items-end justify-between">
            <span
              className={`font-mono text-3xl font-bold tabular-nums ${
                honest.net < 0 ? "text-red-400" : "text-emerald-400"
              }`}
            >
              {fmt(honest.net)}
            </span>
            <span className="text-[11px] text-gray-500">
              {honest.wins}W / {honest.losses}L · PF{" "}
              <span className={pf != null && pf < 1 ? "text-red-400" : "text-emerald-400"}>
                {pf != null ? pf.toFixed(2) : "—"}
              </span>
            </span>
          </div>
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-gray-500">
            <span>
              <span className="text-gray-600">trades</span> {honest.trades.length}
            </span>
            <span>
              <span className="text-gray-600">win rate</span>{" "}
              {(honest.winRate * 100).toFixed(0)}%
            </span>
          </div>
          {honest.relogged > 0 && (
            <p className="text-[10px] text-amber-400">
              {honest.relogged} re-logged row
              {honest.relogged === 1 ? "" : "s"} collapsed — the raw table
              over-counts to a false profit.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
