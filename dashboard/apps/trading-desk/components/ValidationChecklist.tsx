"use client";

import React, { useEffect, useState, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchEngine } from "@/lib/api";
import {
  fetchHonestTrades,
  equityCurve,
  maxDrawdownPct,
  dedupCaveat,
  type HonestTradeSet,
} from "@/lib/honestTrades";

const REFRESH_MS = 300_000; // 5 minutes

// ── Types ─────────────────────────────────────────────────────────────────────

interface TradingDaysData {
  trading_days_completed?: number;
  days_traded?: number;
  completed_days?: number;
  total_days?: number;
  [key: string]: unknown;
}

// Canonical gate targets, sourced from engine/analytics/validation_metrics.py's
// TARGETS (served verbatim by GET /validation/targets). min_trades is read from
// here rather than hardcoded so this checklist can never drift from the
// engine's real go/no-go bar again (T0-05: was hardcoded to a stale 30 while
// the engine gate requires 60).
interface ValidationTargetsResponse {
  targets?: {
    min_trades?: number;
    [key: string]: unknown;
  };
  [key: string]: unknown;
}

type CriterionStatus = "PASS" | "FAIL" | "PENDING";

interface Criterion {
  name: string;
  target: string;
  current: string;
  status: CriterionStatus;
  pass: boolean | null;
}

interface ValidationState {
  criteria: Criterion[];
  loading: boolean;
  error: string | null;
  lastUpdated: Date | null;
  caveat: string | null;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * Max drawdown as a percentage, derived from the honest deduped equity curve.
 * Returns the largest peak-to-trough drop as % of the running equity peak.
 * Returns null when the equity curve has no points or the peak never goes above 0.
 */
function computeMaxDrawdownFromHonest(set: HonestTradeSet): number | null {
  // null distinguishes "no data" from a real 0% in the checklist; otherwise
  // defer to the canonical helper (same running-peak math as the old inline loop).
  if (equityCurve(set.trades).length === 0) return null;
  return maxDrawdownPct(set.trades) * 100;
}

function fmt(value: number | null | undefined, decimals = 2): string {
  if (value === null || value === undefined) return "—";
  return value.toFixed(decimals);
}

// ── Main Component ────────────────────────────────────────────────────────────

export function ValidationChecklist() {
  const [state, setState] = useState<ValidationState>({
    criteria: [],
    loading: true,
    error: null,
    lastUpdated: null,
    caveat: null,
  });

  const fetchData = useCallback(async () => {
    setState((prev) => ({ ...prev, loading: prev.criteria.length === 0, error: null }));

    const [honestResult, daysResult, targetsResult] = await Promise.allSettled([
      fetchHonestTrades(),
      fetchEngine<TradingDaysData>("/portfolio/stats/trading-days"),
      fetchEngine<ValidationTargetsResponse>("/validation/targets"),
    ]);

    // ── Extract honest deduped metrics ───────────────────────────────────────
    let profitFactor: number | null = null;
    let winRate: number | null = null;
    let totalTrades: number | null = null;
    let maxDrawdown: number | null = null;
    let caveat: string | null = null;
    let honestOk = false;

    if (honestResult.status === "fulfilled") {
      const set = honestResult.value;
      profitFactor = set.profitFactor;
      winRate = set.winRate * 100; // convert 0..1 to percentage
      totalTrades = set.trades.length;
      maxDrawdown = computeMaxDrawdownFromHonest(set);
      caveat = dedupCaveat(set);
      honestOk = true;
    }

    // ── Extract canonical min-trades target (engine TARGETS, never hardcoded) ─
    let minTradesTarget: number | null = null;
    if (targetsResult.status === "fulfilled") {
      const t = targetsResult.value?.targets?.min_trades;
      if (typeof t === "number") minTradesTarget = t;
    }

    // ── Extract trading days (still from engine — not in honest record) ──────
    let tradingDays: number | null = null;
    if (daysResult.status === "fulfilled") {
      const d = daysResult.value;
      tradingDays =
        typeof d.trading_days_completed === "number"
          ? d.trading_days_completed
          : typeof d.days_traded === "number"
          ? d.days_traded
          : typeof d.completed_days === "number"
          ? d.completed_days
          : null;
    }

    // ── Build criteria list ──────────────────────────────────────────────────
    const criteria: Criterion[] = [
      {
        name: "Profit Factor",
        target: "≥ 2.0",
        current:
          !honestOk ? "No data" :
          profitFactor !== null ? `${fmt(profitFactor)} vs ≥2.0` : "No data",
        status: profitFactor === null ? "PENDING" : profitFactor >= 2.0 ? "PASS" : "FAIL",
        pass: profitFactor === null ? null : profitFactor >= 2.0,
      },
      {
        // Annualized Sharpe is NOT in the deduped honest record — only fields
        // available are: symbol, direction, entry_time, exit_time, pnl_usd, grade.
        // Surfacing "—" prevents a fabricated PASS. Gating on this criterion is
        // suspended until a time-series source is wired.
        name: "Sharpe Ratio",
        target: "≥ 1.5",
        current: "— (not computed from deduped record)",
        status: "PENDING",
        pass: null,
      },
      {
        name: "Win Rate",
        target: "≥ 55%",
        current:
          !honestOk ? "No data" :
          winRate !== null ? `${fmt(winRate, 1)}% vs ≥55%` : "No data",
        status: winRate === null ? "PENDING" : winRate >= 55 ? "PASS" : "FAIL",
        pass: winRate === null ? null : winRate >= 55,
      },
      {
        name: "Total Trades",
        target: minTradesTarget !== null ? `≥ ${minTradesTarget}` : "≥ —",
        current:
          !honestOk ? "No data" :
          totalTrades === null ? "No data" :
          minTradesTarget !== null ? `${totalTrades} vs ≥${minTradesTarget}` : `${totalTrades}`,
        status:
          totalTrades === null || minTradesTarget === null
            ? "PENDING"
            : totalTrades >= minTradesTarget
            ? "PASS"
            : "FAIL",
        pass:
          totalTrades === null || minTradesTarget === null
            ? null
            : totalTrades >= minTradesTarget,
      },
      {
        name: "Max Drawdown",
        target: "< 15%",
        current:
          !honestOk ? "No data" :
          maxDrawdown === null ? "No data" : `${fmt(maxDrawdown, 1)}% vs <15%`,
        status:
          !honestOk || maxDrawdown === null
            ? "PENDING"
            : maxDrawdown < 15
            ? "PASS"
            : "FAIL",
        pass:
          !honestOk || maxDrawdown === null
            ? null
            : maxDrawdown < 15,
      },
      {
        name: "Trading Days",
        target: "≥ 30 days",
        current:
          tradingDays !== null ? `${tradingDays} days vs ≥30` : "No data",
        status:
          daysResult.status !== "fulfilled" || tradingDays === null
            ? "PENDING"
            : tradingDays >= 30
            ? "PASS"
            : "FAIL",
        pass:
          daysResult.status !== "fulfilled" || tradingDays === null
            ? null
            : tradingDays >= 30,
      },
    ];

    setState({
      criteria,
      loading: false,
      error: null,
      lastUpdated: new Date(),
      caveat,
    });
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, REFRESH_MS);
    return () => clearInterval(interval);
  }, [fetchData]);

  // ── Derived counts ────────────────────────────────────────────────────────
  const passCount = state.criteria.filter((c) => c.pass === true).length;
  const totalCount = state.criteria.length;

  const overallVariant =
    passCount === totalCount && totalCount > 0
      ? "bull"
      : passCount >= 4
      ? "warn"
      : "bear";

  const overallLabel =
    passCount === totalCount && totalCount > 0
      ? "READY FOR LIVE"
      : passCount >= 4
      ? "IN PROGRESS"
      : "NOT READY";

  // ── Row status colors ─────────────────────────────────────────────────────
  function statusColor(status: CriterionStatus): string {
    if (status === "PASS") return "text-green-400";
    if (status === "FAIL") return "text-red-400";
    return "text-muted-foreground";
  }

  function statusIcon(status: CriterionStatus): string {
    if (status === "PASS") return "✓";
    if (status === "FAIL") return "✗";
    return "–";
  }

  function iconColor(status: CriterionStatus): string {
    if (status === "PASS") return "text-green-400";
    if (status === "FAIL") return "text-red-400";
    return "text-muted-foreground";
  }

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <Card className="border-border/50 bg-card">
      <CardHeader className="pb-3">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <CardTitle className="text-base font-semibold tracking-tight">
            Go/No-Go Validation Checklist
          </CardTitle>
          <div className="flex items-center gap-3">
            {!state.loading && state.criteria.length > 0 && (
              <Badge variant={overallVariant} className="text-xs px-3 py-1 font-mono tracking-wider">
                {overallLabel}
              </Badge>
            )}
            {state.loading && (
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <div className="h-3.5 w-3.5 rounded-full border-2 border-accent border-t-transparent animate-spin" />
                Loading...
              </div>
            )}
          </div>
        </div>
        {!state.loading && state.criteria.length > 0 && (
          <div className="mt-1">
            <span className="text-2xl font-bold font-mono tabular-nums text-foreground">
              {passCount}/{totalCount}
            </span>
            <span className="text-sm text-muted-foreground ml-2">Criteria Met</span>
          </div>
        )}
      </CardHeader>

      <CardContent>
        {state.loading && state.criteria.length === 0 ? (
          <div className="flex items-center justify-center py-8">
            <div className="h-5 w-5 rounded-full border-2 border-accent border-t-transparent animate-spin mr-3" />
            <span className="text-sm text-muted-foreground">Fetching validation data...</span>
          </div>
        ) : (
          <div className="space-y-1">
            {/* Header row */}
            <div className="grid grid-cols-[2rem_1fr_1fr_3.5rem] gap-2 px-3 py-1.5 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground border-b border-border/40">
              <span className="text-center">#</span>
              <span>Criterion</span>
              <span>Value vs Target</span>
              <span className="text-right">Status</span>
            </div>

            {/* Criterion rows */}
            {state.criteria.map((criterion, idx) => (
              <div
                key={criterion.name}
                className="grid grid-cols-[2rem_1fr_1fr_3.5rem] gap-2 px-3 py-2.5 rounded-lg hover:bg-muted/20 transition-colors items-center"
              >
                {/* Icon */}
                <span className={`text-center text-base font-bold leading-none ${iconColor(criterion.status)}`}>
                  {statusIcon(criterion.status)}
                </span>

                {/* Name */}
                <span className="text-sm font-medium text-foreground truncate">
                  {criterion.name}
                </span>

                {/* Value vs Target */}
                <span className={`text-sm font-mono tabular-nums truncate ${statusColor(criterion.status)}`}>
                  {criterion.current}
                </span>

                {/* Status badge */}
                <span className={`text-right text-xs font-bold font-mono tracking-wide ${statusColor(criterion.status)}`}>
                  {criterion.status}
                </span>
              </div>
            ))}

            {/* Footer note */}
            <div className="mt-4 pt-3 border-t border-border/40 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-1">
              <div className="flex flex-col gap-0.5">
                <p className="text-xs text-muted-foreground">
                  Paper trading target: April–May 2026 &nbsp;|&nbsp; Live trading: June 2026
                </p>
                {state.caveat && (
                  <p className="text-[10px] text-warn font-mono">
                    {state.caveat} · Sharpe suspended (not computable from deduped record)
                  </p>
                )}
              </div>
              {state.lastUpdated && (
                <p className="text-[10px] text-muted-foreground font-mono">
                  Updated {state.lastUpdated.toLocaleTimeString()}
                </p>
              )}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
