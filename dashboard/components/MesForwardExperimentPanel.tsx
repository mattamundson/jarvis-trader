"use client";

import useSWR from "swr";
import { FlaskConical } from "lucide-react";
import { fetchMesForwardSummary, type MesForwardSummaryResponse } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { POLL_INTERVAL } from "@/lib/polling-config";

// ── MES forward experiment (GET /experiments/mes-forward/summary) ──────────
// The mes_session_hypothesis table accumulates ONE row per (date, symbol) --
// it grows by roughly one row per trading day. Early on that means any
// hit-rate is computed over a handful of rows. This panel's entire reason to
// exist (per Plan Phase 8 row 6) is to make that coverage impossible to miss:
// every hit-rate number renders with its own "N of M rows" denominator right
// next to it, and a small-sample warning badge fires below a fixed threshold
// so "100% hit rate" over 4 rows cannot visually read as a validated edge.

// Below this many outcome-bearing rows, treat the hit-rate as not yet
// statistically meaningful. 20 is a conservative floor -- even 20 binary
// trials leaves a wide confidence interval, but it's enough to distinguish
// "the experiment just started" from "we have a real sample."
const SMALL_SAMPLE_THRESHOLD = 20;

function pct(v: number | null | undefined, digits = 1): string {
  return v != null && Number.isFinite(v) ? `${(v * 100).toFixed(digits)}%` : "—";
}

function SideRow({ label, n, wins, losses, hitRate, totalRows }: {
  label: string;
  n: number;
  wins: number;
  losses: number;
  hitRate: number;
  totalRows: number;
}) {
  const smallSample = n < SMALL_SAMPLE_THRESHOLD;
  return (
    <div className="flex items-center justify-between gap-3 rounded-lg border border-border bg-card/60 px-3 py-2">
      <div className="flex items-center gap-2 min-w-0">
        <span className="font-mono text-xs font-semibold text-foreground uppercase">{label}</span>
        {smallSample && (
          <Badge variant="warn" className="text-[10px] px-1.5 py-0">
            small sample
          </Badge>
        )}
      </div>
      <div className="flex items-baseline gap-2 shrink-0">
        <span className="font-mono text-sm font-bold text-foreground">{pct(hitRate)}</span>
        <span className="font-mono text-[10px] text-muted-foreground">
          {wins} of {n} rows
          {totalRows > 0 && <> &middot; {n} of {totalRows} total</>}
        </span>
        <span className="font-mono text-[10px] text-muted-foreground">({losses} losses)</span>
      </div>
    </div>
  );
}

/**
 * MES session forward-experiment panel. Read-only aggregate view of the
 * mes_session_hypothesis forward-recorder (engine /experiments/mes-forward/*).
 * Mounted on /signal-outcomes -- a sibling honesty-first display, same as the
 * signal-outcomes scoreboard above it on the page.
 */
export function MesForwardExperimentPanel() {
  const { data, error, isLoading } = useSWR<MesForwardSummaryResponse>(
    "mes-forward-summary",
    fetchMesForwardSummary,
    { refreshInterval: POLL_INTERVAL.MINUTE, shouldRetryOnError: false }
  );

  const overall = data?.overall_non_skip;
  const totalRows = data?.n_rows ?? 0;
  const withOutcome = data?.n_with_outcome ?? 0;
  const overallSmallSample = (overall?.n ?? 0) < SMALL_SAMPLE_THRESHOLD;

  return (
    <div className="rounded-xl border border-border bg-card p-4 space-y-3">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <FlaskConical className="h-4 w-4 text-accent" />
          <span className="text-sm font-semibold text-foreground">MES Forward Experiment</span>
        </div>
        {data && (
          <span className="font-mono text-[10px] text-muted-foreground">
            {withOutcome} of {totalRows} rows have a recorded outcome
          </span>
        )}
      </div>

      <p className="text-[11px] text-muted-foreground">
        Daily session-open hypothesis (Corey bias) recorded against the actual session outcome.
        One row accrues per trading day, so any hit-rate below is only as strong as its sample size.
      </p>

      {isLoading && !data && (
        <p className="text-xs text-muted-foreground animate-pulse">Loading forward-experiment summary…</p>
      )}
      {error && (
        <p className="text-xs text-muted-foreground">
          /experiments/mes-forward/summary unreachable — engine offline or endpoint not deployed.
        </p>
      )}
      {data && totalRows === 0 && (
        <p className="text-xs text-muted-foreground">No forward-experiment rows recorded yet.</p>
      )}

      {data && totalRows > 0 && overall && (
        <>
          {/* Headline coverage ratio -- the load-bearing number per spec */}
          <div className="flex items-center justify-between gap-3 rounded-lg border border-warn/30 bg-warn/5 px-3 py-2">
            <div className="flex items-center gap-2">
              <span className="font-mono text-xs font-semibold text-foreground">Overall hit rate</span>
              {overallSmallSample && (
                <Badge variant="warn">SMALL SAMPLE — LOW CONFIDENCE</Badge>
              )}
            </div>
            <div className="flex items-baseline gap-2">
              <span className="font-mono text-lg font-bold text-foreground">{pct(overall.hit_rate)}</span>
              <span className="font-mono text-[11px] text-muted-foreground">
                {overall.wins} of {overall.n} rows
                {totalRows > 0 && <> ({overall.n} of {totalRows} total rows recorded)</>}
              </span>
            </div>
          </div>

          {/* By-side breakdown, same denominator discipline */}
          {Object.keys(data.by_side).length > 0 && (
            <div className="space-y-1.5">
              {Object.entries(data.by_side).map(([side, s]) => (
                <SideRow
                  key={side}
                  label={side}
                  n={s.n}
                  wins={s.wins}
                  losses={s.losses}
                  hitRate={s.hit_rate}
                  totalRows={totalRows}
                />
              ))}
            </div>
          )}

          <p className="font-mono text-[10px] text-muted-foreground/70">
            {data.n_pending_outcome} row{data.n_pending_outcome !== 1 ? "s" : ""} pending outcome
            {data.first_date && data.last_date && <> &middot; {data.first_date} → {data.last_date}</>}
            . Advisory only — never routes capital.
          </p>
        </>
      )}
    </div>
  );
}
