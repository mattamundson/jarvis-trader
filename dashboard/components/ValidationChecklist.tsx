"use client";

import React, { useEffect, useState, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

const ENGINE_URL = process.env.NEXT_PUBLIC_ENGINE_URL || "http://localhost:8010";
const STARTING_BALANCE = 10_000;
const REFRESH_MS = 300_000; // 5 minutes

// ── Types ─────────────────────────────────────────────────────────────────────

interface PerformanceData {
  profit_factor?: number;
  sharpe_ratio?: number;
  win_rate?: number;
  total_trades?: number;
}

interface DailyPnlEntry {
  cumulative_pnl?: number;
  pnl?: number;
  date?: string;
}

interface TradingDaysData {
  trading_days_completed?: number;
  days_traded?: number;
  completed_days?: number;
  total_days?: number;
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
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function computeMaxDrawdown(entries: DailyPnlEntry[]): number | null {
  if (!entries || entries.length === 0) return null;

  // Build cumulative PnL series — prefer cumulative_pnl field, else sum pnl
  const series: number[] = [];
  let running = 0;
  for (const entry of entries) {
    if (typeof entry.cumulative_pnl === "number") {
      series.push(entry.cumulative_pnl);
    } else if (typeof entry.pnl === "number") {
      running += entry.pnl;
      series.push(running);
    }
  }

  if (series.length === 0) return null;

  let peak = series[0];
  let maxDD = 0;

  for (const val of series) {
    if (val > peak) peak = val;
    const dd = (peak - val) / STARTING_BALANCE;
    if (dd > maxDD) maxDD = dd;
  }

  return maxDD * 100; // return as percentage
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
  });

  const fetchData = useCallback(async () => {
    setState((prev) => ({ ...prev, loading: prev.criteria.length === 0, error: null }));

    const [perfResult, pnlResult, daysResult] = await Promise.allSettled([
      fetch(`${ENGINE_URL}/analytics/performance`).then((r) => {
        if (!r.ok) throw new Error(`/analytics/performance ${r.status}`);
        return r.json() as Promise<PerformanceData>;
      }),
      fetch(`${ENGINE_URL}/portfolio/history/daily-pnl?limit=90`).then((r) => {
        if (!r.ok) throw new Error(`/portfolio/history/daily-pnl ${r.status}`);
        return r.json() as Promise<DailyPnlEntry[] | { data?: DailyPnlEntry[] }>;
      }),
      fetch(`${ENGINE_URL}/portfolio/stats/trading-days`).then((r) => {
        if (!r.ok) throw new Error(`/portfolio/stats/trading-days ${r.status}`);
        return r.json() as Promise<TradingDaysData>;
      }),
    ]);

    // ── Extract performance metrics ──────────────────────────────────────────
    const perf: PerformanceData =
      perfResult.status === "fulfilled" ? perfResult.value : {};

    const profitFactor = typeof perf.profit_factor === "number" ? perf.profit_factor : null;
    const sharpeRatio = typeof perf.sharpe_ratio === "number" ? perf.sharpe_ratio : null;
    const winRateRaw = typeof perf.win_rate === "number" ? perf.win_rate : null;
    const winRate =
      winRateRaw !== null ? (winRateRaw < 1 ? winRateRaw * 100 : winRateRaw) : null;
    const totalTrades = typeof perf.total_trades === "number" ? perf.total_trades : null;

    // ── Extract daily PnL ────────────────────────────────────────────────────
    let pnlEntries: DailyPnlEntry[] = [];
    if (pnlResult.status === "fulfilled") {
      const raw = pnlResult.value;
      if (Array.isArray(raw)) {
        pnlEntries = raw;
      } else if (raw && typeof raw === "object" && Array.isArray((raw as { data?: DailyPnlEntry[] }).data)) {
        pnlEntries = (raw as { data: DailyPnlEntry[] }).data;
      }
    }
    const maxDrawdown = computeMaxDrawdown(pnlEntries);

    // ── Extract trading days ─────────────────────────────────────────────────
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
          profitFactor !== null ? `${fmt(profitFactor)} vs ≥2.0` : "No data",
        status: profitFactor === null ? "PENDING" : profitFactor >= 2.0 ? "PASS" : "FAIL",
        pass: profitFactor === null ? null : profitFactor >= 2.0,
      },
      {
        name: "Sharpe Ratio",
        target: "≥ 1.5",
        current:
          sharpeRatio !== null ? `${fmt(sharpeRatio)} vs ≥1.5` : "No data",
        status: sharpeRatio === null ? "PENDING" : sharpeRatio >= 1.5 ? "PASS" : "FAIL",
        pass: sharpeRatio === null ? null : sharpeRatio >= 1.5,
      },
      {
        name: "Win Rate",
        target: "≥ 55%",
        current:
          winRate !== null ? `${fmt(winRate, 1)}% vs ≥55%` : "No data",
        status: winRate === null ? "PENDING" : winRate >= 55 ? "PASS" : "FAIL",
        pass: winRate === null ? null : winRate >= 55,
      },
      {
        name: "Total Trades",
        target: "≥ 30",
        current:
          totalTrades !== null ? `${totalTrades} vs ≥30` : "No data",
        status: totalTrades === null ? "PENDING" : totalTrades >= 30 ? "PASS" : "FAIL",
        pass: totalTrades === null ? null : totalTrades >= 30,
      },
      {
        name: "Max Drawdown",
        target: "< 15%",
        current:
          pnlResult.status !== "fulfilled"
            ? "No data"
            : maxDrawdown === null
            ? "No data"
            : `${fmt(maxDrawdown, 1)}% vs <15%`,
        status:
          pnlResult.status !== "fulfilled" || maxDrawdown === null
            ? "PENDING"
            : maxDrawdown < 15
            ? "PASS"
            : "FAIL",
        pass:
          pnlResult.status !== "fulfilled" || maxDrawdown === null
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
              <p className="text-xs text-muted-foreground">
                Paper trading target: April–May 2026 &nbsp;|&nbsp; Live trading: June 2026
              </p>
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
