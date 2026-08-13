"use client";

import { POLL_INTERVAL } from "@/lib/polling-config";

import useSWR from "swr";
import {
  fetchEntryTiming,
  type EntryTimingResponse,
  type EntryTimingTrade,
  type EntryTimingScenarioRow,
} from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

/**
 * Entry-timing what-if surface for the trade-review page (C4).
 *
 * The engine re-prices each closed trade as if entered N bars earlier/later
 * (exit held constant). We locate this trade by id and render the per-offset
 * delta-vs-actual, flagging the best (least regret) and worst offset, plus the
 * book-wide systematic early/late bias from the aggregates.
 */
function usd(v: number | null | undefined): string {
  if (typeof v !== "number" || !Number.isFinite(v)) return "—";
  const s = `$${Math.abs(v).toFixed(2)}`;
  return v < 0 ? `-${s}` : `+${s}`;
}
function pct(v: number | null | undefined): string {
  return typeof v === "number" && Number.isFinite(v) ? `${(v * 100).toFixed(2)}%` : "—";
}
function offsetLabel(o: number): string {
  if (o === 0) return "actual";
  return o < 0 ? `${o} (earlier)` : `+${o} (later)`;
}
function deltaClass(v: number): string {
  return v > 0 ? "text-green-500" : v < 0 ? "text-red-500" : "text-muted-foreground";
}
function biasVariant(b: string | null | undefined): "bull" | "bear" | "neutral" {
  if (b === "EARLY") return "bear"; // entering later would've helped — entries too early
  if (b === "LATE") return "bull";
  return "neutral";
}

export function EntryTimingScenarios({ tradeId, symbol }: { tradeId: string; symbol: string }) {
  const { data, error, isLoading } = useSWR<EntryTimingResponse>(
    symbol ? `entry-timing-${symbol}` : null,
    () => fetchEntryTiming({ symbol, limit: 200 }),
    { refreshInterval: POLL_INTERVAL.MINUTE, revalidateOnFocus: false }
  );

  const row: EntryTimingTrade | undefined = data?.trades?.find((t) => t.trade_id === tradeId);
  const scenarios: EntryTimingScenarioRow[] = row?.scenarios ?? [];
  const hasScenarios = !!row && row.bars_available && scenarios.length > 0;

  // Best = highest delta-vs-actual (most you left on the table by entering when you did),
  // worst = lowest. offset 0 is the anchor (delta ≈ 0).
  const deltas = scenarios.map((s) => s.delta_vs_actual_usd);
  const bestDelta = deltas.length ? Math.max(...deltas) : null;
  const worstDelta = deltas.length ? Math.min(...deltas) : null;
  const bias = data?.aggregates?.systematic_bias ?? null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          Entry timing <span className="text-muted-foreground">· what-if ±bars</span>
        </CardTitle>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <p className="text-xs text-muted-foreground py-4">Loading entry-timing scenarios…</p>
        ) : error ? (
          <p className="text-xs text-muted-foreground py-4">Entry-timing analytics unavailable.</p>
        ) : !row ? (
          <p className="text-xs text-muted-foreground py-4">
            No entry-timing record found for this trade (only closed paper trades are analysed).
          </p>
        ) : !hasScenarios ? (
          <p className="text-xs text-muted-foreground py-4">
            Bars unavailable for this trade window — scenarios can’t be computed.
          </p>
        ) : (
          <div className="space-y-3">
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-[10px] uppercase tracking-wider text-muted-foreground border-b border-border">
                    <th className="text-left font-medium py-1.5">Offset</th>
                    <th className="text-right font-medium">Hypo entry</th>
                    <th className="text-right font-medium">PnL</th>
                    <th className="text-right font-medium">Δ vs actual</th>
                  </tr>
                </thead>
                <tbody>
                  {scenarios.map((s) => {
                    const isActual = s.offset_bars === 0;
                    const isBest = bestDelta != null && s.delta_vs_actual_usd === bestDelta && bestDelta > 0;
                    const isWorst = worstDelta != null && s.delta_vs_actual_usd === worstDelta && worstDelta < 0;
                    return (
                      <tr
                        key={s.offset_bars}
                        className={`border-b border-border/40 last:border-0 ${isActual ? "bg-muted/30" : ""}`}
                      >
                        <td className="py-1.5 font-mono">
                          {offsetLabel(s.offset_bars)}
                          {isBest && <span className="ml-1.5 text-green-500">▲ best</span>}
                          {isWorst && <span className="ml-1.5 text-red-500">▼ worst</span>}
                        </td>
                        <td className="text-right font-mono text-muted-foreground">
                          {Number.isFinite(s.hypothetical_entry) ? s.hypothetical_entry.toFixed(2) : "—"}
                        </td>
                        <td className="text-right font-mono">
                          {usd(s.pnl_usd)} <span className="text-muted-foreground">/ {pct(s.pnl_pct)}</span>
                        </td>
                        <td className={`text-right font-mono ${isActual ? "text-muted-foreground" : deltaClass(s.delta_vs_actual_usd)}`}>
                          {isActual ? "—" : usd(s.delta_vs_actual_usd)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {bias && (
              <div className="flex items-center gap-2 border-t border-border pt-3">
                <span className="text-[11px] text-muted-foreground">Book-wide entry bias</span>
                <Badge variant={biasVariant(bias)}>{bias}</Badge>
                <span className="text-[11px] text-muted-foreground">
                  {bias === "EARLY"
                    ? "entries tend to be early — waiting often improved PnL"
                    : bias === "LATE"
                    ? "entries tend to be late — entering sooner often improved PnL"
                    : "no systematic early/late entry bias"}
                </span>
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
