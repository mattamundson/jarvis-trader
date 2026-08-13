"use client";

import { POLL_INTERVAL } from "@/lib/polling-config";

import useSWR from "swr";
import { fetchExcursion, type ExcursionResponse, type ExcursionTrade } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

/**
 * Per-trade MAE/MFE excursion surface for the trade-review page.
 *
 * The engine's /analytics/excursion returns the closed-trade set (filterable by
 * symbol); we locate this trade by id and render how far it ran adverse (MAE) vs
 * favorable (MFE) plus the MFE capture ratio, benchmarked against the book avg.
 *
 * Excursion columns are backfilled asynchronously after close, so a matched trade
 * may have NULL mae/mfe — the panel says so rather than rendering empty bars.
 */
function pct(v: number | null | undefined): string {
  return typeof v === "number" && Number.isFinite(v) ? `${(v * 100).toFixed(2)}%` : "—";
}
function usd(v: number | null | undefined): string {
  return typeof v === "number" && Number.isFinite(v) ? `$${v.toFixed(2)}` : "—";
}
function ratio(v: number | null | undefined): string {
  return typeof v === "number" && Number.isFinite(v) ? v.toFixed(2) : "—";
}

function Bar({ label, value, valueLabel, max, color }: {
  label: string;
  value: number | null;
  valueLabel: string;
  max: number;
  color: string;
}) {
  const width = value != null && max > 0 ? Math.min(100, (Math.abs(value) / max) * 100) : 0;
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center justify-between text-[11px]">
        <span className="uppercase tracking-wider text-muted-foreground">{label}</span>
        <span className="font-mono text-foreground">{valueLabel}</span>
      </div>
      <div className="h-2 w-full rounded-full bg-muted/40 overflow-hidden">
        <div className="h-full rounded-full" style={{ width: `${width}%`, backgroundColor: color }} />
      </div>
    </div>
  );
}

export function ExcursionPanel({ tradeId, symbol }: { tradeId: string; symbol: string }) {
  // Filter by symbol to keep the payload small; match the exact trade by id.
  const { data, error, isLoading } = useSWR<ExcursionResponse>(
    symbol ? `excursion-${symbol}` : null,
    () => fetchExcursion({ symbol, limit: 500 }),
    { refreshInterval: POLL_INTERVAL.MINUTE, revalidateOnFocus: false }
  );

  const row: ExcursionTrade | undefined = data?.trades?.find((t) => t.trade_id === tradeId);
  const agg = data?.aggregates;
  const populated = row != null && row.mae_pct != null && row.mfe_pct != null;
  const barMax = Math.max(Math.abs(row?.mae_pct ?? 0), Math.abs(row?.mfe_pct ?? 0), 0.0001);

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          Excursion <span className="text-muted-foreground">· MAE / MFE</span>
        </CardTitle>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <p className="text-xs text-muted-foreground py-4">Loading excursion…</p>
        ) : error ? (
          <p className="text-xs text-muted-foreground py-4">Excursion analytics unavailable.</p>
        ) : !row ? (
          <p className="text-xs text-muted-foreground py-4">
            No excursion record found for this trade (only closed paper trades are tracked).
          </p>
        ) : !populated ? (
          <p className="text-xs text-muted-foreground py-4">
            Excursion backfill pending for this trade — MAE/MFE populate asynchronously after close.
          </p>
        ) : (
          <div className="space-y-4">
            <div className="space-y-3">
              <Bar
                label="MFE (favorable)"
                value={row.mfe_pct}
                valueLabel={`${pct(row.mfe_pct)} · ${usd(row.mfe_usd)}`}
                max={barMax}
                color="#22c55e"
              />
              <Bar
                label="MAE (adverse)"
                value={row.mae_pct}
                valueLabel={`${pct(row.mae_pct)} · ${usd(row.mae_usd)}`}
                max={barMax}
                color="#ef4444"
              />
            </div>
            <div className="flex flex-wrap items-baseline gap-x-6 gap-y-2 border-t border-border pt-3">
              <div className="flex flex-col gap-0.5">
                <span className="text-[10px] uppercase tracking-wider text-muted-foreground">MFE capture</span>
                <span className="font-mono text-sm text-foreground">{ratio(row.mfe_capture_ratio)}</span>
              </div>
              {agg?.avg_mfe_capture_ratio != null && (
                <div className="flex flex-col gap-0.5">
                  <span className="text-[10px] uppercase tracking-wider text-muted-foreground">book avg</span>
                  <span className="font-mono text-sm text-muted-foreground">{ratio(agg.avg_mfe_capture_ratio)}</span>
                </div>
              )}
              <p className="text-[11px] text-muted-foreground max-w-xs">
                Capture closer to 1.0 = exited near the peak; closer to 0 = left favorable move on the table.
              </p>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
