"use client";

import useSWR from "swr";
import { AlertTriangle, CheckCircle2, ShieldAlert } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

type BadgeKey =
  | "operator_analysis_ready"
  | "monitoring_ready"
  | "execution_ready"
  | "recommendation_attribution_proven"
  | "queue_order_lineage_proven"
  | "edge_certified";

interface ReadinessScorecard {
  schema_version: "jarvis-readiness-scorecard.v1";
  generated_at?: string;
  mode: "READ_ONLY_ANALYSIS";
  badges: Record<BadgeKey, boolean>;
  metrics: {
    dashboard_ok: boolean;
    engine_ok: boolean;
    current_actionable_shown?: number;
    current_actionable_raw?: number;
    pending_approvals?: number;
    unique_linked_paper_trades: number;
    linked_rth_paper_trades: number;
    queue_order_id_matches_to_paper: number;
    linked_closed_pnl: number;
    linked_profit_factor: number;
    rth_linked_closed_pnl: number;
    rth_linked_profit_factor: number;
    linked_vs_unlinked_pnl_delta?: number;
    linked_vs_all_paper_avg_trade_delta?: number;
  };
  blockers: string[];
  display_notes: string[];
}

const FEED_URL = "/api/jarvis/readiness-scorecard";

const BADGE_COPY: { key: BadgeKey; label: string; positive: string; negative: string }[] = [
  {
    key: "operator_analysis_ready",
    label: "Analysis",
    positive: "operator analysis ready",
    negative: "analysis degraded",
  },
  {
    key: "monitoring_ready",
    label: "Monitoring",
    positive: "monitoring ready",
    negative: "monitoring degraded",
  },
  {
    key: "execution_ready",
    label: "Execution",
    positive: "execution ready",
    negative: "execution blocked",
  },
  {
    key: "recommendation_attribution_proven",
    label: "Attribution",
    positive: "recommendation linked",
    negative: "attribution missing",
  },
  {
    key: "queue_order_lineage_proven",
    label: "Lineage",
    positive: "queue lineage proven",
    negative: "queue lineage gap",
  },
  {
    key: "edge_certified",
    label: "Edge",
    positive: "edge certified",
    negative: "edge not certified",
  },
];

function fmtCurrency(value: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(value);
}

export function ReadinessScorecardPanel() {
  const { data, error, isLoading } = useSWR<ReadinessScorecard>(
    FEED_URL,
    (url: string) => fetch(url).then((r) => r.json())
  );

  const generatedAt = data?.generated_at
    ? new Date(data.generated_at).toLocaleString()
    : "unknown";

  return (
    <Card>
      <CardHeader className="space-y-2 pb-2">
        <div className="flex items-center justify-between gap-3">
          <CardTitle className="flex items-center gap-2 text-sm font-medium">
            <ShieldAlert className="h-4 w-4 text-amber-400" />
            Readiness Scorecard
          </CardTitle>
          <Badge variant="neutral" className="text-[10px] text-zinc-400">
            {data?.mode ?? "READ_ONLY"}
          </Badge>
        </div>
        <p className="text-[11px] text-zinc-500">
          Analysis, monitoring, execution, and recommendation-lineage truth split. Generated {generatedAt}.
        </p>
      </CardHeader>
      <CardContent>
        {error ? (
          <div className="flex items-center gap-2 text-xs text-red-400">
            <AlertTriangle className="h-4 w-4" /> Failed to load readiness scorecard
          </div>
        ) : isLoading ? (
          <div className="text-xs text-zinc-500">Loading readiness…</div>
        ) : data ? (
          <div className="space-y-4">
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {BADGE_COPY.map((item) => {
                const ok = data.badges[item.key];
                return (
                  <div
                    key={item.key}
                    className="flex items-center justify-between rounded-md border border-zinc-800 bg-zinc-900/40 px-2.5 py-2"
                  >
                    <span className="text-[11px] text-zinc-400">{item.label}</span>
                    <Badge variant={ok ? "bull" : "warn"} className="text-[10px]">
                      {ok ? item.positive : item.negative}
                    </Badge>
                  </div>
                );
              })}
            </div>

            <div className="grid grid-cols-3 gap-2 rounded-lg border border-zinc-800 bg-zinc-950/60 p-2 text-center">
              <div>
                <div className="text-sm font-semibold text-zinc-100">
                  {data.metrics.unique_linked_paper_trades}
                </div>
                <div className="text-[10px] uppercase tracking-wide text-zinc-500">linked trades</div>
              </div>
              <div>
                <div className="text-sm font-semibold text-emerald-300">
                  {fmtCurrency(data.metrics.linked_closed_pnl)}
                </div>
                <div className="text-[10px] uppercase tracking-wide text-zinc-500">linked P&L</div>
              </div>
              <div>
                <div className="text-sm font-semibold text-amber-300">
                  {data.metrics.queue_order_id_matches_to_paper}
                </div>
                <div className="text-[10px] uppercase tracking-wide text-zinc-500">order matches</div>
              </div>
            </div>

            <div className="rounded-lg border border-zinc-800 bg-zinc-950/60 p-2 text-[11px] text-zinc-400">
              <div className="mb-1 font-semibold text-zinc-300">Baseline delta</div>
              <div className="flex flex-wrap gap-x-4 gap-y-1">
                <span>
                  linked vs unlinked P&L:{" "}
                  <span className="text-emerald-300">
                    {fmtCurrency(data.metrics.linked_vs_unlinked_pnl_delta ?? 0)}
                  </span>
                </span>
                <span>
                  avg/trade vs all paper:{" "}
                  <span className="text-emerald-300">
                    {fmtCurrency(data.metrics.linked_vs_all_paper_avg_trade_delta ?? 0)}
                  </span>
                </span>
              </div>
            </div>

            {data.blockers.length > 0 && (
              <div className="rounded-md border border-amber-500/20 bg-amber-500/5 p-2">
                <div className="mb-1 flex items-center gap-1.5 text-[11px] font-semibold text-amber-300">
                  <AlertTriangle className="h-3.5 w-3.5" /> Execution / trust blockers
                </div>
                <ul className="space-y-0.5 text-[11px] text-zinc-400">
                  {data.blockers.slice(0, 4).map((blocker) => (
                    <li key={blocker}>• {blocker}</li>
                  ))}
                </ul>
              </div>
            )}

            <p className="flex items-start gap-1.5 text-[10px] leading-snug text-zinc-600">
              <CheckCircle2 className="mt-0.5 h-3 w-3 shrink-0 text-emerald-500" />
              Read-only scorecard: does not change live trading, risk, kill switch, broker execution, or symbol gates.
            </p>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

export default ReadinessScorecardPanel;
