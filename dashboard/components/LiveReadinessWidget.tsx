"use client";

import { useState, useEffect } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { AlertCircle, Target } from "lucide-react";
import { fetchEngine } from "@/lib/api";

interface PerformanceData {
  profit_factor: number;
  sharpe_ratio: number;
  win_rate: number;
  total_trades: number;
  max_drawdown: number;
  trading_days: number;
}

interface Criterion {
  label: string;
  threshold: string;
  passed: boolean;
  displayValue: string;
}

function buildCriteria(data: PerformanceData): Criterion[] {
  const profitFactor = data.profit_factor;
  const sharpeRatio = data.sharpe_ratio;
  const winRatePct = data.win_rate * 100;
  const totalTrades = data.total_trades;
  const tradingDays = data.trading_days;
  const maxDrawdownPct = Math.abs(data.max_drawdown) * 100;

  return [
    {
      label: "Profit Factor",
      threshold: "≥ 2.0",
      passed: profitFactor >= 2.0,
      displayValue: `${profitFactor.toFixed(2)}`,
    },
    {
      label: "Sharpe Ratio",
      threshold: "≥ 1.5",
      passed: sharpeRatio >= 1.5,
      displayValue: `${sharpeRatio.toFixed(2)}`,
    },
    {
      label: "Win Rate",
      threshold: "≥ 55%",
      passed: winRatePct >= 55,
      displayValue: `${winRatePct.toFixed(1)}%`,
    },
    {
      label: "Total Trades",
      threshold: "≥ 60",
      passed: totalTrades >= 60,
      displayValue: `${totalTrades}`,
    },
    {
      label: "Trading Days",
      threshold: "≥ 30",
      passed: tradingDays >= 30,
      displayValue: `${tradingDays}`,
    },
    {
      label: "Max Drawdown",
      threshold: "≤ 15%",
      passed: maxDrawdownPct <= 15,
      displayValue: `${maxDrawdownPct.toFixed(1)}%`,
    },
  ];
}

function CriterionRow({ criterion }: { criterion: Criterion }) {
  return (
    <div className="flex items-center gap-3 py-2 border-b border-border last:border-0">
      <span
        className={`text-sm font-bold w-4 text-center flex-shrink-0 ${
          criterion.passed ? "text-[hsl(var(--bull))]" : "text-[hsl(var(--bear))]"
        }`}
      >
        {criterion.passed ? "✓" : "✗"}
      </span>
      <span className="flex-1 text-xs text-card-foreground">
        {criterion.label} {criterion.threshold}
      </span>
      <span
        className={`text-xs font-mono font-semibold tabular-nums ${
          criterion.passed ? "text-[hsl(var(--bull))]" : "text-[hsl(var(--bear))]"
        }`}
      >
        current: {criterion.displayValue}
      </span>
    </div>
  );
}

export function LiveReadinessWidget() {
  const [data, setData] = useState<PerformanceData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  async function fetchData() {
    try {
      const json = await fetchEngine<PerformanceData>("/analytics/performance");
      setData(json);
      setError(null);
      setLastUpdated(new Date());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 60000);
    return () => clearInterval(interval);
  }, []);

  if (loading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Target className="h-4 w-4" />
            Live Trading Readiness — June 2026
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-xs text-muted-foreground">Loading readiness data...</p>
        </CardContent>
      </Card>
    );
  }

  if (error || !data) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Target className="h-4 w-4" />
            Live Trading Readiness — June 2026
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-2">
            <AlertCircle className="h-4 w-4 text-[hsl(var(--warn))]" />
            <p className="text-xs text-muted-foreground">
              Unable to load performance data{error ? `: ${error}` : ""}
            </p>
          </div>
        </CardContent>
      </Card>
    );
  }

  const criteria = buildCriteria(data);
  const passCount = criteria.filter((c) => c.passed).length;
  const total = criteria.length;

  let overallVariant: "bull" | "info" | "warn" | "neutral";
  let overallLabel: string;

  if (passCount === total) {
    overallVariant = "bull";
    overallLabel = "READY FOR LIVE";
  } else if (passCount >= 4) {
    overallVariant = "info";
    overallLabel = "NEARLY READY";
  } else if (passCount >= 2) {
    overallVariant = "warn";
    overallLabel = "NEEDS WORK";
  } else {
    overallVariant = "neutral";
    overallLabel = "NOT READY";
  }

  const borderClass =
    passCount === total
      ? "border-[hsl(var(--bull))]"
      : "border-border";

  return (
    <Card className={borderClass}>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2">
            <Target className="h-4 w-4" />
            Live Trading Readiness — June 2026
          </CardTitle>
          <Badge variant={overallVariant} className="text-sm px-3 py-1 font-bold">
            {overallLabel}
          </Badge>
        </div>
      </CardHeader>
      <CardContent>
        <div className="mb-3 flex items-center justify-between">
          <span className="text-xs text-muted-foreground">
            Criteria met:{" "}
            <span className="font-semibold text-card-foreground">
              {passCount}/{total}
            </span>
          </span>
          {lastUpdated && (
            <span className="text-[10px] text-muted-foreground">
              Updated {lastUpdated.toLocaleTimeString()} · auto-refresh 60s
            </span>
          )}
        </div>

        <div>
          {criteria.map((c) => (
            <CriterionRow key={c.label} criterion={c} />
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
