"use client";

import useSWR from "swr";
import { AlertTriangle, CheckCircle2, ShieldAlert, ShieldOff } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { fetchEngine } from "@/lib/api";
import type { CircuitBreakerState } from "@/lib/api";

function fetcher<T>(url: string): Promise<T> {
  return fetchEngine<T>(url);
}

// ── Sub-components ────────────────────────────────────────────────────────────

function GaugeRow({
  label,
  current,
  limit,
  displayCurrent,
  displayLimit,
  pct,
}: {
  label: string;
  current: number;
  limit: number;
  displayCurrent: string;
  displayLimit: string;
  pct: number;
}) {
  const clamped = Math.min(1, Math.max(0, pct));
  const tripped = pct >= 1;
  const warning = !tripped && pct > 0.5;

  const barColor = tripped
    ? "bg-bear"
    : warning
    ? "bg-warn"
    : "bg-bull";

  const valueColor = tripped
    ? "text-bear"
    : warning
    ? "text-warn"
    : "text-foreground";

  void current;
  void limit;

  const statusText = tripped ? "TRIPPED" : warning ? "WARNING" : "NORMAL";

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between text-xs">
        <span className="text-muted-foreground font-medium">{label}</span>
        <div className="flex items-center gap-2">
          <span className="text-muted-foreground/60 tabular-nums">{displayLimit}</span>
          <span className={`tabular-nums font-semibold ${valueColor}`}>{displayCurrent}</span>
        </div>
      </div>
      <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-500 ${barColor}`}
          style={{ width: `${clamped * 100}%` }}
          role="progressbar"
          aria-valuenow={Math.round(clamped * 100)}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label={`${label} status: ${statusText}`}
        />
      </div>
      {/* Text status label */}
      <div className="flex justify-between text-xs">
        <span className="text-muted-foreground/60"></span>
        <span className={`font-semibold ${valueColor}`}>{statusText}</span>
      </div>
    </div>
  );
}

// ── Main Component ────────────────────────────────────────────────────────────

export function CircuitBreakerPanel() {
  const {
    data,
    error,
    isLoading,
  } = useSWR<CircuitBreakerState>("/safety/circuit-breakers", fetcher, {
    refreshInterval: 10_000,
    shouldRetryOnError: true,
  });

  // ── Loading state ──────────────────────────────────────────────────────────
  if (isLoading) {
    return (
      <div className="rounded-xl border border-border bg-card p-4 space-y-3 animate-pulse">
        <div className="h-5 w-32 rounded bg-muted" />
        <div className="h-8 w-full rounded-lg bg-muted" />
        <div className="space-y-2">
          <div className="h-4 w-full rounded bg-muted" />
          <div className="h-4 w-full rounded bg-muted" />
        </div>
      </div>
    );
  }

  // ── Error state ────────────────────────────────────────────────────────────
  if (error || !data) {
    return (
      <div className="rounded-xl border border-border bg-card p-4">
        <div className="flex items-center gap-2 text-muted-foreground">
          <AlertTriangle className="h-4 w-4" />
          <span className="text-xs">Circuit breaker data unavailable</span>
        </div>
      </div>
    );
  }

  // ── Derive display values ──────────────────────────────────────────────────
  const dailyPct =
    data.daily_limit !== 0
      ? Math.abs(data.daily_pnl) / Math.abs(data.daily_limit)
      : 0;

  // Real engine field is `drawdown_limit_pct`, not `drawdown_limit` (which
  // does not exist in the response). Both drawdown_pct and drawdown_limit_pct
  // are negative fractions (e.g. -0.012 / -0.20), so dividing them directly
  // yields a correct positive "how much of the limit is used" ratio.
  const drawdownPct =
    data.drawdown_limit_pct !== 0
      ? data.drawdown_pct / data.drawdown_limit_pct
      : 0;

  const dailyPnlSign = data.daily_pnl >= 0 ? "+" : "";
  const displayDailyPnl = `${dailyPnlSign}$${data.daily_pnl.toFixed(0)}`;
  const displayDailyLimit = `limit: -$${Math.abs(data.daily_limit).toFixed(0)}`;

  const displayDrawdown = `-${(Math.abs(data.drawdown_pct) * 100).toFixed(2)}%`;
  const displayDrawdownLimit = `limit: -${(Math.abs(data.drawdown_limit_pct) * 100).toFixed(1)}%`;

  // ── Status banner ──────────────────────────────────────────────────────────
  let bannerLabel: string;
  let bannerIcon: React.ReactNode;
  let bannerClasses: string;

  if (data.kill_switch_active) {
    bannerLabel = "HALTED";
    bannerIcon = <ShieldOff className="h-4 w-4" />;
    bannerClasses = "border-bear/40 bg-bear/10 text-bear";
  } else if (!data.all_clear) {
    bannerLabel = "WARNING";
    bannerIcon = <ShieldAlert className="h-4 w-4" />;
    bannerClasses = "border-warn/40 bg-warn/10 text-warn";
  } else {
    bannerLabel = "All Clear";
    bannerIcon = <CheckCircle2 className="h-4 w-4" />;
    bannerClasses = "border-bull/30 bg-bull/10 text-bull";
  }

  return (
    <div className="rounded-xl border border-border bg-card p-4 space-y-3">
      {/* Section label */}
      <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
        Circuit Breakers
      </p>

      {/* Status banner */}
      <div
        className={`flex items-center justify-between rounded-lg border px-3 py-2 ${bannerClasses}`}
        role="status"
        aria-live="polite"
        aria-label={`Circuit breaker status: ${bannerLabel}`}
      >
        <div className="flex items-center gap-2 font-semibold text-sm">
          {bannerIcon}
          <span>{bannerLabel}</span>
        </div>

        {/* Kill switch pill */}
        <Badge
          variant={data.kill_switch_active ? "bear" : "neutral"}
          aria-label={`Kill switch is ${data.kill_switch_active ? "active" : "inactive"}`}
        >
          Kill Switch: {data.kill_switch_active ? "Active" : "Inactive"}
        </Badge>
      </div>

      {/* Gauges */}
      <div className="space-y-3">
        <GaugeRow
          label="Daily P&L"
          current={data.daily_pnl}
          limit={data.daily_limit}
          displayCurrent={displayDailyPnl}
          displayLimit={displayDailyLimit}
          pct={dailyPct}
        />
        <GaugeRow
          label="Drawdown"
          current={data.drawdown_pct}
          limit={data.drawdown_limit_pct}
          displayCurrent={displayDrawdown}
          displayLimit={displayDrawdownLimit}
          pct={drawdownPct}
        />
      </div>
    </div>
  );
}
