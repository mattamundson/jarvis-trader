"use client";

import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { fetchEngine } from "@/lib/api";


// ── Types ────────────────────────────────────────────────────────────────────

interface Decision {
  id: number;
  symbol: string;
  timestamp: string;
  action: string;
  confidence?: number | null;
  regime?: string | null;
  signal_data_json?: unknown;
  reasoning?: string | null;
  // Extended fields (may be present in future engine versions)
  decision?: string;
  reason?: string;
  price?: number | null;
  quantity?: number | null;
  executed?: boolean | null;
  pnl?: number | null;
}

interface DecisionHistoryResponse {
  decisions?: Decision[];
  count?: number;
  total?: number;
  [key: string]: unknown;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function decisionBadge(
  action: string
): "bull" | "bear" | "warn" | "info" | "neutral" {
  const a = action.toUpperCase();
  if (a === "BUY" || a === "BUY_LONG") return "bull";
  if (a === "SELL" || a === "SHORT" || a === "SELL_SHORT") return "bear";
  if (a === "CLOSE" || a === "EXIT_LONG" || a === "EXIT_SHORT") return "warn";
  if (a === "HOLD") return "neutral";
  return "neutral";
}

function timeAgo(isoString: string): string {
  try {
    const now = Date.now();
    const then = new Date(isoString).getTime();
    const diffMs = now - then;
    if (isNaN(diffMs)) return isoString;
    const diffSec = Math.floor(diffMs / 1000);
    if (diffSec < 60) return `${diffSec}s ago`;
    const diffMin = Math.floor(diffSec / 60);
    if (diffMin < 60) return `${diffMin}m ago`;
    const diffHr = Math.floor(diffMin / 60);
    if (diffHr < 24) return `${diffHr}h ago`;
    const diffDays = Math.floor(diffHr / 24);
    return `${diffDays}d ago`;
  } catch {
    return isoString;
  }
}

// ── Component ─────────────────────────────────────────────────────────────────

export function RecentDecisionsWidget() {
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [error, setError] = useState<string | null>(null);

  const fetchDecisions = async () => {
    try {
      const payload: unknown = await fetchEngine(
        `/portfolio/history/decisions?limit=10`
      );
      const obj = payload as { decisions?: Decision[] };
      setDecisions(
        Array.isArray(obj?.decisions)
          ? obj.decisions
          : Array.isArray(payload)
            ? (payload as Decision[])
            : [],
      );
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to fetch decisions");
    }
  };

  useEffect(() => {
    fetchDecisions();
    const interval = setInterval(fetchDecisions, 60_000);
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3">
        <CardTitle className="text-sm font-semibold">
          Recent AI Decisions
        </CardTitle>
        <Badge variant="neutral">Last 10</Badge>
      </CardHeader>
      <CardContent>
        {error && (
          <p className="text-xs text-destructive mb-2">{error}</p>
        )}
        {decisions.length === 0 && !error ? (
          <p className="text-sm text-muted-foreground text-center py-6">
            No decisions recorded
          </p>
        ) : (
          <div className="space-y-1">
            {decisions.map((d) => {
              // Support both `action` (real schema) and `decision` (spec shape)
              const actionLabel = (d.decision ?? d.action ?? "").toUpperCase();
              // Support both `reasoning` (real schema) and `reason` (spec shape)
              const reasonText = d.reason ?? d.reasoning ?? null;

              return (
                <div
                  key={d.id}
                  className="flex items-start justify-between text-xs py-1.5 border-b border-border last:border-0 gap-2"
                >
                  {/* Left side: decision badge + symbol + reason snippet */}
                  <div className="flex items-start gap-2 min-w-0">
                    <Badge
                      variant={decisionBadge(actionLabel)}
                      className="shrink-0 mt-0.5"
                    >
                      {actionLabel || "—"}
                    </Badge>
                    <div className="min-w-0">
                      <span className="font-mono font-medium">{d.symbol}</span>
                      {reasonText && (
                        <p className="text-muted-foreground truncate max-w-[200px]">
                          {reasonText}
                        </p>
                      )}
                      {d.confidence != null && (
                        <p className="text-muted-foreground">
                          conf: {(d.confidence * 100).toFixed(0)}%
                          {d.regime ? ` · ${d.regime}` : ""}
                        </p>
                      )}
                    </div>
                  </div>

                  {/* Right side: price, executed, P&L, time */}
                  <div className="shrink-0 text-right space-y-0.5">
                    {d.price != null && (
                      <p className="font-mono">${d.price.toFixed(2)}</p>
                    )}
                    {(d.executed != null || d.pnl != null) && (
                      <div className="flex items-center justify-end gap-1">
                        {d.executed != null && (
                          <Badge
                            variant={d.executed ? "bull" : "neutral"}
                            className="text-xs"
                          >
                            {d.executed ? "EXEC" : "SKIP"}
                          </Badge>
                        )}
                        {d.pnl != null && (
                          <span
                            className={cn(
                              "font-mono",
                              d.pnl >= 0 ? "text-green-400" : "text-red-400"
                            )}
                          >
                            {d.pnl >= 0 ? "+" : ""}${d.pnl.toFixed(2)}
                          </span>
                        )}
                      </div>
                    )}
                    <p className="text-muted-foreground">
                      {timeAgo(d.timestamp)}
                    </p>
                  </div>
                </div>
              );
            })}
          </div>
        )}
        <p className="text-xs text-muted-foreground mt-2">
          Refreshes every 60s
        </p>
      </CardContent>
    </Card>
  );
}
