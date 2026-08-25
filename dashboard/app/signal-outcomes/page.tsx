"use client";

import useSWR from "swr";
import { Target } from "lucide-react";
import {
  fetchSignalOutcomes,
  fetchSignalQuality,
  type SignalOutcome,
  type SignalOutcomesResponse,
  type SignalQualityResponse,
} from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { ConfidenceGauge } from "@/components/ConfidenceGauge";
import { ResultLabel } from "@/components/ResultLabel";
import { WidgetErrorBoundary } from "@/components/WidgetErrorBoundary";
import { MesForwardExperimentPanel } from "@/components/MesForwardExperimentPanel";

const REFRESH_MS = 120_000;

function fmt(v: number | null | undefined, digits = 2, suffix = ""): string {
  return v != null ? `${v.toFixed(digits)}${suffix}` : "—";
}

function signed(v: number | null | undefined, digits = 2): string {
  if (v == null) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(digits)}`;
}

const HIT_VARIANT: Record<string, "bull" | "bear" | "warn" | "neutral"> = {
  target1_hit: "bull",
  target2_hit: "bull",
  stop_hit: "bear",
  expired: "neutral",
  open: "neutral",
};

function StatCard({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "bull" | "bear" | "muted";
}) {
  const color =
    tone === "bull" ? "text-bull" : tone === "bear" ? "text-bear" : "text-foreground";
  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        {label}
      </p>
      <p className={`mt-1 font-mono text-2xl font-bold tabular-nums ${color}`}>{value}</p>
    </div>
  );
}

function OutcomeRow({ o }: { o: SignalOutcome }) {
  return (
    <tr className="border-b border-border/40 last:border-0">
      <td className="py-2 pr-3 font-mono text-xs text-muted-foreground whitespace-nowrap">
        {o.decision_date ?? "—"}
      </td>
      <td className="py-2 pr-3 font-mono text-xs font-semibold text-foreground">{o.symbol}</td>
      <td className="py-2 pr-3">
        <Badge variant={o.direction === "short" ? "bear" : "bull"}>{o.direction}</Badge>
      </td>
      <td className="py-2 pr-3 font-mono text-xs text-muted-foreground whitespace-nowrap">
        {fmt(o.entry_price)} / {fmt(o.stop_loss)} / {fmt(o.target_1)}
      </td>
      <td className="py-2 pr-3">
        <span title={o.note ?? undefined}>
          <Badge variant={HIT_VARIANT[o.hit] ?? "neutral"}>
            {o.evaluable ? o.hit.replace(/_/g, " ") : "not evaluated"}
          </Badge>
        </span>
      </td>
      <td className="py-2 pr-3 font-mono text-xs text-muted-foreground">{fmt(o.mfe_pct, 2, "%")}</td>
      <td className="py-2 pr-3 font-mono text-xs text-muted-foreground">{fmt(o.mae_pct, 2, "%")}</td>
      <td
        className={`py-2 pr-3 font-mono text-xs ${
          (o.hypothetical_pnl_pct ?? 0) > 0
            ? "text-bull"
            : (o.hypothetical_pnl_pct ?? 0) < 0
            ? "text-bear"
            : "text-muted-foreground"
        }`}
      >
        {o.hypothetical_pnl_pct != null ? `${signed(o.hypothetical_pnl_pct)}%` : "—"}
      </td>
      <td className="py-2 font-mono text-xs text-muted-foreground">
        {o.confidence != null ? `${Math.round(o.confidence * 100)}%` : "—"}
      </td>
    </tr>
  );
}

function QualityCard() {
  const { data, error } = useSWR<SignalQualityResponse>(
    "/analytics/signal-quality",
    fetchSignalQuality,
    { refreshInterval: REFRESH_MS, shouldRetryOnError: false }
  );

  return (
    <div className="rounded-xl border border-border bg-card p-4 space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-semibold text-foreground">
          Signal Quality (executed trades)
        </span>
        <ResultLabel kind="paper" />
      </div>
      {error ? (
        <p className="text-xs text-muted-foreground">
          /analytics/signal-quality unreachable — engine offline or endpoint not deployed.
        </p>
      ) : !data ? (
        <p className="text-xs text-muted-foreground animate-pulse">Loading signal quality…</p>
      ) : data.overall.total_signals === 0 ? (
        <p className="text-xs text-muted-foreground">No graded signals yet.</p>
      ) : (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
            <div>
              <p className="text-muted-foreground">Accuracy</p>
              {/* Engine SignalMetrics.accuracy is a 0-1 fraction — scale for display. */}
              <p className="font-mono text-foreground">{fmt(data.overall.accuracy * 100, 1, "%")}</p>
            </div>
            <div>
              <p className="text-muted-foreground">Signals graded</p>
              <p className="font-mono text-foreground">{data.overall.total_signals}</p>
            </div>
            <div>
              <p className="text-muted-foreground">Best time of day</p>
              <p className="font-mono text-foreground">{data.overall.best_time_of_day || "—"}</p>
            </div>
            <div>
              <p className="text-muted-foreground">Worst time of day</p>
              <p className="font-mono text-foreground">{data.overall.worst_time_of_day || "—"}</p>
            </div>
          </div>
          {Object.keys(data.by_regime).length > 0 && (
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-1">
                By regime at signal time
              </p>
              <div className="flex flex-wrap gap-1.5">
                {Object.entries(data.by_regime).map(([regime, m]) => (
                  <Badge key={regime} variant={m.accuracy >= 0.5 ? "bull" : "warn"}>
                    {regime} · {fmt(m.accuracy * 100, 0, "%")} ({m.total_signals})
                  </Badge>
                ))}
              </div>
            </div>
          )}
          {data.recommendations.length > 0 && (
            <ul className="text-[11px] text-muted-foreground list-disc pl-4 space-y-0.5">
              {data.recommendations.slice(0, 4).map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}

/**
 * Signal-outcome scoreboard — "did our predictions pay off?" Every recent
 * directional pipeline decision scored against subsequent daily bars
 * (hit/stop/expired, MFE/MAE, hypothetical P&L), regardless of whether the
 * trade executed. Amo-arbitrage's signal-outcomes pattern applied to
 * jarvis's own pipeline. Display-only; nothing here feeds a trade decision.
 */
export default function SignalOutcomesPage() {
  const { data, error } = useSWR<SignalOutcomesResponse>(
    "/analytics/signal-outcomes",
    fetchSignalOutcomes,
    { refreshInterval: REFRESH_MS, shouldRetryOnError: false }
  );

  const agg = data?.aggregate;

  return (
    <div className="p-4 sm:p-6 max-w-6xl mx-auto space-y-6">
      <div className="flex items-center gap-3">
        <Target className="h-5 w-5 text-accent" />
        <div>
          <h1 className="text-lg font-bold text-foreground flex items-center gap-2">
            Signal Outcomes
            <ResultLabel
              kind="signal"
              hint="Scores the pipeline's emitted signals against what the market did next. Hypothetical fills — not an executed-trade P&L record."
            />
          </h1>
          <p className="text-xs text-muted-foreground">
            Did past predictions pay off? Recent directional decisions scored against
            subsequent daily bars — executed or not. Daily-bar granularity: a
            ~10-trading-day horizon read of each signal&apos;s geometry, not a
            live-trade replay (same-day resolution of 1h signals is not captured).
            {data?.universe && <> Universe: {data.universe}.</>}
          </p>
        </div>
      </div>

      {/* Headline aggregate */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          label="Hit rate (T1+T2)"
          value={agg?.hit_rate != null ? `${agg.hit_rate.toFixed(1)}%` : "—"}
          tone={agg?.hit_rate != null ? (agg.hit_rate >= 50 ? "bull" : "bear") : "muted"}
        />
        <StatCard
          label="Avg hypothetical P&L"
          value={agg?.avg_hypothetical_pnl_pct != null ? `${signed(agg.avg_hypothetical_pnl_pct)}%` : "—"}
          tone={
            agg?.avg_hypothetical_pnl_pct != null
              ? agg.avg_hypothetical_pnl_pct >= 0
                ? "bull"
                : "bear"
              : "muted"
          }
        />
        <StatCard label="Resolved" value={agg ? String(agg.total_evaluated) : "—"} tone="muted" />
        <StatCard label="Signals scored" value={agg ? String(agg.total_signals) : "—"} tone="muted" />
      </div>

      {/* Calibration + executed-trade quality side by side */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <WidgetErrorBoundary name="Calibration">
          <ConfidenceGauge />
        </WidgetErrorBoundary>
        <WidgetErrorBoundary name="Signal Quality">
          <QualityCard />
        </WidgetErrorBoundary>
      </div>

      {/* MES forward experiment -- daily session-hypothesis recorder, coverage-first */}
      <WidgetErrorBoundary name="MES Forward Experiment">
        <MesForwardExperimentPanel />
      </WidgetErrorBoundary>

      {/* Outcomes table */}
      <div className="rounded-xl border border-border bg-card p-4 space-y-3">
        <div className="flex items-center justify-between">
          <span className="text-sm font-semibold text-foreground">Recent Signals</span>
          {data?.model && (
            <span className="text-[10px] text-muted-foreground max-w-[50%] truncate" title={data.model}>
              {data.model}
            </span>
          )}
        </div>
        {error ? (
          <p className="text-xs text-muted-foreground">
            /analytics/signal-outcomes unreachable — engine offline or endpoint not deployed.
          </p>
        ) : !data ? (
          <p className="text-xs text-muted-foreground animate-pulse">Scoring recent signals…</p>
        ) : !data.available ? (
          <p className="text-xs text-muted-foreground">
            Outcomes unavailable{data.note ? ` — ${data.note}` : ""}.
          </p>
        ) : data.outcomes.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            No directional decisions recorded yet — nothing to score.
          </p>
        ) : (
          <>
            {data.note && <p className="text-[11px] text-warn">{data.note}</p>}
            <div className="overflow-x-auto">
              <table className="w-full text-left">
                <thead>
                  <tr className="text-[10px] uppercase tracking-wider text-muted-foreground border-b border-border">
                    <th className="py-2 pr-3 font-semibold">Date</th>
                    <th className="py-2 pr-3 font-semibold">Symbol</th>
                    <th className="py-2 pr-3 font-semibold">Dir</th>
                    <th className="py-2 pr-3 font-semibold">Entry / Stop / T1</th>
                    <th className="py-2 pr-3 font-semibold">Outcome</th>
                    <th className="py-2 pr-3 font-semibold">MFE</th>
                    <th className="py-2 pr-3 font-semibold">MAE</th>
                    <th className="py-2 pr-3 font-semibold">Hyp. P&L</th>
                    <th className="py-2 font-semibold">Conf</th>
                  </tr>
                </thead>
                <tbody>
                  {data.outcomes.map((o) => (
                    <OutcomeRow key={`${o.approval_id ?? ""}-${o.symbol}-${o.decision_date ?? ""}`} o={o} />
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
