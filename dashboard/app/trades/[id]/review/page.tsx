"use client";

import { useMemo, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import dynamic from "next/dynamic";
import useSWR from "swr";
import { fetchTradeFullReview, fetchBars, type TradeFullReview, type OHLCVBar } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { SeriesMarker, Time } from "lightweight-charts";

// lightweight-charts backed candle view — only renders once `bars` has loaded, so defer
// the chunk instead of paying for it in the initial route JS.
const CandlestickChart = dynamic(
  () => import("@/components/command-center/charts/CandlestickChart").then((m) => ({ default: m.CandlestickChart })),
  { ssr: false, loading: () => <div className="h-[420px] animate-pulse rounded-md bg-muted/20" /> }
);

// Both panels are gated behind `Boolean(t.symbol)` at render time (i.e. only after the
// trade record has loaded) — defer their JS the same way.
const ExcursionPanel = dynamic(
  () => import("@/components/ExcursionPanel").then((m) => ({ default: m.ExcursionPanel })),
  { ssr: false, loading: () => <div className="h-40 animate-pulse rounded-md bg-muted/20" /> }
);
const EntryTimingScenarios = dynamic(
  () => import("@/components/EntryTimingScenarios").then((m) => ({ default: m.EntryTimingScenarios })),
  { ssr: false, loading: () => <div className="h-40 animate-pulse rounded-md bg-muted/20" /> }
);

/** Pick a bar timeframe + lookback window sized to how old the trade is. */
function chartWindow(entryTime: string | null | undefined): { timeframe: string; days: number } {
  if (!entryTime) return { timeframe: "15m", days: 14 };
  const ageDays = (Date.now() - new Date(entryTime).getTime()) / 86_400_000;
  if (!Number.isFinite(ageDays) || ageDays < 2) return { timeframe: "5m", days: 3 };
  if (ageDays < 10) return { timeframe: "15m", days: 14 };
  if (ageDays < 45) return { timeframe: "1h", days: 60 };
  return { timeframe: "1d", days: 365 };
}

function toUnix(ts: string | null | undefined): number | null {
  if (!ts) return null;
  const ms = new Date(ts).getTime();
  return Number.isFinite(ms) ? Math.floor(ms / 1000) : null;
}

function num(v: unknown): number | null {
  const n = typeof v === "string" ? Number(v) : (v as number);
  return typeof n === "number" && Number.isFinite(n) ? n : null;
}

function fmt(v: unknown, digits = 2): string {
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

  // Live bars for the trade window — sized to the trade's age.
  const tradeSym = (data?.trade?.symbol as string | undefined) ?? "";
  const entryTime = (data?.trade?.entry_time as string | undefined) ?? null;
  const win = chartWindow(entryTime);
  const { data: bars } = useSWR<OHLCVBar[]>(
    tradeSym ? `bars-${tradeSym}-${win.timeframe}-${win.days}` : null,
    () => fetchBars(tradeSym, { timeframe: win.timeframe, days: win.days, futures: true }),
    { refreshInterval: 60000, revalidateOnFocus: false }
  );

  const markers = useMemo<SeriesMarker<Time>[]>(() => {
    const tr = data?.trade;
    if (!tr) return [];
    const out: SeriesMarker<Time>[] = [];
    const side = String(tr.side ?? tr.direction ?? "").toLowerCase();
    const isBuy = side.includes("buy") || side.includes("long");
    const entryT = toUnix(tr.entry_time as string | null | undefined);
    if (entryT != null) {
      out.push({
        time: entryT as Time,
        position: isBuy ? "belowBar" : "aboveBar",
        color: isBuy ? "#00ff88" : "#ff4466",
        shape: isBuy ? "arrowUp" : "arrowDown",
        text: `ENTRY ${num(tr.entry_price) ?? ""}`.trim(),
      });
    }
    const exitT = toUnix(tr.exit_time as string | null | undefined);
    if (exitT != null) {
      out.push({
        time: exitT as Time,
        position: isBuy ? "aboveBar" : "belowBar",
        color: "#00d4ff",
        shape: isBuy ? "arrowDown" : "arrowUp",
        text: `EXIT ${num(tr.exit_price) ?? ""}`.trim(),
      });
    }
    return out.sort((x, y) => (x.time as number) - (y.time as number));
  }, [data?.trade]);

  const priceLines = useMemo(() => {
    const tr = data?.trade;
    const at = data?.attribution;
    if (!tr) return [];
    const lines: Array<{ price: number; color: string; title: string }> = [];
    const entry = num(tr.entry_price);
    const stop = num(tr.stop_loss ?? tr.stop_price ?? at?.stop_loss ?? at?.stop);
    const target = num(tr.take_profit ?? tr.target_1 ?? tr.target_price ?? at?.take_profit ?? at?.target);
    if (entry != null) lines.push({ price: entry, color: "#9ca3af", title: "entry" });
    if (stop != null) lines.push({ price: stop, color: "#ff4466", title: "stop" });
    if (target != null) lines.push({ price: target, color: "#00ff88", title: "target" });
    return lines;
  }, [data?.trade, data?.attribution]);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <p className="text-muted-foreground">Loading trade review…</p>
      </div>
    );
  }
  if (error || !data) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-2">
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
            {String(t.symbol ?? "—")} <span className="text-muted-foreground">·</span> Trade Review
          </h1>
          {grade && <Badge variant={gradeVariant(grade)}>Grade {grade}</Badge>}
          <Badge variant="neutral">{String(t.status ?? "—")}</Badge>
        </div>
        <div className="flex flex-wrap gap-x-8 gap-y-2 mt-3">
          <Stat label="Entry" value={fmt(t.entry_price)} />
          <Stat label="Exit" value={t.exit_price != null ? fmt(t.exit_price) : "—"} />
          <Stat label="P&L" value={t.pnl != null ? `$${fmt(t.pnl)}` : "—"} className={pnlClass(num(t.pnl))} />
          <Stat label="Side" value={String(t.side ?? "—")} />
          <Stat label="Entered" value={t.entry_time ? new Date(String(t.entry_time)).toLocaleString() : "—"} />
          <Stat label="trade_id" value={<span className="text-[11px] text-muted-foreground">{String(t.trade_id ?? id)}</span>} />
        </div>
      </div>

      <div className="flex-1 overflow-auto px-6 py-4 grid grid-cols-1 xl:grid-cols-2 gap-4">
        {/* PRICE CHART — entry/exit markers + stop/target lines */}
        <Card className="xl:col-span-2">
          <CardHeader>
            <CardTitle>
              Price action <span className="text-muted-foreground">· {String(t.symbol ?? "—")} · {win.timeframe}</span>
            </CardTitle>
          </CardHeader>
          <CardContent>
            {bars && bars.length ? (
              <CandlestickChart bars={bars} markers={markers} priceLines={priceLines} height={420} />
            ) : (
              <p className="text-xs text-muted-foreground py-8 text-center">
                No bar data available for {String(t.symbol ?? "this symbol")} in the trade window.
              </p>
            )}
          </CardContent>
        </Card>

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

        {/* MAE/MFE POST-TRADE EXCURSION — how far adverse vs favorable it ran */}
        {Boolean(t.symbol) && (
          <ExcursionPanel tradeId={String(t.trade_id ?? id)} symbol={String(t.symbol)} />
        )}

        {/* ENTRY-TIMING WHAT-IF — PnL if entered ±N bars (exit held constant) */}
        {Boolean(t.symbol) && (
          <EntryTimingScenarios tradeId={String(t.trade_id ?? id)} symbol={String(t.symbol)} />
        )}
      </div>
    </div>
  );
}
