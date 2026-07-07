"use client";

import React from "react";
import useSWR from "swr";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { fetchEngine } from "@/lib/api";
import { cn } from "@/lib/utils";

// ── Constants ─────────────────────────────────────────────────────────────────

const REFRESH_MS = 2 * 60 * 1000; // 2 minutes

// ── Types ─────────────────────────────────────────────────────────────────────

interface PaperPhaseSummary {
  phase: string;
  start_date: string;
  starting_balance: number;
  current_balance: number;
  total_return_pct: number;
  total_pnl: number;
  trading_days: number;
  target_trading_days: number;
  trades_completed: number;
  validation_status: string;
}

// ── Fetcher ───────────────────────────────────────────────────────────────────

const fetchPaperPhaseSummary = () =>
  fetchEngine<PaperPhaseSummary>("/portfolio/stats/paper-phase-summary");

// ── Component ─────────────────────────────────────────────────────────────────

export function PaperBalanceWidget() {
  const { data, isLoading, error } = useSWR<PaperPhaseSummary>(
    "portfolio/stats/paper-phase-summary",
    fetchPaperPhaseSummary,
    { refreshInterval: REFRESH_MS }
  );

  // Loading state — skeleton pulse
  if (isLoading) {
    return (
      <Card>
        <CardHeader className="flex flex-row justify-between items-center">
          <CardTitle>Paper Account</CardTitle>
          <div className="h-5 w-24 bg-muted rounded-full animate-pulse" />
        </CardHeader>
        <CardContent>
          <div className="text-center py-3 animate-pulse">
            <div className="h-3 w-28 bg-muted rounded mx-auto mb-2" />
            <div className="h-10 w-44 bg-muted rounded mx-auto mb-2" />
            <div className="h-3 w-32 bg-muted rounded mx-auto" />
          </div>
          <div className="grid grid-cols-3 gap-3 mt-2 animate-pulse">
            {[0, 1, 2].map((i) => (
              <div key={i} className="text-center space-y-1">
                <div className="h-3 w-14 bg-muted rounded mx-auto" />
                <div className="h-4 w-16 bg-muted rounded mx-auto" />
              </div>
            ))}
          </div>
          <div className="mt-3 animate-pulse space-y-1">
            <div className="h-3 w-full bg-muted rounded" />
            <div className="h-2 w-full bg-muted rounded-full" />
            <div className="h-3 w-24 bg-muted rounded" />
          </div>
        </CardContent>
      </Card>
    );
  }

  // Error state — fallback message
  if (error || !data) {
    return (
      <Card>
        <CardHeader className="flex flex-row justify-between items-center">
          <CardTitle>Paper Account</CardTitle>
          <Badge variant="warn">Unavailable</Badge>
        </CardHeader>
        <CardContent>
          <p className="text-xs text-muted-foreground text-center py-4">
            Unable to load paper phase summary. Engine may be offline.
          </p>
        </CardContent>
      </Card>
    );
  }

  // Derived values
  const balance = data.current_balance ?? 0;
  const startingBalance = data.starting_balance > 0 ? data.starting_balance : 10000.0;
  const returnPct = data.total_return_pct ?? 0;
  // Total P&L = broker balance delta (current − starting). The raw `total_pnl`
  // field is re-summed from the trade record and over-counts re-logged winners
  // (fabricated inflation); the balance is broker-computed and trustworthy, so
  // derive P&L from it — this also keeps it consistent with the return% badge.
  const totalPnl = balance - startingBalance;
  const tradingDays = data.trading_days ?? 0;
  const targetDays = data.target_trading_days ?? 30;
  const tradesCompleted = data.trades_completed ?? 0;
  const progressPct = Math.min(100, Math.round((tradingDays / targetDays) * 100));

  return (
    <Card>
      <CardHeader className="flex flex-row justify-between items-center">
        <CardTitle>Paper Account</CardTitle>
        <Badge variant={returnPct >= 0 ? "bull" : "bear"}>
          {returnPct >= 0 ? "+" : ""}
          {returnPct.toFixed(2)}% Return
        </Badge>
      </CardHeader>
      <CardContent>
        {/* Large balance display */}
        <div className="text-center py-3">
          <p className="text-xs text-muted-foreground mb-1">Current Balance</p>
          <p
            className={cn(
              "text-4xl font-mono font-bold",
              balance > startingBalance
                ? "text-green-400"
                : balance < startingBalance
                ? "text-red-400"
                : ""
            )}
          >
            $
            {balance.toLocaleString("en-US", {
              minimumFractionDigits: 2,
              maximumFractionDigits: 2,
            })}
          </p>
          <p className="text-sm text-muted-foreground mt-1">
            Started: ${startingBalance.toLocaleString()}
          </p>
        </div>

        {/* Stats row */}
        <div className="grid grid-cols-3 gap-3 mt-2">
          <div className="text-center">
            <p className="text-xs text-muted-foreground">Total P&L</p>
            <p
              className={cn(
                "text-sm font-mono font-medium",
                totalPnl >= 0 ? "text-green-400" : "text-red-400"
              )}
            >
              {totalPnl >= 0 ? "+" : ""}${Math.abs(totalPnl).toFixed(2)}
            </p>
          </div>
          <div className="text-center">
            <p className="text-xs text-muted-foreground">Trading Days</p>
            <p className="text-sm font-mono font-medium">
              {tradingDays} / {targetDays}
            </p>
          </div>
          <div className="text-center">
            <p className="text-xs text-muted-foreground">Trades</p>
            <p className="text-sm font-mono font-medium">{tradesCompleted}</p>
          </div>
        </div>

        {/* Progress toward 30-day target */}
        <div className="mt-3">
          <div className="flex justify-between text-xs text-muted-foreground mb-1">
            <span>Validation Progress</span>
            <span>{progressPct}%</span>
          </div>
          {/* Inline progress bar without importing Progress component */}
          <div className="h-2 w-full rounded-full bg-muted overflow-hidden">
            <div
              className="h-full rounded-full bg-accent transition-all duration-500"
              style={{ width: `${progressPct}%` }}
            />
          </div>
          <p className="text-xs text-muted-foreground mt-1">
            {targetDays - tradingDays > 0
              ? `${targetDays - tradingDays} days remaining`
              : "Target reached!"}
          </p>
        </div>

        {/* Balance, return% and Total P&L are all broker-derived (balance delta),
            not a re-summed trade list, so they are dedup-safe. Only the "Trades"
            COUNT still comes from the raw engine record and may include re-logged
            duplicates — see the deduped stats widgets for the honest trade count. */}
        <p className="text-[10px] text-muted-foreground/60 mt-2">
          Balance, return &amp; P&amp;L from broker account · trade count may include re-logs
        </p>
        <p className="text-xs text-muted-foreground mt-1">Refreshes every 2m</p>
      </CardContent>
    </Card>
  );
}
