"use client";

import { POLL_INTERVAL } from "@/lib/polling-config";
import Link from "next/link";
import useSWR from "swr";
import { fetchRealizedPnl, type RealizedPnl } from "@/lib/masterApi";

function fmt(n: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(n);
}

function fmtTime(t: string | null): string {
  if (!t) return "—";
  const d = new Date(t);
  return Number.isNaN(d.getTime()) ? t : d.toLocaleString();
}

export default function TradingDetailPage() {
  const { data, error } = useSWR<RealizedPnl>("trading-realized", fetchRealizedPnl, {
    refreshInterval: POLL_INTERVAL.MINUTE,
  });

  if (error) {
    return (
      <main className="p-6 space-y-4">
        <Header />
        <div className="rounded-xl border border-red-800/40 bg-red-950/20 p-4">
          <p className="font-mono text-sm text-red-400">Trading API unreachable — master-api :8030 offline?</p>
          <p className="font-mono text-xs text-zinc-500 mt-1">Check: http://127.0.0.1:8030/master/trading/realized</p>
        </div>
      </main>
    );
  }
  if (!data) {
    return (
      <main className="p-6 space-y-4">
        <Header />
        <div className="space-y-3">
          <div className="h-20 animate-pulse rounded-xl bg-zinc-900/60 border border-zinc-800" />
          {[1,2,3].map((i) => (
            <div key={i} className="h-10 animate-pulse rounded bg-zinc-900/60 border border-zinc-800" />
          ))}
        </div>
      </main>
    );
  }

  const es = data.engine_sim;
  const ib = data.ibkr_account;
  const relogs = Math.max(0, es.raw_rows - es.trades);
  const net = es.net_realized;

  return (
    <main className="p-6 space-y-8">
      <Header />

      {/* Realized P&L — real JARVIS trades */}
      <section>
        <p className="mb-1 text-xs uppercase tracking-widest text-zinc-500">
          Realized P&amp;L · real JARVIS trades (deduplicated)
        </p>
        <p className={`text-4xl font-bold ${net < 0 ? "text-red-400" : "text-emerald-400"}`}>
          {net < 0 ? `−${fmt(Math.abs(net))}` : `+${fmt(net)}`}
        </p>
        <div className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-sm text-zinc-300">
          <span>
            <span className="text-zinc-500">trades</span> {es.trades}
          </span>
          <span>
            <span className="text-zinc-500">record</span> {es.wins}W / {es.losses}L
          </span>
          <span>
            <span className="text-zinc-500">win rate</span> {(es.win_rate * 100).toFixed(0)}%
          </span>
          <span>
            <span className="text-zinc-500">profit factor</span>{" "}
            <span className={es.profit_factor < 1 ? "text-red-400" : "text-emerald-400"}>
              {es.profit_factor.toFixed(2)}
            </span>
          </span>
          <span>
            <span className="text-zinc-500">gross</span> +{fmt(es.gross_win)} / {fmt(es.gross_loss)}
          </span>
        </div>
        {relogs > 0 && (
          <p className="mt-2 text-xs text-amber-400">
            {es.raw_rows} logged rows → {es.trades} distinct trades ({relogs} re-logs collapsed).
            The raw table over-counts the one winner ~6×, which inflates it to a false profit.
          </p>
        )}
        {!es.ok && (
          <p className="mt-2 text-xs text-red-400">engine record unavailable: {es.error}</p>
        )}
      </section>

      {/* Trade list */}
      <section>
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-zinc-400">
          Closed trades
        </h2>
        <div className="overflow-x-auto rounded-lg border border-zinc-700">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-zinc-700 bg-zinc-800/50 text-left text-xs uppercase tracking-wide text-zinc-500">
                <th className="px-4 py-2">Symbol</th>
                <th className="px-4 py-2">Side</th>
                <th className="px-4 py-2">Entry → Exit</th>
                <th className="px-4 py-2">Grade</th>
                <th className="px-4 py-2 text-right">P&amp;L</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-800 bg-zinc-900">
              {es.trade_list.map((t, i) => (
                <tr key={i} className="hover:bg-zinc-800/40">
                  <td className="px-4 py-2 font-medium text-zinc-100">{t.symbol}</td>
                  <td className="px-4 py-2 text-zinc-400">{t.direction}</td>
                  <td className="px-4 py-2 text-xs text-zinc-400 tabular-nums">
                    {fmtTime(t.entry_time)} → {fmtTime(t.exit_time)}
                  </td>
                  <td className="px-4 py-2">
                    {t.grade && (
                      <span
                        className={`rounded px-1.5 py-0.5 text-xs font-semibold ${
                          t.grade === "F"
                            ? "bg-red-900/50 text-red-400"
                            : "bg-zinc-800 text-zinc-300"
                        }`}
                      >
                        {t.grade}
                      </span>
                    )}
                  </td>
                  <td
                    className={`px-4 py-2 text-right font-semibold tabular-nums ${
                      t.pnl_usd >= 0 ? "text-emerald-400" : "text-red-400"
                    }`}
                  >
                    {t.pnl_usd >= 0 ? `+${fmt(t.pnl_usd)}` : `−${fmt(Math.abs(t.pnl_usd))}`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* IBKR demo account — explicitly NOT strategy */}
      {ib && (
        <section className="rounded-xl border-2 border-amber-700/60 bg-amber-950/10 p-5">
          <div className="mb-3 flex items-center gap-3">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-300">
              IBKR account
            </h2>
            <span className="rounded bg-amber-900/60 px-2 py-0.5 text-xs font-bold uppercase tracking-wide text-amber-300">
              demo · not strategy
            </span>
            <span className="text-xs text-zinc-500">as of {ib.as_of}</span>
          </div>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <Stat label="NAV" value={fmt(ib.nav_total)} tone="zinc" />
            <Stat label="realized YTD (locked-in)" value={`+${fmt(ib.realized_ytd)}`} tone="emerald" />
            <Stat label="unrealized (open MTM)" value={`+${fmt(ib.unrealized_total)}`} tone="amber" />
            <Stat label="cash" value={fmt(ib.cash)} tone="zinc" />
          </div>
          {ib.top_unrealized_position && (
            <p className="mt-3 text-xs text-zinc-400">
              {Math.round(
                (ib.top_unrealized_position.unrealized_pnl / ib.unrealized_total) * 100,
              )}
              % of unrealized gains is one demo-seed position:{" "}
              <span className="font-medium text-zinc-200">
                {ib.top_unrealized_position.symbol}
              </span>{" "}
              (cost ${ib.top_unrealized_position.cost_price} → ${ib.top_unrealized_position.close_price},{" "}
              {fmt(ib.top_unrealized_position.unrealized_pnl)}).
            </p>
          )}
          <p className="mt-2 text-xs italic text-zinc-500">{ib.note}</p>
        </section>
      )}

      {/* Caveats */}
      {data.caveats?.length > 0 && (
        <section>
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-zinc-400">
            Read this before trusting any number
          </h2>
          <ul className="space-y-1">
            {data.caveats.map((c) => (
              <li key={c} className="text-xs text-zinc-400">
                • {c}
              </li>
            ))}
          </ul>
        </section>
      )}
    </main>
  );
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: "zinc" | "emerald" | "amber";
}) {
  const color =
    tone === "emerald" ? "text-emerald-400" : tone === "amber" ? "text-amber-400" : "text-zinc-100";
  return (
    <div>
      <p className="text-xs text-zinc-500">{label}</p>
      <p className={`text-lg font-semibold tabular-nums ${color}`}>{value}</p>
    </div>
  );
}

function Header() {
  return (
    <div className="flex items-center gap-4">
      <Link href="/master" className="text-sm text-zinc-400 transition-colors hover:text-zinc-200">
        ← Master Jarvis
      </Link>
      <h1 className="text-2xl font-bold text-zinc-100">Trading</h1>
    </div>
  );
}
