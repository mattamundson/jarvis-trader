"use client";

import useSWR from "swr";
import { CheckCircle2, AlertTriangle, XCircle, Clock } from "lucide-react";
import {
  fetchForwardTestStatus,
  type ForwardTestStatusResponse,
} from "@/lib/api";
import { ResultLabel } from "@/components/ResultLabel";

// Active paper instruments (Tier-3 auth 2026-05-24). MCL/MNQ are HALTED and
// deliberately absent — showing a forward-test row for a halted symbol would
// read as progress toward promotion.
const ACTIVE_SYMBOLS = ["MES", "MGC"] as const;

const REFRESH_MS = 60_000;

/**
 * Evidence-to-live gate, amo-arbitrage style: the backtest gate verdict shown
 * BESIDE the live paper record it is being forward-tested against, plus a
 * progress bar of evidence gathered toward the canonical promotion
 * thresholds. Reads /forward-test/status (which recomputes nothing) — the
 * binding decision stays in the engine's live-readiness module.
 */
function statusChip(s: ForwardTestStatusResponse["status"]) {
  switch (s) {
    case "pass":
      return { icon: CheckCircle2, cls: "text-bull", label: "PASS" };
    case "fail":
      return { icon: XCircle, cls: "text-bear", label: "FAIL" };
    case "in_progress":
      return { icon: Clock, cls: "text-warn", label: "IN PROGRESS" };
    default:
      return { icon: AlertTriangle, cls: "text-muted-foreground", label: "NOT RUN" };
  }
}

function SymbolRow({ symbol }: { symbol: string }) {
  const { data, error } = useSWR<ForwardTestStatusResponse>(
    `/forward-test/status?symbol=${symbol}`,
    () => fetchForwardTestStatus(symbol),
    { refreshInterval: REFRESH_MS, shouldRetryOnError: false }
  );

  if (error) {
    return (
      <div className="rounded-lg border border-border/60 bg-muted/20 px-3 py-2 text-xs text-muted-foreground">
        {symbol}: forward-test status unreachable (engine offline or endpoint
        not deployed) — no verdict shown.
      </div>
    );
  }
  if (!data) {
    return (
      <div className="rounded-lg border border-border/60 bg-muted/20 px-3 py-2 text-xs text-muted-foreground animate-pulse">
        {symbol}: loading forward-test status…
      </div>
    );
  }

  const chip = statusChip(data.status);
  const Icon = chip.icon;
  const minTrades = data.thresholds.min_trades ?? 0;
  const minDays = data.thresholds.min_days ?? 0;
  const minPf = data.thresholds.min_pf;
  const tradeProgress =
    minTrades > 0 ? Math.min(100, (data.n_closed / minTrades) * 100) : 0;
  const dayProgress =
    minDays > 0
      ? Math.min(100, ((data.days_elapsed ?? 0) / minDays) * 100)
      : 0;
  const pfLabel = data.forward_pf_infinite
    ? "inf (no losers)"
    : data.forward_pf != null
    ? data.forward_pf.toFixed(2)
    : "—";

  return (
    <div className="rounded-lg border border-border bg-card/50 p-3 space-y-2">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <Icon className={`h-4 w-4 shrink-0 ${chip.cls}`} />
          <span className="text-sm font-semibold text-foreground">{symbol}</span>
          <span className={`text-[10px] font-bold ${chip.cls}`}>{chip.label}</span>
          {data.stale && (
            <span className="text-[10px] text-warn font-medium">
              STALE ({data.as_of_age_days}d old)
            </span>
          )}
        </div>
        <div className="flex items-center gap-3 text-xs font-mono shrink-0">
          <span className="text-muted-foreground">
            Fwd PF{" "}
            <span className="text-foreground">{pfLabel}</span>
            {minPf != null && (
              <span className="text-muted-foreground/70"> / ≥{minPf}</span>
            )}
          </span>
          <ResultLabel kind="paper" />
        </div>
      </div>

      {/* Evidence progress toward the promotion thresholds */}
      <div className="grid grid-cols-2 gap-3">
        <div>
          <div className="flex justify-between text-[10px] text-muted-foreground mb-0.5">
            <span>Closed trades</span>
            <span className="font-mono">
              {data.n_closed}/{minTrades || "?"}
            </span>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
            <div
              className={`h-full rounded-full ${
                tradeProgress >= 100 ? "bg-bull" : "bg-accent"
              }`}
              style={{ width: `${tradeProgress}%` }}
            />
          </div>
        </div>
        <div>
          <div className="flex justify-between text-[10px] text-muted-foreground mb-0.5">
            <span>Days elapsed</span>
            <span className="font-mono">
              {data.days_elapsed ?? 0}/{minDays || "?"}
            </span>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
            <div
              className={`h-full rounded-full ${
                dayProgress >= 100 ? "bg-bull" : "bg-accent"
              }`}
              style={{ width: `${dayProgress}%` }}
            />
          </div>
        </div>
      </div>

      <p className="text-[10px] text-muted-foreground leading-snug">
        {data.detail}
        {data.gate_verdict && (
          <>
            {" "}
            · gate verdict{" "}
            <span className="font-mono text-foreground/80">
              {data.gate_verdict}
            </span>
            {data.gate_family && (
              <span className="font-mono"> ({data.gate_family})</span>
            )}{" "}
            <ResultLabel kind="backtest" className="ml-0.5" />
          </>
        )}
      </p>
    </div>
  );
}

export function ForwardVsBacktestCard() {
  return (
    <div className="rounded-xl border border-border bg-card p-4 space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-semibold text-foreground">
          Evidence-to-Live Gate
        </span>
        <span className="text-[10px] text-muted-foreground">
          forward record vs backtest verdict · promotion is manual
        </span>
      </div>
      <div className="space-y-2">
        {ACTIVE_SYMBOLS.map((s) => (
          <SymbolRow key={s} symbol={s} />
        ))}
      </div>
    </div>
  );
}
