"use client";

import { useMemo } from "react";
import useSWR from "swr";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchEngine } from "@/lib/api";
import { FlaskConical } from "lucide-react";

const REFRESH_MS = 60_000;

type SideStats = {
  n: number;
  wins: number;
  losses: number;
  hit_rate: number;
  avg_delta: number;
};

type SummaryResponse = {
  n_rows: number;
  n_with_outcome: number;
  n_pending_outcome: number;
  first_date: string | null;
  last_date: string | null;
  by_side: Record<string, SideStats>;
  overall_non_skip: { n: number; wins: number; hit_rate: number; avg_delta: number };
};

type RowRecord = {
  date: string;
  symbol: string;
  recorded_at: string | null;
  corey_bias: string | null;
  corey_conviction: number | null;
  corey_session_type: string | null;
  corey_ib_bias: string | null;
  corey_data_quality: string | null;
  entry_hypothesis_side: string | null;
  entry_hypothesis_reason: string | null;
  open_price: number | null;
  high_price: number | null;
  low_price: number | null;
  close_price: number | null;
  outcome_delta: number | null;
  outcome_recorded_at: string | null;
};

type RowsResponse = { rows: RowRecord[]; count: number };

function fmtNum(n: number | null | undefined, digits = 2): string {
  if (n == null || !isFinite(n)) return "—";
  return n.toFixed(digits);
}

function fmtPct(n: number | null | undefined): string {
  if (n == null || !isFinite(n)) return "—";
  return `${(n * 100).toFixed(1)}%`;
}

function fmtDelta(n: number | null | undefined): string {
  if (n == null || !isFinite(n)) return "—";
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(2)}`;
}

function sideColor(side: string | null | undefined): string {
  if (side === "long") return "bg-emerald-950/60 text-emerald-300 border-emerald-900";
  if (side === "short") return "bg-rose-950/60 text-rose-300 border-rose-900";
  if (side === "skip") return "bg-zinc-900 text-zinc-400 border-zinc-800";
  return "bg-zinc-900 text-zinc-500 border-zinc-800";
}

function deltaColor(d: number | null | undefined): string {
  if (d == null) return "text-zinc-500";
  if (d > 0) return "text-emerald-400";
  if (d < 0) return "text-rose-400";
  return "text-zinc-400";
}

export function MESForwardRecorderPanel() {
  const summaryReq = useSWR<SummaryResponse>(
    "/experiments/mes-forward/summary",
    (p: string) => fetchEngine<SummaryResponse>(p),
    { refreshInterval: REFRESH_MS }
  );
  const rowsReq = useSWR<RowsResponse>(
    "/experiments/mes-forward/rows?limit=15",
    (p: string) => fetchEngine<RowsResponse>(p),
    { refreshInterval: REFRESH_MS }
  );

  const loading = summaryReq.isLoading || rowsReq.isLoading;
  const error = summaryReq.error || rowsReq.error;
  const summary = summaryReq.data;
  const rows = rowsReq.data?.rows ?? [];

  const long = summary?.by_side?.long;
  const short = summary?.by_side?.short;
  const skip = summary?.by_side?.skip;
  const overall = summary?.overall_non_skip;

  const weeksElapsed = useMemo(() => {
    if (!summary?.first_date) return null;
    const first = new Date(summary.first_date).getTime();
    const now = Date.now();
    return Math.max(0, (now - first) / (1000 * 60 * 60 * 24 * 7));
  }, [summary?.first_date]);

  if (loading) {
    return (
      <Card className="border-zinc-800 bg-zinc-950/60">
        <CardHeader className="py-3">
          <CardTitle className="text-sm font-medium text-zinc-300 flex items-center gap-2">
            <FlaskConical className="h-4 w-4" /> MES forward-recorder
          </CardTitle>
        </CardHeader>
        <CardContent className="pb-3">
          <div className="h-24 animate-pulse rounded bg-zinc-800/80" />
        </CardContent>
      </Card>
    );
  }

  if (error) {
    return (
      <Card className="border-zinc-800 bg-zinc-950/60">
        <CardHeader className="py-3">
          <CardTitle className="text-sm font-medium text-zinc-300 flex items-center gap-2">
            <FlaskConical className="h-4 w-4" /> MES forward-recorder
          </CardTitle>
        </CardHeader>
        <CardContent className="pb-3">
          <p className="text-xs text-rose-400">
            Failed to load: {String((error as Error)?.message ?? error)}
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="border-zinc-800 bg-zinc-950/60">
      <CardHeader className="py-3">
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="text-sm font-medium text-zinc-300 flex items-center gap-2">
            <FlaskConical className="h-4 w-4" /> MES forward-recorder
          </CardTitle>
          <div className="flex items-center gap-2">
            <Badge variant="neutral" className="border-zinc-700 text-zinc-400 text-[10px]">
              observational
            </Badge>
            <Badge variant="neutral" className="border-zinc-700 text-zinc-400 text-[10px]">
              no trades fired
            </Badge>
          </div>
        </div>
        <p className="text-[11px] text-zinc-500 mt-1">
          Corey bias + gamma levels + IB levels recorded daily; outcome filled 15:15 CT.
          Evaluation gate: ~40–60 rows (week 8–12).
        </p>
      </CardHeader>
      <CardContent className="pb-4 space-y-4">
        {/* ── Totals row ─────────────────────────────────────────────────── */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">
          <Stat label="rows" value={String(summary?.n_rows ?? 0)} />
          <Stat
            label="with outcome"
            value={String(summary?.n_with_outcome ?? 0)}
            sub={`${summary?.n_pending_outcome ?? 0} pending`}
          />
          <Stat
            label="date range"
            value={summary?.first_date ?? "—"}
            sub={summary?.last_date ?? "—"}
          />
          <Stat
            label="weeks elapsed"
            value={weeksElapsed != null ? weeksElapsed.toFixed(1) : "—"}
            sub="gate @ 8–12w"
          />
        </div>

        {/* ── By-side row ────────────────────────────────────────────────── */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
          <SideCard label="LONG" side="long" stats={long} />
          <SideCard label="SHORT" side="short" stats={short} />
          <SideCard label="SKIP" side="skip" stats={skip} skipVariant />
        </div>

        {/* ── Overall (non-skip) ─────────────────────────────────────────── */}
        <div className="rounded border border-zinc-800 bg-zinc-900/40 p-3">
          <p className="text-[10px] uppercase tracking-wider text-zinc-500 mb-1">
            Overall (long + short only)
          </p>
          <div className="grid grid-cols-3 gap-3 text-xs">
            <div>
              <p className="text-zinc-500 text-[10px]">n</p>
              <p className="text-zinc-100 text-sm font-semibold">{overall?.n ?? 0}</p>
            </div>
            <div>
              <p className="text-zinc-500 text-[10px]">hit rate</p>
              <p className="text-zinc-100 text-sm font-semibold">{fmtPct(overall?.hit_rate)}</p>
            </div>
            <div>
              <p className="text-zinc-500 text-[10px]">avg Δ (pts)</p>
              <p
                className={`text-sm font-semibold ${deltaColor(overall?.avg_delta)}`}
              >
                {fmtDelta(overall?.avg_delta)}
              </p>
            </div>
          </div>
        </div>

        {/* ── Recent rows table ──────────────────────────────────────────── */}
        <div>
          <p className="text-[10px] uppercase tracking-wider text-zinc-500 mb-2">
            Recent rows (newest first)
          </p>
          {rows.length === 0 ? (
            <p className="text-xs text-zinc-500 italic">
              No rows yet — first scheduled run fires 08:30 CT on the next weekday.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-[11px]">
                <thead>
                  <tr className="text-zinc-500 border-b border-zinc-800">
                    <th className="text-left py-1 pr-2 font-normal">date</th>
                    <th className="text-left py-1 pr-2 font-normal">side</th>
                    <th className="text-right py-1 pr-2 font-normal">conv</th>
                    <th className="text-right py-1 pr-2 font-normal">open</th>
                    <th className="text-right py-1 pr-2 font-normal">close</th>
                    <th className="text-right py-1 pr-2 font-normal">Δ pts</th>
                    <th className="text-left py-1 font-normal">reason</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r, i) => (
                    <tr
                      key={`${r.date}-${r.symbol}-${i}`}
                      className="border-b border-zinc-900/60"
                    >
                      <td className="py-1.5 pr-2 text-zinc-300 font-mono">{r.date}</td>
                      <td className="py-1.5 pr-2">
                        <span
                          className={`inline-block px-1.5 py-0.5 rounded border text-[10px] ${sideColor(
                            r.entry_hypothesis_side
                          )}`}
                        >
                          {r.entry_hypothesis_side ?? "—"}
                        </span>
                      </td>
                      <td className="py-1.5 pr-2 text-right text-zinc-400 font-mono">
                        {fmtNum(r.corey_conviction)}
                      </td>
                      <td className="py-1.5 pr-2 text-right text-zinc-400 font-mono">
                        {fmtNum(r.open_price)}
                      </td>
                      <td className="py-1.5 pr-2 text-right text-zinc-400 font-mono">
                        {fmtNum(r.close_price)}
                      </td>
                      <td
                        className={`py-1.5 pr-2 text-right font-mono ${deltaColor(
                          r.outcome_delta
                        )}`}
                      >
                        {fmtDelta(r.outcome_delta)}
                      </td>
                      <td
                        className="py-1.5 text-zinc-500 truncate max-w-[280px]"
                        title={r.entry_hypothesis_reason ?? ""}
                      >
                        {r.entry_hypothesis_reason ?? "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

// ── Sub-components ──────────────────────────────────────────────────────────

function Stat({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div className="rounded border border-zinc-800 bg-zinc-900/40 p-2">
      <p className="text-[10px] uppercase tracking-wider text-zinc-500">{label}</p>
      <p className="text-zinc-100 text-sm font-semibold leading-tight">{value}</p>
      {sub && <p className="text-[10px] text-zinc-500 mt-0.5">{sub}</p>}
    </div>
  );
}

function SideCard({
  label,
  side,
  stats,
  skipVariant = false,
}: {
  label: string;
  side: string;
  stats: SideStats | undefined;
  skipVariant?: boolean;
}) {
  const n = stats?.n ?? 0;
  return (
    <div className={`rounded border p-2 ${sideColor(side)}`}>
      <p className="text-[10px] uppercase tracking-wider opacity-70">{label}</p>
      {skipVariant ? (
        <div className="text-xs mt-1">
          <span className="font-semibold">{n}</span>
          <span className="opacity-60"> rows (no position)</span>
        </div>
      ) : (
        <div className="mt-1 grid grid-cols-3 gap-1.5 text-[11px]">
          <div>
            <p className="opacity-60 text-[9px]">n</p>
            <p className="font-semibold">{n}</p>
          </div>
          <div>
            <p className="opacity-60 text-[9px]">hit</p>
            <p className="font-semibold">{fmtPct(stats?.hit_rate)}</p>
          </div>
          <div>
            <p className="opacity-60 text-[9px]">avg Δ</p>
            <p className="font-semibold">{fmtDelta(stats?.avg_delta)}</p>
          </div>
        </div>
      )}
    </div>
  );
}
