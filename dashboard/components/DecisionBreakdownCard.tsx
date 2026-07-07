"use client";

import { useEffect, useState } from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchEngine } from "@/lib/api";


interface DecisionRecord {
  action?: string;
  confidence?: number | null;
}

interface DecisionsResponse {
  decisions?: DecisionRecord[];
  // Some endpoints return the array directly
  [key: string]: unknown;
}

interface Counts {
  longCount: number;
  shortCount: number;
  holdCount: number;
  exitCount: number;
  otherCount: number;
  totalDecisions: number;
  signalRate: number;
  holdRate: number;
  avgConfidence: number | null;
}

function countDecisions(records: DecisionRecord[]): Counts {
  let longCount = 0;
  let shortCount = 0;
  let holdCount = 0;
  let exitCount = 0;
  let otherCount = 0;
  const confidenceValues: number[] = [];

  for (const rec of records) {
    const action = (rec.action ?? "").toUpperCase().trim();

    if (action === "BUY_LONG" || action === "BUY") {
      longCount++;
    } else if (action === "SELL_SHORT" || action === "SELL") {
      shortCount++;
    } else if (action === "HOLD") {
      holdCount++;
    } else if (
      action === "EXIT_LONG" ||
      action === "EXIT_SHORT" ||
      action === "CLOSE"
    ) {
      exitCount++;
    } else {
      otherCount++;
    }

    if (rec.confidence != null) {
      confidenceValues.push(rec.confidence);
    }
  }

  const totalDecisions = longCount + shortCount + holdCount + exitCount + otherCount;
  const signalRate =
    totalDecisions > 0
      ? ((longCount + shortCount) / totalDecisions) * 100
      : 0;
  const holdRate =
    totalDecisions > 0 ? (holdCount / totalDecisions) * 100 : 0;
  const avgConfidence =
    confidenceValues.length > 0
      ? confidenceValues.reduce((a, b) => a + b, 0) / confidenceValues.length
      : null;

  return {
    longCount,
    shortCount,
    holdCount,
    exitCount,
    otherCount,
    totalDecisions,
    signalRate,
    holdRate,
    avgConfidence,
  };
}

function pct(val: number, decimals = 1): string {
  return `${val.toFixed(decimals)}%`;
}

export function DecisionBreakdownCard() {
  const [records, setRecords] = useState<DecisionRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  async function fetchDecisions() {
    try {
      const payload = await fetchEngine<unknown>(
        `/portfolio/history/decisions?limit=500`
      );
      // Handle both { decisions: [...] } and a top-level array
      const list: DecisionRecord[] = Array.isArray(payload)
        ? (payload as DecisionRecord[])
        : ((payload as { decisions?: DecisionRecord[] }).decisions ?? []);
      setRecords(list);
      setError(false);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchDecisions();
    const interval = setInterval(fetchDecisions, 300_000);
    return () => clearInterval(interval);
  }, []);

  const counts = countDecisions(records);
  const {
    longCount,
    shortCount,
    holdCount,
    exitCount,
    otherCount,
    totalDecisions,
    signalRate,
    holdRate,
    avgConfidence,
  } = counts;

  // Badge variant based on signal rate
  const badgeVariant: "bull" | "info" | "neutral" =
    signalRate >= 15 ? "bull" : signalRate >= 5 ? "info" : "neutral";
  const badgeLabel =
    badgeVariant === "bull"
      ? "Active"
      : badgeVariant === "info"
      ? "Moderate"
      : "Conservative";

  // Bar segment widths (% of total)
  function segWidth(count: number): number {
    return totalDecisions > 0 ? (count / totalDecisions) * 100 : 0;
  }

  const segments = [
    { label: "BUY", count: longCount, colorClass: "bg-green-500/80", textColor: "text-green-400" },
    { label: "SELL", count: shortCount, colorClass: "bg-red-500/80", textColor: "text-red-400" },
    { label: "HOLD", count: holdCount, colorClass: "bg-zinc-500/70", textColor: "text-zinc-400" },
    { label: "EXIT", count: exitCount, colorClass: "bg-blue-500/80", textColor: "text-blue-400" },
    { label: "OTHER", count: otherCount, colorClass: "bg-zinc-700/70", textColor: "text-muted-foreground" },
  ];

  const statsRows: { label: string; value: string; valueClass?: string }[] = [
    {
      label: "Signal Rate",
      value: totalDecisions > 0 ? pct(signalRate) : "—",
      valueClass:
        signalRate >= 15
          ? "text-green-400"
          : signalRate >= 5
          ? "text-blue-400"
          : "text-muted-foreground",
    },
    {
      label: "Hold Rate",
      value: totalDecisions > 0 ? pct(holdRate) : "—",
    },
    {
      label: "Avg Confidence",
      value: avgConfidence != null ? pct(avgConfidence * 100) : "—",
    },
    {
      label: "Exits",
      value: totalDecisions > 0 ? String(exitCount) : "—",
    },
  ];

  return (
    <Card>
      <CardHeader className="flex flex-row justify-between items-center">
        <div>
          <CardTitle>Pipeline Decision Breakdown</CardTitle>
          <p className="text-xs text-muted-foreground mt-0.5">
            {totalDecisions > 0
              ? `${totalDecisions.toLocaleString()} total decisions analyzed`
              : "No decisions loaded"}
          </p>
        </div>
        <Badge variant={badgeVariant}>{badgeLabel}</Badge>
      </CardHeader>

      <CardContent>
        {loading ? (
          <p className="text-sm text-muted-foreground text-center py-6">
            Loading decision history…
          </p>
        ) : error ? (
          <p className="text-sm text-muted-foreground text-center py-6">
            Could not load decisions — engine offline?
          </p>
        ) : totalDecisions === 0 ? (
          <p className="text-sm text-muted-foreground text-center py-6">
            No decision records found yet.
          </p>
        ) : (
          <>
            {/* Stacked bar */}
            <div className="mb-4">
              <div className="flex rounded-full overflow-hidden h-6 w-full">
                {segments.map((seg) => {
                  const w = segWidth(seg.count);
                  if (w === 0) return null;
                  return (
                    <div
                      key={seg.label}
                      className={`flex items-center justify-center ${seg.colorClass} text-xs font-bold text-white transition-all duration-500`}
                      style={{ width: `${w}%` }}
                    >
                      {w >= 8 && seg.count}
                    </div>
                  );
                })}
              </div>

              {/* Legend */}
              <div className="flex flex-wrap gap-x-4 gap-y-1 mt-2">
                {segments.map((seg) => {
                  const w = segWidth(seg.count);
                  if (seg.count === 0) return null;
                  return (
                    <span
                      key={seg.label}
                      className={`text-xs font-medium ${seg.textColor}`}
                    >
                      {seg.label} {w.toFixed(1)}%
                    </span>
                  );
                })}
              </div>
            </div>

            {/* Stats grid */}
            <div className="grid grid-cols-2 gap-3 mb-4">
              {statsRows.map((row) => (
                <div
                  key={row.label}
                  className="rounded-lg border border-border bg-background p-3"
                >
                  <p className="text-xs text-muted-foreground uppercase tracking-wider">
                    {row.label}
                  </p>
                  <p
                    className={`text-lg font-bold font-mono tabular-nums mt-0.5 ${
                      row.valueClass ?? "text-foreground"
                    }`}
                  >
                    {row.value}
                  </p>
                </div>
              ))}
            </div>

            {/* Footer note */}
            <p className="text-xs text-muted-foreground">
              Higher signal rate = more trading opportunities | Lower = more selective
            </p>
            <p className="text-xs text-muted-foreground mt-1">
              From last 500 decisions · Refreshes every 5m
            </p>
          </>
        )}
      </CardContent>
    </Card>
  );
}
