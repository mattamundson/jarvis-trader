"use client";

import React from "react";
import useSWR from "swr";
import { RefreshCw } from "lucide-react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchEODSummary, type EODSummary } from "@/lib/api";

const POLLING_INTERVAL_MS = 30_000; // 30 seconds

const fetcher = (): Promise<EODSummary> => fetchEODSummary();

function getStatusColor(status: "on_track" | "at_risk" | "insufficient_data"): string {
  switch (status) {
    case "on_track":
      return "text-bull";
    case "at_risk":
      return "text-warn";
    case "insufficient_data":
      return "text-muted-foreground";
  }
}

function getStatusBadgeVariant(
  status: "on_track" | "at_risk" | "insufficient_data"
): "bull" | "warn" | "info" {
  switch (status) {
    case "on_track":
      return "bull";
    case "at_risk":
      return "warn";
    case "insufficient_data":
      return "info";
  }
}

function getStatusLabel(status: "on_track" | "at_risk" | "insufficient_data"): string {
  switch (status) {
    case "on_track":
      return "ON TRACK";
    case "at_risk":
      return "AT RISK";
    case "insufficient_data":
      return "INSUFFICIENT DATA";
  }
}

interface GateBarProps {
  label: string;
  current: number | null;
  target: number;
  unit?: string;
}

function GateBar({ label, current, target, unit = "" }: GateBarProps) {
  const currentVal = current ?? 0;
  const percentage = Math.min(100, (currentVal / target) * 100);
  const isMetTarget = current !== null && current >= target;
  const isHalfTarget = current !== null && current >= target * 0.5;

  let barColor = "bg-red-500";
  if (isMetTarget) {
    barColor = "bg-green-500";
  } else if (isHalfTarget) {
    barColor = "bg-yellow-500";
  }

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-xs">
        <span className="text-muted-foreground">{label}</span>
        <span className="font-mono font-semibold text-foreground">
          {current === null ? "—" : `${current.toFixed(2)}${unit}`}
        </span>
      </div>
      <div className="relative h-2 w-full bg-muted rounded overflow-hidden">
        <div className={`h-full ${barColor} transition-all`} style={{ width: `${percentage}%` }} />
      </div>
      <div className="flex items-center justify-between text-[10px] text-muted-foreground">
        <span>Target: {target.toFixed(2)}{unit}</span>
        <span>{Math.min(percentage, 100).toFixed(0)}%</span>
      </div>
    </div>
  );
}

export function EODSummaryWidget() {
  const { data, error, isLoading, mutate } = useSWR<EODSummary>(
    "eod-summary",
    fetcher,
    { refreshInterval: POLLING_INTERVAL_MS, shouldRetryOnError: false }
  );

  if (error) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <CardTitle>EOD SUMMARY</CardTitle>
          </div>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-bear">Engine offline</p>
        </CardContent>
      </Card>
    );
  }

  if (isLoading || !data) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle>EOD SUMMARY</CardTitle>
          <p className="text-xs text-muted-foreground pt-0.5">End-of-day performance snapshot</p>
        </CardHeader>
        <CardContent>
          <div className="space-y-4 animate-pulse">
            <div className="h-12 bg-muted rounded" />
            <div className="space-y-2">
              <div className="h-4 bg-muted rounded w-32" />
              <div className="h-2 bg-muted rounded w-full" />
            </div>
          </div>
        </CardContent>
      </Card>
    );
  }

  const {
    date,
    trades_today,
    pnl_today_usd,
    wins_today,
    losses_today,
    win_rate_today,
    avg_r_today,
    cumulative_trades,
    cumulative_pnl_usd,
    validation_gates,
    status,
  } = data;

  const pnlColor = pnl_today_usd >= 0 ? "text-bull" : "text-bear";

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle>EOD SUMMARY</CardTitle>
          <button
            onClick={() => mutate()}
            disabled={isLoading}
            className="flex items-center gap-1 rounded border border-border px-2 py-1 text-xs text-muted-foreground hover:text-foreground transition-colors disabled:opacity-40"
          >
            <RefreshCw className={`h-3 w-3 ${isLoading ? "animate-spin" : ""}`} />
            Refresh
          </button>
        </div>
        <p className="text-xs text-muted-foreground pt-0.5">
          {date} — End-of-day performance snapshot
        </p>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* Today's P&L — large prominent display */}
        <div className="space-y-1">
          <p className="text-xs text-muted-foreground uppercase tracking-wider">Today's P&L</p>
          <div className={`text-3xl font-bold font-mono tabular-nums ${pnlColor}`}>
            ${pnl_today_usd.toFixed(2)}
          </div>
          <div className="flex items-center gap-4 text-xs text-muted-foreground">
            <span>{trades_today} trades</span>
            <span className="font-mono">
              {wins_today}W {losses_today}L
            </span>
            {win_rate_today !== null && <span>{win_rate_today.toFixed(1)}% WR</span>}
          </div>
        </div>

        {/* Status badge */}
        <div className="flex items-center justify-between">
          <p className="text-xs text-muted-foreground uppercase tracking-wider">Status</p>
          <Badge variant={getStatusBadgeVariant(status)}>
            {getStatusLabel(status)}
          </Badge>
        </div>

        {/* Validation gate progress bars */}
        <div className="space-y-3 pt-2 border-t border-border">
          <p className="text-xs text-muted-foreground uppercase tracking-wider">Validation Gates</p>
          <div className="space-y-3">
            <GateBar
              label="Profit Factor"
              current={validation_gates.pf}
              target={2.0}
            />
            <GateBar
              label="Win Rate"
              current={validation_gates.win_rate}
              target={55}
              unit="%"
            />
            <GateBar
              label="Total Trades"
              current={validation_gates.trades_count}
              target={60}
            />
            <GateBar
              label="Days Trading"
              current={validation_gates.days_trading}
              target={30}
            />
          </div>
        </div>

        {/* Cumulative stats footer */}
        <div className="pt-2 border-t border-border space-y-1 text-xs text-muted-foreground">
          <div className="flex items-center justify-between">
            <span>Cumulative P&L</span>
            <span className="font-mono font-semibold text-foreground">
              ${cumulative_pnl_usd.toFixed(2)}
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span>Total Trades</span>
            <span className="font-mono">{cumulative_trades}</span>
          </div>
          {validation_gates.sharpe !== null && (
            <div className="flex items-center justify-between">
              <span>Sharpe Ratio</span>
              <span className="font-mono">{validation_gates.sharpe.toFixed(2)}</span>
            </div>
          )}
          {validation_gates.max_drawdown !== null && (
            <div className="flex items-center justify-between">
              <span>Max Drawdown</span>
              <span className="font-mono">{validation_gates.max_drawdown.toFixed(2)}%</span>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
