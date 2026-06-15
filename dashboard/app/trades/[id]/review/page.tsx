"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import useSWR from "swr";
import { fetchTradeFullReview, type TradeFullReview } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

function fmt(v: any, digits = 2): string {
  return typeof v === "number" && Number.isFinite(v) ? v.toFixed(digits) : "—";
}

function pnlClass(v: number | null | undefined): string {
  if (typeof v !== "number") return "text-muted-foreground";
  return v > 0 ? "text-green-500" : v < 0 ? "text-red-500" : "text-muted-foreground";
}

function gradeVariant(g: string | undefined): "bull" | "warn" | "bear" | "neutral" {
  if (!g) return "neutral";
  if (g === "A" || g === "B") return "bull";
  if (g === "C") return "warn";
  return "bear";
}

function verdictVariant(v: string | null | undefined): "bull" | "bear" | "neutral" {
  if (v === "PASS") return "bull";
  if (v === "FAIL") return "bear";
  return "neutral";
}

function Stat({ label, value, className }: { label: string; value: React.ReactNode; className?: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</span>
      <span className={`font-mono text-sm ${className ?? ""}`}>{value}</span>
    </div>
  );
}

export default function TradeReviewPage() {
  const params = useParams();
  const id = String(params?.id ?? "");
  const { data, error, isLoading } = useSWR<TradeFullReview>(
    id ? `full-review-${id}` : null,
    () => fetchTradeFullReview(id),
    { refreshInterval: 30000 }
  );
  const [showPipeline, setShowPipeline] = useState(false);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-screen">
        <p className="text-muted-foreground">Loading trade review…</p>
      </div>
    );
  }
  if (error || !data) {
    return (
      <div className="flex flex-col items-center justify-center h-screen gap-2">
        <p className="text-destructive font-semibold">Error loading trade review</p>
        <p className="text-sm text-muted-foreground">{String(error ?? "not found")}</p>
        <Link href="/trades" className="text-xs text-blue-400 underline mt-2">← back to Trade History</Link>
      </div>
    );
  }

  const t = data.trade ?? {};
  const a = data.attribution ?? {};
  const w = data.why;
  const b = data.backtest;
  const f = data.forward;
  const r = data.review;
  const grade = r?.grade as string | undefined;

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex-shrink-0 px-6 py-4 border-b border-border">
        <div className="flex items-center gap-3">
          <Link href="/trades" className="text-xs text-blue-400 underline">← Trades</Link>
          <h1 className="font-mono text-lg font-bold text-foreground">
            {t.symbol ?? "—"} <span className="text-muted-foreground">·</span> Trade Review
          </h1>
          {grade && <Badge variant={gradeVariant(grade)}>Grade {grade}</Badge>}
          <Badge variant="neutral">{String(t.status ?? "—")}</Badge>
        </div>
        <div className="flex flex-wrap gap-x-8 gap-y-2 mt-3">
          <Stat label="Entry" value={fmt(t.entry_price)} />
          <Stat label="Exit" value={t.exit_price != null ? fmt(t.exit_price) : "—"} />
          <Stat label="P&L" value={t.pnl != null ? `$${fmt(t.pnl)}` : "—"} className={pnlClass(t.pnl)} />
          <Stat label="Side" value={String(t.side ?? "—")} />
          <Stat label="Entered" value={t.entry_time ? new Date(t.entry_time).toLocaleString() : "—"} />
          <Stat label="trade_id" value={<span className="text-[11px] text-muted-foreground">{String(t.trade_id ?? id)}</span>} />
        </div>
      </div>

      <div className="flex-1 overflow-auto px-6 py-4 grid grid-cols-1 xl:grid-cols-2 gap-4">
        {/* WHY IT FIRED */}
        <Card className="xl:col-span-2">
          <CardHeader>
            <CardTitle>Why it fired</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-x-8 gap-y-2 mb-3">
              <Stat label="Source" value={String(a.source ?? "—")} />
              <Stat label="Conviction" value={fmt(a.conviction)} />
              <Stat label="Direction" value={String(a.direction ?? a.bias ?? "—")} />
              <Stat label="Regime" value={String(a.regime ?? w?.regime ?? "—")} />
              {a.composite_score != null && <Stat label="Composite" value={fmt(a.composite_score)} />}
            </div>
            {w ? (
              <>
                <div className="flex flex-wrap gap-x-8 gap-y-2 border-t border-border pt-3">
                  <Stat label="Decision" value={`#${w.decision_id ?? "—"}`} />
                  <Stat label="Action" value={String(w.action ?? "—")} />
                  <Stat label="Confidence" value={fmt(w.confidence)} />
                  <Stat
                    label="Match"
                    value={w.match_delta_seconds != null ? `${Math.round(w.match_delta_seconds)}s` : "—"}
                  />
                  <Stat label="Decision time" value={w.timestamp ? new Date(w.timestamp).toLocaleString() : "—"} />
                </div>
                {w.reasoning && (
                  <p className="text-sm text-foreground/90 mt-3 whitespace-pre-wrap border-l-2 border-border pl-3">
                    {w.reasoning}
                  </p>
                )}
                {w.pipeline ? (
                  <div className="mt-3">
                    <button
                      onClick={() => setShowPipeline((s) => !s)}
                      className="text-xs text-blue-400 underline"
                    >
                      {showPipeline ? "Hide" : "Show"} full 5-stage pipeline transcript
                    </button>
                    {showPipeline && (
                      <pre className="mt-2 max-h-[480px] overflow-auto rounded-md bg-muted/40 p-3 text-[11px] leading-relaxed font-mono">
                        {JSON.stringify(w.pipeline, null, 2)}
                      </pre>
                    )}
                  </div>
                ) : (
                  <p className="text-xs text-muted-foreground mt-3">
                    No full pipeline transcript stored for the matched decision.
                  </p>
                )}
              </>
            ) : (
              <p className="text-xs text-muted-foreground border-t border-border pt-3">
                No decision matched this trade by symbol + time. It may be a logger-only or
                manually-placed trade without a pipeline decision record.
              </p>
            )}
          </CardContent>
        </Card>

        {/* STRATEGY BACKTEST */}
        <Card>
          <CardHeader>
            <CardTitle>Strategy backtest (gate-v2)</CardTitle>
          </CardHeader>
          <CardContent>
            {b ? (
              <>
                <div className="flex items-center gap-3 mb-3">
                  <Badge variant={verdictVariant(b.verdict)}>{b.verdict ?? "—"}</Badge>
                  <span className="font-mono text-sm text-muted-foreground">
                    {b.symbol} {b.family}{typeof b.rank === "number" ? ` #${b.rank}` : ""}
                    {b.passed_via ? ` · via ${b.passed_via}` : ""}
                  </span>
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                  <Stat label="PF-CI lower" value={fmt(b.pf_ci_lower)} />
                  <Stat label="p_edge" value={fmt(b.p_edge)} />
                  <Stat label="MC-95 DD %" value={fmt(b.mc_95th_dd_pct)} />
                  <Stat label="DSR" value={fmt(b.dsr)} />
                  <Stat label="WFO" value={b.wfo_consistency ?? "—"} />
                  <Stat label="OOS trades" value={b.oos_trades ?? "—"} />
                </div>
                <Link href="/strategy-ledger" className="text-xs text-blue-400 underline mt-3 inline-block">
                  view full strategy ledger →
                </Link>
              </>
            ) : (
              <p className="text-xs text-muted-foreground">
                No gate-v2 verdict found for {String(t.symbol ?? "this symbol")}.
              </p>
            )}
          </CardContent>
        </Card>

        {/* STRATEGY FORWARD TEST */}
        <Card>
          <CardHeader>
            <CardTitle>Forward test (live / paper)</CardTitle>
          </CardHeader>
          <CardContent>
            {f ? (
              <>
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                  <Stat label="Closed trades" value={f.total_trades} />
                  <Stat label="Win rate" value={`${fmt(f.win_rate * 100, 1)}%`} />
                  <Stat label="Profit factor" value={fmt(f.profit_factor)} />
                  <Stat label="Sharpe" value={fmt(f.sharpe_ratio)} />
                  <Stat label="Total P&L" value={`$${fmt(f.total_pnl)}`} className={pnlClass(f.total_pnl)} />
                  <Stat label="Max DD" value={`${fmt(f.max_drawdown * 100, 1)}%`} />
                </div>
                <div className="mt-3">
                  <Badge variant={f.meets_paper_threshold ? "bull" : "warn"}>
                    {f.meets_paper_threshold ? "meets paper threshold" : "below paper threshold"}
                  </Badge>
                  <span className="text-[11px] text-muted-foreground ml-2">
                    {f.total_trades} trades over {f.period_days}d for {String(t.symbol ?? "")}
                  </span>
                </div>
              </>
            ) : (
              <p className="text-xs text-muted-foreground">No forward-test stats available.</p>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
