"use client";

// ── Unified Trust Pane ────────────────────────────────────────────────────────
// One read-only surface answering, at a glance, for BOTH trading systems:
//   1. Is it live?   2. What's open?   3. Today's P&L (one truthful number)?
//   4. Per-trade post-mortem (win/loss + why)?
// The two engines stay independent; this unifies only at the glass. Every panel
// carries a live/static provenance badge, and futures entry prices are sanity-
// flagged so a corrupted price (e.g. the 2026-06-12 MES@100.5 incident) shows up
// here loudly instead of hiding. No engine changes — reuses the existing proxies.

import { useCallback, useEffect, useState } from "react";
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
import { fetchAmoHealth, type AmoHealthResponse } from "@/lib/amo-api";
import { BarDepthCard } from "@/components/BarDepthCard";

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
  const amo = useSWR<AmoHealthResponse>("amo-health", () => fetchAmoHealth(), { refreshInterval: 30_000 });

  const [secondsSince, setSecondsSince] = useState(0);
  useEffect(() => {
    const i = setInterval(() => {
      if (lastUpdated) setSecondsSince(Math.floor((Date.now() - lastUpdated.getTime()) / 1000));
    }, 1000);
    return () => clearInterval(i);
  }, [lastUpdated]);

  const refreshAll = useCallback(() => {
    health.mutate(); positions.mutate(); pnl.mutate(); trades.mutate(); amo.mutate();
  }, [health, positions, pnl, trades, amo]);

  // ── jarvis derived ──
  const h = health.data;
  const jarvisLive = !!h && h.status === "ok";
  const dataLegDown = h?.ibkr_data_connected === false;
  const openPaper = positions.data?.paper?.positions ?? [];
  const suspectCount = openPaper.filter((p) => suspectPrice(p.symbol, p.entry_price)).length;

  // ── amo derived ──
  const a = amo.data;
  const amoLive = !!a && a.status === "ok";

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
        {/* Integrity banner — surfaces suspect prices + data-leg degradation loudly */}
        {(suspectCount > 0 || dataLegDown) && (
          <div className="rounded-xl border border-bear/30 bg-bear/5 p-4 flex items-start gap-3">
            <AlertTriangle className="h-5 w-5 text-bear mt-0.5 shrink-0" />
            <div className="text-sm">
              <p className="font-semibold text-bear">Data-integrity warnings</p>
              <ul className="text-xs text-muted-foreground mt-1 list-disc pl-4 space-y-0.5">
                {suspectCount > 0 && (
                  <li>{suspectCount} open paper position{suspectCount > 1 ? "s have" : " has"} an implausible entry price — likely a corrupted field. Do not trust the signal until reconciled.</li>
                )}
                {dataLegDown && <li>jarvis IB data leg is disconnected — engine is on fallback data.</li>}
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
              <PanelHeader title="Liveness" provenance="live" />
              <div className="grid grid-cols-3 gap-3">
                <Stat label="Status" value={h?.status?.toUpperCase() ?? (health.error ? "DOWN" : "…")} tone={jarvisLive ? "bull" : "bear"} />
                <Stat label="Uptime" value={fmtUptime(h?.uptime_seconds)} />
                <Stat label="LLM" value={h?.llm_path_healthy ? "OK" : "DEGRADED"} tone={h?.llm_path_healthy ? "bull" : "bear"} />
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                <Badge variant={h?.ibkr_execution_connected ? "bull" : "warn"}>exec IB {h?.ibkr_execution_connected ? "✓" : "✗"}</Badge>
                <Badge variant={h?.ibkr_data_connected ? "bull" : "bear"}>data IB {h?.ibkr_data_connected ? "✓" : "✗"}</Badge>
                <Badge variant={h?.kill_switch_active ? "bear" : "neutral"}>kill {h?.kill_switch_active ? "ON" : "off"}</Badge>
                <Badge variant={h?.tradingview_mcp_healthy ? "bull" : "warn"}>TV {h?.tradingview_mcp_healthy ? "✓" : "✗"}</Badge>
              </div>
            </Card>

            {/* 2. Today's P&L */}
            <Card>
              <PanelHeader title={`Today's P&L${pnl.data?.date ? ` · ${pnl.data.date}` : ""}`} provenance="live" />
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
              <PanelHeader title={`Open Positions (${openPaper.length})`} provenance="live" />
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

            {/* 4. Per-trade post-mortem */}
            <Card>
              <PanelHeader title="Recent Trades — win/loss & why" provenance="live" />
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

            {/* 5. Data integrity — bar coverage/health (live after engine restart) */}
            <BarDepthCard />
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
              <PanelHeader title="Liveness" provenance="live" />
              <div className="grid grid-cols-3 gap-3">
                <Stat label="Status" value={a?.status?.toUpperCase() ?? (amo.error ? "DOWN" : "…")} tone={amoLive ? "bull" : "bear"} />
                <Stat label="Scheduler" value={a?.scheduler_running ? "RUNNING" : "STOPPED"} tone={a?.scheduler_running ? "bull" : "bear"} />
                <Stat label="Jobs" value={String(a?.scheduled_jobs ?? 0)} />
              </div>
              {a?.version && <p className="text-[11px] text-muted-foreground mt-2">v{a.version}</p>}
            </Card>

            {/* Scheduled jobs */}
            <Card>
              <PanelHeader title="Scheduled Jobs" provenance="live" />
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
                  surfaces seasonal/spread setups but has no live order execution or per-trade P&L feed yet. Trades
                  are placed manually off its signals, so same-day P&L and post-trade analysis live on the jarvis side.
                  Building an amo execution/outcomes view is a tracked Phase-4 item.
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
