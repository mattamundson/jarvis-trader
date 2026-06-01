"use client";
import Link from "next/link";
import useSWR from "swr";
import { fetchFinancesDetail, type FinancesDetail } from "@/lib/masterApi";

function fmt(n: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(n);
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
      <main className="p-6">
        <Header />
        <p className="mt-6 text-red-400">Finances API unreachable.</p>
      </main>
    );
  }

  if (!data) {
    return (
      <main className="p-6">
        <Header />
        <p className="mt-6 text-zinc-400">Loading finances…</p>
      </main>
    );
  }

  const budgetMap = new Map(data.budget_status.map((b) => [b.category, b]));
  const spendEntries = Object.entries(data.spend_by_category).sort((a, b) => b[1] - a[1]);
  const maxSpend = spendEntries.length > 0 ? Math.max(...spendEntries.map(([, v]) => v)) : 1;

  return (
    <main className="p-6 space-y-8">
      <Header />

      {/* Net Worth */}
      <section>
        <p className="text-xs uppercase tracking-widest text-zinc-500 mb-1">Net Worth</p>
        <p
          className={`text-4xl font-bold ${
            data.net_worth < 0 ? "text-red-400" : "text-emerald-400"
          }`}
        >
          {fmt(data.net_worth)}
        </p>
      </section>

      {/* Accounts */}
      <section>
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-zinc-400">
          Accounts
        </h2>
        <div className="space-y-2">
          {data.accounts.map((acct) => (
            <div
              key={`${acct.org}-${acct.name}`}
              className="flex items-center justify-between rounded-lg border border-zinc-700 bg-zinc-900 px-4 py-3"
            >
              <div>
                <span className="text-sm font-medium text-zinc-100">{acct.name}</span>
                <span className="ml-2 text-xs text-zinc-500">{acct.org}</span>
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
      </section>

      {/* Spend by category */}
      <section>
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-zinc-400">
          Spend this month
        </h2>
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
                    {isOver
                      ? `${fmt(spent)} / ${fmt(budget.limit)}`
                      : fmt(spent)}
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
      </section>

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
