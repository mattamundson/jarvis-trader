"use client";

import { useEffect, useState } from "react";
import {
  FlaskConical,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  TrendingUp,
} from "lucide-react";
import { fetchEngine } from "@/lib/api";
import type {
  ForwardTestReport,
  ForwardTestCandidate,
  ForwardTestLineage,
} from "@/lib/api";

const POLL_MS = 60_000; // forward-test verdict changes at most daily; 60s is plenty

function pnlColor(v: number): string {
  return v > 0 ? "text-bull" : v < 0 ? "text-bear" : "text-muted-foreground";
}

/**
 * Per-candidate verdict glyph. Graduation is the loud, rare win. Precise
 * attribution that has not graduated is "tracking"; symbol-level attribution is
 * context only (the trade was not tagged with a candidate_id, so it can never
 * graduate) and is rendered muted so it never reads as progress toward an edge.
 */
function CandidateRow({ c }: { c: ForwardTestCandidate }) {
  const Icon = c.graduated
    ? CheckCircle2
    : c.precise_attribution
    ? TrendingUp
    : AlertTriangle;
  const color = c.graduated
    ? "text-bull"
    : c.precise_attribution
    ? "text-accent"
    : "text-muted-foreground";

  const f = c.forward;
  return (
    <div className="flex items-center justify-between gap-2 py-1.5 border-b border-border/40 last:border-0">
      <div className="flex items-center gap-2 min-w-0">
        <Icon className={`h-3.5 w-3.5 shrink-0 ${color}`} />
        <div className="min-w-0">
          <p className="text-xs font-medium text-foreground truncate">
            {c.id}
          </p>
          <p className="text-[10px] text-muted-foreground truncate">
            {c.graduated
              ? "GRADUATED"
              : c.precise_attribution
              ? "tracking (tagged)"
              : "context only — untagged"}
            {" · "}
            {f.n_oos_windows} OOS win · {f.total_trades} trades
          </p>
        </div>
      </div>
      <div className="text-right shrink-0">
        <p className={`text-xs font-mono ${pnlColor(f.total_pnl)}`}>
          {f.total_pnl >= 0 ? "+" : ""}
          {f.total_pnl.toFixed(0)}
        </p>
        <p className="text-[10px] text-muted-foreground font-mono">
          PF-CI {f.pf_ci_lower.toFixed(2)} · p {f.p_edge.toFixed(2)}
        </p>
      </div>
    </div>
  );
}

/**
 * Per-lineage verdict glyph. A decision lineage is the LLM identity that
 * actually trades live (P4). Graduation is the loud win; a pre-registered
 * lineage that has not graduated is "tracking"; a default-material
 * (unregistered) lineage is context only — it can clear the stats but can never
 * graduate, so it renders muted and is labelled so it never reads as an edge.
 */
function LineageRow({ l }: { l: ForwardTestLineage }) {
  const Icon = l.graduated
    ? CheckCircle2
    : l.pre_registered
    ? TrendingUp
    : AlertTriangle;
  const color = l.graduated
    ? "text-bull"
    : l.pre_registered
    ? "text-accent"
    : "text-muted-foreground";

  const f = l.forward;
  return (
    <div className="flex items-center justify-between gap-2 py-1.5 border-b border-border/40 last:border-0">
      <div className="flex items-center gap-2 min-w-0">
        <Icon className={`h-3.5 w-3.5 shrink-0 ${color}`} />
        <div className="min-w-0">
          <p className="text-xs font-mono text-foreground truncate">
            {l.lineage}
          </p>
          <p className="text-[10px] text-muted-foreground truncate">
            {l.graduated
              ? "GRADUATED"
              : l.pre_registered
              ? "tracking (pre-registered)"
              : "context only — unregistered"}
            {" · "}
            {f.n_oos_windows} OOS win · {f.total_trades} trades
          </p>
        </div>
      </div>
      <div className="text-right shrink-0">
        <p className={`text-xs font-mono ${pnlColor(f.total_pnl)}`}>
          {f.total_pnl >= 0 ? "+" : ""}
          {f.total_pnl.toFixed(0)}
        </p>
        <p className="text-[10px] text-muted-foreground font-mono">
          PF-CI {f.pf_ci_lower.toFixed(2)} · p {f.p_edge.toFixed(2)}
        </p>
      </div>
    </div>
  );
}

export function ForwardTestPanel() {
  const [data, setData] = useState<ForwardTestReport | null>(null);
  const [error, setError] = useState(false);

  async function refresh() {
    try {
      const payload = await fetchEngine<ForwardTestReport>(
        "/analytics/forward-test"
      );
      setData(payload);
      setError(false);
    } catch {
      // Endpoint absent until the forward-test stack merges + engine restarts.
      setError(true);
      setData(null);
    }
  }

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, POLL_MS);
    return () => clearInterval(id);
  }, []);

  const lineages = data?.lineages ?? [];
  const lineagesGraduated = data?.n_lineages_graduated ?? 0;
  const insufficient =
    !!data &&
    (data.status === "INSUFFICIENT_DATA" ||
      (data.candidates.length === 0 && lineages.length === 0));
  // Lineages are the unit that actually trades live, so a graduated lineage is
  // the real headline; candidate graduations fold in behind it.
  const graduated = (data?.n_graduated ?? 0) + lineagesGraduated;

  return (
    <div className="rounded-xl border border-border bg-card p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <FlaskConical className="h-4 w-4 text-accent" />
          <span className="text-sm font-semibold text-foreground">
            Forward Test
          </span>
        </div>
        {data && !insufficient && (
          <span
            className={`text-[11px] font-semibold ${
              graduated > 0 ? "text-bull" : "text-muted-foreground"
            }`}
          >
            {graduated > 0
              ? `${graduated} GRADUATED`
              : `${data.n_active_candidates} tracking`}
          </span>
        )}
      </div>

      {error ? (
        <div className="flex items-center gap-1.5 rounded-lg bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
          <XCircle className="h-3.5 w-3.5" />
          Forward-test endpoint not available (engine restart pending)
        </div>
      ) : !data ? (
        <p className="text-xs text-muted-foreground">Loading…</p>
      ) : insufficient ? (
        <div className="flex items-center gap-1.5 rounded-lg bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
          <AlertTriangle className="h-3.5 w-3.5" />
          {data.recommendation ??
            "No active candidates with a forward record yet."}
        </div>
      ) : (
        <>
          {data.candidates.length > 0 && (
            <div className="space-y-0">
              {data.candidates.map((c) => (
                <CandidateRow key={c.id} c={c} />
              ))}
            </div>
          )}
          {lineages.length > 0 && (
            <div className="space-y-0">
              <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground/70 pt-1 pb-0.5">
                Decision lineages · LLM path (trades live)
              </p>
              {lineages.map((l) => (
                <LineageRow key={l.lineage} l={l} />
              ))}
            </div>
          )}
          {data.note && (
            <p className="text-[10px] text-muted-foreground/80 leading-snug pt-1">
              {data.note}
            </p>
          )}
        </>
      )}
    </div>
  );
}
