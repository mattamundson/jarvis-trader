"use client";

import { useState } from "react";
import useSWR from "swr";
import { GitCompare, TrendingUp, TrendingDown, Minus } from "lucide-react";
import {
  fetchAccountStats,
  AccountStatsResponse,
  EquityCurvePoint,
} from "@/lib/api";
import {
  fetchHonestTrades,
  type HonestTradeSet,
  dedupCaveat,
} from "@/lib/honestTrades";
import { fmt, fmtPct, fmtCalmar, statColor } from "@/lib/parallelPaperFormat";

// ── Types ─────────────────────────────────────────────────────────────────────

type WindowDays = 30 | 90 | 180;

// ── Inline SVG sparkline ──────────────────────────────────────────────────────

function EquitySparkline({
  data,
  color,
}: {
  data: EquityCurvePoint[];
  color: string;
}) {
  if (!data || data.length < 2) {
    return (
      <div className="h-24 flex items-center justify-center text-xs text-muted-foreground">
        No equity data
      </div>
    );
  }

  const equities = data.map((d) => d.equity);
  const min = Math.min(...equities);
  const max = Math.max(...equities);
  const range = max - min || 1;

  const W = 320;
  const H = 80;
  const pad = 4;

  const points = data.map((d, i) => {
    const x = pad + (i / (data.length - 1)) * (W - 2 * pad);
    const y = pad + ((max - d.equity) / range) * (H - 2 * pad);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });

  const polyline = points.join(" ");

  // Fill area under curve
  const first = points[0];
  const last = points[points.length - 1];
  const area = `${first} ${polyline} ${last.split(",")[0]},${H - pad} ${pad},${H - pad}`;

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className="w-full h-24"
      preserveAspectRatio="none"
      aria-hidden="true"
    >
      <defs>
        <linearGradient id={`grad-${color}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.3" />
          <stop offset="100%" stopColor={color} stopOpacity="0.02" />
        </linearGradient>
      </defs>
      <polygon points={area} fill={`url(#grad-${color})`} />
      <polyline
        points={polyline}
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
    </svg>
  );
}

// ── Account column ────────────────────────────────────────────────────────────

function AccountColumn({
  label,
  accountId,
  days,
  color,
  honestSet,
}: {
  label: string;
  accountId: "A" | "B";
  days: WindowDays;
  color: string;
  honestSet: HonestTradeSet | null;
}) {
  const { data, error, isLoading } = useSWR<AccountStatsResponse>(
    [`account-stats`, accountId, days],
    () => fetchAccountStats(accountId, days),
    { refreshInterval: 60_000 }
  );

  const isB = accountId === "B";

  if (isLoading) {
    return (
      <div className="flex-1 rounded-xl border border-border bg-card p-5 animate-pulse">
        <div className="h-4 w-24 bg-muted rounded mb-6" />
        <div className="space-y-3">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="h-3 bg-muted rounded" />
          ))}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex-1 rounded-xl border border-destructive/40 bg-card p-5">
        <p className="text-xs text-destructive">Failed to load account {accountId} data</p>
      </div>
    );
  }

  if (!data) return null;

  const isEmpty = data.n_trades === 0;

  const emptyMsg = isB
    ? "Account B has no trades. Enable ENABLE_PARALLEL_PAPER=1 and restart the engine."
    : "No closed trades in this window.";

  return (
    <div
      className="flex-1 rounded-xl border bg-card p-5 space-y-5"
      style={{ borderColor: isEmpty ? undefined : color + "44" }}
    >
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <p className="text-[10px] uppercase tracking-widest text-muted-foreground">
            {label}
          </p>
          <h2 className="text-lg font-bold text-foreground">Account {accountId}</h2>
        </div>
        <div
          className="h-8 w-8 rounded-lg flex items-center justify-center text-sm font-bold"
          style={{ background: color + "22", color }}
        >
          {accountId}
        </div>
      </div>

      {/* Raw-record caveat — account-level dedup is not derivable because the
          honest record is not split by account A/B. Stats below are the raw
          per-account figures from /portfolio/paper/account/{id}/stats. */}
      <div className="rounded-md border border-yellow-500/30 bg-yellow-500/5 px-3 py-2 text-[11px] text-yellow-200/70">
        <span className="font-semibold text-yellow-300">Raw record · not deduped</span>
        {" "}— per-account dedup is not derivable (honest record is combined, not split by A/B).
        {accountId === "A" && honestSet && (
          <span className="block mt-1 text-yellow-200/50">
            Combined honest net: {honestSet.net >= 0 ? "+" : ""}${honestSet.net.toFixed(0)} · {dedupCaveat(honestSet)}
          </span>
        )}
      </div>

      {isEmpty ? (
        <p className="text-xs text-muted-foreground italic">{emptyMsg}</p>
      ) : (
        <>
          {/* Equity sparkline */}
          <div>
            <p className="text-[10px] uppercase tracking-widest text-muted-foreground mb-1">
              Equity Curve
            </p>
            <EquitySparkline data={data.equity_curve} color={color} />
          </div>

          {/* Metrics grid */}
          <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-xs">
            <div>
              <dt className="text-muted-foreground">Trades</dt>
              <dd className="font-semibold text-foreground">{data.n_trades}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Win Rate</dt>
              <dd className={`font-semibold ${statColor(data.win_rate)}`}>
                {fmtPct(data.win_rate)}
              </dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Sortino</dt>
              <dd className={`font-semibold ${statColor(data.sortino)}`}>
                {fmt(data.sortino)}
              </dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Sharpe</dt>
              <dd className={`font-semibold ${statColor(data.sharpe)}`}>
                {fmt(data.sharpe)}
              </dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Calmar</dt>
              <dd className={`font-semibold ${statColor(data.calmar)}`}>
                {fmtCalmar(data.calmar)}
              </dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Max DD</dt>
              <dd className={`font-semibold ${statColor(data.max_dd, false)}`}>
                {fmtPct(data.max_dd)}
              </dd>
            </div>
          </dl>
        </>
      )}
    </div>
  );
}

// ── Delta badge ───────────────────────────────────────────────────────────────

function DeltaRow({
  label,
  a,
  b,
  higherBetter = true,
  isPct = false,
}: {
  label: string;
  a: number | null | undefined;
  b: number | null | undefined;
  higherBetter?: boolean;
  isPct?: boolean;
}) {
  const display = isPct ? fmtPct : (v: number | null | undefined) => fmt(v);
  if (a == null || b == null) {
    return (
      <tr>
        <td className="py-1.5 text-muted-foreground text-xs w-32">{label}</td>
        <td className="py-1.5 text-xs text-foreground font-mono">{display(a)}</td>
        <td className="py-1.5 text-xs text-foreground font-mono">{display(b)}</td>
        <td className="py-1.5 text-xs text-muted-foreground pl-3">—</td>
      </tr>
    );
  }

  const diff = b - a;
  const bWins = higherBetter ? diff > 0 : diff < 0;
  const DeltaIcon = diff === 0 ? Minus : bWins ? TrendingUp : TrendingDown;
  const deltaColor = diff === 0 ? "text-muted-foreground" : bWins ? "text-green-400" : "text-red-400";

  return (
    <tr>
      <td className="py-1.5 text-muted-foreground text-xs w-32">{label}</td>
      <td className="py-1.5 text-xs text-foreground font-mono">{display(a)}</td>
      <td className="py-1.5 text-xs text-foreground font-mono">{display(b)}</td>
      <td className={`py-1.5 text-xs font-semibold pl-3 ${deltaColor} flex items-center gap-1`}>
        <DeltaIcon className="h-3 w-3 shrink-0" />
        {isPct ? fmtPct(Math.abs(diff)) : fmt(Math.abs(diff))}
      </td>
    </tr>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function ParallelPaperPage() {
  const [days, setDays] = useState<WindowDays>(30);

  const { data: dataA } = useSWR<AccountStatsResponse>(
    [`account-stats`, "A", days],
    () => fetchAccountStats("A", days),
    { refreshInterval: 60_000 }
  );
  const { data: dataB } = useSWR<AccountStatsResponse>(
    [`account-stats`, "B", days],
    () => fetchAccountStats("B", days),
    { refreshInterval: 60_000 }
  );

  // Honest combined set — used only to show combined net in the caveat badge.
  // Per-account dedup is not derivable (honest record is not split by A/B).
  const { data: honestSet } = useSWR<HonestTradeSet>(
    "honest-trades-parallel-paper",
    fetchHonestTrades,
    { refreshInterval: 5 * 60_000, shouldRetryOnError: false }
  );

  const windowOptions: { label: string; value: WindowDays }[] = [
    { label: "30d", value: 30 },
    { label: "90d", value: 90 },
    { label: "180d", value: 180 },
  ];

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="sticky top-0 z-50 border-b border-border bg-background/95 backdrop-blur">
        <div className="mx-auto max-w-[1920px] flex items-center justify-between px-6 py-3">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent/10">
              <GitCompare className="h-5 w-5 text-accent" />
            </div>
            <div>
              <h1 className="font-bold text-foreground tracking-tight">
                Parallel Paper A/B Comparison
              </h1>
              <p className="text-xs text-muted-foreground">
                Production config vs. challenger — same signals, different risk params
              </p>
            </div>
          </div>

          {/* Window selector */}
          <div className="flex gap-1">
            {windowOptions.map(({ label, value }) => (
              <button
                key={value}
                onClick={() => setDays(value)}
                className={`rounded-md px-3 py-1 text-xs font-medium transition-colors ${
                  days === value
                    ? "bg-accent text-accent-foreground"
                    : "text-muted-foreground hover:text-foreground hover:bg-muted"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1920px] px-6 py-6 space-y-6">
        {/* Caveat banner */}
        <div className="rounded-lg border border-yellow-500/30 bg-yellow-500/5 px-4 py-3 text-xs text-yellow-200/80">
          <strong className="text-yellow-300">Statistical caveat:</strong>{" "}
          30 days is barely above the noise floor for risk-param comparison. 90 days is the
          recommended minimum before concluding one config outperforms the other. Sample size
          matters more than short-term P&amp;L.
          <span className="block mt-1">
            <strong className="text-yellow-300">Annualization:</strong> Sharpe / Sortino are
            annualized by each account&apos;s observed trade frequency (not a fixed 252);
            sub-90-day windows fall back to the 252 convention and are not directly comparable
            to a daily-trader Sharpe.
          </span>
        </div>

        {/* Two-column account panels */}
        <div className="flex flex-col lg:flex-row gap-4">
          <AccountColumn
            label="Production config"
            accountId="A"
            days={days}
            color="#22c55e"
            honestSet={honestSet ?? null}
          />
          <AccountColumn
            label="Challenger config"
            accountId="B"
            days={days}
            color="#a78bfa"
            honestSet={honestSet ?? null}
          />
        </div>

        {/* Side-by-side tearsheet diff */}
        {dataA && dataB && (
          <div className="rounded-xl border border-border bg-card p-5">
            <h3 className="text-sm font-semibold text-foreground mb-3">
              Config comparison — {days}-day window
            </h3>
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="text-[10px] uppercase tracking-widest text-muted-foreground">
                    <th className="text-left pb-2 w-32">Metric</th>
                    <th className="text-left pb-2">A (prod)</th>
                    <th className="text-left pb-2">B (challenger)</th>
                    <th className="text-left pb-2 pl-3">Delta</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/40">
                  <DeltaRow label="Trades" a={dataA.n_trades} b={dataB.n_trades} />
                  <DeltaRow label="Win rate" a={dataA.win_rate} b={dataB.win_rate} isPct />
                  <DeltaRow label="Sortino" a={dataA.sortino} b={dataB.sortino} />
                  <DeltaRow label="Sharpe" a={dataA.sharpe} b={dataB.sharpe} />
                  <DeltaRow label="Calmar" a={dataA.calmar} b={dataB.calmar} />
                  <DeltaRow
                    label="Max DD"
                    a={dataA.max_dd}
                    b={dataB.max_dd}
                    higherBetter={false}
                    isPct
                  />
                </tbody>
              </table>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
