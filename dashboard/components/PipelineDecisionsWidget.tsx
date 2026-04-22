"use client";

import { useState, useEffect } from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { fetchEngine } from "@/lib/api";


// ── Types ─────────────────────────────────────────────────────────────────────

interface PipelineRun {
  id?: number;
  run_id?: string;
  symbol?: string | null;
  triggered_by?: string | null;
  status?: string | null;
  signal_generated?: string | null;
  entry_approved?: boolean | null;
  rejection_reason?: string | null;
  regime?: string | null;
  momentum_score?: number | null;
  started_at?: string | null;
  completed_at?: string | null;
  duration_ms?: number | null;
}

type FilterType = "all" | "approved" | "rejected";

// ── Helpers ───────────────────────────────────────────────────────────────────

function relativeTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

function isToday(iso: string | null | undefined): boolean {
  if (!iso) return false;
  const d = new Date(iso);
  const now = new Date();
  return (
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate()
  );
}

function borderColor(entry_approved: boolean | null | undefined): string {
  if (entry_approved === true) return "border-l-4 border-l-green-500";
  if (entry_approved === false) return "border-l-4 border-l-red-500";
  return "border-l-4 border-l-neutral-600";
}

function signalColor(signal: string | null | undefined): string {
  if (!signal) return "text-neutral-500";
  const s = signal.toUpperCase();
  if (s === "LONG") return "text-green-400";
  if (s === "SHORT") return "text-red-400";
  if (s === "FLAT") return "text-neutral-400";
  return "text-neutral-400";
}

function regimeColor(regime: string | null | undefined): string {
  if (!regime) return "text-neutral-500";
  const r = regime.toLowerCase();
  if (r === "bull") return "text-green-400";
  if (r === "bear") return "text-red-400";
  return "text-neutral-400";
}

// ── Loading skeleton ───────────────────────────────────────────────────────────

function SkeletonRow() {
  return (
    <div className="flex items-start gap-3 rounded-lg border border-border bg-card p-3 animate-pulse">
      <div className="flex-1 space-y-2">
        <div className="h-3 w-1/3 rounded bg-muted" />
        <div className="h-2 w-2/3 rounded bg-muted" />
      </div>
      <div className="h-5 w-16 rounded-full bg-muted" />
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export function PipelineDecisionsWidget() {
  const [runs, setRuns] = useState<PipelineRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [filter, setFilter] = useState<FilterType>("all");

  async function fetchRuns() {
    try {
      const json = await fetchEngine(`/pipeline/history?limit=20`);
      // Handle both {runs: [...]} and bare array
      const data: PipelineRun[] = Array.isArray(json)
        ? json
        : Array.isArray(json?.runs)
        ? json.runs
        : [];
      setRuns(data);
      setError(false);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchRuns();
    const id = setInterval(fetchRuns, 30_000);
    return () => clearInterval(id);
  }, []);

  // Summary counts for today
  const todayRuns = runs.filter((r) => isToday(r.started_at));
  const todayApproved = todayRuns.filter((r) => r.entry_approved === true).length;
  const todayRejected = todayRuns.filter((r) => r.entry_approved === false).length;
  const todayTotal = todayRuns.length;

  // Filter logic
  const displayed = runs
    .slice(0, 10)
    .filter((r) => {
      if (filter === "approved") return r.entry_approved === true;
      if (filter === "rejected") return r.entry_approved === false;
      return true;
    });

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <CardTitle>Pipeline Decision Log</CardTitle>

          {/* Summary bar */}
          <span className="font-mono text-[11px] text-muted-foreground">
            Today:{" "}
            <span className="text-green-400 font-semibold">{todayApproved} approved</span>
            {" / "}
            <span className="text-red-400 font-semibold">{todayRejected} rejected</span>
            {" / "}
            <span className="text-foreground font-semibold">{todayTotal} total</span>
          </span>
        </div>

        {/* Filter buttons */}
        <div className="flex items-center gap-2 mt-2">
          {(["all", "approved", "rejected"] as FilterType[]).map((f) => (
            <Button
              key={f}
              variant={filter === f ? "default" : "outline"}
              size="sm"
              onClick={() => setFilter(f)}
              className="h-6 px-3 text-[10px] font-mono uppercase tracking-wider"
            >
              {f}
            </Button>
          ))}
        </div>
      </CardHeader>

      <CardContent>
        {/* Loading state */}
        {loading && (
          <div className="space-y-2">
            {Array.from({ length: 5 }).map((_, i) => (
              <SkeletonRow key={i} />
            ))}
          </div>
        )}

        {/* Error state */}
        {!loading && error && (
          <p className="text-center text-xs text-red-400 py-8">
            Decision log unavailable
          </p>
        )}

        {/* Empty state */}
        {!loading && !error && displayed.length === 0 && (
          <p className="text-center text-sm text-muted-foreground py-8">
            No pipeline runs yet
          </p>
        )}

        {/* Run list */}
        {!loading && !error && displayed.length > 0 && (
          <div className="space-y-2">
            {displayed.map((run, i) => (
              <div
                key={run.id ?? run.run_id ?? i}
                className={`rounded-lg border border-border bg-card/50 p-3 ${borderColor(run.entry_approved)}`}
              >
                {/* Top row */}
                <div className="flex items-center gap-2 flex-wrap">
                  {/* Symbol */}
                  <span className="font-mono text-xs font-bold text-foreground">
                    {run.symbol ?? "—"}
                  </span>

                  {/* Signal */}
                  <span className={`font-mono text-xs font-semibold ${signalColor(run.signal_generated)}`}>
                    {run.signal_generated ?? "—"}
                  </span>

                  {/* Decision badge */}
                  {run.entry_approved === true && (
                    <Badge variant="bull" className="text-[9px] px-1.5 py-0 font-mono tracking-wider">
                      APPROVED
                    </Badge>
                  )}
                  {run.entry_approved === false && (
                    <Badge variant="bear" className="text-[9px] px-1.5 py-0 font-mono tracking-wider">
                      REJECTED
                    </Badge>
                  )}
                  {run.entry_approved == null && (
                    <Badge variant="neutral" className="text-[9px] px-1.5 py-0 font-mono tracking-wider">
                      N/A
                    </Badge>
                  )}

                  {/* Spacer */}
                  <span className="flex-1" />

                  {/* Duration */}
                  {run.duration_ms != null && (
                    <span className="font-mono text-[10px] text-muted-foreground tabular-nums">
                      {run.duration_ms}ms
                    </span>
                  )}

                  {/* Relative time */}
                  <span className="font-mono text-[10px] text-muted-foreground">
                    {relativeTime(run.started_at)}
                  </span>
                </div>

                {/* Rejection reason */}
                {run.entry_approved === false && run.rejection_reason && (
                  <p className="mt-1 font-mono text-[10px] text-red-400 italic leading-relaxed">
                    {run.rejection_reason}
                  </p>
                )}

                {/* Bottom row — regime + triggered_by */}
                <div className="flex items-center gap-3 mt-1.5">
                  {run.regime && (
                    <span className={`font-mono text-[10px] ${regimeColor(run.regime)}`}>
                      {run.regime}
                    </span>
                  )}
                  {run.triggered_by && (
                    <span className="font-mono text-[10px] text-muted-foreground">
                      via {run.triggered_by}
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
