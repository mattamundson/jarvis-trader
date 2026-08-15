"use client";

import { useCallback, useEffect, useState } from "react";
import { Activity, Clock, Cpu } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchEngine } from "@/lib/api";


// ── Types ──────────────────────────────────────────────────────────────────

interface DecisionEntry {
  id: number;
  timestamp: string;
  symbol?: string;
  action?: string;
  /** Some log entries may also carry a `signal` field from the webhook path */
  signal?: string;
  direction?: string;
  regime?: string;
  confidence?: number;
  source?: string;
  summary?: string;
  /** pipeline_history entries use these field names */
  final_action?: string;
  created_at?: string;
  webhook_action?: string;
  status?: string;
  error_message?: string;
}

interface PipelineStatus {
  available: boolean;
  last_run: DecisionEntry | null;
  decision_count: number;
}

// ── Helpers ────────────────────────────────────────────────────────────────

/**
 * Resolve the canonical "action / signal" string from whichever field is
 * present (decisions/recent uses `action`; pipeline/history uses
 * `final_action` / `webhook_action`).
 */
function resolveAction(entry: DecisionEntry): string {
  return (
    entry.signal ??
    entry.action ??
    entry.final_action ??
    entry.webhook_action ??
    ""
  ).toUpperCase();
}

function resolveTimestamp(entry: DecisionEntry): string {
  return entry.timestamp ?? entry.created_at ?? "";
}

/** Return relative time string like "2m ago", "just now", "1h ago". */
function timeAgo(iso: string): string {
  if (!iso) return "—";
  try {
    const diffMs = Date.now() - new Date(iso).getTime();
    const secs = Math.floor(diffMs / 1000);
    if (secs < 10) return "just now";
    if (secs < 60) return `${secs}s ago`;
    const mins = Math.floor(secs / 60);
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    return `${Math.floor(hrs / 24)}d ago`;
  } catch {
    return iso;
  }
}

type BadgeVariant = "bull" | "bear" | "warn" | "info" | "neutral";

function signalBadgeVariant(action: string): BadgeVariant {
  switch (action.toUpperCase()) {
    case "ENTRY_NOW":
    case "BUY":
    case "LONG":
      return "bull";
    case "WAIT":
    case "HOLD":
    case "NO_ENTRY":
      return "neutral";
    case "FADE":
    case "SELL":
    case "SHORT":
      return "warn";
    default:
      return "info";
  }
}

function confidenceLabel(confidence?: number): string | null {
  if (confidence == null) return null;
  return `${Math.round(confidence * 100)}%`;
}

// ── Sub-components ─────────────────────────────────────────────────────────

function DecisionRow({ entry }: { entry: DecisionEntry }) {
  const action = resolveAction(entry);
  const ts = resolveTimestamp(entry);
  const variant = signalBadgeVariant(action);
  const conf = confidenceLabel(entry.confidence);

  return (
    <div className="flex items-start gap-3 py-2.5 border-b border-border/50 last:border-0">
      {/* Timestamp */}
      <div className="shrink-0 flex items-center gap-1 text-[11px] text-muted-foreground w-16 pt-0.5">
        <Clock className="h-3 w-3 shrink-0" />
        <span className="truncate">{timeAgo(ts)}</span>
      </div>

      {/* Signal badge */}
      <div className="shrink-0 w-24">
        <Badge variant={variant}>{action || "—"}</Badge>
      </div>

      {/* Symbol + direction + regime */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          {entry.symbol && (
            <span className="text-xs font-semibold text-foreground font-mono">
              {entry.symbol}
            </span>
          )}
          {entry.direction && (
            <span className="text-[11px] text-muted-foreground">
              {entry.direction}
            </span>
          )}
          {entry.regime && (
            <span className="text-[11px] text-muted-foreground/70 italic">
              {entry.regime}
            </span>
          )}
          {conf && (
            <span className="text-[11px] text-accent font-medium">{conf}</span>
          )}
          {entry.source && (
            <span className="text-[10px] text-muted-foreground/50 uppercase tracking-wide">
              {entry.source}
            </span>
          )}
        </div>
        {/* Summary / reason */}
        {entry.summary && (
          <p className="text-[11px] text-muted-foreground mt-0.5 line-clamp-2 leading-relaxed">
            {entry.summary}
          </p>
        )}
        {entry.error_message && (
          <p className="text-[11px] text-bear mt-0.5 line-clamp-1">
            {entry.error_message}
          </p>
        )}
      </div>
    </div>
  );
}

// ── Widget ─────────────────────────────────────────────────────────────────

export function DecisionLogWidget() {
  const [decisions, setDecisions] = useState<DecisionEntry[]>([]);
  const [status, setStatus] = useState<PipelineStatus | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    let decErr: string | null = null;
    try {
      const raw = await fetchEngine<unknown>(`/decisions/recent?limit=10`, {
        cache: "no-store",
      });
      if (Array.isArray(raw)) {
        setDecisions([...raw].reverse() as DecisionEntry[]);
      }
    } catch (e) {
      decErr =
        e instanceof Error ? e.message : "Decisions endpoint unavailable";
    }
    setError(decErr);

    try {
      const s = await fetchEngine<PipelineStatus>(`/pipeline/status`, {
        cache: "no-store",
      });
      setStatus(s);
    } catch {
      /* pipeline status optional */
    } finally {
      setLoading(false);
      setLastRefresh(new Date());
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 15_000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const decisionCount = status?.decision_count ?? decisions.length;
  const pipelineAvailable = status?.available ?? true;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Cpu className="h-4 w-4 text-muted-foreground" />
            <CardTitle>Decision Log</CardTitle>
          </div>
          <div className="flex items-center gap-2">
            {/* Pipeline availability */}
            <Badge variant={pipelineAvailable ? "bull" : "bear"}>
              {pipelineAvailable ? "Pipeline Ready" : "Pipeline Down"}
            </Badge>
            {/* Decision count */}
            <Badge variant="info">{decisionCount} decisions</Badge>
          </div>
        </div>
      </CardHeader>

      <CardContent>
        {/* Loading skeleton */}
        {loading && (
          <div className="space-y-3 animate-pulse">
            {Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="flex items-center gap-3">
                <div className="h-3 w-14 rounded bg-muted" />
                <div className="h-5 w-20 rounded-full bg-muted" />
                <div className="h-3 flex-1 rounded bg-muted" />
              </div>
            ))}
          </div>
        )}

        {/* Error state */}
        {!loading && error && (
          <div className="rounded-lg border border-bear/20 bg-bear/5 px-4 py-3 text-center space-y-1">
            <p className="text-xs font-semibold text-bear">Unable to load decisions</p>
            <p className="text-[11px] text-muted-foreground">{error}</p>
          </div>
        )}

        {/* Decision list */}
        {!loading && !error && decisions.length > 0 && (
          <div className="max-h-64 overflow-y-auto -mx-1 px-1">
            {decisions.map((entry, idx) => (
              <DecisionRow key={entry.id ?? idx} entry={entry} />
            ))}
          </div>
        )}

        {/* Empty state — pipeline available but no decisions yet */}
        {!loading && !error && decisions.length === 0 && (
          <div className="py-8 text-center space-y-2">
            <Activity className="h-8 w-8 text-muted-foreground/40 mx-auto" />
            <p className="text-xs text-muted-foreground">No decisions recorded yet</p>
            <p className="text-[11px] text-muted-foreground/60">
              Decisions appear here after the pipeline runs on watchlist symbols.
            </p>
          </div>
        )}

        {/* Footer: last refresh */}
        <div className="mt-3 pt-2 border-t border-border/50 flex items-center justify-between">
          <span className="text-[11px] text-muted-foreground">
            Auto-refreshes every 15s
          </span>
          {lastRefresh && (
            <span className="text-[11px] text-muted-foreground">
              Last refresh: {lastRefresh.toLocaleTimeString("en-US", {
                hour: "2-digit",
                minute: "2-digit",
                second: "2-digit",
                hour12: false,
              })}
            </span>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
