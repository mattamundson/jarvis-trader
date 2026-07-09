"use client";

import useSWR from "swr";
import { fetchPostMortems } from "@/lib/api";
import { Badge } from "@/components/ui/badge";

const REFRESH_MS = 60_000;

function fmtUsd(v: number | null): string {
  if (v == null) return "—";
  const sign = v >= 0 ? "+" : "";
  return `${sign}$${v.toFixed(2)}`;
}

function fmtDate(ts: string | null): string {
  if (!ts) return "";
  try {
    return new Date(ts).toLocaleString("en-US", {
      month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
    });
  } catch {
    return ts;
  }
}

export function PostMortemPanel() {
  const { data, isLoading, error } = useSWR(
    ["post-mortems", 20],
    () => fetchPostMortems({ limit: 20 }),
    { refreshInterval: REFRESH_MS }
  );

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-border bg-card p-4 space-y-1">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div>
            <div className="flex items-center gap-2">
              <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
                Trade Post-Mortems
              </p>
              <Badge variant={error ? "static" : "live"}>{error ? "static" : "live"}</Badge>
            </div>
            <p className="font-mono text-[10px] text-muted-foreground/40 mt-0.5">
              Opus-written analysis per closed trade (agents/post_mortem.py)
            </p>
          </div>
          {data && (
            <span className="font-mono text-[10px] text-muted-foreground/50">
              {data.total} total
            </span>
          )}
        </div>
      </div>

      {isLoading ? (
        <div className="rounded-xl border border-border bg-card p-4">
          <p className="font-mono text-xs text-muted-foreground/50 animate-pulse">
            Loading post-mortems…
          </p>
        </div>
      ) : error ? (
        <div className="rounded-xl border border-border bg-card p-4">
          <p className="font-mono text-xs text-red-400/70 italic">
            Post-mortems unavailable — engine may be unreachable
          </p>
        </div>
      ) : data!.entries.length === 0 ? (
        <div className="rounded-xl border border-border bg-card p-6 text-center">
          <p className="font-mono text-xs text-muted-foreground/50 italic">
            No post-mortems recorded yet. This feature writes an analysis after
            each closed trade, but nothing in the pipeline currently triggers it —
            wiring it into the trade-close flow is a separate follow-up.
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {data!.entries.map((entry) => (
            <div
              key={entry.trade_id}
              className="rounded-xl border border-border bg-card p-4 space-y-2 hover:border-border/80 transition-colors"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-center gap-2 flex-wrap">
                  {entry.symbol && <Badge variant="neutral">{entry.symbol}</Badge>}
                  <Badge variant={(entry.pnl ?? 0) >= 0 ? "bull" : "bear"}>
                    {fmtUsd(entry.pnl)}
                  </Badge>
                  <span className="font-mono text-[10px] text-muted-foreground/50">
                    {entry.trade_id}
                  </span>
                </div>
                {entry.created_at && (
                  <span className="font-mono text-[10px] text-muted-foreground/40 whitespace-nowrap shrink-0">
                    {fmtDate(entry.created_at)}
                  </span>
                )}
              </div>

              {entry.analysis && (
                <p className="font-mono text-[11px] text-foreground/80 leading-relaxed">
                  {entry.analysis}
                </p>
              )}

              {entry.lesson && (
                <div className="flex items-start gap-2 pt-1 border-t border-border/40">
                  <span className="font-mono text-[10px] text-muted-foreground/40 uppercase tracking-wider shrink-0 mt-0.5">
                    Lesson
                  </span>
                  <p className="font-mono text-[11px] text-accent/90">{entry.lesson}</p>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
