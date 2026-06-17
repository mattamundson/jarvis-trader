"use client";

import React, { useEffect, useState } from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { AlertCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import { fetchEngine } from "@/lib/api";


interface TradingDaysStats {
  trading_days: number;
  threshold: number;
  threshold_met: boolean;
}

interface PaperPhaseSummary {
  total_return_pct: number;
  total_pnl: number;
  validation_status: string;
}

type FetchStatus = "loading" | "unavailable" | "ok";

export function TradingDaysCountdownCard() {
  const [tradingDays, setTradingDays] = useState<number | null>(null);
  const [threshold, setThreshold] = useState(30);
  const [returnPct, setReturnPct] = useState<number | null>(null);
  const [totalPnl, setTotalPnl] = useState<number | null>(null);
  const [validationStatus, setValidationStatus] = useState<string | null>(null);
  const [status, setStatus] = useState<FetchStatus>("loading");
  const [unavailableReason, setUnavailableReason] = useState<string>("");

  async function fetchData() {
    try {
      const [daysRes, summaryRes] = await Promise.allSettled([
        fetchEngine<TradingDaysStats>(`/portfolio/stats/trading-days`),
        fetchEngine<PaperPhaseSummary>(`/portfolio/stats/paper-phase-summary`),
      ]);

      const daysOk = daysRes.status === "fulfilled";
      const summaryOk = summaryRes.status === "fulfilled";

      if (!daysOk && !summaryOk) {
        const msg =
          daysRes.status === "rejected" && daysRes.reason instanceof Error
            ? daysRes.reason.message
            : "Endpoint unavailable";
        setUnavailableReason(msg);
        setStatus("unavailable");
        return;
      }

      if (daysOk) {
        const data = daysRes.value;
        setTradingDays(data.trading_days ?? 0);
        setThreshold(data.threshold ?? 30);
      }

      if (summaryOk) {
        const data = summaryRes.value;
        setReturnPct(data.total_return_pct ?? 0);
        setTotalPnl(data.total_pnl ?? 0);
        setValidationStatus(data.validation_status ?? "in_progress");
      }

      setStatus("ok");
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Endpoint unavailable";
      setUnavailableReason(msg);
      setStatus("unavailable");
    }
  }

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 5 * 60 * 1000);
    return () => clearInterval(interval);
  }, []);

  if (status === "loading") {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Validation Progress</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-center py-6">
            <span className="text-xs text-muted-foreground animate-pulse">Loading…</span>
          </div>
        </CardContent>
      </Card>
    );
  }

  if (status === "unavailable") {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Validation Progress</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-start gap-3 rounded-lg border border-border bg-muted px-4 py-3">
            <AlertCircle className="h-4 w-4 mt-0.5 flex-shrink-0 text-warn" />
            <div className="space-y-0.5">
              <p className="text-xs font-medium text-muted-foreground">
                Validation data unavailable
              </p>
              <p className="text-[10px] text-muted-foreground/70 font-mono break-all">
                {unavailableReason}
              </p>
            </div>
          </div>
        </CardContent>
      </Card>
    );
  }

  const days = tradingDays ?? 0;
  const pct = returnPct ?? 0;
  const pnl = totalPnl ?? 0;
  const valStatus = validationStatus ?? "in_progress";

  return (
    <Card>
      <CardHeader>
        <CardTitle>Validation Progress</CardTitle>
      </CardHeader>
      <CardContent>
        {/* 2-column grid */}
        <div className="grid grid-cols-2 gap-6">

          {/* Left: Trading Days countdown */}
          <div className="text-center">
            <p className="text-xs text-muted-foreground uppercase tracking-wider mb-2">Trading Days</p>
            <div className="relative inline-flex items-center justify-center">
              {/* Big number */}
              <span className={cn(
                "text-5xl font-mono font-bold",
                days >= 30 ? "text-green-400" : days >= 20 ? "text-yellow-400" : ""
              )}>
                {tradingDays === null ? "—" : days}
              </span>
            </div>
            <p className="text-sm text-muted-foreground mt-1">of {threshold} days</p>
            {/* Progress bar */}
            <div className="h-2 w-full rounded-full bg-muted overflow-hidden mt-2">
              <div
                className={cn("h-full rounded-full transition-all duration-500",
                  days >= 30 ? "bg-green-500" : "bg-accent"
                )}
                style={{ width: `${Math.min(100, (days / threshold) * 100)}%` }}
              />
            </div>
            <Badge variant={days >= 30 ? "bull" : "warn"} className="mt-2">
              {days >= 30 ? "TARGET MET" : `${threshold - days} days left`}
            </Badge>
          </div>

          {/* Right: Phase milestones */}
          <div className="space-y-3">
            <p className="text-xs text-muted-foreground uppercase tracking-wider">Phase Timeline</p>

            {/* Paper phase */}
            <div className="flex justify-between items-center">
              <span className="text-xs text-muted-foreground">Paper Phase</span>
              <Badge variant="warn">Apr–May 2026</Badge>
            </div>

            {/* Live gate */}
            <div className="flex justify-between items-center">
              <span className="text-xs text-muted-foreground">Live Gate</span>
              <Badge variant="neutral">Jun 2026</Badge>
            </div>

            {/* Total return so far */}
            <div className="flex justify-between items-center border-t border-border pt-2">
              <span className="text-xs text-muted-foreground">Return So Far</span>
              {returnPct === null ? (
                <span className="text-sm font-mono text-muted-foreground">—</span>
              ) : (
                <span className={cn(
                  "text-sm font-mono font-medium",
                  pct > 0 ? "text-green-400" : pct < 0 ? "text-red-400" : ""
                )}>
                  {pct >= 0 ? "+" : ""}{pct.toFixed(2)}%
                </span>
              )}
            </div>

            {/* Total P&L */}
            <div className="flex justify-between items-center">
              <span className="text-xs text-muted-foreground">Total P&amp;L</span>
              {totalPnl === null ? (
                <span className="text-sm font-mono text-muted-foreground">—</span>
              ) : (
                <span className={cn(
                  "text-sm font-mono font-medium",
                  pnl > 0 ? "text-green-400" : pnl < 0 ? "text-red-400" : ""
                )}>
                  {pnl >= 0 ? "+$" : "-$"}{Math.abs(pnl).toFixed(2)}
                </span>
              )}
            </div>

            {/* Validation status */}
            <div className="flex justify-between items-center">
              <span className="text-xs text-muted-foreground">Status</span>
              <Badge variant={valStatus === "passed" ? "bull" : valStatus === "failed" ? "bear" : "warn"}>
                {valStatus === "passed" ? "PASSED" : valStatus === "failed" ? "FAILED" : "IN PROGRESS"}
              </Badge>
            </div>
          </div>
        </div>

        <p className="text-xs text-muted-foreground mt-4">Target: 30 trading days with PF≥2.0, Sharpe≥1.5 • Refreshes every 5m</p>
      </CardContent>
    </Card>
  );
}
