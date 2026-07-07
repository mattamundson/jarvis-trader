"use client";

import { Clock, TrendingUp, TrendingDown } from "lucide-react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { formatCurrency } from "@/lib/utils";
import {
  dedupCaveat,
  durationMinutes,
  type HonestTrade,
  type HonestTradeSet,
} from "@/lib/honestTrades";
import { useHonestTrades } from "@/lib/useHonestTrades";

// Columns dropped vs. prior raw version:
//   - Qty (not in honest record)
//   - Price (not in honest record — only direction + P&L are available)
//   - TradeReviewPanel (required trade_id from raw engine record)
// Replaced: timestamp → exit_time; grade still available.

const REFRESH_MS = 30_000;

function formatDateTime(iso: string | null): string {
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

const GRADE_STYLES: Record<string, string> = {
  A: "bg-emerald-500/15 text-emerald-400 border border-emerald-500/30",
  B: "bg-teal-500/15 text-teal-400 border border-teal-500/30",
  C: "bg-yellow-500/15 text-yellow-400 border border-yellow-500/30",
  D: "bg-orange-500/15 text-orange-400 border border-orange-500/30",
  F: "bg-red-500/15 text-red-400 border border-red-500/30",
};

function GradeBadge({ grade }: { grade: string | null }) {
  if (grade && GRADE_STYLES[grade]) {
    return (
      <span
        className={`inline-flex items-center justify-center w-6 h-6 rounded text-[10px] font-bold ${GRADE_STYLES[grade]}`}
      >
        {grade}
      </span>
    );
  }
  return <span className="text-muted-foreground/40">—</span>;
}

export function TradeHistory() {
  const { honest: set, isLoading, error: loadError } = useHonestTrades(REFRESH_MS);
  const error = loadError
    ? loadError instanceof Error
      ? loadError.message
      : String(loadError)
    : null;

  // Sort by exit_time descending (most recent first)
  const rows: HonestTrade[] = set
    ? [...set.trades]
        .filter((t) => t.exit_time)
        .sort((a, b) => Date.parse(b.exit_time!) - Date.parse(a.exit_time!))
    : [];

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2">
            <Clock className="h-4 w-4 text-muted-foreground" />
            Trade History
          </CardTitle>
          <span className="text-xs text-muted-foreground tabular-nums">
            {set ? `${rows.length} records · ${dedupCaveat(set)}` : ""}
          </span>
        </div>
      </CardHeader>
      <CardContent>
        {isLoading && (
          <div className="flex items-center justify-center py-8">
            <div className="h-4 w-4 rounded-full border-2 border-accent border-t-transparent animate-spin mr-2" />
            <span className="text-xs text-muted-foreground">Loading trade history…</span>
          </div>
        )}

        {error && !isLoading && (
          <p className="text-center text-xs text-bear py-6">
            Failed to load trade history — {error}
          </p>
        )}

        {!isLoading && !error && rows.length === 0 && (
          <p className="text-center text-sm text-muted-foreground py-8">
            No trade history yet
          </p>
        )}

        {!isLoading && !error && rows.length > 0 && (
          <div className="overflow-x-auto -mx-1">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border">
                  <th className="pb-2 pr-3 text-left font-semibold text-muted-foreground uppercase tracking-wider whitespace-nowrap">
                    Exit Time
                  </th>
                  <th className="pb-2 pr-3 text-left font-semibold text-muted-foreground uppercase tracking-wider">
                    Symbol
                  </th>
                  <th className="pb-2 pr-3 text-left font-semibold text-muted-foreground uppercase tracking-wider">
                    Direction
                  </th>
                  <th className="pb-2 pr-3 text-right font-semibold text-muted-foreground uppercase tracking-wider">
                    P&L
                  </th>
                  <th className="pb-2 pr-3 text-right font-semibold text-muted-foreground uppercase tracking-wider">
                    Duration
                  </th>
                  <th className="pb-2 text-center font-semibold text-muted-foreground uppercase tracking-wider">
                    Grade
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/50">
                {rows.map((trade) => {
                  const pnl = trade.pnl;
                  const pnlColor =
                    pnl > 0
                      ? "text-bull"
                      : pnl < 0
                      ? "text-bear"
                      : "text-muted-foreground";
                  const PnlIcon =
                    pnl > 0 ? TrendingUp : pnl < 0 ? TrendingDown : null;
                  const dur = durationMinutes(trade);
                  const durStr =
                    dur === null
                      ? "—"
                      : dur < 60
                      ? `${Math.round(dur)}m`
                      : `${Math.floor(dur / 60)}h ${Math.round(dur % 60)}m`;

                  return (
                    <tr
                      key={trade.id}
                      className="hover:bg-muted/20"
                    >
                      {/* Exit Time */}
                      <td className="py-2 pr-3 font-mono text-muted-foreground whitespace-nowrap">
                        {formatDateTime(trade.exit_time)}
                      </td>

                      {/* Symbol */}
                      <td className="py-2 pr-3">
                        <span className="font-mono font-semibold text-foreground">
                          {trade.symbol}
                        </span>
                      </td>

                      {/* Direction */}
                      <td className="py-2 pr-3">
                        <Badge variant={trade.direction === "LONG" ? "bull" : "bear"}>
                          {trade.direction}
                        </Badge>
                      </td>

                      {/* P&L */}
                      <td className={`py-2 pr-3 text-right tabular-nums font-medium ${pnlColor}`}>
                        <span className="flex items-center justify-end gap-1">
                          {PnlIcon && <PnlIcon className="h-3 w-3 shrink-0" />}
                          {formatCurrency(pnl)}
                        </span>
                      </td>

                      {/* Duration */}
                      <td className="py-2 pr-3 text-right font-mono text-muted-foreground tabular-nums">
                        {durStr}
                      </td>

                      {/* Grade */}
                      <td className="py-2 text-center">
                        <GradeBadge grade={trade.grade} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
