"use client";

import { useEffect, useState } from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { fetchDailyPnLHistory, type DailyPnlRecord } from "@/lib/api";

type Trend = "IMPROVING" | "DECLINING" | "FLAT";

function linearRegression(values: number[]): { slope: number; rSquared: number } {
  const n = values.length;
  const xVals = Array.from({ length: n }, (_, i) => i);
  const yVals = values;

  const sumX = xVals.reduce((a, b) => a + b, 0);
  const sumY = yVals.reduce((a, b) => a + b, 0);
  const sumXY = xVals.reduce((acc, x, i) => acc + x * yVals[i], 0);
  const sumXX = xVals.reduce((acc, x) => acc + x * x, 0);

  const slope = (n * sumXY - sumX * sumY) / (n * sumXX - sumX * sumX);
  const intercept = (sumY - slope * sumX) / n;

  // R-squared
  const yMean = sumY / n;
  const ssTot = yVals.reduce((acc, y) => acc + Math.pow(y - yMean, 2), 0);
  const ssRes = yVals.reduce((acc, y, i) => {
    const predicted = slope * xVals[i] + intercept;
    return acc + Math.pow(y - predicted, 2);
  }, 0);

  const rSquared = ssTot === 0 ? 0 : 1 - ssRes / ssTot;

  return { slope, rSquared };
}

export function PerformanceTrendWidget() {
  const [records, setRecords] = useState<DailyPnlRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchDailyPnLHistory({ days: 30 })
      .then((data) => {
        setRecords(data.daily_pnl ?? []);
        setLoading(false);
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "Failed to load data");
        setLoading(false);
      });
  }, []);

  if (loading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Performance Trend</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            <div className="h-8 rounded bg-muted animate-pulse" />
            <div className="h-16 rounded bg-muted animate-pulse" />
            <div className="h-8 rounded bg-muted animate-pulse" />
          </div>
        </CardContent>
      </Card>
    );
  }

  if (error) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Performance Trend</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">Error: {error}</p>
        </CardContent>
      </Card>
    );
  }

  const filtered = records.filter((r) => r.num_trades > 0);
  const dataPoints = filtered.length;

  if (dataPoints < 5) {
    return (
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle>Performance Trend</CardTitle>
            <Badge variant="neutral">INSUFFICIENT DATA</Badge>
          </div>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground text-center py-4">
            Need more trade data ({dataPoints}/5 trading days with trades)
          </p>
          <p className="text-xs text-muted-foreground mt-2">
            Based on last 30 trading days cumulative P&amp;L
          </p>
        </CardContent>
      </Card>
    );
  }

  const cumPnlValues = filtered.map((r) => r.cumulative_pnl);
  const { slope, rSquared } = linearRegression(cumPnlValues);

  const trend: Trend =
    slope > 1.0 ? "IMPROVING" : slope < -1.0 ? "DECLINING" : "FLAT";

  const badgeVariant: "bull" | "bear" | "neutral" =
    trend === "IMPROVING" ? "bull" : trend === "DECLINING" ? "bear" : "neutral";

  const trendStrength =
    rSquared >= 0.7 ? "Strong" : rSquared >= 0.4 ? "Moderate" : "Weak";

  const interpretationText =
    trend === "IMPROVING"
      ? "Positive trajectory -- P&L is trending upward over the last 30 trading days"
      : trend === "DECLINING"
      ? "Negative trajectory -- P&L is trending downward. Review recent trades."
      : "Flat trajectory -- P&L is relatively stable over the period";

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>Performance Trend</CardTitle>
          <Badge variant={badgeVariant}>{trend}</Badge>
        </div>
      </CardHeader>
      <CardContent>
        {/* Large trend indicator */}
        <div className="text-center py-3">
          <p
            className={cn(
              "text-3xl font-mono font-bold",
              trend === "IMPROVING"
                ? "text-green-400"
                : trend === "DECLINING"
                ? "text-red-400"
                : "text-muted-foreground"
            )}
          >
            {slope > 0 ? "+" : ""}
            {slope.toFixed(2)}/day
          </p>
          <p className="text-sm text-muted-foreground mt-1">
            Trend slope (avg daily P&amp;L change)
          </p>
        </div>

        {/* Stats row */}
        <div className="grid grid-cols-3 gap-3 text-center mt-2">
          <div>
            <p className="text-xs text-muted-foreground">Data Points</p>
            <p className="text-sm font-mono font-medium">{dataPoints}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">R&sup2;</p>
            <p className="text-sm font-mono font-medium">{rSquared.toFixed(3)}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Trend Strength</p>
            <p className="text-sm font-mono font-medium">{trendStrength}</p>
          </div>
        </div>

        {/* Interpretation */}
        <div className="mt-3 rounded bg-muted p-2 text-xs text-muted-foreground">
          {interpretationText}
        </div>

        <p className="text-xs text-muted-foreground mt-2">
          Based on last 30 trading days cumulative P&amp;L
        </p>
      </CardContent>
    </Card>
  );
}
