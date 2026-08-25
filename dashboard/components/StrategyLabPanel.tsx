"use client";

import useSWR from "swr";
import { fetchEngine } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { POLL_INTERVAL } from "@/lib/polling-config";

// ── Strategy Lab results (GET /strategy-lab/results) ──────────────────────────
// LLM-driven autonomous strategy-variant search (engine/strategy_lab/). Results
// are LAB-ELIGIBLE only -- they pass the lab's own internal dual-gate (DD<15%,
// Sharpe>=1.2, Calmar>=0.8, PF>=1.8), NOT the production gate-v2 battery. The
// lab searches up to 20 variants per run and keeps only the best; showing a
// headline PF without the eligible/evaluated denominator would launder a
// best-of-N search as if it were a single validated result. POST
// /strategy-lab/run is intentionally never wired here (plan decision D7 -- v1
// is read-only display; the run job is a billable, uncancellable 20-iteration
// LLM loop with no progress endpoint).

interface StrategyLabMetrics {
  profit_factor?: number | null;
  pf?: number | null;
  sharpe_ratio?: number | null;
  sharpe?: number | null;
  total_trades?: number | null;
  n_trades?: number | null;
}

interface StrategyLabResult {
  strategy_name?: string | null;
  description?: string | null;
  verdict?: string | null;
  focus_area?: string | null;
  timestamp?: string | null;
  iteration?: number | null;
  metrics?: StrategyLabMetrics;
  violations?: string[];
}

interface StrategyLabStats {
  total_evaluated: number;
  eligible_count: number;
  best_pf: number;
}

interface StrategyLabResultsResponse {
  best_strategies: StrategyLabResult[];
  stats: StrategyLabStats;
  message: string;
}

async function fetchStrategyLabResults(): Promise<StrategyLabResultsResponse> {
  return fetchEngine<StrategyLabResultsResponse>("/strategy-lab/results");
}

function metricPf(m?: StrategyLabMetrics): number | null {
  const v = m?.profit_factor ?? m?.pf;
  return v === undefined || v === null ? null : v;
}

function metricSharpe(m?: StrategyLabMetrics): number | null {
  const v = m?.sharpe_ratio ?? m?.sharpe;
  return v === undefined || v === null ? null : v;
}

function metricTrades(m?: StrategyLabMetrics): number | null {
  const v = m?.total_trades ?? m?.n_trades;
  return v === undefined || v === null ? null : v;
}

function fmt(v: number | null, digits = 2): string {
  return v === null || !Number.isFinite(v) ? "—" : v.toFixed(digits);
}

/** The eligible/evaluated denominator -- must sit beside every headline PF number. */
function Denominator({ eligible, total }: { eligible: number; total: number }) {
  return (
    <span className="font-mono text-[10px] text-muted-foreground">
      {eligible} of {total} evaluated
    </span>
  );
}

function ResultCard({ r, stats }: { r: StrategyLabResult; stats: StrategyLabStats }) {
  const pf = metricPf(r.metrics);
  const sharpe = metricSharpe(r.metrics);
  const trades = metricTrades(r.metrics);
  const isEligible = r.verdict === "ELIGIBLE" || r.verdict == null;

  return (
    <div className="border border-border rounded-lg p-3 bg-card/60 flex flex-col gap-2">
      <div className="flex items-start justify-between gap-2">
        <div className="flex flex-col gap-0.5 min-w-0">
          <span className="font-mono text-sm font-bold text-foreground truncate">
            {r.strategy_name ?? "—"}
          </span>
          {r.focus_area && (
            <span className="font-mono text-[10px] text-muted-foreground truncate">{r.focus_area}</span>
          )}
        </div>
        {isEligible && <Badge variant="warn">LAB-ELIGIBLE &mdash; NOT GATE-V2 VALIDATED</Badge>}
      </div>

      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <span className="font-mono text-sm font-semibold text-foreground">PF {fmt(pf)}</span>
        <Denominator eligible={stats.eligible_count} total={stats.total_evaluated} />
        <span className="font-mono text-[11px] text-muted-foreground">
          Sharpe {fmt(sharpe)} &middot; N {trades ?? "—"}
        </span>
      </div>

      {r.description && (
        <p className="font-mono text-[11px] text-muted-foreground leading-snug">{r.description}</p>
      )}
    </div>
  );
}

/**
 * Strategy Lab — results from the autonomous LLM strategy-variant search
 * (engine/strategy_lab/, GET /strategy-lab/results). Folded into the existing
 * Strategy Research page rather than a new route. Read-only: the billable
 * POST /strategy-lab/run job is never exposed from the dashboard (D7).
 */
export function StrategyLabPanel() {
  const { data, error, isLoading } = useSWR<StrategyLabResultsResponse>(
    "strategy-lab-results",
    fetchStrategyLabResults,
    { refreshInterval: POLL_INTERVAL.MINUTE }
  );

  const results = data?.best_strategies ?? [];
  const stats = data?.stats ?? { total_evaluated: 0, eligible_count: 0, best_pf: 0 };

  return (
    <div className="border border-border rounded-lg p-4 bg-card">
      <div className="flex items-baseline justify-between gap-3 mb-3">
        <h2 className="font-mono text-sm font-bold text-foreground">Strategy Lab &middot; LLM Variant Search</h2>
        {data && (
          <span className="font-mono text-xs text-muted-foreground">
            best PF {fmt(stats.best_pf)} &middot; <Denominator eligible={stats.eligible_count} total={stats.total_evaluated} />
          </span>
        )}
      </div>

      {isLoading && <p className="text-xs text-muted-foreground">Loading strategy lab results…</p>}
      {error && <p className="text-xs text-destructive">Error loading strategy lab results</p>}
      {data && results.length === 0 && (
        <p className="text-xs text-muted-foreground">{data.message}</p>
      )}

      {results.length > 0 && (
        <div className="flex flex-col gap-2">
          {results.map((r, i) => (
            <ResultCard key={`${r.strategy_name ?? "variant"}-${r.iteration ?? i}`} r={r} stats={stats} />
          ))}
        </div>
      )}

      <p className="font-mono text-[10px] text-muted-foreground/70 mt-3">
        LLM-driven autonomous variant search (up to 20 iterations/run). LAB-ELIGIBLE means the lab's own
        internal dual-gate passed &mdash; not the production gate-v2 battery. Never routes capital.
      </p>
    </div>
  );
}
