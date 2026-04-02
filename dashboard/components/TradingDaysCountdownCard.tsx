"use client";

import React, { useEffect, useState } from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
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

export function TradingDaysCountdownCard() {
  const [tradingDays, setTradingDays] = useState(0);
  const [threshold, setThreshold] = useState(30);
  const [returnPct, setReturnPct] = useState(0);
  const [totalPnl, setTotalPnl] = useState(0);
  const [validationStatus, setValidationStatus] = useState("in_progress");

  async function fetchData() {
    try {
      const [daysRes, summaryRes] = await Promise.allSettled([
        fetchEngine(`/portfolio/stats/trading-days`),
        fetchEngine(`/portfolio/stats/paper-phase-summary`),
      ]);

      if (daysRes.status === "fulfilled" && daysRes.value.ok) {
        const data: TradingDaysStats = await daysRes.value.json();
        setTradingDays(data.trading_days ?? 0);
        setThreshold(data.threshold ?? 30);
      }

      if (summaryRes.status === "fulfilled" && summaryRes.value.ok) {
        const data: PaperPhaseSummary = await summaryRes.value.json();
        setReturnPct(data.total_return_pct ?? 0);
        setTotalPnl(data.total_pnl ?? 0);
        setValidationStatus(data.validation_status ?? "in_progress");
      }
    } catch {
      // silently use defaults on error
    }
  }

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 5 * 60 * 1000);
    return () => clearInterval(interval);
  }, []);

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
                tradingDays >= 30 ? "text-green-400" : tradingDays >= 20 ? "text-yellow-400" : ""
              )}>
                {tradingDays}
              </span>
            </div>
            <p className="text-sm text-muted-foreground mt-1">of {threshold} days</p>
            {/* Progress bar */}
            <div className="h-2 w-full rounded-full bg-muted overflow-hidden mt-2">
              <div
                className={cn("h-full rounded-full transition-all duration-500",
                  tradingDays >= 30 ? "bg-green-500" : "bg-accent"
                )}
                style={{ width: `${Math.min(100, (tradingDays / threshold) * 100)}%` }}
              />
            </div>
            <Badge variant={tradingDays >= 30 ? "bull" : "warn"} className="mt-2">
              {tradingDays >= 30 ? "TARGET MET" : `${threshold - tradingDays} days left`}
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
              <span className={cn(
                "text-sm font-mono font-medium",
                returnPct > 0 ? "text-green-400" : returnPct < 0 ? "text-red-400" : ""
              )}>
                {returnPct >= 0 ? "+" : ""}{returnPct.toFixed(2)}%
              </span>
            </div>

            {/* Total P&L */}
            <div className="flex justify-between items-center">
              <span className="text-xs text-muted-foreground">Total P&amp;L</span>
              <span className={cn(
                "text-sm font-mono font-medium",
                totalPnl > 0 ? "text-green-400" : totalPnl < 0 ? "text-red-400" : ""
              )}>
                {totalPnl >= 0 ? "+$" : "-$"}{Math.abs(totalPnl).toFixed(2)}
              </span>
            </div>

            {/* Validation status */}
            <div className="flex justify-between items-center">
              <span className="text-xs text-muted-foreground">Status</span>
              <Badge variant={validationStatus === "passed" ? "bull" : validationStatus === "failed" ? "bear" : "warn"}>
                {validationStatus === "passed" ? "PASSED" : validationStatus === "failed" ? "FAILED" : "IN PROGRESS"}
              </Badge>
            </div>
          </div>
        </div>

        <p className="text-xs text-muted-foreground mt-4">Target: 30 trading days with PF≥2.0, Sharpe≥1.5 • Refreshes every 5m</p>
      </CardContent>
    </Card>
  );
}
