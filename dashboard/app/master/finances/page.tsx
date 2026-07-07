"use client";
import Link from "next/link";
import useSWR from "swr";
import {
  fetchFinancesDetail,
  type Account,
  type FinancesDetail,
  type NetWorthPoint,
} from "@/lib/masterApi";

function fmt(n: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(n);
}

function signed(n: number): string {
  return `${n >= 0 ? "+" : "−"}${fmt(Math.abs(n))}`;
}

function fmtDate(posted: string): string {
  return new Date(Number(posted) * 1000).toLocaleDateString();
}

export default function FinancesDetailPage() {
  const { data, error } = useSWR<FinancesDetail>(
    "finances-detail",
    fetchFinancesDetail,
    { refreshInterval: 60000 },
  );

  if (error) {
    return (
      <main className="p-6 space-y-4">
        <Header />
        <div className="rounded-xl border border-red-800/40 bg-red-950/20 p-4">
          <p className="font-mono text-sm text-red-400">Finances API unreachable — master-api :8030 offline?</p>
          <p className="font-mono text-xs text-zinc-500 mt-1">Check: http://127.0.0.1:8030/master/finances/detail</p>
        </div>
      </main>
    );
  }

  if (!data) {
    return (
      <main className="p-6 space-y-4">
        <Header />
        <div className="space-y-3">
          <div className="h-14 animate-pulse rounded-xl bg-zinc-900/60 border border-zinc-800" />
          {[1,2,3,4].map((i) => (
            <div key={i} className="h-24 animate-pulse rounded-xl bg-zinc-900/60 border border-zinc-800" />
          ))}
        </div>
      </main>
    );
  }

  const budgetMap = new Map(data.budget_status.map((b) => [b.category, b]));
  const spendEntries = Object.entries(data.spend_by_category).sort((a, b) => b[1] - a[1]);
  const maxSpend = spendEntries.length > 0 ? Math.max(...spendEntries.map(([, v]) => v)) : 1;

  const history = data.net_worth_history ?? [];
  const change30d =
    history.length >= 2
      ? history[history.length - 1].net_worth - history[0].net_worth
      : null;

  const momEntries = Object.entries(data.month_over_month ?? {})
    .filter(([, v]) => v.this > 0 || v.last > 0)
    .sort((a, b) => Math.abs(b[1].delta) - Math.abs(a[1].delta));

  const byOrg = data.accounts_by_org ?? {};
  const orgs = Object.keys(byOrg).sort();

  return (
    <main className="p-6 space-y-8">
      <Header />

      {/* Net Worth + trend */}
      <section>
        <p className="text-xs uppercase tracking-widest text-zinc-500 mb-1">Net Worth</p>
        <div className="flex items-end gap-4 flex-wrap">
          <p
            className={`text-4xl font-bold ${
              data.net_worth < 0 ? "text-red-400" : "text-emerald-400"
            }`}
          >
            {fmt(data.net_worth)}
          </p>
          {change30d !== null && (
            <span
              className={`mb-1 rounded px-2 py-0.5 text-sm font-medium ${
                change30d >= 0
                  ? "bg-emerald-900/40 text-emerald-400"
                  : "bg-red-900/40 text-red-400"
              }`}
            >
              {signed(change30d)} ({history.length}d)
            </span>
          )}
          <div className="mb-1">
            <Sparkline points={history} />
          </div>
        </div>
      </section>

      {/* Accounts, grouped by institution */}
      <section>
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-zinc-400">
          Accounts
        </h2>
        <div className="space-y-5">
          {orgs.map((org) => (
            <div key={org}>
              <p className="mb-2 text-xs font-medium uppercase tracking-wide text-zinc-500">
                {org}
              </p>
              <div className="space-y-2">
                {byOrg[org].map((acct: Account) => (
                  <div
                    key={`${acct.org}-${acct.name}`}
                    className="flex items-center justify-between rounded-lg border border-zinc-700 bg-zinc-900 px-4 py-3"
                  >
                    <div>
                      <span className="text-sm font-medium text-zinc-100">{acct.name}</span>
                      {acct.is_liability && (
                        <span className="ml-2 rounded bg-red-900/50 px-1.5 py-0.5 text-xs font-medium text-red-400">
                          liability
                        </span>
                      )}
                    </div>
                    <span
                      className={`text-sm font-semibold tabular-nums ${
                        acct.balance < 0 || acct.is_liability ? "text-red-400" : "text-zinc-100"
                      }`}
                    >
                      {acct.balance < 0 ? `−${fmt(Math.abs(acct.balance))}` : fmt(acct.balance)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Spend by category */}
      <section>
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-zinc-400">
          Spend this month
        </h2>
        {spendEntries.length === 0 ? (
          <p className="text-sm text-zinc-500">No spend recorded this month.</p>
        ) : (
          <div className="space-y-3">
            {spendEntries.map(([cat, spent]) => {
              const budget = budgetMap.get(cat);
              const isOver = budget && budget.over_by > 0;
              const pct = maxSpend > 0 ? (spent / maxSpend) * 100 : 0;
              return (
                <div key={cat}>
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-sm text-zinc-200">{cat}</span>
                    <span
                      className={`text-sm font-semibold tabular-nums ${
                        isOver ? "text-amber-400" : "text-zinc-100"
                      }`}
                    >
                      {isOver ? `${fmt(spent)} / ${fmt(budget.limit)}` : fmt(spent)}
                      {isOver && (
                        <span className="ml-1 text-xs text-red-400">
                          (+{fmt(budget.over_by)})
                        </span>
                      )}
                    </span>
                  </div>
                  <div className="h-2 w-full rounded-full bg-zinc-800">
                    <div
                      className={`h-2 rounded-full ${isOver ? "bg-amber-500" : "bg-emerald-500"}`}
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>

      {/* Month over month */}
      {momEntries.length > 0 && (
        <section>
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-zinc-400">
            vs last month
          </h2>
          <div className="space-y-2">
            {momEntries.map(([cat, v]) => (
              <div
                key={cat}
                className="flex items-center justify-between rounded-lg border border-zinc-800 bg-zinc-900 px-4 py-2"
              >
                <span className="text-sm text-zinc-200">{cat}</span>
                <span className="flex items-center gap-3 text-sm tabular-nums">
                  <span className="text-zinc-400">
                    {fmt(v.this)} <span className="text-zinc-600">/ {fmt(v.last)}</span>
                  </span>
                  <span
                    className={`font-semibold ${
                      v.delta > 0 ? "text-amber-400" : "text-emerald-400"
                    }`}
                  >
                    {signed(v.delta)}
                  </span>
                </span>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Top merchants */}
      {data.top_merchants && data.top_merchants.length > 0 && (
        <section>
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-zinc-400">
            Top merchants this month
          </h2>
          <div className="space-y-2">
            {data.top_merchants.map((m) => (
              <div
                key={m.merchant}
                className="flex items-center justify-between rounded-lg border border-zinc-800 bg-zinc-900 px-4 py-2"
              >
                <span className="text-sm text-zinc-200">{m.merchant}</span>
                <span className="text-sm font-semibold tabular-nums text-zinc-100">
                  {fmt(m.total)}
                </span>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Recent transactions */}
      <section>
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-zinc-400">
          Recent transactions
        </h2>
        <div className="overflow-x-auto rounded-lg border border-zinc-700">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-zinc-700 bg-zinc-800/50">
                <th className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wide text-zinc-500">
                  Date
                </th>
                <th className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wide text-zinc-500">
                  Description
                </th>
                <th className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wide text-zinc-500">
                  Category
                </th>
                <th className="px-4 py-2 text-right text-xs font-semibold uppercase tracking-wide text-zinc-500">
                  Amount
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-800 bg-zinc-900">
              {data.recent.map((txn, i) => (
                <tr key={i} className="hover:bg-zinc-800/40">
                  <td className="px-4 py-2 text-zinc-400 tabular-nums">{fmtDate(txn.posted)}</td>
                  <td className="px-4 py-2 font-medium text-zinc-100">{txn.description}</td>
                  <td className="px-4 py-2 text-zinc-400">{txn.category}</td>
                  <td
                    className={`px-4 py-2 text-right tabular-nums font-semibold ${
                      txn.amount >= 0 ? "text-emerald-400" : "text-zinc-200"
                    }`}
                  >
                    {txn.amount >= 0 ? `+${fmt(txn.amount)}` : fmt(txn.amount)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </main>
  );
}

function Sparkline({ points }: { points: NetWorthPoint[] }) {
  if (points.length < 2) return null;
  const w = 240;
  const h = 48;
  const values = points.map((p) => p.net_worth);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const coords = values.map((v, i) => {
    const x = (i / (values.length - 1)) * w;
    const y = h - ((v - min) / span) * h;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const rising = values[values.length - 1] >= values[0];
  return (
    <svg width={w} height={h} className="overflow-visible">
      <polyline
        points={coords.join(" ")}
        fill="none"
        stroke={rising ? "#34d399" : "#f87171"}
        strokeWidth={2}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}

function Header() {
  return (
    <div className="flex items-center gap-4">
      <Link
        href="/master"
        className="text-sm text-zinc-400 hover:text-zinc-200 transition-colors"
      >
        ← Mission Control
      </Link>
      <h1 className="text-2xl font-bold text-zinc-100">Finances</h1>
    </div>
  );
}
