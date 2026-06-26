"use client";

import { useState, useEffect } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { AlertCircle, Target } from "lucide-react";
import {
  maxDrawdownPct,
  dedupCaveat,
  type HonestTradeSet,
} from "@/lib/honestTrades";
import { useHonestTrades } from "@/lib/useHonestTrades";

interface Criterion {
  label: string;
  threshold: string;
  /** null = indeterminate (not countable as pass or fail) */
  passed: boolean | null;
  displayValue: string;
}

function buildCriteria(set: HonestTradeSet): Criterion[] {
  const pf = set.profitFactor ?? 0;
  const wrPct = set.winRate * 100;
  const tradeCount = set.trades.length;

  // Max drawdown as % of peak (canonical running-peak helper). An all-losing
  // record that never rose above its $0 baseline counts as a full 100%
  // drawdown for the readiness gate, not 0%.
  const ddPctRaw = maxDrawdownPct(set.trades) * 100;
  const maxDdPct = ddPctRaw > 0 ? ddPctRaw : set.net < 0 ? 100 : 0;

  return [
    {
      label: "Profit Factor",
      threshold: "≥ 2.0",
      passed: pf >= 2.0,
      displayValue: set.profitFactor != null ? (set.profitFactor ?? 0).toFixed(2) : "—",
    },
    {
      label: "Sharpe Ratio",
      threshold: "≥ 1.5",
      // Sharpe is not derivable from deduped trade record — mark indeterminate
      passed: null,
      displayValue: "— (not computed)",
    },
    {
      label: "Win Rate",
      threshold: "≥ 55%",
      passed: wrPct >= 55,
      displayValue: `${wrPct.toFixed(1)}%`,
    },
    {
      label: "Total Trades",
      threshold: "≥ 60",
      passed: tradeCount >= 60,
      displayValue: `${tradeCount}`,
    },
    {
      label: "Max Drawdown",
      threshold: "≤ 15%",
      passed: maxDdPct <= 15,
      displayValue: `${maxDdPct.toFixed(1)}%`,
    },
  ];
}

function CriterionRow({ criterion }: { criterion: Criterion }) {
  const isIndeterminate = criterion.passed === null;
  const colorClass = isIndeterminate
    ? "text-muted-foreground"
    : criterion.passed
    ? "text-[hsl(var(--bull))]"
    : "text-[hsl(var(--bear))]";

  return (
    <div className="flex items-center gap-3 py-2 border-b border-border last:border-0">
      <span className={`text-sm font-bold w-4 text-center flex-shrink-0 ${colorClass}`}>
        {isIndeterminate ? "–" : criterion.passed ? "✓" : "✗"}
      </span>
      <span className="flex-1 text-xs text-card-foreground">
        {criterion.label} {criterion.threshold}
      </span>
      <span className={`text-xs font-mono font-semibold tabular-nums ${colorClass}`}>
        current: {criterion.displayValue}
      </span>
    </div>
  );
}

export function LiveReadinessWidget() {
  const { honest: set, isLoading: loading, error: loadError } = useHonestTrades(60_000);
  const error = loadError ? (loadError instanceof Error ? loadError.message : String(loadError)) : null;
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  useEffect(() => {
    if (set != null) {
      setLastUpdated(new Date());
    }
  }, [set]);

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

  if (error || !set) {
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
              Unable to load honest trade record{error ? `: ${error}` : ""}
            </p>
          </div>
        </CardContent>
      </Card>
    );
  }

  const criteria = buildCriteria(set);
  // Only count definite pass/fail (null = indeterminate = excluded from tally)
  const decidable = criteria.filter((c) => c.passed !== null);
  const passCount = decidable.filter((c) => c.passed === true).length;
  const total = decidable.length;

  let overallVariant: "bull" | "info" | "warn" | "neutral";
  let overallLabel: string;

  if (passCount === total) {
    overallVariant = "bull";
    overallLabel = "READY FOR LIVE";
  } else if (passCount >= Math.ceil(total * 0.7)) {
    overallVariant = "info";
    overallLabel = "NEARLY READY";
  } else if (passCount >= Math.ceil(total * 0.4)) {
    overallVariant = "warn";
    overallLabel = "NEEDS WORK";
  } else {
    overallVariant = "neutral";
    overallLabel = "NOT READY";
  }

  const borderClass =
    passCount === total ? "border-[hsl(var(--bull))]" : "border-border";

  const caveat = dedupCaveat(set);

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
            <span className="ml-1 text-[10px]">(Sharpe excluded — not computable)</span>
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

        <p className="text-[10px] text-muted-foreground mt-3">{caveat}</p>
        {set.caveats.length > 0 && (
          <p className="text-[10px] text-muted-foreground mt-1">
            {set.caveats.join(" · ")}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
