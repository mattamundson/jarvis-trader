"use client";

import React, { useState, useEffect } from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchEngine } from "@/lib/api";


// ── Types ─────────────────────────────────────────────────────────────────────

interface PipelineRun {
  id?: number;
  symbol?: string;
  regime?: string;
  momentum_score?: number;
  signal_generated?: string;
  started_at?: string;
  created_at?: string;
  // pipeline/decisions shape
  action?: string;
  confidence?: number;
  timestamp?: string;
}

interface PipelineHistoryResponse {
  runs?: PipelineRun[];
}

interface DecisionsResponse {
  decisions?: PipelineRun[];
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function relativeTime(isoStr: string): string {
  const diffMs = Date.now() - new Date(isoStr).getTime();
  if (isNaN(diffMs)) return "—";
  const diffSec = Math.floor(diffMs / 1000);
  if (diffSec < 60) return `${diffSec}s ago`;
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDay = Math.floor(diffHr / 24);
  return `${diffDay}d ago`;
}

function normalizeRegime(regime?: string): "bull" | "bear" | "neutral" {
  if (!regime) return "neutral";
  const r = regime.toLowerCase();
  if (r === "bull" || r === "bullish" || r === "uptrend") return "bull";
  if (r === "bear" || r === "bearish" || r === "downtrend") return "downtrend" as never;
  return "neutral";
}

function regimeCategory(regime?: string): "bull" | "bear" | "neutral" {
  if (!regime) return "neutral";
  const r = regime.toLowerCase();
  if (r === "bull" || r === "bullish" || r === "uptrend") return "bull";
  if (r === "bear" || r === "bearish" || r === "downtrend") return "bear";
  return "neutral";
}

function regimeDotColor(cat: "bull" | "bear" | "neutral"): string {
  if (cat === "bull") return "bg-emerald-500";
  if (cat === "bear") return "bg-red-500";
  return "bg-muted-foreground/50";
}

function regimeTextColor(cat: "bull" | "bear" | "neutral"): string {
  if (cat === "bull") return "text-emerald-500";
  if (cat === "bear") return "text-red-500";
  return "text-muted-foreground";
}

function momentumColor(score?: number): string {
  if (score == null) return "text-muted-foreground";
  if (score > 0.5) return "text-emerald-500";
  if (score < 0.3) return "text-red-500";
  return "text-muted-foreground";
}

function signalColor(signal?: string): string {
  if (!signal) return "text-muted-foreground";
  if (signal === "LONG") return "text-emerald-500";
  if (signal === "SHORT") return "text-red-500";
  return "text-muted-foreground";
}

function getTimestamp(run: PipelineRun): string | undefined {
  return run.started_at ?? run.created_at ?? run.timestamp;
}

function getSignal(run: PipelineRun): string | undefined {
  return run.signal_generated ?? run.action;
}

// ── Skeleton ──────────────────────────────────────────────────────────────────

function RegimeSkeleton() {
  return (
    <div className="space-y-3 animate-pulse">
      <div className="flex items-center gap-3">
        <div className="h-7 w-24 bg-muted rounded" />
        <div className="h-5 w-16 bg-muted rounded-full" />
      </div>
      <div className="h-2 w-full bg-muted rounded-full" />
      <div className="flex gap-4">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-4 w-20 bg-muted rounded" />
        ))}
      </div>
      <div className="space-y-2 pt-2">
        {[1, 2, 3, 4, 5].map((i) => (
          <div key={i} className="flex items-center gap-2">
            <div className="h-3 w-16 bg-muted rounded" />
            <div className="h-2 w-2 bg-muted rounded-full" />
            <div className="h-3 w-12 bg-muted rounded" />
            <div className="h-3 w-8 bg-muted rounded ml-auto" />
            <div className="h-3 w-10 bg-muted rounded" />
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Main Component ─────────────────────────────────────────────────────────────

export function RegimeHistoryWidget() {
  const [runs, setRuns] = useState<PipelineRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [tick, setTick] = useState(0);

  const fetchData = async () => {
    // Try /pipeline/history first, then /pipeline/decisions
    let fetched: PipelineRun[] = [];
    let success = false;

    // Attempt 1: GET /pipeline/history?limit=20
    try {
      const raw = await fetchEngine(`/pipeline/history?limit=20`);
      if (Array.isArray(raw)) {
        fetched = raw;
      } else {
        fetched = (raw as PipelineHistoryResponse).runs ?? [];
      }
      success = true;
    } catch {
      // fall through to attempt 2
    }

    // Attempt 2: GET /pipeline/decisions?limit=20
    if (!success || fetched.length === 0) {
      try {
        const raw = await fetchEngine(`/pipeline/decisions?limit=20`);
        if (Array.isArray(raw)) {
          fetched = raw;
        } else {
          fetched = (raw as DecisionsResponse).decisions ?? [];
        }
        success = true;
      } catch {
        // both failed
      }
    }

    if (success) {
      setRuns(fetched);
      setError(false);
    } else if (fetched.length === 0 && !success) {
      setError(true);
    }

    setLoading(false);
  };

  // Initial fetch + 30-second interval
  useEffect(() => {
    fetchData();
    const id = setInterval(fetchData, 30_000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Tick every 30s to keep relative times current
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 30_000);
    return () => clearInterval(id);
  }, []);

  void tick;

  // ── Derived stats ─────────────────────────────────────────────────────────

  const total = runs.length;
  const bullCount = runs.filter((r) => regimeCategory(r.regime) === "bull").length;
  const bearCount = runs.filter((r) => regimeCategory(r.regime) === "bear").length;
  const neutralCount = total - bullCount - bearCount;

  const bullPct = total > 0 ? (bullCount / total) * 100 : 0;
  const bearPct = total > 0 ? (bearCount / total) * 100 : 0;
  const neutralPct = total > 0 ? (neutralCount / total) * 100 : 0;

  const latestRun = runs[0] ?? null;
  const latestRegimeCat = regimeCategory(latestRun?.regime);

  // ── Render helpers ────────────────────────────────────────────────────────

  const currentRegimeBadgeVariant = latestRegimeCat === "bull"
    ? "bull"
    : latestRegimeCat === "bear"
    ? "bear"
    : "neutral";

  // ── States ────────────────────────────────────────────────────────────────

  if (loading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Regime History</CardTitle>
        </CardHeader>
        <CardContent>
          <RegimeSkeleton />
        </CardContent>
      </Card>
    );
  }

  if (error) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Regime History</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">Regime data unavailable</p>
        </CardContent>
      </Card>
    );
  }

  if (runs.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Regime History</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">No regime history yet</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between gap-2">
          <CardTitle>Regime History</CardTitle>
          {latestRun && (
            <Badge variant={currentRegimeBadgeVariant}>
              {latestRun.regime ?? "unknown"}
            </Badge>
          )}
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* Current regime display */}
        {latestRun && (
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2">
              <span
                className={`inline-block h-3 w-3 rounded-full ${regimeDotColor(latestRegimeCat)}`}
              />
              <span className={`text-xl font-bold capitalize ${regimeTextColor(latestRegimeCat)}`}>
                {latestRun.regime ?? "Unknown"}
              </span>
            </div>
            <span className="text-xs text-muted-foreground">
              Current regime
            </span>
          </div>
        )}

        {/* Summary stats */}
        <div className="space-y-2">
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
            <span>
              <span className="text-emerald-500 font-medium">Bull:</span>{" "}
              {bullCount} runs ({bullPct.toFixed(0)}%)
            </span>
            <span>
              <span className="text-red-500 font-medium">Bear:</span>{" "}
              {bearCount} runs ({bearPct.toFixed(0)}%)
            </span>
            <span>
              <span className="font-medium">Neutral:</span>{" "}
              {neutralCount} runs ({neutralPct.toFixed(0)}%)
            </span>
          </div>

          {/* Proportion bar */}
          <div className="h-2 rounded-full flex overflow-hidden">
            <div style={{ width: `${bullPct}%` }} className="bg-emerald-500" />
            <div style={{ width: `${bearPct}%` }} className="bg-red-500" />
            <div style={{ width: `${neutralPct}%` }} className="bg-muted-foreground/30" />
          </div>
        </div>

        {/* Timeline */}
        <div className="space-y-1 max-h-96 overflow-y-auto pr-1">
          {runs.map((run, idx) => {
            const prevRun = runs[idx + 1];
            const currentCat = regimeCategory(run.regime);
            const prevCat = prevRun ? regimeCategory(prevRun.regime) : null;
            const regimeChanged = prevCat !== null && currentCat !== prevCat;
            const ts = getTimestamp(run);
            const signal = getSignal(run);

            return (
              <React.Fragment key={run.id ?? idx}>
                {/* Regime change divider */}
                {regimeChanged && prevCat !== null && (
                  <div className="flex items-center gap-2 py-1.5">
                    <div className="flex-1 h-px bg-border" />
                    <span className="text-[10px] font-medium text-muted-foreground whitespace-nowrap px-1">
                      Regime Change:{" "}
                      <span className={regimeTextColor(prevCat)}>{prevRun?.regime ?? prevCat}</span>
                      {" → "}
                      <span className={regimeTextColor(currentCat)}>{run.regime ?? currentCat}</span>
                    </span>
                    <div className="flex-1 h-px bg-border" />
                  </div>
                )}

                {/* Run row */}
                <div className="flex items-center gap-2 text-xs py-0.5">
                  {/* Relative time */}
                  <span className="text-[10px] text-muted-foreground w-14 shrink-0 tabular-nums">
                    {ts ? relativeTime(ts) : "—"}
                  </span>

                  {/* Regime dot */}
                  <span
                    className={`inline-block h-2 w-2 rounded-full shrink-0 ${regimeDotColor(currentCat)}`}
                  />

                  {/* Regime label */}
                  <span className={`capitalize font-medium w-16 shrink-0 ${regimeTextColor(currentCat)}`}>
                    {run.regime ?? "—"}
                  </span>

                  {/* Symbol */}
                  {run.symbol && (
                    <span className="text-muted-foreground font-mono text-[10px] w-10 shrink-0">
                      {run.symbol}
                    </span>
                  )}

                  {/* Momentum score */}
                  {run.momentum_score != null ? (
                    <span className={`font-mono text-[10px] tabular-nums ${momentumColor(run.momentum_score)}`}>
                      {run.momentum_score.toFixed(2)}
                    </span>
                  ) : (
                    <span className="text-[10px] text-muted-foreground/40 w-8">—</span>
                  )}

                  {/* Signal */}
                  <span className={`ml-auto font-mono text-[10px] font-semibold ${signalColor(signal)}`}>
                    {signal ?? "—"}
                  </span>
                </div>
              </React.Fragment>
            );
          })}
        </div>

        {/* Footer */}
        <p className="text-[10px] text-muted-foreground text-right">
          Refreshes every 30s · {total} run{total !== 1 ? "s" : ""}
        </p>
      </CardContent>
    </Card>
  );
}
