"use client";

import useSWR from "swr";
import dynamic from "next/dynamic";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  TrendingUp,
  TrendingDown,
  Minus,
  RefreshCw,
  Wifi,
  WifiOff,
  Brain,
  Monitor,
  Server,
  BarChart3,
} from "lucide-react";
import { fetchEngine } from "@/lib/api";
import { executionStatus, type ExecutionPathProbe } from "@/lib/executionPath";
import { MarketContextStrip } from "@/components/charts/MarketContextStrip";
import { getBannerVariant, type BannerVariant } from "@/lib/todayBanner";

// lightweight-charts backed live chart, second-screen content below the status banner
// and metric cards — defer the chunk instead of paying for it in the initial route JS.
const MarketChart = dynamic(
  () => import("@/components/charts/MarketChart").then((m) => ({ default: m.MarketChart })),
  { ssr: false, loading: () => <div className="h-[320px] animate-pulse rounded-lg bg-muted/20" /> }
);

// ── Constants ──────────────────────────────────────────────────────────────────

const REFRESH_MS = 30_000;

// ── Types ──────────────────────────────────────────────────────────────────────

interface LLMProviders {
  active_provider: string;
  primary_provider: string;
  providers_configured: string[];
  providers_available: number;
  primary_healthy: boolean;
  single_leg_warning: boolean;
}

interface HealthResponse {
  status: string;
  version: string;
  live_trading: boolean;
  kill_switch_active: boolean;
  paper_mode: boolean;
  ibkr_connected: boolean;
  ibkr_execution_connected?: boolean | null;
  ibkr_data_connected?: boolean | null;
  schwab_connected: boolean;
  uptime_seconds: number;
  tradingview_mcp_healthy?: boolean | null;
  tradingview_mcp_details?: string | null;
  llm_path_healthy?: boolean | null;
  llm_available?: boolean | null;
  llm_providers?: LLMProviders | null;
  // D3-01: honest execution-path fields — see @/lib/executionPath.
  execution_connected_verified?: boolean | null;
  ib_execution_stale?: boolean | null;
  execution_path?: ExecutionPathProbe | null;
}

interface SessionTodayResponse {
  date: string;
  session: string;
  closed_trades: number;
  open_trades: number;
  gross_pnl: number;
  wins: number;
  losses: number;
  win_rate: number | null;
  best_trade: number | null;
  worst_trade: number | null;
  avg_pnl: number | null;
  symbols_traded: string[];
  last_updated: string;
}

interface EODSummaryResponse {
  date: string;
  trades_today: number;
  pnl_today_usd: number;
  wins_today: number;
  losses_today: number;
  win_rate_today: number | null;
  avg_r_today: number | null;
  cumulative_trades: number;
  cumulative_pnl_usd: number;
  validation_gates: {
    pf: number | null;
    sharpe: number | null;
    win_rate: number | null;
    trades_count: number;
    days_trading: number;
    max_drawdown: number | null;
  };
  status: "on_track" | "at_risk" | "insufficient_data";
}

interface OpenPositionsResponse {
  positions: Array<{
    trade_id: string;
    symbol: string;
    action: string;
    quantity: number;
    entry_price: number;
    entry_time: string;
    stop_loss: number | null;
    take_profit: number | null;
    unrealized_pnl?: number | null;
  }>;
  count: number;
}

// ── Fetcher ────────────────────────────────────────────────────────────────────

function fetcher<T>(url: string): Promise<T> {
  return fetchEngine<T>(url);
}

// ── Status helpers ─────────────────────────────────────────────────────────────
// getBannerVariant itself now lives in @/lib/todayBanner (GT-09) so it can be
// unit-tested with node:test without pulling in this file's JSX/React deps.

const BANNER_CONFIG: Record<BannerVariant, { label: string; sublabel: string; color: string; bg: string; borderColor: string }> = {
  live_ok: {
    label: "LIVE TRADING",
    sublabel: "Engine healthy — live execution enabled",
    color: "#00ff88",
    bg: "rgba(0,255,136,0.06)",
    borderColor: "rgba(0,255,136,0.35)",
  },
  paper_ok: {
    label: "PAPER MODE",
    sublabel: "Engine healthy — paper simulation active",
    color: "#00d4ff",
    bg: "rgba(0,212,255,0.06)",
    borderColor: "rgba(0,212,255,0.35)",
  },
  degraded: {
    label: "DEGRADED",
    sublabel: "Engine connected — a subsystem (LLM/data/execution) needs attention",
    color: "#ffcc00",
    bg: "rgba(255,204,0,0.06)",
    borderColor: "rgba(255,204,0,0.35)",
  },
  unreachable: {
    label: "ENGINE UNREACHABLE",
    sublabel: "Cannot connect to engine at :8010",
    color: "#ff4444",
    bg: "rgba(255,68,68,0.06)",
    borderColor: "rgba(255,68,68,0.35)",
  },
};

// ── Sub-components ─────────────────────────────────────────────────────────────

function StatusBadge({ ok, label }: { ok: boolean | null | undefined; label: string }) {
  const c = ok === true ? "#00ff88" : ok === false ? "#ff4444" : "#888";
  const icon = ok === true
    ? <CheckCircle2 className="h-3 w-3" />
    : ok === false
    ? <XCircle className="h-3 w-3" />
    : <Minus className="h-3 w-3" />;
  return (
    <div className="flex items-center gap-1.5">
      <span style={{ color: c }}>{icon}</span>
      <span className="font-mono text-[10px] text-muted-foreground">{label}</span>
    </div>
  );
}

function PulsingDot({ color }: { color: string }) {
  return (
    <span className="relative flex h-2.5 w-2.5 shrink-0">
      <span className="animate-ping absolute inline-flex h-full w-full rounded-full opacity-60" style={{ backgroundColor: color }} />
      <span className="relative inline-flex rounded-full h-2.5 w-2.5" style={{ backgroundColor: color }} />
    </span>
  );
}

function MetricCard({
  icon,
  label,
  value,
  sub,
  subTitle,
  valueColor,
}: {
  icon: React.ReactNode;
  label: string;
  value: React.ReactNode;
  sub?: string;
  /** Hover/title disclosure for the sub line (e.g. metric-honesty notes). */
  subTitle?: string;
  valueColor?: string;
}) {
  return (
    <div className="rounded-xl border border-border bg-card p-4 space-y-2">
      <div className="flex items-center gap-2">
        <span className="text-muted-foreground/60">{icon}</span>
        <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
          {label}
        </p>
      </div>
      <p
        className="font-mono text-2xl font-bold tabular-nums leading-none"
        style={{ color: valueColor ?? "hsl(var(--foreground))" }}
      >
        {value}
      </p>
      {sub && (
        <p
          className="font-mono text-[10px] text-muted-foreground truncate"
          title={subTitle}
        >
          {sub}
        </p>
      )}
    </div>
  );
}

function LoadingCard() {
  return (
    <div className="rounded-xl border border-border bg-card p-4 space-y-2 animate-pulse">
      <div className="h-2.5 w-20 bg-muted rounded" />
      <div className="h-7 w-28 bg-muted rounded" />
      <div className="h-2.5 w-16 bg-muted rounded" />
    </div>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────────

export default function TodayPage() {
  const {
    data: health,
    error: healthError,
    isLoading: healthLoading,
    mutate: mutateHealth,
  } = useSWR<HealthResponse>("/health", fetcher, { refreshInterval: REFRESH_MS });

  const { data: session, isLoading: sessionLoading } = useSWR<SessionTodayResponse>(
    "/portfolio/stats/session-today",
    fetcher,
    { refreshInterval: REFRESH_MS }
  );

  const { data: eod, isLoading: eodLoading } = useSWR<EODSummaryResponse>(
    "/paper/validation/summary/eod",
    fetcher,
    { refreshInterval: REFRESH_MS }
  );

  const { data: positions, isLoading: positionsLoading } = useSWR<OpenPositionsResponse>(
    "/portfolio/paper/positions",
    fetcher,
    { refreshInterval: REFRESH_MS }
  );

  const isAnyLoading = healthLoading || sessionLoading || eodLoading || positionsLoading;
  const bannerVariant = getBannerVariant(health, !!healthError);
  const banner = BANNER_CONFIG[bannerVariant];

  // PnL: prefer eod.pnl_today_usd (realized) + note if positions have unrealized
  const pnlRealized = eod?.pnl_today_usd ?? session?.gross_pnl ?? 0;
  const pnlColor = pnlRealized > 0 ? "#00ff88" : pnlRealized < 0 ? "#ff4444" : "#888";
  const pnlSign = pnlRealized >= 0 ? "+" : "";

  // Trades today: use session endpoint (closed + open)
  const tradesToday = session ? session.closed_trades + session.open_trades : null;
  const openCount = positions?.count ?? session?.open_trades ?? null;

  // Lead symbol for the live chart: first open position, else first traded symbol,
  // else MES. MarketChart routes futures → our real-time bars, equities → TradingView.
  const leadSymbol =
    positions?.positions?.[0]?.symbol ?? session?.symbols_traded?.[0] ?? "MES";

  // LLM provider display
  const llmProvider = health?.llm_providers?.active_provider ?? null;
  const llmHealthy = health?.llm_path_healthy ?? null;
  const tvHealthy = health?.tradingview_mcp_healthy ?? null;
  const dataLegOk = health?.ibkr_data_connected ?? null;
  // D3-01: derive execution-leg status through the honesty layer — never
  // read ibkr_execution_connected directly (see @/lib/executionPath).
  const exec = executionStatus(health);

  // Validation status color
  const statusColor =
    eod?.status === "on_track" ? "#00ff88"
    : eod?.status === "at_risk" ? "#ffcc00"
    : "#888";

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="sticky top-0 z-50 border-b border-border bg-background/95 backdrop-blur">
        <div className="flex items-center justify-between px-6 py-3">
          <div className="flex items-center gap-2">
            <Activity className="h-4 w-4 text-accent" />
            <h1 className="font-mono text-sm font-bold tracking-widest uppercase text-foreground">
              Today at a Glance
            </h1>
          </div>
          <div className="flex items-center gap-3">
            {isAnyLoading && (
              <RefreshCw className="h-3.5 w-3.5 text-muted-foreground animate-spin" />
            )}
            <span className="font-mono text-[10px] text-muted-foreground">
              Auto-refresh 30s
            </span>
            <button
              onClick={() => mutateHealth()}
              className="font-mono text-[10px] text-muted-foreground hover:text-foreground transition-colors"
            >
              Refresh
            </button>
          </div>
        </div>
      </header>

      <main className="px-6 py-6 space-y-6 max-w-5xl mx-auto">

        {/* ── Status Banner ─────────────────────────────────────────────────── */}
        <div
          className="rounded-xl border p-4 flex items-center gap-4"
          style={{ background: banner.bg, borderColor: banner.borderColor }}
        >
          {bannerVariant !== "unreachable" && bannerVariant !== "degraded" ? (
            <PulsingDot color={banner.color} />
          ) : (
            <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: banner.color }} />
          )}
          <div className="flex-1 min-w-0">
            <p className="font-mono text-sm font-bold tracking-widest uppercase" style={{ color: banner.color }}>
              {banner.label}
            </p>
            <p className="font-mono text-[10px] text-muted-foreground">{banner.sublabel}</p>
          </div>
          {health && (
            <div className="text-right hidden sm:block">
              <p className="font-mono text-[10px] text-muted-foreground">
                Uptime {Math.floor((health.uptime_seconds ?? 0) / 3600)}h {Math.floor(((health.uptime_seconds ?? 0) % 3600) / 60)}m
              </p>
              <p className="font-mono text-[10px]" style={{ color: banner.color }}>
                v{health.version}
              </p>
            </div>
          )}
        </div>

        {/* ── Metric cards ───────────────────────────────────────────────────── */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {/* Trades Today */}
          {sessionLoading ? (
            <LoadingCard />
          ) : (
            <MetricCard
              icon={<BarChart3 className="h-4 w-4" />}
              label="Trades Today"
              value={tradesToday ?? "—"}
              sub={session
                ? `${session.closed_trades} closed · ${session.open_trades} open · ${session.session}`
                : undefined}
              valueColor="#00d4ff"
            />
          )}

          {/* Today PnL */}
          {eodLoading && sessionLoading ? (
            <LoadingCard />
          ) : (
            <MetricCard
              icon={pnlRealized >= 0 ? <TrendingUp className="h-4 w-4" /> : <TrendingDown className="h-4 w-4" />}
              label="Today PnL"
              value={`${pnlSign}$${Math.abs(pnlRealized).toFixed(2)}`}
              sub={eod
                ? `${eod.wins_today}W / ${eod.losses_today}L · cum $${eod.cumulative_pnl_usd.toFixed(2)}`
                : session
                ? "raw session record · not deduped"
                : undefined}
              valueColor={pnlColor}
            />
          )}

          {/* Open Positions */}
          {positionsLoading ? (
            <LoadingCard />
          ) : (
            <MetricCard
              icon={<Monitor className="h-4 w-4" />}
              label="Open Positions"
              value={openCount ?? "—"}
              sub={
                positions && positions.count > 0
                  ? positions.positions.map((p) => `${p.symbol} ${p.action.toUpperCase()} x${p.quantity}`).join(" · ")
                  : "No open positions"
              }
              valueColor={openCount && openCount > 0 ? "#ffcc00" : "#888"}
            />
          )}

          {/* Validation Status */}
          {eodLoading ? (
            <LoadingCard />
          ) : (
            <MetricCard
              icon={<AlertTriangle className="h-4 w-4" />}
              label="Val Status"
              value={eod?.status?.replace("_", " ").toUpperCase() ?? "—"}
              sub={eod
                ? `PF ${eod.validation_gates.pf?.toFixed(2) ?? "?"} · Sharpe ${eod.validation_gates.sharpe?.toFixed(2) ?? "?"} · ${eod.validation_gates.trades_count} trades`
                : undefined}
              subTitle="Sharpe annualized by observed trading-days-per-year (not fixed 252)"
              valueColor={statusColor}
            />
          )}
        </div>

        {/* ── Live Chart ─────────────────────────────────────────────────────── */}
        <div className="rounded-xl border border-border bg-card p-4 space-y-3">
          <div className="flex items-center gap-2">
            <BarChart3 className="h-4 w-4 text-muted-foreground/60" />
            <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
              Live Chart — {leadSymbol}
            </p>
          </div>
          <MarketChart symbol={leadSymbol} timeframe="15m" height={320} />
        </div>

        {/* ── System Health Checklist ────────────────────────────────────────── */}
        <div className="rounded-xl border border-border bg-card p-4 space-y-4">
          <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
            System Health
          </p>

          {healthLoading ? (
            <div className="animate-pulse space-y-2">
              {[...Array(5)].map((_, i) => (
                <div key={i} className="h-4 w-48 bg-muted rounded" />
              ))}
            </div>
          ) : healthError ? (
            <div className="flex items-center gap-2 text-destructive">
              <XCircle className="h-4 w-4" />
              <span className="font-mono text-xs">Engine unreachable — check :8010</span>
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-8 gap-y-2">
              <StatusBadge
                ok={health?.status === "ok"}
                label={`Engine — ${health?.status ?? "unknown"}`}
              />
              <StatusBadge
                ok={exec.brokerReachable}
                label={`IBKR execution — ${exec.label.toLowerCase()}`}
              />
              <StatusBadge
                ok={dataLegOk}
                label={`IBKR data feed — ${dataLegOk ? "connected" : "down (TV covers bars)"}`}
              />
              <StatusBadge
                ok={tvHealthy}
                label={`TradingView MCP — ${tvHealthy ? "healthy" : health?.tradingview_mcp_details ?? "unavailable"}`}
              />
              <StatusBadge
                ok={llmHealthy}
                label={`LLM (${llmProvider ?? "?"}) — ${llmHealthy ? "healthy" : "degraded"}`}
              />
              <StatusBadge
                ok={!health?.kill_switch_active}
                label={`Kill switch — ${health?.kill_switch_active ? "ACTIVE" : "inactive"}`}
              />
            </div>
          )}

          {/* Provider chain when healthy */}
          {health?.llm_providers && (
            <div className="pt-2 border-t border-border/50">
              <div className="flex flex-wrap gap-2">
                {health.llm_providers.providers_configured?.map((p: string) => (
                  <span
                    key={p}
                    className="font-mono text-[9px] px-2 py-0.5 rounded-full border"
                    style={{
                      borderColor: p === health.llm_providers!.active_provider ? "#00ff88" : "hsl(var(--border))",
                      color: p === health.llm_providers!.active_provider ? "#00ff88" : "hsl(var(--muted-foreground))",
                    }}
                  >
                    {p === health.llm_providers!.active_provider ? "▶ " : ""}{p}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* ── Open Positions Detail ──────────────────────────────────────────── */}
        {positions && positions.count > 0 && (
          <div className="rounded-xl border border-border bg-card p-4 space-y-3">
            <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
              Open Positions — {positions.count}
            </p>
            <div className="space-y-2">
              {positions.positions.map((pos) => {
                const unreal = pos.unrealized_pnl ?? null;
                const unrColor = unreal === null ? "#888" : unreal >= 0 ? "#00ff88" : "#ff4444";
                return (
                  <div
                    key={pos.trade_id}
                    className="flex items-center justify-between rounded-lg border border-border/60 bg-muted/20 px-3 py-2"
                  >
                    <div className="flex items-center gap-3">
                      <span className="font-mono text-xs font-bold text-foreground">{pos.symbol}</span>
                      <span
                        className="font-mono text-[10px] px-1.5 py-0.5 rounded border uppercase"
                        style={{
                          color: pos.action.toLowerCase() === "buy" ? "#00ff88" : "#ff4444",
                          borderColor: pos.action.toLowerCase() === "buy" ? "rgba(0,255,136,0.3)" : "rgba(255,68,68,0.3)",
                        }}
                      >
                        {pos.action.toUpperCase()}
                      </span>
                      <span className="font-mono text-[10px] text-muted-foreground">
                        {pos.quantity}x @ ${pos.entry_price.toFixed(2)}
                      </span>
                    </div>
                    <div className="text-right">
                      {unreal !== null ? (
                        <span className="font-mono text-xs tabular-nums font-semibold" style={{ color: unrColor }}>
                          {unreal >= 0 ? "+" : ""}${unreal.toFixed(2)}
                        </span>
                      ) : (
                        <span className="font-mono text-[10px] text-muted-foreground/50">unrealized —</span>
                      )}
                      {pos.stop_loss && (
                        <p className="font-mono text-[9px] text-muted-foreground">
                          SL {pos.stop_loss.toFixed(2)}
                        </p>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* ── Market Context (TradingView — equities/indices/macro/crypto) ────── */}
        <MarketContextStrip />

      </main>
    </div>
  );
}
