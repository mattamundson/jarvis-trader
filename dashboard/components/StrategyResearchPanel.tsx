"use client";

import { POLL_INTERVAL } from "@/lib/polling-config";

import useSWR from "swr";
import {
  fetchResearchCandidates,
  type ResearchCandidate,
  type ResearchCandidatesResponse,
} from "@/lib/api";

// Class-independent gate thresholds (same as gate-v2 CORE). The MC-DD ceiling is
// class-dependent — long-biased equity is judged against an equity-class bar
// (~25%), not the 6% intraday-futures ceiling — so DD is shown as context, not
// a hard pass/fail here (see class_note on each card).
const T_PF = 1.1;
const T_PEDGE = 0.95;
const T_DSR = 0.1;
const EQUITY_DD_CEILING = 25.0;

function isRefuted(c: ResearchCandidate): boolean {
  return /refuted/i.test(c.class_note ?? "");
}

/** A candidate is a "real edge" when the three class-independent gates pass. */
function isRealEdge(c: ResearchCandidate): boolean {
  return (
    (c.pf_ci_lower ?? 0) >= T_PF &&
    (c.p_edge ?? 0) >= T_PEDGE &&
    (c.dsr ?? 0) >= T_DSR &&
    !isRefuted(c)
  );
}

function tileStyle(passed: boolean | null): { bg: string; border: string } {
  if (passed === true) return { bg: "rgba(21,128,61,0.12)", border: "#15803d" };
  if (passed === false) return { bg: "rgba(185,28,28,0.12)", border: "#b91c1c" };
  return { bg: "rgba(120,120,120,0.10)", border: "#6b7280" };
}

function fmt(v: number | null, digits = 2): string {
  return v === null || !Number.isFinite(v) ? "—" : v.toFixed(digits);
}

function statusBadge(c: ResearchCandidate): { label: string; bg: string; border: string; color: string } {
  if (isRefuted(c)) return { label: "REFUTED", bg: "rgba(185,28,28,0.12)", border: "#b91c1c", color: "#f87171" };
  if (c.verdict === "PASS") return { label: "PASS", bg: "rgba(21,128,61,0.15)", border: "#15803d", color: "#4ade80" };
  if (isRealEdge(c)) return { label: "EDGE · DD-class", bg: "rgba(202,138,4,0.14)", border: "#ca8a04", color: "#facc15" };
  return { label: c.verdict ?? "—", bg: "rgba(120,120,120,0.10)", border: "#6b7280", color: "#9ca3af" };
}

function Tile({ label, value, passed, hint }: { label: string; value: string; passed: boolean | null; hint?: string }) {
  const s = tileStyle(passed);
  return (
    <div
      className="rounded-md px-2 py-1.5 flex flex-col gap-0.5"
      style={{ backgroundColor: s.bg, border: `1px solid ${s.border}` }}
      title={hint}
    >
      <span className="font-mono text-[10px] text-muted-foreground truncate">{label}</span>
      <span className="font-mono text-sm font-semibold text-foreground">{value}</span>
    </div>
  );
}

function CandidateCard({ c }: { c: ResearchCandidate }) {
  const sb = statusBadge(c);
  const ddPassEquity = c.mc_95th_dd_pct === null ? null : c.mc_95th_dd_pct <= EQUITY_DD_CEILING;
  return (
    <div className="border border-border rounded-lg p-3 bg-card/60 flex flex-col gap-2">
      <div className="flex items-start justify-between gap-2">
        <div className="flex flex-col gap-0.5 min-w-0">
          {c.source_bookmark_url ? (
            <a
              href={c.source_bookmark_url}
              target="_blank"
              rel="noopener noreferrer"
              className="font-mono text-sm font-bold text-accent hover:underline truncate"
            >
              {c.strategy ?? "—"}
            </a>
          ) : (
            <span className="font-mono text-sm font-bold text-foreground truncate">{c.strategy ?? "—"}</span>
          )}
          <span className="font-mono text-[10px] text-muted-foreground">
            {c.symbol ?? "—"} · {c.family ?? "—"} · {c.strategy_class ?? "—"}
            {c.author ? ` · ${c.author}` : ""}
          </span>
        </div>
        <span
          className="font-mono text-[10px] font-bold shrink-0 rounded px-1.5 py-0.5"
          style={{ backgroundColor: sb.bg, border: `1px solid ${sb.border}`, color: sb.color }}
        >
          {sb.label}
        </span>
      </div>

      <div className="grid grid-cols-4 gap-1.5">
        <Tile label="PF-CI lo" value={fmt(c.pf_ci_lower)} passed={c.pf_ci_lower === null ? null : c.pf_ci_lower >= T_PF} hint={`>= ${T_PF}`} />
        <Tile label="P(edge)" value={fmt(c.p_edge)} passed={c.p_edge === null ? null : c.p_edge >= T_PEDGE} hint={`>= ${T_PEDGE}`} />
        <Tile label="DSR" value={fmt(c.dsr)} passed={c.dsr === null ? null : c.dsr >= T_DSR} hint={`>= ${T_DSR}`} />
        <Tile label="MC-DD %" value={fmt(c.mc_95th_dd_pct)} passed={ddPassEquity} hint={`equity class <= ${EQUITY_DD_CEILING}%`} />
      </div>

      {c.class_note && (
        <p className="font-mono text-[11px] text-muted-foreground leading-snug">{c.class_note}</p>
      )}
    </div>
  );
}

/**
 * Strategy Research — X-bookmark edge-scan candidates and their RESEARCH gate-v2
 * verdicts (GET /strategy/research-candidates). Non-authorizing namespace: these
 * never route capital; DD is judged against an equity-class ceiling, not the
 * intraday-futures 6% bar. Mirrors ProdGateScorecard's card + tile styling.
 */
export function StrategyResearchPanel() {
  const { data, error, isLoading } = useSWR<ResearchCandidatesResponse>(
    "research-candidates",
    fetchResearchCandidates,
    { refreshInterval: POLL_INTERVAL.FIVE_MINUTES }
  );

  const candidates = data?.candidates ?? [];
  const nReal = candidates.filter(isRealEdge).length;
  const nRefuted = candidates.filter(isRefuted).length;

  return (
    <div className="border border-border rounded-lg p-4 bg-card">
      <div className="flex items-baseline justify-between gap-3 mb-3">
        <h2 className="font-mono text-sm font-bold text-foreground">Strategy Research · Edge Candidates</h2>
        {data && (
          <span className="font-mono text-xs text-muted-foreground">
            {candidates.length} candidates · {nReal} real{nRefuted ? ` · ${nRefuted} refuted` : ""}
          </span>
        )}
      </div>

      {isLoading && <p className="text-xs text-muted-foreground">Loading research candidates…</p>}
      {error && <p className="text-xs text-destructive">Error loading research candidates</p>}
      {data && candidates.length === 0 && (
        <p className="text-xs text-muted-foreground">
          No research candidates yet. Run the X-bookmark edge-scan runners to populate.
        </p>
      )}

      {candidates.length > 0 && (
        <div className="flex flex-col gap-2">
          {candidates.map((c) => (
            <CandidateCard key={c.source_file ?? `${c.symbol}-${c.family}`} c={c} />
          ))}
        </div>
      )}

      <p className="font-mono text-[10px] text-muted-foreground/70 mt-3">
        Non-authorizing research namespace — never routes capital. DD judged vs equity-class ceiling.
      </p>
    </div>
  );
}
