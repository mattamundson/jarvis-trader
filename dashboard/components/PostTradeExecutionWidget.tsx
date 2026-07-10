"use client";

import useSWR from "swr";
import { fetchEngine } from "@/lib/api";
import { Badge } from "@/components/ui/badge";

// Surfaces the WS4B post-trade execution-quality endpoints (jarvis PR #78) that
// nothing else in the dashboard shows: exit-reason attribution, slippage cost,
// and losing-streak. Regime P&L attribution is intentionally NOT duplicated here
// (RegimeAttributionWidget + RegimePnLBreakdownWidget already cover it).
//
// All three endpoints go live only after master is deployed onto the running
// engine; until then each section degrades to an honest "unavailable" / "no
// closed trades yet" state rather than erroring the page.

const REFRESH_MS = 120_000;

function fetcher<T>(url: string): Promise<T> {
  return fetchEngine<T>(url);
}

interface ExitReasonBlock {
  count: number;
  total_pnl: number;
  avg_pnl: number | null;
  win_rate: number | null;
  wins: number;
  losses: number;
  profit_factor: number | null;
}
interface ExitAttribution {
  by_reason: Record<string, ExitReasonBlock>;
  overall: ExitReasonBlock;
  classified_pct: number | null;
}
interface SlippageSymbol {
  count: number;
  avg_ticks: number | null;
  total_slippage_usd: number | null;
}
interface SlippageAttribution {
  trade_count: number;
  populated_count: number;
  by_symbol: Record<string, SlippageSymbol>;
  total_slippage_usd: number | null;
  slippage_pct_of_pnl: number | null;
}
interface LosingStreak {
  trade_count: number;
  max_consecutive_losses: number;
  max_consecutive_wins: number;
  current_streak: number;
  worst_drawdown_run_usd: number;
}

function pnlColor(v: number): string {
  if (v > 0) return "text-green-400";
  if (v < 0) return "text-red-400";
  return "text-muted-foreground";
}

function money(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return `${v >= 0 ? "+" : "-"}$${Math.abs(v).toFixed(0)}`;
}

const EXIT_ORDER = ["target", "stop", "manual", "unknown"] as const;
const EXIT_COLOR: Record<string, string> = {
  target: "bg-green-500",
  stop: "bg-red-500",
  manual: "bg-yellow-500",
  unknown: "bg-sky-500",
};

function SectionHead({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/60">
      {children}
    </p>
  );
}

/** Honest per-section fallback: distinguishes "not deployed yet" from "no data". */
function Unavailable({ error, label }: { error: boolean; label: string }) {
  return (
    <p className="text-[11px] text-muted-foreground/50">
      {error ? `${label} unavailable — lights up after deploy onto master` : "No closed trades yet"}
    </p>
  );
}

function ExitReasons() {
  const { data, error, isLoading } = useSWR<ExitAttribution>(
    "/analytics/exit-attribution",
    fetcher,
    { refreshInterval: REFRESH_MS }
  );
  if (isLoading) return <div className="h-12 rounded bg-white/5 animate-pulse" />;
  if (error || !data || data.overall.count === 0)
    return <Unavailable error={!!error} label="Exit attribution" />;

  const total = data.overall.count || 1;
  return (
    <div className="space-y-1.5">
      {EXIT_ORDER.filter((r) => data.by_reason[r]?.count).map((r) => {
        const b = data.by_reason[r];
        const pct = (b.count / total) * 100;
        return (
          <div key={r} className="space-y-1">
            <div className="flex items-center justify-between text-xs">
              <span className="font-mono uppercase text-muted-foreground">{r}</span>
              <div className="flex items-center gap-3 text-right">
                <span className="text-muted-foreground/60 tabular-nums w-8">{b.count}t</span>
                <span className="text-muted-foreground tabular-nums w-10">
                  {b.win_rate !== null ? `${(b.win_rate * 100).toFixed(0)}%` : "—"}
                </span>
                <span className={`tabular-nums w-14 ${pnlColor(b.total_pnl)}`}>{money(b.total_pnl)}</span>
              </div>
            </div>
            <div className="relative h-1 w-full rounded-full bg-white/10 overflow-hidden">
              <div className={`absolute inset-y-0 left-0 rounded-full ${EXIT_COLOR[r]}`} style={{ width: `${pct}%`, opacity: 0.7 }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

function Slippage() {
  const { data, error, isLoading } = useSWR<SlippageAttribution>(
    "/analytics/slippage-attribution",
    fetcher,
    { refreshInterval: REFRESH_MS }
  );
  if (isLoading) return <div className="h-8 rounded bg-white/5 animate-pulse" />;
  if (error || !data || data.populated_count === 0)
    return <Unavailable error={!!error} label="Slippage" />;

  const syms = Object.entries(data.by_symbol).sort((a, b) => b[1].count - a[1].count).slice(0, 4);
  return (
    <div className="space-y-1.5 text-xs">
      <div className="flex items-center justify-between">
        <span className="text-muted-foreground">Total cost</span>
        <span className="tabular-nums text-orange-400">
          {data.total_slippage_usd !== null ? `-$${Math.abs(data.total_slippage_usd).toFixed(0)}` : "—"}
          <span className="text-muted-foreground/50 ml-1">
            ({data.populated_count}/{data.trade_count})
          </span>
        </span>
      </div>
      {syms.map(([sym, s]) => (
        <div key={sym} className="flex items-center justify-between text-[11px]">
          <span className="font-mono text-muted-foreground/70">{sym}</span>
          <span className="tabular-nums text-muted-foreground/60">
            {s.avg_ticks !== null ? `${s.avg_ticks.toFixed(1)} ticks avg` : "—"}
          </span>
        </div>
      ))}
    </div>
  );
}

function Streak() {
  const { data, error, isLoading } = useSWR<LosingStreak>(
    "/analytics/losing-streak",
    fetcher,
    { refreshInterval: REFRESH_MS }
  );
  if (isLoading) return <div className="h-8 rounded bg-white/5 animate-pulse" />;
  if (error || !data || data.trade_count === 0)
    return <Unavailable error={!!error} label="Streak" />;

  const cur = data.current_streak;
  const curLabel = cur === 0 ? "flat" : cur > 0 ? `${cur}W` : `${Math.abs(cur)}L`;
  const curColor = cur > 0 ? "text-green-400" : cur < 0 ? "text-red-400" : "text-muted-foreground";
  return (
    <div className="grid grid-cols-3 gap-2 text-center">
      <div>
        <p className="text-base font-mono font-semibold text-red-400 tabular-nums">{data.max_consecutive_losses}</p>
        <p className="text-[10px] text-muted-foreground/50">max losses</p>
      </div>
      <div>
        <p className={`text-base font-mono font-semibold tabular-nums ${curColor}`}>{curLabel}</p>
        <p className="text-[10px] text-muted-foreground/50">current</p>
      </div>
      <div>
        <p className="text-base font-mono font-semibold text-red-400 tabular-nums">
          {money(data.worst_drawdown_run_usd)}
        </p>
        <p className="text-[10px] text-muted-foreground/50">worst run</p>
      </div>
    </div>
  );
}

export function PostTradeExecutionWidget() {
  // Same SWR keys as ExitReasons/Slippage/Streak below — SWR dedupes requests
  // by key, so this shares their cache instead of issuing extra fetches. Used
  // only to derive a single card-level live/static provenance badge.
  const exitQ = useSWR<ExitAttribution>("/analytics/exit-attribution", fetcher, { refreshInterval: REFRESH_MS });
  const slipQ = useSWR<SlippageAttribution>("/analytics/slippage-attribution", fetcher, { refreshInterval: REFRESH_MS });
  const streakQ = useSWR<LosingStreak>("/analytics/losing-streak", fetcher, { refreshInterval: REFRESH_MS });
  const allFailed = !!exitQ.error && !!slipQ.error && !!streakQ.error;

  return (
    <div className="rounded-xl border border-border bg-card p-4 space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Post-Trade Execution Quality
        </p>
        <Badge variant={allFailed ? "static" : "live"}>
          <span className="flex items-center gap-1">
            <span className={`h-1.5 w-1.5 rounded-full ${allFailed ? "bg-muted-foreground" : "bg-bull animate-pulse"}`} />
            {allFailed ? "STATIC" : "LIVE"}
          </span>
        </Badge>
      </div>
      <div className="space-y-1.5">
        <SectionHead>Exit reasons (target / stop / manual)</SectionHead>
        <ExitReasons />
      </div>
      <div className="space-y-1.5">
        <SectionHead>Slippage cost</SectionHead>
        <Slippage />
      </div>
      <div className="space-y-1.5">
        <SectionHead>Losing streak</SectionHead>
        <Streak />
      </div>
    </div>
  );
}
