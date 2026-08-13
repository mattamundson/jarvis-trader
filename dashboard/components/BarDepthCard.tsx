"use client";

import { POLL_INTERVAL } from "@/lib/polling-config";

import useSWR from "swr";
import { Database, AlertTriangle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { fetchBarDepth, type BarDepthResponse, type BarDepthPair } from "@/lib/api";

/**
 * Data-Integrity card: per-instrument bar-data coverage/health from
 * GET /analytics/bar-depth (rows / span / gaps / contaminated%).
 *
 * That endpoint is additive and only goes live after an engine restart, so this
 * card degrades gracefully — a 404/unreachable shows an "awaiting engine restart"
 * note instead of crashing the page.
 */
function fmtSpan(days: number): string {
  if (!Number.isFinite(days) || days <= 0) return "—";
  if (days >= 1) return `${days.toFixed(days >= 10 ? 0 : 1)}d`;
  return `${(days * 24).toFixed(1)}h`;
}

function PairRow({ p }: { p: BarDepthPair }) {
  const dirty = p.contaminated_pct > 0;
  return (
    <tr className="border-b border-border/40 last:border-0">
      <td className="py-1.5 font-mono text-xs font-semibold text-foreground">{p.symbol}</td>
      <td className="py-1.5 font-mono text-[11px] text-muted-foreground">{p.interval}</td>
      <td className="py-1.5 text-right font-mono text-xs text-foreground">{p.rows.toLocaleString()}</td>
      <td className="py-1.5 text-right font-mono text-[11px] text-muted-foreground">{fmtSpan(p.span_days)}</td>
      <td className="py-1.5 text-right font-mono text-[11px] text-muted-foreground">{p.gap_count}</td>
      <td className="py-1.5 text-right">
        {dirty ? (
          <span className="font-mono text-[11px] text-bear">{p.contaminated_pct.toFixed(2)}%</span>
        ) : (
          <span className="font-mono text-[11px] text-bull">clean</span>
        )}
      </td>
    </tr>
  );
}

export function BarDepthCard() {
  const { data, error, isLoading } = useSWR<BarDepthResponse>(
    "/analytics/bar-depth",
    (p: string) => fetchBarDepth(),
    { refreshInterval: POLL_INTERVAL.FIVE_MINUTES, shouldRetryOnError: false }
  );

  const pairs = data?.pairs ?? [];
  const summary = data?.summary;
  const dirtyOverall = (summary?.contaminated_pct ?? 0) > 0;

  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-foreground tracking-wide flex items-center gap-2">
          <Database className="h-4 w-4 text-muted-foreground" />
          Data Integrity — bar coverage
        </h3>
        {summary && (
          <Badge variant={dirtyOverall ? "bear" : "bull"}>
            {summary.total_rows.toLocaleString()} bars · {summary.contaminated_pct.toFixed(2)}% bad
          </Badge>
        )}
      </div>

      {isLoading ? (
        <p className="text-xs text-muted-foreground py-2">Loading bar coverage…</p>
      ) : error ? (
        <div className="flex items-start gap-2 py-1">
          <AlertTriangle className="h-4 w-4 text-muted-foreground mt-0.5 shrink-0" />
          <p className="text-xs text-muted-foreground">
            <span className="text-foreground font-medium">Awaiting engine restart</span> — the
            /analytics/bar-depth endpoint isn’t live yet on the running engine. It activates on the
            next restart; coverage stats will appear here automatically.
          </p>
        </div>
      ) : pairs.length === 0 ? (
        <p className="text-xs text-muted-foreground py-2">No bar data recorded yet.</p>
      ) : (
        <div className="overflow-x-auto max-h-[280px] overflow-y-auto">
          <table className="w-full">
            <thead>
              <tr className="text-[10px] uppercase tracking-wider text-muted-foreground border-b border-border">
                <th className="text-left font-medium py-1">Symbol</th>
                <th className="text-left font-medium py-1">TF</th>
                <th className="text-right font-medium py-1">Bars</th>
                <th className="text-right font-medium py-1">Span</th>
                <th className="text-right font-medium py-1">Gaps</th>
                <th className="text-right font-medium py-1">Quality</th>
              </tr>
            </thead>
            <tbody>
              {pairs.map((p) => (
                <PairRow key={`${p.symbol}-${p.interval}`} p={p} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
