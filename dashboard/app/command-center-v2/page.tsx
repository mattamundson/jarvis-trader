"use client";

import useSWR from "swr";

import {
  executionCapability,
  fetchControlPlaneSnapshot,
  type ControlPlanePosition,
} from "@/lib/controlPlane";

function money(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(value);
}

function pct(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  const normalized = Math.abs(value) <= 1 ? value * 100 : value;
  return `${normalized.toFixed(2)}%`;
}

function ageSeconds(asOf: string | number | null | undefined, nowMs: number): number | null {
  if (asOf == null) return null;
  const ms = typeof asOf === "number"
    ? (asOf < 10_000_000_000 ? asOf * 1000 : asOf)
    : Date.parse(asOf);
  if (!Number.isFinite(ms)) return null;
  return Math.max(0, (nowMs - ms) / 1000);
}

function freshnessLabel(position: ControlPlanePosition, nowMs: number): string {
  const age = ageSeconds(position.as_of, nowMs);
  if (age == null) return "unknown";
  const staleAfter = position.stale_after_s ?? 60;
  return age <= staleAfter ? `live · ${age.toFixed(0)}s` : `stale · ${age.toFixed(0)}s`;
}

function StatePill({
  label,
  tone = "neutral",
}: {
  label: string;
  tone?: "good" | "bad" | "warn" | "neutral";
}) {
  const classes = {
    good: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
    bad: "border-red-500/40 bg-red-500/10 text-red-300",
    warn: "border-amber-500/40 bg-amber-500/10 text-amber-300",
    neutral: "border-zinc-700 bg-zinc-900 text-zinc-300",
  }[tone];
  return <span className={`rounded-full border px-2.5 py-1 text-xs font-semibold ${classes}`}>{label}</span>;
}

function MetricCard({ title, value, detail }: { title: string; value: string; detail?: string }) {
  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-950 p-4">
      <div className="text-xs uppercase tracking-[0.16em] text-zinc-500">{title}</div>
      <div className="mt-2 text-2xl font-semibold text-zinc-100">{value}</div>
      {detail ? <div className="mt-1 text-xs text-zinc-500">{detail}</div> : null}
    </div>
  );
}

export default function CommandCenterV2Page() {
  const { data, error, isLoading, mutate } = useSWR(
    "command-center-v2-control-plane",
    fetchControlPlaneSnapshot,
    { refreshInterval: 3000, revalidateOnFocus: true },
  );

  const capability = data ? executionCapability(data) : null;
  const nowMs = Date.now();
  const positions = data?.portfolio?.positions ?? [];
  const approvals = data?.pendingApprovals?.candidates ?? [];
  const degraded = data ? Object.entries(data.errors) : [];

  return (
    <main className="min-h-screen bg-black px-5 py-6 text-zinc-100">
      <div className="mx-auto max-w-[1600px] space-y-5">
        <header className="flex flex-col gap-3 border-b border-zinc-800 pb-5 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <div className="text-xs font-semibold uppercase tracking-[0.25em] text-zinc-500">
              JARVIS operator control plane
            </div>
            <h1 className="mt-1 text-3xl font-semibold">Command Center V2</h1>
            <p className="mt-2 max-w-3xl text-sm text-zinc-400">
              RT-0 read-only cockpit. No order-submission controls are enabled on this page yet.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <StatePill
              label={capability?.mode ?? "UNKNOWN"}
              tone={capability?.mode === "PAPER" ? "good" : capability?.mode === "LIVE" ? "bad" : "warn"}
            />
            <StatePill
              label={data?.health?.ibkr_execution_connected || data?.health?.ibkr_connected ? "IB EXEC CONNECTED" : "IB EXEC OFFLINE"}
              tone={data?.health?.ibkr_execution_connected || data?.health?.ibkr_connected ? "good" : "bad"}
            />
            <StatePill
              label={data?.safety?.kill_switch_active ? "KILL SWITCH ACTIVE" : "KILL SWITCH CLEAR"}
              tone={data?.safety?.kill_switch_active ? "bad" : "good"}
            />
            <button
              type="button"
              onClick={() => void mutate()}
              className="rounded-md border border-zinc-700 px-3 py-1.5 text-xs font-semibold text-zinc-300 hover:border-zinc-500"
            >
              Refresh
            </button>
          </div>
        </header>

        {error ? (
          <div className="rounded-lg border border-red-500/40 bg-red-500/10 p-4 text-sm text-red-300">
            Control-plane fetch failed: {error instanceof Error ? error.message : String(error)}
          </div>
        ) : null}

        {degraded.length > 0 ? (
          <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-4">
            <div className="font-semibold text-amber-300">Cockpit degraded — execution must remain disabled</div>
            <ul className="mt-2 space-y-1 text-sm text-amber-200/80">
              {degraded.map(([key, message]) => <li key={key}>{key}: {message}</li>)}
            </ul>
          </div>
        ) : null}

        <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-6">
          <MetricCard title="Equity" value={money(data?.portfolio?.total_equity ?? data?.safety?.portfolio_equity)} />
          <MetricCard title="Daily P&L" value={money(data?.portfolio?.daily_pnl ?? data?.safety?.daily_pnl)} />
          <MetricCard title="Unrealized P&L" value={money(data?.portfolio?.unrealized_pnl)} />
          <MetricCard title="Current Drawdown" value={pct(data?.safety?.drawdown_pct ?? data?.safety?.current_drawdown)} />
          <MetricCard title="Orders Today" value={data?.safety ? String(data.safety.orders_today) : "—"} />
          <MetricCard title="Pending Approvals" value={data?.pendingApprovals ? String(data.pendingApprovals.count) : "—"} />
        </section>

        <section className="grid gap-5 xl:grid-cols-[1.35fr_0.65fr]">
          <div className="rounded-xl border border-zinc-800 bg-zinc-950">
            <div className="flex items-center justify-between border-b border-zinc-800 px-4 py-3">
              <div>
                <h2 className="font-semibold">Broker / Portfolio State</h2>
                <p className="text-xs text-zinc-500">Broker-visible positions with mark provenance.</p>
              </div>
              <StatePill label={`${positions.length} positions`} />
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[760px] text-left text-sm">
                <thead className="text-xs uppercase tracking-wider text-zinc-500">
                  <tr className="border-b border-zinc-900">
                    <th className="px-4 py-3">Symbol</th>
                    <th className="px-4 py-3">Qty</th>
                    <th className="px-4 py-3">Avg Cost</th>
                    <th className="px-4 py-3">Mark</th>
                    <th className="px-4 py-3">Unrealized</th>
                    <th className="px-4 py-3">Source / freshness</th>
                  </tr>
                </thead>
                <tbody>
                  {positions.length === 0 ? (
                    <tr><td colSpan={6} className="px-4 py-8 text-center text-zinc-600">No open positions.</td></tr>
                  ) : positions.map((position, index) => (
                    <tr key={`${position.symbol}-${index}`} className="border-b border-zinc-900/70">
                      <td className="px-4 py-3 font-semibold">{position.symbol}</td>
                      <td className="px-4 py-3">{position.quantity}</td>
                      <td className="px-4 py-3">{money(position.avg_cost ?? position.average_price)}</td>
                      <td className="px-4 py-3">{money(position.current_price)}</td>
                      <td className={`px-4 py-3 ${(position.unrealized_pnl ?? 0) >= 0 ? "text-emerald-300" : "text-red-300"}`}>
                        {money(position.unrealized_pnl)}
                      </td>
                      <td className="px-4 py-3 text-xs text-zinc-500">
                        {position.source ?? "unknown"} · {freshnessLabel(position, nowMs)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="rounded-xl border border-zinc-800 bg-zinc-950 p-4">
            <h2 className="font-semibold">Execution Gate</h2>
            <p className="mt-1 text-xs text-zinc-500">Preview only. RT-1 will reuse the existing paper approval route.</p>
            <div className="mt-4">
              <StatePill
                label={capability?.canApprovePaper ? "PAPER APPROVAL READY" : "PAPER APPROVAL BLOCKED"}
                tone={capability?.canApprovePaper ? "good" : "warn"}
              />
            </div>
            <ul className="mt-4 space-y-2 text-sm text-zinc-400">
              {(capability?.reasons.length ? capability.reasons : ["all read-model gates currently clear"]).map((reason) => (
                <li key={reason} className="rounded-md border border-zinc-900 bg-black px-3 py-2">{reason}</li>
              ))}
            </ul>
          </div>
        </section>

        <section className="rounded-xl border border-zinc-800 bg-zinc-950">
          <div className="flex items-center justify-between border-b border-zinc-800 px-4 py-3">
            <div>
              <h2 className="font-semibold">Pending JARVIS Candidates</h2>
              <p className="text-xs text-zinc-500">Read-only in RT-0. Approve/reject controls arrive in RT-1.</p>
            </div>
            <StatePill label={`${approvals.length} pending`} tone={approvals.length ? "warn" : "neutral"} />
          </div>
          <div className="grid gap-3 p-4 md:grid-cols-2 xl:grid-cols-3">
            {approvals.length === 0 ? (
              <div className="text-sm text-zinc-600">No pending candidates.</div>
            ) : approvals.map((candidate) => (
              <article key={candidate.id} className="rounded-lg border border-zinc-800 bg-black p-4">
                <div className="flex items-center justify-between">
                  <div className="text-lg font-semibold">{candidate.symbol}</div>
                  <StatePill
                    label={candidate.validation_only ? "VALIDATION ONLY" : candidate.status.toUpperCase()}
                    tone={candidate.validation_only ? "bad" : "warn"}
                  />
                </div>
                <div className="mt-3 grid grid-cols-2 gap-2 text-sm">
                  <div className="text-zinc-500">Direction</div><div>{candidate.direction}</div>
                  <div className="text-zinc-500">Confidence</div><div>{candidate.confidence == null ? "—" : pct(candidate.confidence)}</div>
                  <div className="text-zinc-500">Strategy</div><div>{candidate.stark_signal ?? "—"}</div>
                  <div className="text-zinc-500">Expires</div><div>{new Date(candidate.expires_at).toLocaleTimeString()}</div>
                </div>
              </article>
            ))}
          </div>
        </section>

        <footer className="flex flex-col gap-1 border-t border-zinc-900 pt-4 text-xs text-zinc-600 sm:flex-row sm:justify-between">
          <span>RT-0 · read-only · no execution mutations on this page</span>
          <span>{isLoading ? "Loading…" : data ? `Snapshot ${new Date(data.fetchedAt).toLocaleTimeString()}` : "No snapshot"}</span>
        </footer>
      </div>
    </main>
  );
}
