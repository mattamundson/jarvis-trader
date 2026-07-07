"use client";

import { useEffect, useState } from "react";
import type { LucideIcon } from "lucide-react";
import { TrendingUp, Activity, Target, Award, DollarSign, TrendingDown } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { fetchRealizedPnl } from "@/lib/masterApi";

// Trade-record fields (PF, win-rate, net P&L, avg win/loss, counts) read from the
// honest deduped record (GET /master/trading/realized) rather than the
// over-counting /analytics/performance. Sharpe / max-drawdown / duration are not
// computed by the deduped view, so they render "—" instead of a fabricated value.
// See lib/honestMetrics.ts.


// ── Types ─────────────────────────────────────────────────────────────────────

interface PerformanceData {
  profit_factor?: number;
  sharpe_ratio?: number;
  win_rate?: number;
  total_trades?: number;
  winning_trades?: number;
  losing_trades?: number;
  total_pnl?: number;
  avg_win?: number;
  avg_loss?: number;
  max_drawdown?: number;
  avg_trade_duration_minutes?: number;
}

// ── Thresholds ────────────────────────────────────────────────────────────────

const THRESHOLDS = {
  profit_factor: 2.0,
  sharpe_ratio: 1.5,
  win_rate: 55,   // stored as percent (62.5 not 0.625)
  total_trades: 30,
} as const;

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtNum(v: number | undefined, decimals = 2): string {
  if (v === undefined || v === null || isNaN(v)) return "—";
  return v.toFixed(decimals);
}

function fmtUsd(v: number | undefined): string {
  if (v === undefined || v === null || isNaN(v)) return "—";
  const sign = v >= 0 ? "+" : "";
  return `${sign}$${Math.abs(v).toFixed(2)}`;
}

function fmtDuration(minutes: number | undefined): string {
  if (minutes === undefined || minutes === null || isNaN(minutes)) return "—";
  if (minutes < 60) return `${Math.round(minutes)}m`;
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  return m > 0 ? `${h}h ${m}m` : `${h}h`;
}

// win_rate from API may be either 0–100 range or 0–1 range; normalise to 0–100
function normaliseWinRate(v: number | undefined): number | undefined {
  if (v === undefined || v === null || isNaN(v)) return undefined;
  return v <= 1 ? v * 100 : v;
}

// ── Skeleton ──────────────────────────────────────────────────────────────────

function Skeleton() {
  return (
    <div className="rounded-xl border border-border bg-card p-5 space-y-4 animate-pulse">
      <div className="h-4 w-48 bg-muted rounded" />
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="rounded-lg border border-border/50 p-4 space-y-2">
            <div className="h-3 w-24 bg-muted rounded" />
            <div className="h-7 w-16 bg-muted rounded" />
            <div className="h-4 w-12 bg-muted rounded" />
          </div>
        ))}
      </div>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="rounded-lg border border-border/50 p-3 space-y-1.5">
            <div className="h-3 w-20 bg-muted rounded" />
            <div className="h-5 w-14 bg-muted rounded" />
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Primary Metric Card ───────────────────────────────────────────────────────

interface PrimaryCardProps {
  label: string;
  value: string;
  threshold: string;
  pass: boolean | null;
  icon: LucideIcon;
}

function PrimaryCard({ label, value, threshold, pass, icon: Icon }: PrimaryCardProps) {
  const passVariant: "bull" | "bear" | "neutral" =
    pass === null ? "neutral" : pass ? "bull" : "bear";

  return (
    <div className="rounded-lg border border-border/50 bg-background/40 p-4 flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5 text-xs text-muted-foreground uppercase tracking-wider">
          <Icon className="h-3.5 w-3.5" />
          {label}
        </div>
        {pass !== null && (
          <Badge variant={passVariant} className="text-xs px-1.5 py-0 h-5">
            {pass ? "PASS" : "FAIL"}
          </Badge>
        )}
      </div>
      <p className="text-2xl font-bold font-mono tabular-nums text-foreground leading-none">
        {value}
      </p>
      <p className="text-xs text-muted-foreground">
        Threshold: <span className="text-foreground/70">{threshold}</span>
      </p>
    </div>
  );
}

// ── Secondary Metric ──────────────────────────────────────────────────────────

interface SecondaryMetricProps {
  label: string;
  value: string;
  valueClass?: string;
}

function SecondaryMetric({ label, value, valueClass = "text-foreground" }: SecondaryMetricProps) {
  return (
    <div className="rounded-lg border border-border/50 bg-background/20 px-4 py-3 flex flex-col gap-1">
      <p className="text-xs text-muted-foreground uppercase tracking-wider">{label}</p>
      <p className={`text-sm font-semibold font-mono tabular-nums ${valueClass}`}>{value}</p>
    </div>
  );
}

// ── Main Component ────────────────────────────────────────────────────────────

export function PerformanceSummaryWidget() {
  const [data, setData] = useState<PerformanceData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const load = () => {
    fetchRealizedPnl()
      .then((p) => {
        const es = p.engine_sim;
        if (!es?.ok) throw new Error(es?.error || "honest trade record unavailable");
        setData({
          profit_factor: es.profit_factor,
          win_rate: es.win_rate, // 0..1 — normaliseWinRate handles it
          total_trades: es.trades,
          winning_trades: es.wins,
          losing_trades: es.losses,
          total_pnl: es.net_realized,
          avg_win: es.wins > 0 ? es.gross_win / es.wins : undefined,
          avg_loss: es.losses > 0 ? -(es.gross_loss / es.losses) : undefined,
          // sharpe_ratio / max_drawdown / avg_trade_duration_minutes are not
          // computed by the deduped trade-record view -> left undefined -> "—".
        });
        setError(false);
      })
      .catch(() => {
        setError(true);
      })
      .finally(() => {
        setLoading(false);
      });
  };

  useEffect(() => {
    load();
    // Auto-refresh every 2 minutes
    const id = setInterval(load, 2 * 60 * 1000);
    return () => clearInterval(id);
  }, []);

  if (loading) return <Skeleton />;

  if (error || !data) {
    return (
      <div className="rounded-xl border border-border bg-card p-5">
        <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3">
          Performance Summary
        </p>
        <p className="text-sm text-muted-foreground">
          Unable to load performance data. Ensure the engine is running and reachable through the dashboard proxy.
        </p>
      </div>
    );
  }

  // Normalise win_rate to 0–100 range
  const winRatePct = normaliseWinRate(data?.win_rate);

  // Determine PASS/FAIL for each primary metric
  const pfPass = data?.profit_factor !== undefined ? (data.profit_factor ?? 0) >= THRESHOLDS.profit_factor : null;
  const sharpePass = data?.sharpe_ratio !== undefined ? (data.sharpe_ratio ?? 0) >= THRESHOLDS.sharpe_ratio : null;
  const winRatePass = winRatePct !== undefined ? winRatePct >= THRESHOLDS.win_rate : null;
  const tradesPass = data?.total_trades !== undefined ? (data.total_trades ?? 0) >= THRESHOLDS.total_trades : null;

  // Overall status from the gates the deduped record actually computes
  // (PF / win-rate / trades). Sharpe is informational here — the honest
  // trade-record view does not compute it — so it does not gate the verdict.
  const allPass =
    pfPass === true &&
    winRatePass === true &&
    tradesPass === true;

  const anyNull = pfPass === null || winRatePass === null || tradesPass === null;

  const overallVariant: "bull" | "warn" | "neutral" =
    anyNull ? "neutral" : allPass ? "bull" : "warn";

  const overallLabel = anyNull
    ? "PAPER PHASE: AWAITING DATA"
    : allPass
    ? "PAPER PHASE: ON TRACK"
    : "PAPER PHASE: IN PROGRESS";

  // Secondary metric colours
  const pnlClass =
    (data?.total_pnl ?? 0) > 0 ? "text-bull" : (data?.total_pnl ?? 0) < 0 ? "text-bear" : "text-foreground";
  const avgWinClass = "text-bull";
  const avgLossClass = "text-bear";
  const drawdownClass = "text-warn";

  return (
    <div className="rounded-xl border border-border bg-card p-5 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-accent/10">
            <Activity className="h-4 w-4 text-accent" />
          </div>
          <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Performance Summary
          </p>
        </div>
        <Badge variant={overallVariant} className="text-xs font-semibold">
          {overallLabel}
        </Badge>
      </div>

      {/* Primary metrics — 4 columns */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <PrimaryCard
          label="Profit Factor"
          value={fmtNum(data?.profit_factor, 2)}
          threshold={`\u2265 ${THRESHOLDS.profit_factor}`}
          pass={pfPass}
          icon={TrendingUp}
        />
        <PrimaryCard
          label="Sharpe Ratio"
          value={fmtNum(data?.sharpe_ratio, 2)}
          threshold={`\u2265 ${THRESHOLDS.sharpe_ratio}`}
          pass={sharpePass}
          icon={Award}
        />
        <PrimaryCard
          label="Win Rate"
          value={winRatePct !== undefined ? `${winRatePct.toFixed(1)}%` : "—"}
          threshold={`\u2265 ${THRESHOLDS.win_rate}%`}
          pass={winRatePass}
          icon={Target}
        />
        <PrimaryCard
          label="Total Trades"
          value={data?.total_trades !== undefined ? String(data.total_trades) : "—"}
          threshold={`\u2265 ${THRESHOLDS.total_trades}`}
          pass={tradesPass}
          icon={Activity}
        />
      </div>

      {/* Secondary metrics row */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <SecondaryMetric
          label="Total P&L"
          value={fmtUsd(data?.total_pnl)}
          valueClass={pnlClass}
        />
        <SecondaryMetric
          label="Avg Win"
          value={data?.avg_win !== undefined ? `+$${data.avg_win.toFixed(2)}` : "—"}
          valueClass={avgWinClass}
        />
        <SecondaryMetric
          label="Avg Loss"
          value={data?.avg_loss !== undefined ? `-$${Math.abs(data.avg_loss).toFixed(2)}` : "—"}
          valueClass={avgLossClass}
        />
        <SecondaryMetric
          label="Max Drawdown"
          value={
            data?.max_drawdown !== undefined
              ? data.max_drawdown < 0
                ? `$${data.max_drawdown.toFixed(2)}`
                : `-$${Math.abs(data.max_drawdown).toFixed(2)}`
              : "—"
          }
          valueClass={drawdownClass}
        />
      </div>

      {/* Footer detail row */}
      <div className="flex items-center justify-between pt-1 border-t border-border/50 text-xs text-muted-foreground">
        <span>
          {data?.winning_trades ?? "—"}W&nbsp;/&nbsp;{data?.losing_trades ?? "—"}L
          {data?.total_trades !== undefined && data.total_trades > 0 && (
            <span className="ml-2 opacity-60">
              ({data.total_trades} total)
            </span>
          )}
        </span>
        {data?.avg_trade_duration_minutes !== undefined && (
          <span>
            Avg duration: <span className="text-foreground/70">{fmtDuration(data.avg_trade_duration_minutes)}</span>
          </span>
        )}
        <span className="opacity-50">Honest deduped record · Sharpe/DD not computed</span>
      </div>
    </div>
  );
}
