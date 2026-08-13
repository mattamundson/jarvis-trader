"use client";

import { EXECUTION_STATE_KEY, HEALTH_KEY, POLL_INTERVAL } from "@/lib/polling-config";

import useSWR from "swr";
import { ShieldAlert, ShieldCheck, ShieldOff } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { HealthResponse } from "@/lib/api";
import { fetcher, formatPct, formatUsd, UnreachableNote } from "./shared";

// Mirrors the live shape returned by engine/routers/safety_router.py
// get_safety_status() — narrower than the (partially stale) SafetyStatus
// interface in lib/api.ts, so this panel defines its own accurate type
// rather than trusting fields that endpoint does not actually return.
interface SafetyStatusLive {
  kill_switch_active: boolean;
  kill_switch_reason: string | null;
  daily_pnl: number;
  daily_pnl_pct: number;
  daily_limit_pct: number;
  daily_limit_breached: boolean;
  drawdown_pct: number;
  drawdown_limit_pct: number;
  drawdown_breached: boolean;
  portfolio_equity: number;
  current_balance: number;
  consecutive_losses?: number | null;
}

interface PaperPositionLite {
  quantity?: number;
}

interface PaperPositionsResponse {
  positions: PaperPositionLite[];
  count: number;
}

function RiskBar({ pctOfLimit, breached }: { pctOfLimit: number; breached: boolean }) {
  const clamped = Math.min(100, Math.max(0, pctOfLimit * 100));
  const color = breached ? "bg-bear" : pctOfLimit >= 0.75 ? "bg-warn" : "bg-bull";
  return (
    <div className="h-2 w-full rounded-full bg-muted overflow-hidden">
      <div
        className={`h-full rounded-full transition-all duration-500 ${color}`}
        style={{ width: `${clamped}%` }}
      />
    </div>
  );
}

export function RiskSafetyPanel() {
  const {
    data: safety,
    error: safetyError,
    isLoading: safetyLoading,
  } = useSWR<SafetyStatusLive>(EXECUTION_STATE_KEY, fetcher, { refreshInterval: POLL_INTERVAL.STATUS });

  const { data: health } = useSWR<HealthResponse>(HEALTH_KEY, fetcher, { refreshInterval: POLL_INTERVAL.STATUS });

  const { data: positions } = useSWR<PaperPositionsResponse>(
    "/portfolio/paper/positions",
    fetcher,
    { refreshInterval: POLL_INTERVAL.STATUS }
  );

  const contractsHeld = (positions?.positions ?? []).reduce(
    (sum, p) => sum + Math.abs(Number(p.quantity ?? 0)),
    0
  );

  const dailyWarn = (safety?.daily_pnl_pct ?? 0) <= -0.015;
  const state: "SAFE" | "WARNING" | "KILLED" = safety?.kill_switch_active
    ? "KILLED"
    : dailyWarn || safety?.drawdown_breached
      ? "WARNING"
      : "SAFE";

  const dailyLimitPct = Math.abs(safety?.daily_limit_pct ?? 0.02);
  const dailyPnlPctAbs = Math.abs(safety?.daily_pnl_pct ?? 0);
  const dailyPctOfLimit = dailyLimitPct > 0 ? dailyPnlPctAbs / dailyLimitPct : 0;

  const ddLimitPct = Math.abs(safety?.drawdown_limit_pct ?? 0.1);
  const ddPctAbs = Math.abs(safety?.drawdown_pct ?? 0);
  const ddPctOfLimit = ddLimitPct > 0 ? ddPctAbs / ddLimitPct : 0;

  const badgeConfig = {
    SAFE: { label: "SAFE", cls: "bg-bull/15 border-bull/25 text-bull", Icon: ShieldCheck },
    WARNING: { label: "WARNING", cls: "bg-warn/15 border-warn/25 text-warn", Icon: ShieldAlert },
    KILLED: { label: "KILL SWITCH ACTIVE", cls: "bg-bear/15 border-bear/25 text-bear", Icon: ShieldOff },
  }[state];

  return (
    <div className="rounded-xl border-2 border-border bg-card p-5 space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
            Risk &amp; Safety
          </h2>
          <p className="text-xs text-muted-foreground mt-0.5">
            Kill switch, daily loss halt, drawdown halt — most prominent panel
          </p>
        </div>

        {safetyError ? (
          <div className="flex items-center gap-2 rounded-full bg-bear/15 border border-bear/25 px-4 py-2">
            <ShieldOff className="h-5 w-5 text-bear" />
            <span className="text-sm font-bold text-bear tracking-wide">SAFETY STATUS UNREACHABLE</span>
          </div>
        ) : (
          <div className={`flex items-center gap-2 rounded-full border px-4 py-2 ${badgeConfig.cls}`}>
            <badgeConfig.Icon className="h-5 w-5" />
            <span className="text-sm font-bold tracking-wide">
              {safetyLoading ? "LOADING…" : `[${badgeConfig.label}]`}
            </span>
          </div>
        )}
      </div>

      {safetyError ? (
        <UnreachableNote endpoint="/safety/status" />
      ) : (
        <>
          {safety?.kill_switch_active && safety?.kill_switch_reason && (
            <p className="text-xs text-bear font-mono">Reason: {safety.kill_switch_reason}</p>
          )}

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {/* Daily P&L vs daily halt */}
            <div className="space-y-1.5">
              <div className="flex items-baseline justify-between">
                <span className="text-xs text-muted-foreground">Daily P&amp;L</span>
                <span
                  className={`font-mono text-sm font-semibold ${(safety?.daily_pnl ?? 0) >= 0 ? "text-bull" : "text-bear"}`}
                >
                  {formatUsd(safety?.daily_pnl)} ({formatPct(safety?.daily_pnl_pct)})
                </span>
              </div>
              <RiskBar pctOfLimit={dailyPctOfLimit} breached={!!safety?.daily_limit_breached} />
              <p className="text-[10px] text-muted-foreground">
                Halt at {formatPct(-dailyLimitPct)} daily P&amp;L
              </p>
            </div>

            {/* Drawdown vs drawdown halt */}
            <div className="space-y-1.5">
              <div className="flex items-baseline justify-between">
                <span className="text-xs text-muted-foreground">Drawdown</span>
                <span
                  className={`font-mono text-sm font-semibold ${ddPctAbs > 0 ? "text-bear" : "text-foreground"}`}
                >
                  {formatPct(safety?.drawdown_pct)}
                </span>
              </div>
              <RiskBar pctOfLimit={ddPctOfLimit} breached={!!safety?.drawdown_breached} />
              <p className="text-[10px] text-muted-foreground">
                Halt at {formatPct(-ddLimitPct)} drawdown
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-3 border-t border-border pt-3">
            <div className="flex items-center gap-1.5 rounded-lg border border-border bg-muted/30 px-3 py-1.5">
              <span className="text-[11px] text-muted-foreground">Live Trading</span>
              <Badge variant={health?.live_trading ? "bear" : "info"}>
                {health ? (health.live_trading ? "LIVE" : "PAPER MODE") : "—"}
              </Badge>
            </div>
            <div className="flex items-center gap-1.5 rounded-lg border border-border bg-muted/30 px-3 py-1.5">
              <span className="text-[11px] text-muted-foreground">Contracts Held</span>
              <span className="font-mono text-xs font-semibold text-foreground">{contractsHeld}</span>
            </div>
            <div className="flex items-center gap-1.5 rounded-lg border border-border bg-muted/30 px-3 py-1.5">
              <span className="text-[11px] text-muted-foreground">Portfolio Equity</span>
              <span className="font-mono text-xs font-semibold text-foreground">
                {safety ? formatUsd(safety.portfolio_equity).replace("+", "") : "—"}
              </span>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
