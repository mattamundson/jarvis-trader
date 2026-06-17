"use client";

import useSWR from "swr";
import { Badge } from "@/components/ui/badge";
import {
  fetchExcursion,
  fetchEntryTiming,
  type ExcursionResponse,
  type EntryTimingResponse,
} from "@/lib/api";

/**
 * Compact post-trade quality snippet for the one-pane (C4+C5), composing the
 * book-wide excursion (J1) and entry-timing (J2) aggregates the engine already
 * computes: how much of the favorable move we capture, and how much PnL we leave
 * on the table to imperfect entry timing. Read-only; degrades gracefully.
 */
function pct(v: number | null | undefined): string {
  return typeof v === "number" && Number.isFinite(v) ? `${(v * 100).toFixed(2)}%` : "—";
}
function ratio(v: number | null | undefined): string {
  return typeof v === "number" && Number.isFinite(v) ? v.toFixed(2) : "—";
}
function signedUsd(v: number | null | undefined): string {
  if (typeof v !== "number" || !Number.isFinite(v)) return "—";
  const s = `$${Math.abs(v).toFixed(0)}`;
  return v < 0 ? `-${s}` : `+${s}`;
}
function biasVariant(b: string | null | undefined): "bull" | "bear" | "neutral" {
  if (b === "EARLY") return "bear";
  if (b === "LATE") return "bull";
  return "neutral";
}
function offsetWord(o: number | null | undefined): string {
  if (o == null || o === 0) return "actual timing";
  return o < 0 ? `${o} bars (earlier)` : `+${o} bars (later)`;
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: "bull" | "bear" | "muted" }) {
  const color = tone === "bull" ? "text-bull" : tone === "bear" ? "text-bear" : "text-foreground";
  return (
    <div>
      <p className="text-[11px] uppercase tracking-wider text-muted-foreground">{label}</p>
      <p className={`text-lg font-bold font-mono ${color}`}>{value}</p>
    </div>
  );
}

export function PostTradeSnippet() {
  const exc = useSWR<ExcursionResponse>(
    "post-trade-excursion",
    () => fetchExcursion({ limit: 100 }),
    { refreshInterval: 60_000, shouldRetryOnError: false }
  );
  const et = useSWR<EntryTimingResponse>(
    "post-trade-entry-timing",
    () => fetchEntryTiming({ limit: 100 }),
    { refreshInterval: 60_000, shouldRetryOnError: false }
  );

  const ea = exc.data?.aggregates;
  const ta = et.data?.aggregates;
  const loading = exc.isLoading || et.isLoading;
  const bothFailed = !!exc.error && !!et.error;
  const havePopulated = (ea?.populated_count ?? 0) > 0 || (ta?.computed_count ?? 0) > 0;

  // Avg regret = the most-favorable average offset delta (best the book could've
  // done by retiming entries). Positive = PnL left on the table.
  const bestOffset = ta?.best_avg_offset ?? null;
  const avgRegret =
    bestOffset != null ? ta?.avg_delta_by_offset?.[String(bestOffset)] ?? null : null;

  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-foreground tracking-wide">Post-Trade Quality</h3>
        {ta?.systematic_bias && (
          <Badge variant={biasVariant(ta.systematic_bias)}>entries {ta.systematic_bias}</Badge>
        )}
      </div>

      {loading ? (
        <p className="text-xs text-muted-foreground py-2">Loading post-trade analytics…</p>
      ) : bothFailed ? (
        <p className="text-xs text-muted-foreground py-2">Post-trade analytics unavailable.</p>
      ) : !havePopulated ? (
        <p className="text-xs text-muted-foreground py-2">
          Post-trade analytics pending — MAE/MFE and entry-timing populate as closed paper trades
          accrue and the excursion backfill runs.
        </p>
      ) : (
        <>
          <div className="grid grid-cols-3 gap-3">
            <Stat label="MFE capture" value={ratio(ea?.avg_mfe_capture_ratio)} tone="muted" />
            <Stat label="Avg MFE" value={pct(ea?.avg_mfe_pct)} tone="bull" />
            <Stat label="Avg MAE" value={pct(ea?.avg_mae_pct)} tone="bear" />
          </div>
          <div className="mt-3 border-t border-border pt-3 flex items-center justify-between">
            <div>
              <p className="text-[11px] uppercase tracking-wider text-muted-foreground">Avg entry-timing regret</p>
              <p className="text-sm font-mono text-foreground">
                {avgRegret != null ? signedUsd(avgRegret) : "—"}
                <span className="text-[11px] text-muted-foreground ml-1.5">
                  best at {offsetWord(bestOffset)}
                </span>
              </p>
            </div>
            <span className="text-[11px] text-muted-foreground">
              {ea?.populated_count ?? 0} trades · capture→1 = exits near peak
            </span>
          </div>
        </>
      )}
    </div>
  );
}
