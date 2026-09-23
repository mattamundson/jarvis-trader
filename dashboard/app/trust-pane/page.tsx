"use client";

// ── Unified Trust Pane ────────────────────────────────────────────────────────
// One read-only surface answering, at a glance, for BOTH trading systems:
//   1. Is it live?   2. What's open?   3. Today's P&L (one truthful number)?
//   4. Per-trade post-mortem (win/loss + why)?
// The two engines stay independent; this unifies only at the glass. Every panel
// carries a live/static provenance badge, and futures entry prices are sanity-
// flagged so a corrupted price (e.g. the 2026-06-12 MES@100.5 incident) shows up
// here loudly instead of hiding. No engine changes — reuses the existing proxies.

import { useCallback, useEffect, useRef, useState } from "react";
import useSWR from "swr";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Clock,
  Gauge,
  RefreshCw,
  TrendingDown,
  TrendingUp,
  XCircle,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import {
  fetchEngine,
  fetchDailyAttribution,
  fetchTradeJournal,
  type HealthResponse,
  type DailyAttributionResponse,
  type TradeJournalEntry,
} from "@/lib/api";
import { executionStatus } from "@/lib/executionPath";
import {
  fetchAmoHealth,
  fetchAmoEdgeVerdict,
  fetchAmoCommodities,
  fetchAmoSignalOutcomesAggregate,
  fetchAmoScoreboard,
  fetchAmoActionable,
  type AmoHealthResponse,
  type AmoEdgeVerdictResponse,
  type AmoCommodity,
  type AmoSignalOutcomesAggregate,
  type AmoScoreboardResponse,
  type AmoActionableResponse,
} from "@/lib/amo-api";
import { PostTradeExecutionWidget } from "@/components/PostTradeExecutionWidget";
import { WidgetErrorBoundary } from "@/components/WidgetErrorBoundary";
import { BarDepthCard } from "@/components/BarDepthCard";
import { PostTradeSnippet } from "@/components/PostTradeSnippet";

// ── Brokers/positions response (subset we render) ─────────────────────────────
interface PaperOpenPosition {
  trade_id: string;
  symbol: string;
  direction?: string;
  side?: string;
  quantity: number;
  entry_price: number;
  entry_time: string;
}
interface BrokersPositionsResponse {
  paper?: { positions?: PaperOpenPosition[] };
  ibkr?: { connected?: boolean; positions?: unknown[] };
  reconciliation?: { health?: string; discrepancies?: { symbol: string; detail: string }[] };
}

// ── Bar-quality gate observability (/analytics/bar-quality) ───────────────────
interface BarQualityResponse {
  window_hours: number;
  total_rejections: number;
  by_reason: { reason: string; count: number }[];
  by_symbol: { symbol: string; count: number }[];
  by_path: { sanity: number; gate: number };
  recent: { ts_utc: string; symbol: string; source: string; path: string; reason: string; detail: string; count: number }[];
  gate_active: boolean;
}

// ── jarvis gate-v2 edge ledger (/reports/edge-ledger) — the validated-edge truth ─
interface EdgeLedgerRow {
  source_file: string;
  is_archived: boolean;
  symbol: string;
  base_family: string;
  conditioning: string;
  rank: number;
  verdict: string; // PASS | FAIL | NO_TRADE | …
  passed_via: string | null; // core | alt
  design: { total_oos_trades: number; n_oos_windows: number };
  metrics: {
    pf_ci_lower: number | null;
    p_edge: number | null;
    mc_95th_dd_pct: number | null;
    dsr: number | null;
    wfo_consistency: string | null;
  };
}
interface EdgeLedgerResponse {
  total: number;
  n_pass: number;
  n_fail: number;
  n_other: number;
  rows: EdgeLedgerRow[];
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function money(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—";
  const sign = n > 0 ? "+" : n < 0 ? "-" : "";
  return `${sign}$${Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}
function fmtUptime(seconds?: number): string {
  if (seconds == null) return "—";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}
function fmtTime(iso?: string): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("en-US", {
      month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false,
    });
  } catch {
    return iso;
  }
}
function fmtDate(iso?: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" });
  } catch {
    return iso;
  }
}
function pct(n: number | null | undefined): string {
  return n == null || Number.isNaN(n) ? "—" : `${Math.round(n * 100)}%`;
}
function num(n: number | null | undefined, digits = 2): string {
  return n == null || Number.isNaN(n) ? "—" : n.toFixed(digits);
}

// Per-symbol lower price floors. A futures entry below its floor is almost
// certainly a corrupted field (the MES@100.5 STC-leak class). Conservative —
// only flags the obviously-impossible, never a real price.
const PRICE_FLOORS: Record<string, number> = {
  MES: 1000, ES: 1000, MNQ: 1000, NQ: 1000, MGC: 500, GC: 500, MCL: 5, CL: 5, MES_micro: 1000,
};
function suspectPrice(symbol: string, price: number): boolean {
  const floor = PRICE_FLOORS[(symbol || "").toUpperCase()];
  return floor != null && price > 0 && price < floor;
}

// ── TradingView embed (TV-hosted data, no API key, no engine dependency) ──────
// Self-contained on this page on purpose: the reusable charts/TradingViewWidget
// component lives on the in-flight feat/dashboard-tv-widget-3d branch — keeping
// this inline avoids colliding/duplicating a shared file before that lands. Maps
// internal futures symbols to TV front-month continuous tickers.
const TV_SYMBOL: Record<string, string> = {
  MES: "CME_MINI:MES1!", ES: "CME_MINI:ES1!",
  MNQ: "CME_MINI:MNQ1!", NQ: "CME_MINI:NQ1!",
  M2K: "CME_MINI:M2K1!",
  MGC: "COMEX_MINI:MGC1!", GC: "COMEX:GC1!",
  MCL: "NYMEX:MCL1!", CL: "NYMEX:CL1!",
};
function tvTicker(symbol: string): string | null {
  return TV_SYMBOL[(symbol || "").toUpperCase()] ?? null;
}

function TradingViewMini({ symbol, height = 360 }: { symbol: string; height?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const ticker = tvTicker(symbol);
  useEffect(() => {
    const container = ref.current;
    if (!container || !ticker) return;
    container.innerHTML = "";
    const script = document.createElement("script");
    script.src = "https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js";
    script.type = "text/javascript";
    script.async = true;
    script.innerHTML = JSON.stringify({
      autosize: true,
      symbol: ticker,
      interval: "60",
      timezone: "America/Chicago",
      theme: "dark",
      style: "1",
      locale: "en",
      backgroundColor: "rgba(6, 13, 26, 1)",
      gridColor: "rgba(0, 212, 255, 0.06)",
      hide_side_toolbar: true,
      allow_symbol_change: false,
      studies: ["STD;EMA", "STD;VWAP"],
      support_host: "https://www.tradingview.com",
    });
    container.appendChild(script);
    return () => { container.innerHTML = ""; };
  }, [ticker]);

  if (!ticker) {
    return <p className="text-xs text-muted-foreground">No TradingView mapping for {symbol}.</p>;
  }
  return (
    <div style={{ height }} className="w-full overflow-hidden rounded-lg border border-border">
      <div ref={ref} className="tradingview-widget-container h-full w-full" />
    </div>
  );
}

// ── Small presentational pieces ───────────────────────────────────────────────
function PanelHeader({
  title,
  provenance,
}: {
  title: string;
  provenance: "live" | "static";
}) {
  return (
    <div className="flex items-center justify-between mb-3">
      <h3 className="text-sm font-semibold text-foreground tracking-wide">{title}</h3>
      <Badge variant={provenance}>
        <span className="flex items-center gap-1">
          <span className={`h-1.5 w-1.5 rounded-full ${provenance === "live" ? "bg-bull animate-pulse" : "bg-muted-foreground"}`} />
          {provenance === "live" ? "LIVE" : "STATIC"}
        </span>
      </Badge>
    </div>
  );
}

function Card({ children }: { children: React.ReactNode }) {
  return <div className="rounded-xl border border-border bg-card p-4">{children}</div>;
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

// ── Page ────────────────────────────────────────────────────────────────────
export default function TrustPanePage() {
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const onOk = useCallback(() => setLastUpdated(new Date()), []);

  const health = useSWR<HealthResponse>("/health", (p: string) => fetchEngine<HealthResponse>(p), {
    refreshInterval: 15_000, onSuccess: onOk,
  });
  const positions = useSWR<BrokersPositionsResponse>(
    "/brokers/positions", (p: string) => fetchEngine<BrokersPositionsResponse>(p), { refreshInterval: 15_000 },
  );
  const pnl = useSWR<DailyAttributionResponse>("attr-daily", () => fetchDailyAttribution(), { refreshInterval: 30_000 });
  const trades = useSWR<TradeJournalEntry[]>("trades-journal", () => fetchTradeJournal(undefined, undefined, 12), { refreshInterval: 30_000 });
  const barQuality = useSWR<BarQualityResponse>(
    "/analytics/bar-quality?hours=168", (p: string) => fetchEngine<BarQualityResponse>(p), { refreshInterval: 60_000 },
  );
  const edgeLedger = useSWR<EdgeLedgerResponse>(
    "/reports/edge-ledger", (p: string) => fetchEngine<EdgeLedgerResponse>(p), { refreshInterval: 120_000 },
  );
  const amo = useSWR<AmoHealthResponse>("amo-health", () => fetchAmoHealth(), { refreshInterval: 30_000 });
  const verdict = useSWR<AmoEdgeVerdictResponse>("amo-edge-verdict", () => fetchAmoEdgeVerdict(), { refreshInterval: 60_000 });
  // Commodities rarely change — refresh slowly, just enough to pick up a new listing.
  const commodities = useSWR<AmoCommodity[]>("amo-commodities", () => fetchAmoCommodities(), { refreshInterval: 300_000 });
  const amoOutcomes = useSWR<AmoSignalOutcomesAggregate>(
    "amo-signal-outcomes", () => fetchAmoSignalOutcomesAggregate(), { refreshInterval: 120_000 },
  );
  const amoScoreboard = useSWR<AmoScoreboardResponse>(
    "amo-scoreboard", () => fetchAmoScoreboard(), { refreshInterval: 120_000 },
  );
  const amoActionable = useSWR<AmoActionableResponse>(
    "amo-actionable", () => fetchAmoActionable(), { refreshInterval: 60_000 },
  );

  const [secondsSince, setSecondsSince] = useState(0);
  const [selectedSymbol, setSelectedSymbol] = useState<string>("");
  useEffect(() => {
    const i = setInterval(() => {
      if (lastUpdated) setSecondsSince(Math.floor((Date.now() - lastUpdated.getTime()) / 1000));
    }, 1000);
    return () => clearInterval(i);
  }, [lastUpdated]);

  const refreshAll = useCallback(() => {
    health.mutate(); positions.mutate(); pnl.mutate(); trades.mutate();
    barQuality.mutate(); edgeLedger.mutate(); amo.mutate(); verdict.mutate(); commodities.mutate();
    amoOutcomes.mutate(); amoScoreboard.mutate(); amoActionable.mutate();
  }, [health, positions, pnl, trades, barQuality, edgeLedger, amo, verdict, commodities, amoOutcomes, amoScoreboard, amoActionable]);

  // ── jarvis derived ──
  const h = health.data;
  const jarvisLive = !!h && h.status === "ok";
  const dataLegDown = h?.ibkr_data_connected === false;
  const llmDegraded = !!h && h.llm_path_healthy === false;
  // D3-01: this page's whole purpose is telling the operator what's real —
  // never read ibkr_execution_connected directly (see @/lib/executionPath).
  const exec = executionStatus(h);
  const jarvisDegraded = !!health.error || (!!h && h.status !== "ok");
  const openPaper = positions.data?.paper?.positions ?? [];
  const suspectCount = openPaper.filter((p) => suspectPrice(p.symbol, p.entry_price)).length;
  const bq = barQuality.data;
  const bqTotal = bq?.total_rejections ?? 0;
  // gate-v2 validated edge: live PASS rows, strongest pf_ci_lower first.
  const el = edgeLedger.data;
  const passRows = (el?.rows ?? [])
    .filter((r) => r.verdict === "PASS" && !r.is_archived)
    .sort((a, b) => (b.metrics.pf_ci_lower ?? 0) - (a.metrics.pf_ci_lower ?? 0));
  // Chart symbols: distinct open-position symbols that have a TV mapping; else a sane default.
  const chartSymbols = (() => {
    const fromOpen = Array.from(
      new Set(openPaper.map((p) => (p.symbol || "").toUpperCase()).filter((s) => s && tvTicker(s))),
    );
    return fromOpen.length > 0 ? fromOpen : ["MES", "MGC"];
  })();
  const activeSymbol = selectedSymbol && chartSymbols.includes(selectedSymbol) ? selectedSymbol : chartSymbols[0];

  // ── amo derived ──
  const a = amo.data;
  const amoLive = !!a && a.status === "ok";
  const v = verdict.data;
  const verdictOk = !!v && v.status === "ok" && v.n_total > 0;
  const amoDegraded = !!amo.error || (!!a && a.status !== "ok");
  const commodityById = new Map<number, AmoCommodity>((commodities.data ?? []).map((c) => [c.id, c]));
  const commodityLabel = (id: number | null): string => {
    if (id == null) return "—";
    return commodityById.get(id)?.symbol ?? `#${id}`;
  };

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="sticky top-0 z-50 border-b border-border bg-background/95 backdrop-blur">
        <div className="mx-auto max-w-[1600px] flex items-center justify-between px-6 py-3">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent/10">
              <Gauge className="h-5 w-5 text-accent" />
            </div>
            <div>
              <h1 className="font-bold text-foreground tracking-tight">Trust Pane</h1>
              <p className="text-xs text-muted-foreground">Both systems · one glance · live data</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            {lastUpdated && <span className="text-xs text-muted-foreground">Updated {secondsSince}s ago</span>}
            <button
              onClick={refreshAll}
              className="flex items-center gap-1.5 rounded-lg border border-border bg-card px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${health.isLoading ? "animate-spin" : ""}`} />
              Refresh
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1600px] px-6 py-6 space-y-6">
        {/* System-health banner — surfaces ANY degraded state loudly so neither
            system reads "LIVE" while quietly degraded (suspect prices, data-leg
            down, LLM on fallback, jarvis/amo not-ok). */}
        {(suspectCount > 0 || dataLegDown || llmDegraded || jarvisDegraded || amoDegraded) && (
          <div className="rounded-xl border border-bear/30 bg-bear/5 p-4 flex items-start gap-3">
            <AlertTriangle className="h-5 w-5 text-bear mt-0.5 shrink-0 animate-pulse" />
            <div className="text-sm">
              <p className="font-semibold text-bear">System degraded — do not trust at a glance</p>
              <ul className="text-xs text-muted-foreground mt-1 list-disc pl-4 space-y-0.5">
                {jarvisDegraded && (
                  <li>jarvis engine is {health.error ? "unreachable" : `reporting status="${h?.status ?? "?"}"`} — not in a healthy live state.</li>
                )}
                {dataLegDown && <li>jarvis IB data leg is disconnected — marks are stale fallback data; unrealized P&L is suppressed, not trustworthy.</li>}
                {llmDegraded && <li>jarvis LLM path is on fallback (primary provider degraded) — decision quality may be affected.</li>}
                {suspectCount > 0 && (
                  <li>{suspectCount} open paper position{suspectCount > 1 ? "s have" : " has"} an implausible entry price — likely a corrupted field. Do not trust the signal until reconciled.</li>
                )}
                {amoDegraded && (
                  <li>amo-arbitrage is {amo.error ? "unreachable" : `reporting status="${a?.status ?? "?"}"`} — the cross-system pane is partial.</li>
                )}
              </ul>
            </div>
          </div>
        )}

        {/* Two-column: JARVIS | AMO-ARBITRAGE */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* ───────── JARVIS column ───────── */}
          <section className="space-y-4">
            <div className="flex items-center gap-2">
              <Activity className="h-4 w-4 text-accent" />
              <h2 className="text-base font-bold text-foreground tracking-tight">JARVIS TRADER</h2>
              {health.error ? (
                <Badge variant="bear">UNREACHABLE</Badge>
              ) : jarvisLive ? (
                <Badge variant="bull">{h?.paper_mode ? "LIVE · PAPER" : "LIVE"}</Badge>
              ) : (
                <Badge variant="warn">{health.isLoading ? "…" : "DEGRADED"}</Badge>
              )}
            </div>

            {/* 1. Liveness */}
            <Card>
              <PanelHeader title="Liveness" provenance={health.error ? "static" : "live"} />
              <div className="grid grid-cols-3 gap-3">
                <Stat label="Status" value={h?.status?.toUpperCase() ?? (health.error ? "DOWN" : "…")} tone={jarvisLive ? "bull" : "bear"} />
                <Stat label="Uptime" value={fmtUptime(h?.uptime_seconds)} />
                <Stat label="LLM" value={h?.llm_path_healthy ? "OK" : "DEGRADED"} tone={h?.llm_path_healthy ? "bull" : "bear"} />
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                <Badge variant={exec.tone} title={exec.detail}>exec IB {exec.label}</Badge>
                <Badge variant={h?.ibkr_data_connected ? "bull" : "bear"}>data IB {h?.ibkr_data_connected ? "✓" : "✗"}</Badge>
                <Badge variant={h?.kill_switch_active ? "bear" : "neutral"}>kill {h?.kill_switch_active ? "ON" : "off"}</Badge>
                <Badge variant={h?.tradingview_mcp_healthy ? "bull" : "warn"}>TV {h?.tradingview_mcp_healthy ? "✓" : "✗"}</Badge>
              </div>
            </Card>

            {/* 2. Today's P&L */}
            <Card>
              <PanelHeader title={`Today's P&L${pnl.data?.date ? ` · ${pnl.data.date}` : ""}`} provenance={pnl.error ? "static" : "live"} />
              {pnl.error ? (
                <p className="text-xs text-muted-foreground">Could not load /attribution/daily.</p>
              ) : (
                <div className="grid grid-cols-3 gap-3">
                  <Stat label="Realized P&L" value={money(pnl.data?.total_pnl)} tone={(pnl.data?.total_pnl ?? 0) >= 0 ? "bull" : "bear"} />
                  <Stat label="Trades" value={String(pnl.data?.n_trades ?? 0)} />
                  <Stat label="Top driver" value={pnl.data?.top_contributor ?? "—"} tone="muted" />
                </div>
              )}
            </Card>

            {/* 3. Open positions */}
            <Card>
              <PanelHeader title={`Open Positions (${openPaper.length})`} provenance={positions.error ? "static" : "live"} />
              {openPaper.length === 0 ? (
                <p className="text-xs text-muted-foreground">No open paper positions.</p>
              ) : (
                <div className="space-y-1.5">
                  {openPaper.map((p) => {
                    const dir = (p.direction || p.side || "").toUpperCase();
                    const bad = suspectPrice(p.symbol, p.entry_price);
                    return (
                      <div key={p.trade_id} className={`flex items-center justify-between rounded-lg border px-3 py-2 ${bad ? "border-bear/40 bg-bear/5" : "border-border"}`}>
                        <div className="flex items-center gap-2">
                          <span className="font-mono text-sm font-semibold text-foreground">{p.symbol}</span>
                          <Badge variant={dir === "LONG" || dir === "BUY" ? "bull" : "bear"}>{dir}</Badge>
                          <span className="text-xs text-muted-foreground">×{p.quantity}</span>
                        </div>
                        <div className="flex items-center gap-2">
                          {bad && <Badge variant="bear"><span className="flex items-center gap-1"><AlertTriangle className="h-3 w-3" />suspect price</span></Badge>}
                          <span className="font-mono text-sm text-foreground">@{p.entry_price}</span>
                          <span className="text-[11px] text-muted-foreground">{fmtTime(p.entry_time)}</span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
              {positions.data?.reconciliation?.health && (
                <p className="text-[11px] text-muted-foreground mt-2">Reconciliation: {positions.data.reconciliation.health}</p>
              )}
            </Card>

            {/* Market chart — TradingView-quality price context for open positions */}
            <Card>
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-semibold text-foreground tracking-wide">Market Chart</h3>
                <div className="flex items-center gap-1">
                  {chartSymbols.map((s) => (
                    <button
                      key={s}
                      onClick={() => setSelectedSymbol(s)}
                      className={`rounded-md px-2 py-0.5 text-xs font-mono transition-colors ${
                        s === activeSymbol
                          ? "bg-accent/15 text-accent border border-accent/30"
                          : "text-muted-foreground border border-border hover:text-foreground"
                      }`}
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
              <TradingViewMini symbol={activeSymbol} />
              <p className="text-[11px] text-muted-foreground mt-2">
                TradingView-hosted data (1h, EMA + VWAP). Market context only — fills/markers are in
                the position + trade panels.
              </p>
            </Card>

            {/* 5. Data-quality gate — proves the write-time bar gate is working */}
            <Card>
              <PanelHeader title="Data-Quality Gate · 7d" provenance={barQuality.error ? "static" : "live"} />
              {barQuality.error ? (
                <p className="text-xs text-muted-foreground">Could not load /analytics/bar-quality.</p>
              ) : bqTotal === 0 ? (
                <div className="flex items-start gap-2">
                  <CheckCircle2 className="h-4 w-4 text-bull mt-0.5 shrink-0" />
                  <p className="text-xs text-muted-foreground">
                    <span className="text-bull font-medium">Gate active · data clean.</span> 0 contaminated bars
                    rejected in the last 7 days — the healthy steady state. The write-time gate screens every
                    persisted bar (IB sentinel ticks, price-band breaks, &gt;50% neighbour jumps).
                  </p>
                </div>
              ) : (
                <>
                  <div className="grid grid-cols-3 gap-3">
                    <Stat label="Rejected (7d)" value={String(bqTotal)} tone="bear" />
                    <Stat label="Sanity / Gate" value={`${bq?.by_path.sanity ?? 0} / ${bq?.by_path.gate ?? 0}`} />
                    <Stat label="Top reason" value={bq?.by_reason[0]?.reason ?? "—"} tone="muted" />
                  </div>
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {bq?.by_reason.slice(0, 5).map((r) => (
                      <Badge key={r.reason} variant="warn">{r.reason} ×{r.count}</Badge>
                    ))}
                  </div>
                  {(bq?.by_symbol.length ?? 0) > 0 && (
                    <p className="text-[11px] text-muted-foreground mt-2">
                      By symbol: {bq!.by_symbol.map((s) => `${s.symbol} (${s.count})`).join(" · ")}
                    </p>
                  )}
                </>
              )}
            </Card>

            {/* 4b. Validated edge — which candidates clear gate-v2 right now */}
            <Card>
              <PanelHeader title="Validated Edge · gate-v2" provenance={edgeLedger.error ? "static" : "live"} />
              {edgeLedger.error ? (
                <p className="text-xs text-muted-foreground">Could not load /reports/edge-ledger.</p>
              ) : !el ? (
                <p className="text-xs text-muted-foreground">Loading edge ledger…</p>
              ) : (
                <>
                  <div className="grid grid-cols-3 gap-3">
                    <Stat label="PASS" value={String(el.n_pass)} tone={el.n_pass > 0 ? "bull" : "muted"} />
                    <Stat label="FAIL" value={String(el.n_fail)} tone="muted" />
                    <Stat label="Candidates" value={String(el.total)} tone="muted" />
                  </div>
                  {passRows.length === 0 ? (
                    <p className="text-[11px] text-muted-foreground mt-3">
                      No candidate currently clears gate-v2 (pf_ci_lower ≥ 1.10, p_edge ≥ 0.95, MC-DD ≤ 5%,
                      DSR ≥ 0.10, ≥ 30 OOS trades). NO_TRADE is the honest verdict.
                    </p>
                  ) : (
                    <div className="space-y-1.5 mt-3">
                      {passRows.slice(0, 6).map((r) => (
                        <div
                          key={r.source_file}
                          className="flex items-center justify-between rounded-lg border border-border px-3 py-2"
                        >
                          <div className="flex items-center gap-2 min-w-0">
                            <span className="font-mono text-sm font-semibold text-foreground">{r.symbol}</span>
                            <span className="text-[11px] uppercase text-muted-foreground truncate">
                              {r.base_family}{r.conditioning && r.conditioning !== "none" ? ` · ${r.conditioning}` : ""}
                            </span>
                            <Badge variant={r.passed_via === "alt" ? "warn" : "live"}>
                              {r.passed_via === "alt" ? "ALT" : "CORE"}
                            </Badge>
                          </div>
                          <div className="flex items-center gap-3 shrink-0 text-[11px] font-mono text-muted-foreground">
                            <span title="profit-factor CI lower bound">PF {num(r.metrics.pf_ci_lower)}</span>
                            <span title="deflated Sharpe">DSR {num(r.metrics.dsr)}</span>
                            <span title="out-of-sample trades">{r.design.total_oos_trades}t</span>
                          </div>
                        </div>
                      ))}
                      {passRows.length > 6 && (
                        <p className="text-[11px] text-muted-foreground">+{passRows.length - 6} more passing</p>
                      )}
                    </div>
                  )}
                </>
              )}
            </Card>

            {/* 4. Per-trade post-mortem */}
            <Card>
              <PanelHeader title="Recent Trades — win/loss & why" provenance={trades.error ? "static" : "live"} />
              {trades.error ? (
                <p className="text-xs text-muted-foreground">Could not load /trades/journal.</p>
              ) : (trades.data?.length ?? 0) === 0 ? (
                <p className="text-xs text-muted-foreground">No trades recorded.</p>
              ) : (
                <div className="space-y-1.5">
                  {trades.data!.map((t) => {
                    const open = t.status === "open";
                    const win = (t.pnl ?? 0) > 0;
                    return (
                      <div key={t.trade_id} className="flex items-center justify-between rounded-lg border border-border px-3 py-2">
                        <div className="flex items-center gap-2 min-w-0">
                          <span className="font-mono text-sm font-semibold text-foreground">{t.symbol}</span>
                          <span className="text-[11px] uppercase text-muted-foreground">{t.side}</span>
                          <span className="text-[11px] text-muted-foreground truncate">
                            {t.regime ?? "—"}{t.deciding_stage ? ` · ${t.deciding_stage}` : ""}{t.bias ? ` · ${t.bias}` : ""}
                          </span>
                        </div>
                        <div className="flex items-center gap-2 shrink-0">
                          {open ? (
                            <Badge variant="neutral">OPEN</Badge>
                          ) : win ? (
                            <span className="flex items-center gap-1 text-bull text-sm font-mono font-semibold"><TrendingUp className="h-3.5 w-3.5" />{money(t.pnl)}</span>
                          ) : (
                            <span className="flex items-center gap-1 text-bear text-sm font-mono font-semibold"><TrendingDown className="h-3.5 w-3.5" />{money(t.pnl)}</span>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </Card>

            {/* 5. Post-trade execution quality (WS4B endpoints — PR #78) */}
            <WidgetErrorBoundary name="Post-Trade Execution">
              <PostTradeExecutionWidget />
            </WidgetErrorBoundary>

            {/* 6. Post-trade quality — book-wide MAE/MFE + entry-timing regret (J1/J2) */}
<<<<<<< HEAD
            <PostTradeSnippet />

            {/* 7. Data integrity — bar coverage/health (live after engine restart) */}
            <BarDepthCard />
=======
            <WidgetErrorBoundary name="Post-Trade Quality">
              <PostTradeSnippet />
            </WidgetErrorBoundary>

            {/* 7. Data integrity — bar coverage/health (live after engine restart) */}
            <WidgetErrorBoundary name="Bar Depth">
              <BarDepthCard />
            </WidgetErrorBoundary>
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
          </section>

          {/* ───────── AMO-ARBITRAGE column ───────── */}
          <section className="space-y-4">
            <div className="flex items-center gap-2">
              <Activity className="h-4 w-4 text-info" />
              <h2 className="text-base font-bold text-foreground tracking-tight">AMO-ARBITRAGE</h2>
              {amo.error ? (
                <Badge variant="bear">UNREACHABLE</Badge>
              ) : amoLive ? (
                <Badge variant="bull">LIVE</Badge>
              ) : (
                <Badge variant="warn">{amo.isLoading ? "…" : "DEGRADED"}</Badge>
              )}
            </div>

            {/* Liveness */}
            <Card>
              <PanelHeader title="Liveness" provenance={amo.error ? "static" : "live"} />
              <div className="grid grid-cols-3 gap-3">
                <Stat label="Status" value={a?.status?.toUpperCase() ?? (amo.error ? "DOWN" : "…")} tone={amoLive ? "bull" : "bear"} />
                <Stat label="Scheduler" value={a?.scheduler_running ? "RUNNING" : "STOPPED"} tone={a?.scheduler_running ? "bull" : "bear"} />
                <Stat label="Jobs" value={String(a?.scheduled_jobs ?? 0)} />
              </div>
              {a?.version && <p className="text-[11px] text-muted-foreground mt-2">v{a.version}</p>}
            </Card>

            {/* Edge verdict — which backtests survive the family-wide BH-FDR gate.
                The honest answer to "is any of this edge real?", straight from the
                same correction that gates Kelly sizing. */}
            <Card>
              <PanelHeader title="Edge Verdict — BH-FDR" provenance={verdict.error ? "static" : "live"} />
              {verdict.error ? (
                <p className="text-xs text-muted-foreground">Could not load /api/edge-verdict.</p>
              ) : !v ? (
                <p className="text-xs text-muted-foreground">{verdict.isLoading ? "Loading verdict…" : "No verdict."}</p>
              ) : !verdictOk ? (
                <div className="flex items-start gap-2">
                  <XCircle className="h-4 w-4 text-muted-foreground mt-0.5 shrink-0" />
                  <p className="text-xs text-muted-foreground">
                    No verdict available yet — the backtests table is empty or unreachable.
                  </p>
                </div>
              ) : (
                <>
                  <div className="grid grid-cols-3 gap-3">
                    <Stat
                      label="Validated"
                      value={`${v.n_validated} / ${v.n_total}`}
                      tone={v.n_validated > 0 ? "bull" : "bear"}
                    />
                    <Stat label="FDR q" value={num(v.fdr_q)} tone="muted" />
                    <Stat label="As of" value={fmtDate(v.as_of)} tone="muted" />
                  </div>
                  {v.validated.length === 0 ? (
                    <p className="text-xs text-muted-foreground mt-3">
                      0 of {v.n_total} strategies survive whole-campaign correction — none are
                      validated for sizing. That is the honest result, not a data gap.
                    </p>
                  ) : (
                    <div className="space-y-1.5 mt-3">
                      {v.validated.map((s) => (
                        <div
                          key={String(s.backtest_id)}
                          className="flex items-center justify-between rounded-lg border border-bull/30 bg-bull/5 px-3 py-2"
                        >
                          <div className="flex items-center gap-2 min-w-0">
                            <span className="font-mono text-sm font-semibold text-foreground">
                              {commodityLabel(s.commodity_id)}
                            </span>
                            <Badge variant="bull">{s.strategy}</Badge>
                          </div>
                          <div className="flex items-center gap-3 text-[11px] text-muted-foreground font-mono shrink-0">
                            <span>PF {num(s.profit_factor)}</span>
                            <span>p {num(s.p_value, 3)}</span>
                            <span>{s.total_trades ?? "—"}t</span>
                            <span>{pct(s.win_rate)}</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                  <p className="text-[11px] text-muted-foreground mt-2">{v.methodology}</p>
                </>
              )}
            </Card>

            {/* Signal outcomes — did amo's emitted setups actually pay off?
                The trust check on everything above: hypothetical (amo has no
                execution), but scored against real forward prices. */}
            <Card>
              <PanelHeader title="Signal Outcomes" provenance={amoOutcomes.error ? "static" : "live"} />
              {amoOutcomes.error ? (
                <p className="text-xs text-muted-foreground">Could not load /api/signal-outcomes/aggregate.</p>
              ) : !amoOutcomes.data ? (
                <p className="text-xs text-muted-foreground">Loading outcomes…</p>
              ) : amoOutcomes.data.provisioned === false ? (
                <p className="text-xs text-muted-foreground">Outcome tracking not provisioned on the amo side yet.</p>
              ) : amoOutcomes.data.total_evaluated === 0 ? (
                <p className="text-xs text-muted-foreground">
                  No evaluated outcomes yet — setups are scored ≥10 days after emission.
                </p>
              ) : (
                <>
                  <div className="grid grid-cols-3 gap-3">
                    <Stat
                      label="Hit rate (T1+T2)"
                      value={amoOutcomes.data.hit_rate != null ? `${amoOutcomes.data.hit_rate.toFixed(1)}%` : "—"}
                      tone={(amoOutcomes.data.hit_rate ?? 0) >= 50 ? "bull" : "bear"}
                    />
                    <Stat
                      label="Avg hyp. P&L"
                      value={
                        amoOutcomes.data.avg_hypothetical_pnl_pct != null
                          ? `${amoOutcomes.data.avg_hypothetical_pnl_pct >= 0 ? "+" : ""}${amoOutcomes.data.avg_hypothetical_pnl_pct.toFixed(2)}%`
                          : "—"
                      }
                      tone={(amoOutcomes.data.avg_hypothetical_pnl_pct ?? 0) >= 0 ? "bull" : "bear"}
                    />
                    <Stat label="Evaluated" value={String(amoOutcomes.data.total_evaluated)} tone="muted" />
                  </div>
                  <div className="flex flex-wrap gap-1.5 mt-2">
                    {Object.entries(amoOutcomes.data.count_by_hit).map(([k, n]) => (
                      <Badge key={k} variant={k.startsWith("target") ? "bull" : k === "stop_hit" ? "bear" : "neutral"}>
                        {k} · {n}
                      </Badge>
                    ))}
                  </div>
                  <p className="text-[11px] text-muted-foreground mt-2">
                    Hypothetical — amo places no orders; exits assume T1 on target hit, stop on stop hit.
                  </p>
                </>
              )}
            </Card>

            {/* Backtest screen vs live forward record, per validated strategy. */}
            <Card>
              <PanelHeader title="Scoreboard — Backtest vs Forward" provenance={amoScoreboard.error ? "static" : "live"} />
              {amoScoreboard.error ? (
                <p className="text-xs text-muted-foreground">Could not load /api/scoreboard.</p>
              ) : !amoScoreboard.data ? (
                <p className="text-xs text-muted-foreground">Loading scoreboard…</p>
              ) : amoScoreboard.data.available === false ? (
                <p className="text-xs text-muted-foreground">
                  amo scoreboard unavailable (fail-open payload) — a feed outage,
                  not a claim that no strategies are validated.
                </p>
              ) : amoScoreboard.data.strategies.length === 0 ? (
                <p className="text-xs text-muted-foreground">
                  No validated strategies on the scoreboard — nothing to compare. Honest empty, not a gap.
                </p>
              ) : (
                <div className="space-y-1.5">
                  {amoScoreboard.data.strategies.slice(0, 5).map((s) => (
                    <div
                      key={`${s.symbol}-${s.strategy}`}
                      className="flex items-center justify-between rounded-lg border border-border px-3 py-2"
                    >
                      <div className="flex items-center gap-2 min-w-0">
                        <span className="font-mono text-xs font-semibold text-foreground">{s.symbol ?? "—"}</span>
                        <Badge variant={s.kelly_sized ? "bull" : "neutral"}>{s.strategy}</Badge>
                        {s.graduation_ready && !s.kelly_sized && <Badge variant="warn">grad-ready</Badge>}
                      </div>
                      <div className="flex items-center gap-3 text-[11px] text-muted-foreground font-mono shrink-0">
                        <span>BT PF {num(s.backtest_pf)}</span>
                        <span className={s.forward_pf != null && s.forward_pf > 1 ? "text-bull" : ""}>
                          Fwd PF {num(s.forward_pf)}
                        </span>
                        <span>
                          {s.evidence_gathered}/{s.evidence_target} ev
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </Card>

            {/* Actionable now — amo's top live setups, advisory display only.
                Never feeds a jarvis trade/risk/fund decision (CROSS_SIGNAL spec). */}
            <Card>
              <PanelHeader title="Actionable Now (advisory)" provenance={amoActionable.error ? "static" : "live"} />
              {amoActionable.error ? (
                <p className="text-xs text-muted-foreground">Could not load /api/actionable.</p>
              ) : !amoActionable.data ? (
                <p className="text-xs text-muted-foreground">Loading actionable board…</p>
              ) : !amoActionable.data.available ? (
                <p className="text-xs text-muted-foreground">
                  amo actionable board unavailable — a feed outage, not a
                  confirmed absence of setups.
                </p>
              ) : amoActionable.data.items.length === 0 ? (
                <p className="text-xs text-muted-foreground">No active setups on the amo board.</p>
              ) : (
                <>
                  <div className="space-y-1.5">
                    {amoActionable.data.items.slice(0, 3).map((it) => (
                      <div
                        key={`${it.symbol}-${String(it.id)}`}
                        className={`rounded-lg border px-3 py-2 ${
                          it.exploratory ? "border-border/60 opacity-70" : "border-border"
                        }`}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <div className="flex items-center gap-2 min-w-0">
                            <span className="font-mono text-xs font-semibold text-foreground">{it.symbol}</span>
                            <Badge variant={it.direction === "short" ? "bear" : "bull"}>{it.direction}</Badge>
                            <Badge variant={it.status === "triggerable" || it.status === "triggered" ? "warn" : "neutral"}>
                              {it.status.replace(/_/g, " ")}
                            </Badge>
                            {it.exploratory && <Badge variant="static">exploratory</Badge>}
                          </div>
                          <div className="flex items-center gap-3 text-[11px] text-muted-foreground font-mono shrink-0">
                            {it.distance_atr != null && <span>{it.distance_atr.toFixed(2)} ATR to entry</span>}
                            {it.planned_rr != null && <span>RR {it.planned_rr.toFixed(1)}</span>}
                          </div>
                        </div>
                        {it.entry_price != null && (
                          <p className="text-[11px] text-muted-foreground font-mono mt-1">
                            entry {it.entry_price} · stop {it.stop_loss ?? "—"} · T1 {it.target_1 ?? "—"} · last{" "}
                            {it.latest_price ?? "—"}
                          </p>
                        )}
                      </div>
                    ))}
                  </div>
                  <p className="text-[11px] text-muted-foreground mt-2">
                    Advisory display only — amo signals never gate or feed a jarvis trade decision.
                  </p>
                </>
              )}
            </Card>

            {/* Scheduled jobs */}
            <Card>
              <PanelHeader title="Scheduled Jobs" provenance={amo.error ? "static" : "live"} />
              {(a?.jobs?.length ?? 0) === 0 ? (
                <p className="text-xs text-muted-foreground">No jobs reported.</p>
              ) : (
                <div className="space-y-1.5 max-h-[280px] overflow-y-auto">
                  {a!.jobs!.map((j) => (
                    <div key={j.id} className="flex items-center justify-between rounded-lg border border-border px-3 py-1.5">
                      <span className="font-mono text-xs text-foreground">{j.id}</span>
                      <span className="flex items-center gap-1 text-[11px] text-muted-foreground"><Clock className="h-3 w-3" />{fmtTime(j.next_run)}</span>
                    </div>
                  ))}
                </div>
              )}
            </Card>

            {/* Honest structural note — amo has no live execution/P&L view */}
            <Card>
              <PanelHeader title="Execution & P&L" provenance="static" />
              <div className="flex items-start gap-2">
                <XCircle className="h-4 w-4 text-muted-foreground mt-0.5 shrink-0" />
                <p className="text-xs text-muted-foreground">
                  amo-arbitrage is <span className="text-foreground font-medium">signal-generation only</span> — it
                  surfaces seasonal/spread setups but has no live order execution, so there is no realized P&L feed.
                  Trades are placed manually off its signals; same-day P&L and post-trade analysis live on the jarvis
                  side. Hypothetical signal outcomes (did the setups pay off on paper?) are tracked in the Signal
                  Outcomes panel above.
                </p>
              </div>
            </Card>
          </section>
        </div>

        <p className="text-xs text-muted-foreground text-center pb-2">
          Read-only. jarvis panels refresh every 15–30s; amo every 30s. <span className="text-bull">LIVE</span> = fetched from a running interface; <span className="text-muted-foreground">STATIC</span> = not yet wired to a live feed.
        </p>
      </main>
    </div>
  );
}
