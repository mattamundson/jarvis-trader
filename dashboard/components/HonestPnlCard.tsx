"use client";

import Link from "next/link";
import useSWR from "swr";
import { useHonestTrades } from "@/lib/useHonestTrades";
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
 * Deduplicated trade-record P&L on the main dashboard, sourced through the
 * honest-metrics layer (not the raw, over-counting engine tables). Surfaces the
 * real record (PF, wins/losses, dedup) so it is visible here, not only on /master.
 *
 * Master-api (:8030) is the RICH source (per-trade dedup, PF, W/L) but it is
 * frequently down, which used to leave this card blank. It no longer does: when
 * the master-api honest record is unavailable, the card FALLS BACK to the
 * engine-native `/pnl/truth` realized number — no external dependency, honest
 * TRUSTED/DEGRADED verdict, and it shows "—" (never a fabricated $0) rather than
 * faking wins/losses/PF it cannot know from an aggregate. This removes the hard
 * master-api dependency for the headline honest number. (Trade-list-derived
 * widgets keep their own "unavailable" states — /pnl/truth is an aggregate, not
 * a trade list, so it is only surfaced where an aggregate is honest.)
 */
export function HonestPnlCard() {
  const { honest, error } = useHonestTrades(60_000);

  // Fallback source, consulted only when the master-api record is unavailable.
  const masterDown = !!error;
  const { data: truth } = useSWR<PnlTruthResponse>(
    masterDown ? "pnl-truth-fallback" : null,
    fetchPnlTruth,
    { refreshInterval: 60_000, shouldRetryOnError: false, errorRetryCount: 0 },
  );

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

      {/* Loading (master-api still deciding, no fallback resolved yet) */}
      {!honest && !masterDown && (
        <p className="py-2 text-xs text-gray-500">Loading record…</p>
      )}

      {/* Primary: rich deduped record from master-api */}
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

      {/* Fallback: engine-native /pnl/truth when master-api is down */}
      {masterDown && !honest && (
        <div className="space-y-2">
          {!truth && (
            <p className="py-2 text-xs text-gray-500">
              master-api offline — reading engine ledger…
            </p>
          )}
          {truth && (
            <>
              <div className="flex items-end justify-between">
                <span
                  className={`font-mono text-3xl font-bold tabular-nums ${
                    truth.realized_pnl == null
                      ? "text-amber-400"
                      : truth.realized_pnl < 0
                        ? "text-red-400"
                        : "text-emerald-400"
                  }`}
                >
                  {truth.realized_pnl == null ? "—" : fmt(truth.realized_pnl)}
                </span>
                <span className="text-[11px] text-gray-500">
                  {truth.closed_trades} closed ·{" "}
                  <span className={truth.trusted ? "text-emerald-400" : "text-amber-400"}>
                    {truth.status}
                  </span>
                </span>
              </div>
              <p className="text-[10px] text-amber-400">
                master-api offline — engine `/pnl/truth` fallback (aggregate; W/L
                and PF unavailable from this source).
                {!truth.trusted && truth.reasons.length > 0 && (
                  <> {truth.reasons.join("; ")}.</>
                )}
              </p>
            </>
          )}
        </div>
      )}
    </div>
  );
}
