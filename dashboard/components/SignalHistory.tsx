"use client";

import { useState } from "react";
import useSWR from "swr";
import { ChevronDown, ChevronRight, Zap } from "lucide-react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { fetchEngine } from "@/lib/api";

const REFRESH_MS = 30_000;

// ── Types ─────────────────────────────────────────────────────────────────────

interface DecisionRecord {
  id?: number;
  created_at?: string;
  timestamp?: string;
  symbol?: string;
  action?: string;
  final_action?: string;
  signal?: number;
  confidence?: number;
  regime?: string;
  reasoning?: string;
  [key: string]: unknown;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fetcher<T>(path: string): Promise<T> {
  return fetchEngine<T>(path);
}

function formatDateTime(iso: string | undefined | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  const date = d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  const time = d.toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
  return `${date} ${time}`;
}

function resolveAction(record: DecisionRecord): string {
  const raw = record.final_action ?? record.action ?? "";
  return raw.toUpperCase();
}

function actionColorClass(action: string): string {
  if (action === "BUY") return "text-bull";
  if (action === "SELL") return "text-bear";
  return "text-muted-foreground";
}

function actionBadgeClass(action: string): string {
  if (action === "BUY")
    return "border-bull/30 bg-bull/10 text-bull";
  if (action === "SELL")
    return "border-bear/30 bg-bear/10 text-bear";
  return "border-border bg-muted/30 text-muted-foreground";
}

function confidencePct(record: DecisionRecord): string {
  const raw = record.confidence;
  if (raw == null) return "—";
  // accept 0–1 float or 0–100 integer
  const pct = raw <= 1 ? raw * 100 : raw;
  return `${pct.toFixed(0)}%`;
}

function formatRegime(raw: string | undefined | null): string {
  if (!raw) return "—";
  return raw
    .replace(/[_\-]/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

// ── Row component ─────────────────────────────────────────────────────────────

function DecisionRow({ record }: { record: DecisionRecord }) {
  const [expanded, setExpanded] = useState(false);
  const action = resolveAction(record);
  const ts = record.created_at ?? record.timestamp;

  return (
    <div className="border-b border-border/50 last:border-0">
      {/* Main row — always visible */}
      <button
        className="w-full flex items-center gap-2 py-2 text-left hover:bg-muted/20 transition-colors rounded px-1 group"
        onClick={() => setExpanded((prev) => !prev)}
        aria-expanded={expanded}
      >
        {/* Expand chevron */}
        <span className="text-muted-foreground/50 shrink-0">
          {expanded ? (
            <ChevronDown className="h-3 w-3" />
          ) : (
            <ChevronRight className="h-3 w-3" />
          )}
        </span>

        {/* Timestamp */}
        <span className="font-mono text-[10px] text-muted-foreground whitespace-nowrap w-[80px] shrink-0">
          {formatDateTime(ts)}
        </span>

        {/* Symbol */}
        <span className="font-mono text-xs font-semibold text-foreground w-[48px] shrink-0">
          {record.symbol ?? "—"}
        </span>

        {/* Action badge */}
        <span
          className={`inline-block rounded border px-1.5 py-0.5 font-mono text-[10px] font-bold tracking-wider shrink-0 ${actionBadgeClass(action)}`}
        >
          {action || "HOLD"}
        </span>

        {/* Confidence */}
        <span
          className={`font-mono text-[11px] font-semibold tabular-nums w-[36px] text-right shrink-0 ${actionColorClass(action)}`}
        >
          {confidencePct(record)}
        </span>

        {/* Regime */}
        <span className="font-mono text-[10px] text-muted-foreground truncate ml-1">
          {formatRegime(record.regime)}
        </span>
      </button>

      {/* Expanded reasoning */}
      {expanded && (
        <div className="px-6 pb-2">
          <div className="rounded-lg bg-muted/40 border border-border p-2.5">
            <p className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground mb-1">
              Reasoning
            </p>
            <p className="text-xs text-foreground/80 leading-relaxed whitespace-pre-wrap">
              {record.reasoning ?? "No reasoning provided."}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

// ── SignalHistory component ───────────────────────────────────────────────────

export function SignalHistory() {
  const { data: decisions, isLoading, error } = useSWR<DecisionRecord[]>(
    "/portfolio/history/decisions?limit=10",
    fetcher,
    { refreshInterval: REFRESH_MS }
  );

  const rows = decisions ?? [];

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2">
            <Zap className="h-4 w-4 text-muted-foreground" />
            Signal History
          </CardTitle>
          <span className="text-xs text-muted-foreground tabular-nums">
            {rows.length > 0 ? `last ${rows.length}` : ""}
          </span>
        </div>
      </CardHeader>
      <CardContent>
        {isLoading && (
          <div className="flex items-center justify-center py-8">
            <div className="h-4 w-4 rounded-full border-2 border-accent border-t-transparent animate-spin mr-2" />
            <span className="text-xs text-muted-foreground">Loading decisions…</span>
          </div>
        )}

        {error && !isLoading && (
          <p className="text-center text-xs text-bear py-6">
            Failed to load signal history — engine may be offline.
          </p>
        )}

        {!isLoading && !error && rows.length === 0 && (
          <p className="text-center text-sm text-muted-foreground py-8">
            No pipeline decisions yet
          </p>
        )}

        {!isLoading && !error && rows.length > 0 && (
          <div>
            {/* Column headers */}
            <div className="flex items-center gap-2 pb-1.5 mb-1 border-b border-border px-1">
              <span className="w-3 shrink-0" />
              <span className="font-mono text-[9px] font-bold uppercase tracking-widest text-muted-foreground w-[80px] shrink-0">
                Time
              </span>
              <span className="font-mono text-[9px] font-bold uppercase tracking-widest text-muted-foreground w-[48px] shrink-0">
                Symbol
              </span>
              <span className="font-mono text-[9px] font-bold uppercase tracking-widest text-muted-foreground shrink-0">
                Action
              </span>
              <span className="font-mono text-[9px] font-bold uppercase tracking-widest text-muted-foreground w-[36px] text-right shrink-0">
                Conf
              </span>
              <span className="font-mono text-[9px] font-bold uppercase tracking-widest text-muted-foreground ml-1">
                Regime
              </span>
            </div>

            {/* Rows */}
            <div>
              {rows.map((decision, idx) => (
                <DecisionRow key={decision.id ?? idx} record={decision} />
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
