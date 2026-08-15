"use client";

import React, { useState } from "react";
import { useWebSocket } from "@/hooks/useWebSocket";
import { useIBDataHealth } from "@/hooks/useIBDataHealth";
import type { SWRResponse } from "swr";
import {
  TrendingUp,
  Activity,
  Shield,
  Clock,
  AlertTriangle,
  Zap,
  CheckCircle,
  XCircle,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/utils";
import { EquityCurveMini } from "@/components/command-center/EquityCurveMini";
import { DrawdownMini } from "@/components/command-center/DrawdownMini";
import { symbolTradeStatus } from "@/lib/approvedSymbols";

// ── Local types (mirrors what the command center page uses) ───────────────

interface HealthData {
  status: string;
  kill_switch_active: boolean;
  uptime_seconds: number;
  ibkr_connected: boolean;
  ibkr_execution_connected?: boolean | null;
  ibkr_data_connected?: boolean | null;
  paper_trading?: boolean;
  version?: string;
}

interface SafetyData {
  daily_pnl: number;
  equity_peak: number;
  drawdown_pct: number;
  orders_last_minute: number;
  consecutive_losses?: number;
  kill_switch_active?: boolean;
}

interface Position {
  symbol: string;
  quantity: number;
  avg_cost: number;
  current_price?: number;
  unrealized_pnl?: number;
}

interface PortfolioData {
  total_equity: number;
  daily_pnl: number;
  positions: Position[];
  cash?: number;
}

interface Decision {
  timestamp: string;
  symbol: string;
  action: string;
  reason?: string;
  signal?: string;
  regime?: string;
  quantity?: number;
  price?: number;
  confidence?: number;
}

interface SchedulerData {
  running: boolean;
  jobs?: { name: string; last_run: string | null; next_run: string | null; running: boolean }[];
  total_decisions_logged: number;
  last_scan?: string;
  next_scan?: string;
}

interface MacroData {
  vix?: number;
  vix_regime?: string;
  regime?: string;
  timestamp?: string;
}

interface SessionInfo {
  label: string;
  color: string;
  badge: string;
  isActive: boolean;
}

export interface CommandCenterData {
  session: SessionInfo;
  health: SWRResponse<HealthData>;
  safety: SWRResponse<SafetyData>;
  portfolio: SWRResponse<PortfolioData>;
  decisions: SWRResponse<Decision[]>;
  scheduler: SWRResponse<SchedulerData>;
  macro: SWRResponse<MacroData>;
  trades: SWRResponse<unknown[]>;
  refreshInterval: number;
}

// ── Instruments config ────────────────────────────────────────────────────

// D2-02: `status` used to be hand-maintained here and drifted backwards
// (MCL/MNQ shown APPROVED, MGC shown HALTED). Status is now always derived
// from symbolTradeStatus() below — never hardcode it in this list again.
const INSTRUMENTS = [
  { symbol: "MCL", tf: "1h", wfe: 0.82 },
  { symbol: "MNQ", tf: "1h", wfe: 0.57 },
  { symbol: "MGC", tf: "1d", wfe: 0.14 },
] as const;

// ── Helpers ───────────────────────────────────────────────────────────────

function fmtUSD(n: number | undefined | null): string {
  if (n == null || isNaN(n)) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(n);
}

function fmtPct(n: number | undefined | null, decimals = 2): string {
  if (n == null || isNaN(n)) return "—";
  return (n >= 0 ? "+" : "") + n.toFixed(decimals) + "%";
}

function fmtTime(ts: string | null | undefined): string {
  if (!ts) return "—";
  try {
    return new Date(ts).toLocaleTimeString("en-US", {
      hour12: false,
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return "—";
  }
}

function pnlColor(n: number | undefined | null): string {
  if (n == null) return "text-gray-400";
  if (n > 0) return "text-green-400";
  if (n < 0) return "text-red-400";
  return "text-gray-300";
}

function wfeBadgeClass(wfe: number): string {
  if (wfe > 0.5) return "bg-green-950 text-green-400 border-green-800";
  if (wfe > 0.3) return "bg-yellow-950 text-yellow-400 border-yellow-800";
  return "bg-red-950 text-red-400 border-red-800";
}

function vixRegimeColor(regime: string | undefined): string {
  if (!regime) return "text-slate-400";
  const r = regime.toUpperCase();
  if (r === "VERY_LOW" || r === "LOW") return "text-green-400";
  if (r === "NORMAL") return "text-yellow-400";
  if (r === "ELEVATED") return "text-orange-400";
  if (r === "HIGH" || r === "EXTREME" || r === "EXTREME_FEAR" || r === "FEAR") return "text-red-400";
  return "text-slate-400";
}

// ── Sub-components ────────────────────────────────────────────────────────

function SectionHeader({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-xs font-mono text-cyan-400 tracking-widest uppercase flex items-center gap-1.5">
      {children}
    </p>
  );
}

function DataRow({
  label,
  value,
  valueClass,
}: {
  label: string;
  value: React.ReactNode;
  valueClass?: string;
}) {
  return (
    <div className="flex justify-between items-baseline">
      <span className="text-xs text-slate-500 font-mono">{label}</span>
      <span className={cn("font-mono text-sm font-bold text-white", valueClass)}>
        {value}
      </span>
    </div>
  );
}

// ── Card 1: Portfolio ─────────────────────────────────────────────────────

function PortfolioCard({ portfolio }: { portfolio?: PortfolioData }) {
  const dailyPnlPct =
    portfolio?.total_equity && portfolio.total_equity > 0
      ? (portfolio.daily_pnl / portfolio.total_equity) * 100
      : 0;

  return (
    <Card className="bg-slate-900/60 border border-cyan-900/40">
      <CardHeader className="pb-1.5 pt-3 px-4">
        <CardTitle className="text-xs font-mono text-cyan-400 tracking-widest flex items-center gap-1.5">
          <TrendingUp className="w-3 h-3" />
          PORTFOLIO
        </CardTitle>
      </CardHeader>
      <CardContent className="px-4 pb-3 space-y-2">
        <div className="mb-1">
          <div className="text-xs text-slate-500 font-mono mb-0.5">Total Equity</div>
          <div className="font-mono text-2xl text-white font-bold tabular-nums leading-none">
            {fmtUSD(portfolio?.total_equity)}
          </div>
        </div>
        <DataRow
          label="Daily P&L"
          value={
            <>
              <span className={pnlColor(portfolio?.daily_pnl)}>
                {fmtUSD(portfolio?.daily_pnl)}
              </span>
              <span className="text-xs ml-1 opacity-60 text-slate-400">
                ({fmtPct(dailyPnlPct)})
              </span>
            </>
          }
        />
        <DataRow
          label="Open Positions"
          value={portfolio?.positions?.length ?? "—"}
        />
        <DataRow
          label="Cash Balance"
          valueClass="text-slate-400 text-xs"
          value={fmtUSD(portfolio?.cash)}
        />
      </CardContent>
    </Card>
  );
}

// ── Card 2: Active Instruments ────────────────────────────────────────────

function InstrumentsCard({
  livePrices,
  wsConnected,
}: {
  livePrices: Record<string, number>;
  wsConnected: boolean;
}) {
  // Honesty: a live WS socket does NOT mean the served market data is live.
  // When the IB data leg is degraded (serving a non-IBKR fallback tier —
  // csv_cache / polygon / sqlite_cache), reflect the actual source instead of
  // claiming LIVE. Mirrors useIBDataHealth's own signal (same as the degraded
  // banner); hasSignal guards engine builds that lack the PR#68 fields.
  const { isDataDegraded, dataSource, hasSignal } = useIBDataHealth();
  const dataDegraded = hasSignal && isDataDegraded;
  const statusLabel = !wsConnected ? "OFFLINE" : dataDegraded ? "STALE" : "LIVE";
  const dotClass = !wsConnected
    ? "bg-slate-700"
    : dataDegraded
      ? "bg-amber-500 animate-pulse"
      : "bg-green-500 animate-pulse";
  const statusTitle = dataDegraded
    ? `Serving ${(dataSource ?? "fallback").toUpperCase()} fallback — not live IBKR data`
    : undefined;

  return (
    <Card className="bg-slate-900/60 border border-cyan-900/40">
      <CardHeader className="pb-1.5 pt-3 px-4">
        <CardTitle className="text-xs font-mono text-cyan-400 tracking-widest flex items-center gap-1.5">
          <Activity className="w-3 h-3" />
          ACTIVE INSTRUMENTS
          <span
            className={`ml-auto flex items-center gap-1 text-[10px] ${
              dataDegraded ? "text-amber-500" : "text-slate-600"
            }`}
            title={statusTitle}
          >
            <span className={`w-1.5 h-1.5 rounded-full ${dotClass}`} />
            {statusLabel}
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="px-4 pb-3 space-y-3">
        {INSTRUMENTS.map((inst) => {
          const price = livePrices[inst.symbol];
          const status = symbolTradeStatus(inst.symbol);
          return (
            <div key={inst.symbol} className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                {status === "APPROVED" ? (
                  <CheckCircle className="w-3.5 h-3.5 text-green-400 flex-shrink-0" />
                ) : (
                  <XCircle className="w-3.5 h-3.5 text-red-400 flex-shrink-0" />
                )}
                <span className="font-mono text-sm text-white font-bold">
                  {inst.symbol}
                </span>
                <span className="font-mono text-xs text-slate-600 bg-slate-800 px-1 rounded">
                  {inst.tf}
                </span>
                {price != null && (
                  <span className="font-mono text-xs text-cyan-400 tabular-nums">
                    {price.toFixed(2)}
                  </span>
                )}
              </div>
              <div className="flex items-center gap-1.5">
                <Badge
                  className={cn(
                    "text-xs font-mono py-0 px-1.5 border",
                    wfeBadgeClass(inst.wfe)
                  )}
                >
                  WFE={inst.wfe}
                </Badge>
                <Badge
                  className={cn(
                    "text-xs font-mono py-0 px-1.5 border",
                    status === "APPROVED"
                      ? "bg-green-950 text-green-400 border-green-800"
                      : "bg-red-950 text-red-400 border-red-800"
                  )}
                >
                  {status === "APPROVED" ? "ACTIVE" : "HALTED"}
                </Badge>
              </div>
            </div>
          );
        })}
        <div className="pt-1 mt-1 border-t border-slate-800/50 text-xs font-mono text-slate-600">
          Next WFE recalc: Sunday 06:00 CT
        </div>
      </CardContent>
    </Card>
  );
}

// ── Card 3: Safety Layer ──────────────────────────────────────────────────

function SafetyCard({
  safety,
  portfolio,
}: {
  safety?: SafetyData;
  portfolio?: PortfolioData;
}) {
  const killSwitchActive = safety?.kill_switch_active ?? false;
  const dailyPnlPct =
    portfolio?.total_equity && portfolio.total_equity > 0
      ? (portfolio.daily_pnl / portfolio.total_equity) * 100
      : 0;
  const drawdownPct = safety?.drawdown_pct ?? 0;
  const consecutiveLosses = safety?.consecutive_losses ?? 0;

  return (
    <Card
      className={cn(
        "bg-slate-900/60 border",
        killSwitchActive ? "border-red-700" : "border-cyan-900/40"
      )}
    >
      <CardHeader className="pb-1.5 pt-3 px-4">
        <CardTitle className="text-xs font-mono text-cyan-400 tracking-widest flex items-center gap-1.5">
          <Shield className="w-3 h-3" />
          SAFETY LAYER
        </CardTitle>
      </CardHeader>
      <CardContent className="px-4 pb-3 space-y-2">
        <div className="flex justify-between items-center">
          <span className="text-xs text-slate-500 font-mono">Kill Switch</span>
          <Badge
            className={cn(
              "text-xs font-mono py-0 px-1.5 border",
              killSwitchActive
                ? "bg-red-900 text-red-200 border-red-600 animate-pulse"
                : "bg-green-950 text-green-400 border-green-800"
            )}
          >
            {killSwitchActive ? "⚠ ACTIVE" : "ARMED"}
          </Badge>
        </div>
        <div className="flex justify-between items-baseline">
          <span className="text-xs text-slate-500 font-mono">Daily Loss</span>
          <span
            className={cn(
              "font-mono text-xs",
              dailyPnlPct < -1 ? "text-red-400" : "text-green-400"
            )}
          >
            {fmtPct(dailyPnlPct)} / -2%
          </span>
        </div>
        <div className="flex justify-between items-baseline">
          <span className="text-xs text-slate-500 font-mono">Drawdown</span>
          <span
            className={cn(
              "font-mono text-xs",
              drawdownPct < -5 ? "text-red-400" : "text-yellow-400"
            )}
          >
            {fmtPct(drawdownPct)} / -10%
          </span>
        </div>
        <div className="flex justify-between items-baseline">
          <span className="text-xs text-slate-500 font-mono">Consec. Losses</span>
          <span
            className={cn(
              "font-mono text-xs",
              consecutiveLosses >= 4 ? "text-red-400" : "text-slate-300"
            )}
          >
            {consecutiveLosses} / 7
          </span>
        </div>
      </CardContent>
    </Card>
  );
}

// ── Card 4: Market Session ────────────────────────────────────────────────

function SessionCard({
  session,
  macro,
}: {
  session: SessionInfo;
  macro?: MacroData;
}) {
  const sessionLabel = session.label ?? "UNKNOWN";

  return (
    <Card className="bg-slate-900/60 border border-cyan-900/40">
      <CardHeader className="pb-1.5 pt-3 px-4">
        <CardTitle className="text-xs font-mono text-cyan-400 tracking-widest flex items-center gap-1.5">
          <Clock className="w-3 h-3" />
          MARKET SESSION
        </CardTitle>
      </CardHeader>
      <CardContent className="px-4 pb-3 space-y-2">
        <Badge
          className={cn(
            "w-full justify-center text-xs font-mono py-1 border",
            session.badge
          )}
        >
          {sessionLabel}
        </Badge>
        <div className="flex justify-between items-baseline">
          <span className="text-xs text-slate-500 font-mono">VIX</span>
          <span className="font-mono text-sm text-white font-bold tabular-nums">
            {macro?.vix != null ? macro.vix.toFixed(2) : "—"}
          </span>
        </div>
        <div className="flex justify-between items-baseline">
          <span className="text-xs text-slate-500 font-mono">VIX Regime</span>
          <span
            className={cn(
              "font-mono text-xs font-bold",
              vixRegimeColor(macro?.vix_regime)
            )}
          >
            {macro?.vix_regime ?? "—"}
          </span>
        </div>
        <div className="flex justify-between items-center">
          <span className="text-xs text-slate-500 font-mono">Status</span>
          <Badge
            className={cn(
              "text-xs font-mono py-0 border",
              session.isActive
                ? "bg-green-950 text-green-400 border-green-800"
                : "bg-slate-800 text-slate-500 border-slate-700"
            )}
          >
            {session.isActive ? "● TRADING" : "○ STANDBY"}
          </Badge>
        </div>
      </CardContent>
    </Card>
  );
}

// ── Row 2 Left: Risk Gauges ───────────────────────────────────────────────

interface GaugeProps {
  label: string;
  value: string;
  progress: number;
  subtext: string;
  danger?: boolean;
  warning?: boolean;
}

function Gauge({ label, value, progress, subtext, danger, warning }: GaugeProps) {
  const barColor = danger
    ? "[&>div]:bg-red-500"
    : warning
    ? "[&>div]:bg-yellow-500"
    : "[&>div]:bg-cyan-500";

  return (
    <div>
      <div className="flex justify-between text-xs font-mono mb-1.5">
        <span className="text-slate-400">{label}</span>
        <span className={cn(danger ? "text-red-400" : warning ? "text-yellow-400" : "text-slate-300")}>
          {value}
        </span>
      </div>
      <Progress
        value={progress}
        className={cn("h-2.5 bg-slate-800", barColor)}
      />
      <div className="text-right text-xs text-slate-600 font-mono mt-0.5">
        {subtext}
      </div>
    </div>
  );
}

function RiskGaugesCard({
  safety,
  portfolio,
}: {
  safety?: SafetyData;
  portfolio?: PortfolioData;
}) {
  const dailyPnlPct =
    portfolio?.total_equity && portfolio.total_equity > 0
      ? (portfolio.daily_pnl / portfolio.total_equity) * 100
      : 0;
  const dailyLossProgress = Math.min(
    (Math.abs(Math.min(dailyPnlPct, 0)) / 2) * 100,
    100
  );
  const drawdownPct = safety?.drawdown_pct ?? 0;
  const drawdownProgress = Math.min((Math.abs(drawdownPct) / 10) * 100, 100);
  const consecutiveLosses = safety?.consecutive_losses ?? 0;
  const consecutiveLossProgress = Math.min((consecutiveLosses / 7) * 100, 100);
  const ordersPerMin = safety?.orders_last_minute ?? 0;
  const ordersProgress = Math.min((ordersPerMin / 10) * 100, 100);

  return (
    <Card className="bg-slate-900/60 border border-cyan-900/40">
      <CardHeader className="pb-2 pt-3 px-4">
        <CardTitle className="text-xs font-mono text-cyan-400 tracking-widest flex items-center gap-1.5">
          <AlertTriangle className="w-3 h-3" />
          RISK GAUGES
        </CardTitle>
      </CardHeader>
      <CardContent className="px-4 pb-4 space-y-4">
        <Gauge
          label="Daily P&L vs Limit"
          value={`${fmtPct(dailyPnlPct)} / -2.00%`}
          progress={dailyLossProgress}
          subtext={`${dailyLossProgress.toFixed(0)}% consumed`}
          danger={dailyLossProgress > 75}
        />
        <Gauge
          label="Peak Drawdown"
          value={`${fmtPct(drawdownPct)} / -10.00%`}
          progress={drawdownProgress}
          subtext={`${drawdownProgress.toFixed(0)}% consumed`}
          danger={drawdownProgress > 75}
        />
        <Gauge
          label="Consecutive Losses"
          value={`${consecutiveLosses} / 7`}
          progress={consecutiveLossProgress}
          subtext={`${consecutiveLossProgress.toFixed(0)}% of circuit breaker`}
          danger={consecutiveLossProgress > 85}
          warning={consecutiveLossProgress > 57}
        />
        <Gauge
          label="Orders / Minute"
          value={`${ordersPerMin} / 10 limit`}
          progress={ordersProgress}
          subtext={`${ordersProgress.toFixed(0)}% of rate limit`}
          danger={ordersProgress > 75}
        />
      </CardContent>
    </Card>
  );
}

// ── Row 2 Right: Recent Signals + Pipeline ────────────────────────────────

function RecentSignalsCard({
  decisions,
  scheduler,
}: {
  decisions?: Decision[];
  scheduler?: SchedulerData;
}) {
  return (
    <Card className="bg-slate-900/60 border border-cyan-900/40">
      <CardHeader className="pb-2 pt-3 px-4">
        <CardTitle className="text-xs font-mono text-cyan-400 tracking-widest flex items-center gap-1.5">
          <Zap className="w-3 h-3" />
          RECENT SIGNALS
        </CardTitle>
      </CardHeader>
      <CardContent className="px-4 pb-3">
        {!decisions || decisions.length === 0 ? (
          <div className="text-xs text-slate-500 font-mono py-6 text-center">
            No recent decisions from /decisions/recent
          </div>
        ) : (
          <div className="space-y-2.5">
            {decisions.slice(0, 5).map((d, i) => (
              <div
                key={i}
                className="flex items-center justify-between border-b border-slate-800/50 pb-2 last:border-0 last:pb-0"
              >
                <div className="flex items-center gap-2 min-w-0">
                  <span className="font-mono text-xs text-slate-500 flex-shrink-0 tabular-nums">
                    {fmtTime(d.timestamp)}
                  </span>
                  <span className="font-mono text-xs text-white font-bold flex-shrink-0">
                    {d.symbol}
                  </span>
                  <Badge
                    className={cn(
                      "text-xs font-mono py-0 px-1.5 flex-shrink-0 border",
                      d.action === "LONG" || d.action === "BUY"
                        ? "bg-green-950 text-green-400 border-green-800"
                        : d.action === "SHORT" || d.action === "SELL"
                        ? "bg-red-950 text-red-400 border-red-800"
                        : "bg-slate-800 text-slate-400 border-slate-700"
                    )}
                  >
                    {d.action}
                  </Badge>
                  {d.confidence != null && (
                    <span className="font-mono text-xs text-slate-500 flex-shrink-0">
                      {(d.confidence * 100).toFixed(0)}%
                    </span>
                  )}
                </div>
                <span className="font-mono text-xs text-slate-500 truncate max-w-[120px] ml-2">
                  {d.reason ?? d.regime ?? "—"}
                </span>
              </div>
            ))}
          </div>
        )}

        {/* Pipeline status */}
        <div className="mt-3 pt-3 border-t border-slate-800/50 space-y-1.5">
          <div className="flex items-center justify-between">
            <span className="text-xs text-slate-500 font-mono">Pipeline Scheduler</span>
            <Badge
              className={cn(
                "text-xs font-mono py-0 border",
                scheduler?.running
                  ? "bg-green-950 text-green-400 border-green-800"
                  : "bg-slate-800 text-slate-500 border-slate-700"
              )}
            >
              {scheduler?.running ? "● RUNNING" : "○ IDLE"}
            </Badge>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-xs text-slate-500 font-mono">Last Scan</span>
            <span className="font-mono text-xs text-white tabular-nums">
              {fmtTime(scheduler?.last_scan)}
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-xs text-slate-500 font-mono">Next Scan</span>
            <span className="font-mono text-xs text-cyan-400 tabular-nums">
              {fmtTime(scheduler?.next_scan)}
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-xs text-slate-500 font-mono">Total Decisions</span>
            <span className="font-mono text-xs text-cyan-400 font-bold">
              {scheduler?.total_decisions_logged ?? "—"}
            </span>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

// ── Main Tab ──────────────────────────────────────────────────────────────

interface OverviewTabProps {
  data: CommandCenterData;
}

export default function OverviewTab({ data }: OverviewTabProps) {
  const portfolio = data.portfolio.data;
  const safety = data.safety.data;
  const macro = data.macro.data;
  const decisions = data.decisions.data;
  const scheduler = data.scheduler.data;

  // ── WebSocket: live price ticks for all instruments ───────────────────────
  const [livePrices, setLivePrices] = useState<Record<string, number>>({});
  const { isConnected: wsConnected } = useWebSocket(undefined, (event) => {
    if (event.type === "price_update") {
      setLivePrices((prev) => ({ ...prev, [event.symbol]: event.price }));
    }
  });

  return (
    <div className="space-y-3 font-mono">
      {/* Row 1 — 4 equal status cards */}
      <div className="grid grid-cols-4 gap-3">
        <PortfolioCard portfolio={portfolio} />
        <InstrumentsCard livePrices={livePrices} wsConnected={wsConnected} />
        <SafetyCard safety={safety} portfolio={portfolio} />
        <SessionCard session={data.session} macro={macro} />
      </div>

      {/* Row 2 — Risk Gauges (60%) + Recent Signals (40%) */}
      <div className="grid grid-cols-5 gap-3">
        <div className="col-span-3">
          <RiskGaugesCard safety={safety} portfolio={portfolio} />
        </div>
        <div className="col-span-2">
          <RecentSignalsCard decisions={decisions} scheduler={scheduler} />
        </div>
      </div>

      {/* Row 3 — Performance Charts */}
      <div className="grid grid-cols-2 gap-4">
        <EquityCurveMini />
        <DrawdownMini />
      </div>
    </div>
  );
}
