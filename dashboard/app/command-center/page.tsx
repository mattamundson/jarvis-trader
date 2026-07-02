"use client";

import React, { useEffect, useState, useCallback, useMemo } from "react";
import useSWR from "swr";
import { JetBrains_Mono, Orbitron } from "next/font/google";
import {
  Shield,
  Zap,
  Activity,
  Clock,
  AlertTriangle,
  CheckCircle,
  XCircle,
  RefreshCw,
  TrendingUp,
  Database,
  Wifi,
  WifiOff,
  Power,
  ChevronRight,
  BookOpen,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { fetchEngine, fetchJournalStats, fetchBars, toggleKillSwitch, type JournalTradeStats, type OHLCVBar } from "@/lib/api";
import {
  fetchHonestTrades,
  type HonestTradeSet,
  dedupCaveat,
} from "@/lib/honestTrades";
import { CandlestickChart } from "@/components/command-center/charts/CandlestickChart";
import { INSTRUMENTS, WFE_ROWS } from "./constants";
import { SignalFeedWidget } from "@/components/SignalFeedWidget";
import LiveTradeReasoningWidget from "@/components/LiveTradeReasoningWidget";
import ApprovalPanel from "@/components/ApprovalPanel";
import { PortfolioCorrelationWidget } from "@/components/PortfolioCorrelationWidget";
import { WidgetErrorBoundary } from "@/components/WidgetErrorBoundary";
import { useToast } from "@/lib/toast-context";

const fontDisplay = Orbitron({
  subsets: ["latin"],
  weight: ["500", "700", "900"],
  variable: "--font-cc-display",
});
const fontMono = JetBrains_Mono({
  subsets: ["latin"],
  weight: ["400", "600"],
  variable: "--font-cc-mono",
});

// ── Types ──────────────────────────────────────────────────────────────────

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
}

interface SchedulerJob {
  name: string;
  last_run: string | null;
  next_run: string | null;
  running: boolean;
}

interface SchedulerData {
  running: boolean;
  jobs?: SchedulerJob[];
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

interface PaperStatusRow {
  status?: string;
  wfe?: number;
  wfe_label?: string;
  reason?: string;
  cleared_date?: string;
  closed_date?: string;
}

interface Trade {
  timestamp: string;
  symbol: string;
  action: string;
  quantity: number;
  price: number;
  pnl?: number;
  commission?: number;
}

// ── Market Session Detection (Central Time) ───────────────────────────────

interface SessionInfo {
  label: string;
  color: string;
  badge: string;
  isActive: boolean;
}

function getMarketSession(): SessionInfo {
  const now = new Date();
  // Rough DST detection: DST is active Mar–Nov in the US
  const month = now.getMonth(); // 0-indexed
  const isDST = month > 2 && month < 10;
  const ctOffsetHours = isDST ? -5 : -6;
  const ctTime = new Date(
    now.getTime() + (now.getTimezoneOffset() + ctOffsetHours * 60) * 60000
  );
  const totalMinutes = ctTime.getHours() * 60 + ctTime.getMinutes();
  const day = ctTime.getDay(); // 0=Sun, 6=Sat

  if (day === 0 || day === 6) {
    return {
      label: "WEEKEND — CLOSED",
      color: "text-gray-500",
      badge: "bg-gray-800 text-gray-400 border-gray-700",
      isActive: false,
    };
  }
  if (totalMinutes < 8 * 60) {
    return {
      label: "PRE-MARKET PREP",
      color: "text-yellow-400",
      badge: "bg-yellow-950 text-yellow-400 border-yellow-800",
      isActive: false,
    };
  }
  if (totalMinutes < 9 * 60 + 35) {
    return {
      label: "PRE-RTH — AVOID",
      color: "text-orange-400",
      badge: "bg-orange-950 text-orange-400 border-orange-800",
      isActive: false,
    };
  }
  if (totalMinutes < 11 * 60 + 30) {
    return {
      label: "RTH MORNING — PRIMARY ★",
      color: "text-green-400",
      badge: "bg-green-950 text-green-400 border-green-800",
      isActive: true,
    };
  }
  if (totalMinutes < 13 * 60) {
    return {
      label: "MIDDAY LULL",
      color: "text-yellow-400",
      badge: "bg-yellow-950 text-yellow-400 border-yellow-800",
      isActive: false,
    };
  }
  if (totalMinutes < 15 * 60 + 30) {
    return {
      label: "RTH AFTERNOON — SECONDARY",
      color: "text-cyan-400",
      badge: "bg-cyan-950 text-cyan-400 border-cyan-800",
      isActive: true,
    };
  }
  if (totalMinutes < 17 * 60) {
    return {
      label: "AFTER-HOURS",
      color: "text-slate-400",
      badge: "bg-slate-800 text-slate-400 border-slate-700",
      isActive: false,
    };
  }
  return {
    label: "CLOSED",
    color: "text-gray-500",
    badge: "bg-gray-800 text-gray-400 border-gray-700",
    isActive: false,
  };
}

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

function fmtUptime(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  return `${h}h ${m}m ${s}s`;
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

function fetcher<T>(path: string): Promise<T> {
  return fetchEngine<T>(path);
}

// ── Page Component ────────────────────────────────────────────────────────

// Stable placeholder session used on the server and the first client paint so
// that both renders produce identical HTML (no React hydration error #418).
// getMarketSession() calls new Date() which differs between server (UTC) and
// client (local timezone + a few ms clock drift), causing a text-content mismatch.
const SESSION_PLACEHOLDER: SessionInfo = {
  label: "LOADING…",
  color: "text-slate-500",
  badge: "bg-slate-800 text-slate-400 border-slate-700",
  isActive: false,
};

export default function CommandCenterPage() {
  // Start null so SSR and the client's first paint match (no new Date() during
  // render); the real clock starts after mount. Prevents React hydration error #418.
  const [now, setNow] = useState<Date | null>(null);
  // session is also deferred to post-mount: getMarketSession() reads new Date()
  // which differs server (UTC) vs client (local tz) → hydration mismatch.
  const [session, setSession] = useState<SessionInfo>(SESSION_PLACEHOLDER);
  useEffect(() => {
    // Initialise both clock and session together so they are always in sync.
    const tick = () => {
      setNow(new Date());
      setSession(getMarketSession());
    };
    tick();
    const timer = setInterval(tick, 1000);
    return () => clearInterval(timer);
  }, []);

  const refreshInterval = session.isActive ? 30_000 : 5 * 60_000;

  // Live price chart symbol (defaults to the first tracked instrument)
  const [chartSym, setChartSym] = useState<string>(INSTRUMENTS[0]?.symbol ?? "MES");
  const { data: ccBars } = useSWR<OHLCVBar[]>(
    `cc-bars-${chartSym}`,
    () => fetchBars(chartSym, { timeframe: "15m", days: 14, futures: true }),
    { refreshInterval: 60_000, revalidateOnFocus: false }
  );

  const { addToast } = useToast();

  const {
    data: health,
    error: healthErr,
    mutate: mutateHealth,
  } = useSWR<HealthData>("/health", fetcher, { refreshInterval });

  const { data: safety } = useSWR<SafetyData>("/safety/status", fetcher, {
    refreshInterval,
  });

  const { data: portfolio } = useSWR<PortfolioData>("/portfolio", fetcher, {
    refreshInterval,
  });

  const { data: decisions } = useSWR<Decision[]>(
    "/decisions/recent?limit=5",
    fetcher,
    { refreshInterval }
  );

  const { data: scheduler } = useSWR<SchedulerData>(
    "/scheduler/status",
    fetcher,
    { refreshInterval }
  );

  const { data: macro } = useSWR<MacroData>("/macro/snapshot", fetcher, {
    refreshInterval: 120_000,
    shouldRetryOnError: false,
  });

  const { data: paperStatus } = useSWR<Record<string, PaperStatusRow>>(
    "/backtest/paper-status",
    fetcher,
    { refreshInterval: 120_000, shouldRetryOnError: false }
  );

  const { data: trades } = useSWR<Trade[]>(
    "/portfolio/history/trades",
    fetcher,
    { refreshInterval }
  );

  const { data: journalStats } = useSWR<JournalTradeStats>(
    "/journal/review/stats?limit=30",
    fetcher,
    { refreshInterval: 60_000, shouldRetryOnError: false }
  );

  // Honest deduped set for the journal HUD row (win_rate + EV/trade).
  // /journal/review/stats over-counts re-logged winners; fetchHonestTrades
  // applies dedup at read time. All other command-center cards are LEGIT.
  const { data: honestSet } = useSWR<HonestTradeSet>(
    "honest-trades-cc",
    fetchHonestTrades,
    { refreshInterval: 5 * 60_000, shouldRetryOnError: false }
  );

  const engineOnline = !healthErr && !!health;
  const killSwitchActive = health?.kill_switch_active ?? false;

  const liveWfeRows = useMemo(() => {
    if (!paperStatus) return WFE_ROWS;
    const keys: { k: string; symbol: string; tf: string; threshold: number }[] = [
      { k: "MES_1h", symbol: "MES", tf: "1h", threshold: 0.3 },
      { k: "MGC_1d", symbol: "MGC", tf: "1d", threshold: 0.3 },
      { k: "MCL_1h", symbol: "MCL", tf: "1h", threshold: 0.3 },
      { k: "MNQ_1h", symbol: "MNQ", tf: "1h", threshold: 0.3 },
    ];
    return keys.map(({ k, symbol, tf, threshold }) => {
      const row = paperStatus[k];
      const wfe = typeof row?.wfe === "number" ? row.wfe : 0;
      const active = (row?.status || "").toUpperCase() === "ACTIVE";
      const status = active ? ("PASS" as const) : ("OVERFIT" as const);
      return { symbol, tf, wfe, threshold, status };
    });
  }, [paperStatus]);

  const liveInstruments = useMemo(() => {
    if (!paperStatus) return INSTRUMENTS;
    return INSTRUMENTS.map((inst) => {
      const key = `${inst.symbol}_${inst.tf}`;
      const row = paperStatus[key];
      if (!row || typeof row.wfe !== "number") return inst;
      const active = (row.status || "").toUpperCase() === "ACTIVE";
      return {
        ...inst,
        wfe: row.wfe,
        status: active ? ("APPROVED" as const) : ("HALTED" as const),
      };
    });
  }, [paperStatus]);

  // Risk gauge calculations
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
  const ordersProgress = Math.min((ordersPerMin / 40) * 100, 100);

  const handleKillSwitch = useCallback(async () => {
    const activating = !killSwitchActive;
    if (
      !confirm(
        activating
          ? "Activate KILL SWITCH? This will halt all trading immediately."
          : "Deactivate the kill switch and allow trading to resume?"
      )
    )
      return;
    try {
      // Use the verified helper — it hits /safety/kill-switch/activate +
      // /deactivate (the bare /safety/kill-switch route is a 404).
      await toggleKillSwitch(
        activating ? "activate" : "deactivate",
        activating ? "Manual kill from command center" : undefined
      );
      addToast(
        activating
          ? "Kill switch ACTIVATED — all trading halted."
          : "Kill switch deactivated — trading re-armed.",
        activating ? "warning" : "success"
      );
      mutateHealth();
    } catch (err) {
      // A safety control that fails must fail LOUDLY — never swallow.
      addToast(
        `Kill switch ${
          activating ? "activation" : "deactivation"
        } FAILED — trading may NOT be halted. ${
          err instanceof Error ? err.message : "Unknown error"
        }`,
        "error"
      );
    }
  }, [killSwitchActive, addToast, mutateHealth]);

  return (
    <div
      className={`min-h-screen bg-gray-950 text-gray-100 p-4 font-sans ${fontDisplay.variable} ${fontMono.variable}`}
      style={{ fontFamily: "var(--font-cc-mono), ui-monospace, monospace" }}
    >
      {/* ═══════════════════════════════════════════════════════
          HEADER
      ═══════════════════════════════════════════════════════ */}
      <div className="flex items-center justify-between mb-5 border-b border-cyan-900/40 pb-4">
        <div>
          <h1
            className="text-2xl font-bold bg-gradient-to-r from-cyan-400 via-blue-300 to-cyan-300 bg-clip-text text-transparent tracking-widest uppercase"
            style={{ fontFamily: "var(--font-cc-display), sans-serif" }}
          >
            JARVIS TRADER — COMMAND CENTER
          </h1>
          <div className="flex items-center gap-3 mt-1">
            <span className="text-xs text-slate-500 font-mono tracking-wider">
              v2.7
            </span>
            <span className="text-slate-700">·</span>
            <span
              className={`text-xs font-mono tracking-wider ${session.color}`}
            >
              {session.label}
            </span>
            <span className="text-slate-700">·</span>
            <span className="text-xs text-slate-500 font-mono">
              AUTO-REFRESH {refreshInterval / 1000}s
            </span>
          </div>
        </div>

        <div className="flex items-center gap-3">
          {/* Live clock */}
          <div className="text-right">
            <div className="text-xl font-mono text-cyan-300 tabular-nums tracking-widest">
              {now ? now.toLocaleTimeString("en-US", { hour12: false }) : "--:--:--"}
            </div>
            <div className="text-xs text-slate-500 font-mono">
              {now
                ? now.toLocaleDateString("en-US", {
                    weekday: "short",
                    month: "short",
                    day: "numeric",
                    year: "numeric",
                  })
                : ""}
            </div>
          </div>

          {/* Paper mode */}
          {health?.paper_trading !== false && (
            <Badge className="bg-yellow-950 text-yellow-300 border border-yellow-700 font-mono text-xs tracking-wider">
              📄 PAPER MODE
            </Badge>
          )}

          {/* Engine status */}
          <Badge
            className={`font-mono text-xs tracking-wider ${
              engineOnline
                ? "bg-green-950 text-green-300 border border-green-700"
                : "bg-red-950 text-red-300 border border-red-800"
            }`}
          >
            {engineOnline ? (
              <Wifi className="w-3 h-3 mr-1" />
            ) : (
              <WifiOff className="w-3 h-3 mr-1" />
            )}
            {engineOnline ? "ENGINE ONLINE" : "ENGINE OFFLINE"}
          </Badge>

          {/* Kill Switch */}
          <Button
            onClick={handleKillSwitch}
            className={`font-mono text-xs font-bold tracking-widest border ${
              killSwitchActive
                ? "bg-red-700 hover:bg-red-600 border-red-400 text-white animate-pulse"
                : "bg-red-950 hover:bg-red-900 border-red-700 text-red-300 hover:text-red-200"
            }`}
          >
            <Power className="w-3.5 h-3.5 mr-1.5" />
            {killSwitchActive ? "⚠ KILL SWITCH ACTIVE" : "KILL SWITCH"}
          </Button>
        </div>
      </div>

      {/* ═══════════════════════════════════════════════════════
          TRADE APPROVALS — human-in-the-loop gate
      ═══════════════════════════════════════════════════════ */}
      <div className="mb-4">
        <Card className="border border-amber-500/30 bg-zinc-900/50">
          <CardHeader className="pb-1.5 pt-3 px-4">
            <CardTitle className="text-xs font-mono text-amber-400 tracking-widest flex items-center gap-1.5">
              <AlertTriangle className="w-3 h-3" />
              TRADE APPROVALS
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-3">
            <ApprovalPanel />
          </CardContent>
        </Card>
      </div>

      {/* ═══════════════════════════════════════════════════════
          PIPELINE REASONING — why each decision was made (expandable)
      ═══════════════════════════════════════════════════════ */}
      <div className="mb-4">
        <WidgetErrorBoundary name="Pipeline Reasoning">
          <LiveTradeReasoningWidget />
        </WidgetErrorBoundary>
      </div>

      {/* ═══════════════════════════════════════════════════════
          ROW 1 — STATUS OVERVIEW (5 columns)
      ═══════════════════════════════════════════════════════ */}
      <div className="grid grid-cols-5 gap-3 mb-4">
        {/* Portfolio */}
        <Card className="bg-slate-900/60 border border-cyan-900/50">
          <CardHeader className="pb-1.5 pt-3 px-4">
            <CardTitle className="text-xs font-mono text-cyan-400 tracking-widest flex items-center gap-1.5">
              <TrendingUp className="w-3 h-3" />
              PORTFOLIO
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-3 space-y-2">
            <div className="flex justify-between items-baseline">
              <span className="text-xs text-slate-500">Equity</span>
              <span className="font-mono text-sm text-white font-bold">
                {fmtUSD(portfolio?.total_equity)}
              </span>
            </div>
            <div className="flex justify-between items-baseline">
              <span className="text-xs text-slate-500">Daily P&amp;L</span>
              <span
                className={`font-mono text-sm font-bold ${pnlColor(portfolio?.daily_pnl)}`}
              >
                {fmtUSD(portfolio?.daily_pnl)}
                <span className="text-xs ml-1 opacity-70">
                  ({fmtPct(dailyPnlPct)})
                </span>
              </span>
            </div>
            <div className="flex justify-between items-baseline">
              <span className="text-xs text-slate-500">Open Positions</span>
              <span className="font-mono text-sm text-white">
                {portfolio?.positions?.length ?? "—"}
              </span>
            </div>
            <div className="flex justify-between items-baseline">
              <span className="text-xs text-slate-500">Cash</span>
              <span className="font-mono text-xs text-slate-400">
                {fmtUSD(portfolio?.cash)}
              </span>
            </div>
          </CardContent>
        </Card>

        {/* Active Instruments */}
        <Card className="bg-slate-900/60 border border-cyan-900/50">
          <CardHeader className="pb-1.5 pt-3 px-4">
            <CardTitle className="text-xs font-mono text-cyan-400 tracking-widest flex items-center gap-1.5">
              <Activity className="w-3 h-3" />
              ACTIVE INSTRUMENTS
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-3 space-y-2.5">
            {liveInstruments.map((inst) => (
              <div
                key={inst.symbol}
                className="flex items-center justify-between"
              >
                <div className="flex items-center gap-1.5">
                  {inst.status === "APPROVED" ? (
                    <CheckCircle className="w-3.5 h-3.5 text-green-400 flex-shrink-0" />
                  ) : (
                    <XCircle className="w-3.5 h-3.5 text-red-400 flex-shrink-0" />
                  )}
                  <span className="font-mono text-xs text-white font-bold">
                    {inst.symbol}
                  </span>
                  <span className="font-mono text-xs text-slate-600">
                    {inst.tf}
                  </span>
                </div>
                <Badge
                  className={`text-xs font-mono py-0 px-1.5 ${
                    inst.status === "APPROVED"
                      ? "bg-green-950 text-green-400 border border-green-800"
                      : "bg-red-950 text-red-400 border border-red-800"
                  }`}
                >
                  {inst.status === "APPROVED" ? `WFE=${inst.wfe}` : "HALTED"}
                </Badge>
              </div>
            ))}
          </CardContent>
        </Card>

        {/* Live Price Chart */}
        <Card className="bg-slate-900/60 border border-cyan-900/50 xl:col-span-2">
          <CardHeader className="pb-1.5 pt-3 px-4">
            <CardTitle className="text-xs font-mono text-cyan-400 tracking-widest flex items-center justify-between gap-1.5">
              <span className="flex items-center gap-1.5">
                <TrendingUp className="w-3 h-3" />
                PRICE ACTION · {chartSym} · 15m
              </span>
              <span className="flex gap-1">
                {INSTRUMENTS.map((inst) => (
                  <button
                    key={inst.symbol}
                    onClick={() => setChartSym(inst.symbol)}
                    className={`px-1.5 py-0.5 rounded font-mono text-[10px] border transition-colors ${
                      chartSym === inst.symbol
                        ? "bg-cyan-950 text-cyan-300 border-cyan-700"
                        : "bg-slate-900 text-slate-500 border-slate-700 hover:text-slate-300"
                    }`}
                  >
                    {inst.symbol}
                  </button>
                ))}
              </span>
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-3">
            {ccBars && ccBars.length ? (
              <CandlestickChart bars={ccBars} height={360} />
            ) : (
              <p className="text-xs text-slate-500 font-mono py-8 text-center">
                No bar data available for {chartSym}.
              </p>
            )}
          </CardContent>
        </Card>

        {/* Safety Layer */}
        <Card
          className={`bg-slate-900/60 border ${
            killSwitchActive ? "border-red-700" : "border-cyan-900/50"
          }`}
        >
          <CardHeader className="pb-1.5 pt-3 px-4">
            <CardTitle className="text-xs font-mono text-cyan-400 tracking-widest flex items-center gap-1.5">
              <Shield className="w-3 h-3" />
              SAFETY LAYER
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-3 space-y-2">
            <div className="flex justify-between items-center">
              <span className="text-xs text-slate-500">Kill Switch</span>
              <Badge
                className={`text-xs font-mono py-0 px-1.5 ${
                  killSwitchActive
                    ? "bg-red-900 text-red-200 border border-red-600 animate-pulse"
                    : "bg-green-950 text-green-400 border border-green-800"
                }`}
              >
                {killSwitchActive ? "⚠ ACTIVE" : "ARMED"}
              </Badge>
            </div>
            <div className="flex justify-between items-baseline">
              <span className="text-xs text-slate-500">Daily Loss</span>
              <span
                className={`font-mono text-xs ${dailyPnlPct < -1 ? "text-red-400" : "text-green-400"}`}
              >
                {fmtPct(dailyPnlPct)} / -2%
              </span>
            </div>
            <div className="flex justify-between items-baseline">
              <span className="text-xs text-slate-500">Drawdown</span>
              <span
                className={`font-mono text-xs ${drawdownPct < -5 ? "text-red-400" : "text-yellow-400"}`}
              >
                {fmtPct(drawdownPct)} / -10%
              </span>
            </div>
            <div className="flex justify-between items-baseline">
              <span className="text-xs text-slate-500">Consec. Losses</span>
              <span
                className={`font-mono text-xs ${consecutiveLosses >= 4 ? "text-red-400" : "text-gray-300"}`}
              >
                {consecutiveLosses} / 7
              </span>
            </div>
          </CardContent>
        </Card>

        {/* Market Session */}
        <Card className="bg-slate-900/60 border border-cyan-900/50">
          <CardHeader className="pb-1.5 pt-3 px-4">
            <CardTitle className="text-xs font-mono text-cyan-400 tracking-widest flex items-center gap-1.5">
              <Clock className="w-3 h-3" />
              MARKET SESSION
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-3 space-y-2">
            <Badge
              className={`w-full justify-center text-xs font-mono py-1 border ${session.badge}`}
            >
              {session.label}
            </Badge>
            <div className="flex justify-between items-baseline">
              <span className="text-xs text-slate-500">VIX</span>
              <span className="font-mono text-sm text-white font-bold">
                {macro?.vix != null ? macro.vix.toFixed(2) : "—"}
              </span>
            </div>
            <div className="flex justify-between items-baseline">
              <span className="text-xs text-slate-500">Regime</span>
              <span
                className={`font-mono text-xs ${
                  macro?.vix_regime === "EXTREME_FEAR"
                    ? "text-red-400"
                    : macro?.vix_regime === "HIGH" ||
                        macro?.vix_regime === "FEAR"
                      ? "text-orange-400"
                      : macro?.vix_regime === "ELEVATED"
                        ? "text-yellow-400"
                        : "text-green-400"
                }`}
              >
                {macro?.vix_regime ?? "—"}
              </span>
            </div>
            <div className="flex justify-between items-baseline">
              <span className="text-xs text-slate-500">Session Active</span>
              <Badge
                className={`text-xs font-mono py-0 ${
                  session.isActive
                    ? "bg-green-950 text-green-400 border border-green-800"
                    : "bg-slate-800 text-slate-500 border border-slate-700"
                }`}
              >
                {session.isActive ? "TRADING" : "STANDBY"}
              </Badge>
            </div>
          </CardContent>
        </Card>

        {/* Portfolio Correlation */}
        <WidgetErrorBoundary name="Portfolio Correlation">
          <PortfolioCorrelationWidget />
        </WidgetErrorBoundary>
      </div>

      {/* ═══════════════════════════════════════════════════════
          ROW 2 — SIGNAL CARDS (3 columns)
      ═══════════════════════════════════════════════════════ */}
      <div className="grid grid-cols-3 gap-3 mb-4">
        {liveInstruments.map((inst) => (
          <Card
            key={inst.symbol}
            className={`bg-slate-900/60 border ${
              inst.status === "HALTED"
                ? "border-red-900/60"
                : "border-cyan-900/50"
            }`}
          >
            <CardHeader className="pb-2 pt-3 px-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <CardTitle className="font-mono text-base text-white font-bold tracking-wider">
                    {inst.symbol}
                  </CardTitle>
                  <span className="font-mono text-xs text-slate-500 bg-slate-800 px-1.5 py-0.5 rounded">
                    {inst.tf}
                  </span>
                </div>
                <Badge
                  className={`text-xs font-mono py-0 px-2 border ${
                    inst.status === "APPROVED"
                      ? "bg-green-950 text-green-400 border-green-800"
                      : "bg-red-950 text-red-400 border-red-800"
                  }`}
                >
                  {inst.status}
                </Badge>
              </div>
            </CardHeader>
            <CardContent className="px-4 pb-3">
              {inst.status === "HALTED" ? (
                <div className="flex flex-col items-center justify-center py-5 gap-2">
                  <XCircle className="w-9 h-9 text-red-500/70" />
                  <span className="font-mono text-sm text-red-400 font-bold tracking-wider">
                    TRADING HALTED
                  </span>
                  <span className="font-mono text-xs text-slate-500 text-center">
                    WFE={inst.wfe} — OVERFIT DETECTED
                    <br />
                    Regime-adaptive boost insufficient
                  </span>
                </div>
              ) : (
                <div className="grid grid-cols-2 gap-x-4 gap-y-3">
                  <div>
                    <div className="text-xs text-slate-500 mb-0.5">
                      WFE Score
                    </div>
                    <div className="font-mono text-lg text-cyan-400 font-bold leading-none">
                      {inst.wfe}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs text-slate-500 mb-0.5">Regime</div>
                    <div
                      className={`font-mono text-sm font-bold ${
                        inst.regime === "BULL"
                          ? "text-green-400"
                          : inst.regime === "BEAR"
                            ? "text-red-400"
                            : "text-yellow-400"
                      }`}
                    >
                      {inst.regime}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs text-slate-500 mb-0.5">
                      Last Signal
                    </div>
                    <div
                      className={`font-mono text-sm font-bold ${
                        inst.lastSignal === "LONG"
                          ? "text-green-400"
                          : inst.lastSignal === "SHORT"
                            ? "text-red-400"
                            : "text-slate-400"
                      }`}
                    >
                      {inst.lastSignal}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs text-slate-500 mb-0.5">
                      ATR Approx
                    </div>
                    <div className="font-mono text-sm text-white">
                      {inst.atr}
                    </div>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        ))}
      </div>

      {/* ═══════════════════════════════════════════════════════
          ROW 3 — RISK GAUGES + RECENT SIGNALS (2 columns)
      ═══════════════════════════════════════════════════════ */}
      <div className="grid grid-cols-2 gap-3 mb-4">
        {/* Risk Gauges */}
        <Card className="bg-slate-900/60 border border-cyan-900/50">
          <CardHeader className="pb-2 pt-3 px-4">
            <CardTitle className="text-xs font-mono text-cyan-400 tracking-widest flex items-center gap-1.5">
              <AlertTriangle className="w-3 h-3" />
              RISK GAUGES
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-4 space-y-4">
            {/* Daily P&L */}
            <div>
              <div className="flex justify-between text-xs font-mono mb-1.5">
                <span className="text-slate-400">Daily P&amp;L vs Limit</span>
                <span
                  className={dailyPnlPct < -1 ? "text-red-400" : "text-green-400"}
                >
                  {fmtPct(dailyPnlPct)} / -2.00%
                </span>
              </div>
              <Progress
                value={dailyLossProgress}
                className="h-2.5 bg-slate-800"
              />
              <div className="text-right text-xs text-slate-600 font-mono mt-0.5">
                {dailyLossProgress.toFixed(0)}% consumed
              </div>
            </div>

            {/* Drawdown */}
            <div>
              <div className="flex justify-between text-xs font-mono mb-1.5">
                <span className="text-slate-400">Peak Drawdown</span>
                <span
                  className={drawdownPct < -5 ? "text-red-400" : "text-yellow-400"}
                >
                  {fmtPct(drawdownPct)} / -10.00%
                </span>
              </div>
              <Progress value={drawdownProgress} className="h-2.5 bg-slate-800" />
              <div className="text-right text-xs text-slate-600 font-mono mt-0.5">
                {drawdownProgress.toFixed(0)}% consumed
              </div>
            </div>

            {/* Consecutive Losses */}
            <div>
              <div className="flex justify-between text-xs font-mono mb-1.5">
                <span className="text-slate-400">Consecutive Losses</span>
                <span
                  className={consecutiveLosses >= 4 ? "text-red-400" : "text-gray-300"}
                >
                  {consecutiveLosses} / 7
                </span>
              </div>
              <Progress
                value={consecutiveLossProgress}
                className="h-2.5 bg-slate-800"
              />
              <div className="text-right text-xs text-slate-600 font-mono mt-0.5">
                {consecutiveLossProgress.toFixed(0)}% of circuit breaker
              </div>
            </div>

            {/* Orders/min */}
            <div>
              <div className="flex justify-between text-xs font-mono mb-1.5">
                <span className="text-slate-400">Orders / Minute</span>
                <span className="text-slate-300">
                  {ordersPerMin} / 40 limit
                </span>
              </div>
              <Progress value={ordersProgress} className="h-2.5 bg-slate-800" />
              <div className="text-right text-xs text-slate-600 font-mono mt-0.5">
                {ordersProgress.toFixed(0)}% of rate limit
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Recent Signals + Pipeline Status */}
        <Card className="bg-slate-900/60 border border-cyan-900/50">
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
                      <span className="font-mono text-xs text-slate-500 flex-shrink-0">
                        {fmtTime(d.timestamp)}
                      </span>
                      <span className="font-mono text-xs text-white font-bold flex-shrink-0">
                        {d.symbol}
                      </span>
                      <Badge
                        className={`text-xs font-mono py-0 px-1.5 flex-shrink-0 border ${
                          d.action === "LONG" || d.action === "BUY"
                            ? "bg-green-950 text-green-400 border-green-800"
                            : d.action === "SHORT" || d.action === "SELL"
                              ? "bg-red-950 text-red-400 border-red-800"
                              : "bg-slate-800 text-slate-400 border-slate-700"
                        }`}
                      >
                        {d.action}
                      </Badge>
                    </div>
                    <span className="font-mono text-xs text-slate-500 truncate max-w-[140px] ml-2">
                      {d.reason ?? d.regime ?? "—"}
                    </span>
                  </div>
                ))}
              </div>
            )}

            {/* Pipeline status */}
            <div className="mt-3 pt-3 border-t border-slate-800/50 space-y-1.5">
              <div className="flex items-center justify-between">
                <span className="text-xs text-slate-500 font-mono">
                  Pipeline Scheduler
                </span>
                <Badge
                  className={`text-xs font-mono py-0 border ${
                    scheduler?.running
                      ? "bg-green-950 text-green-400 border-green-800"
                      : "bg-slate-800 text-slate-500 border-slate-700"
                  }`}
                >
                  {scheduler?.running ? "● RUNNING" : "○ IDLE"}
                </Badge>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-slate-500 font-mono">
                  Total Decisions Logged
                </span>
                <span className="font-mono text-xs text-cyan-400 font-bold">
                  {scheduler?.total_decisions_logged ?? "—"}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-slate-500 font-mono">
                  Last Scan
                </span>
                <span className="font-mono text-xs text-white">
                  {fmtTime(scheduler?.last_scan)}
                </span>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* ═══════════════════════════════════════════════════════
          ROW 4 — TRADES TABLE + WFE MONITOR (2 columns)
      ═══════════════════════════════════════════════════════ */}
      <div className="grid grid-cols-2 gap-3 mb-4">
        {/* Recent Trades */}
        <Card className="bg-slate-900/60 border border-cyan-900/50">
          <CardHeader className="pb-2 pt-3 px-4">
            <CardTitle className="text-xs font-mono text-cyan-400 tracking-widest flex items-center gap-1.5">
              <ChevronRight className="w-3 h-3" />
              RECENT TRADES (last 10)
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-3">
            {!trades || trades.length === 0 ? (
              <div className="text-xs text-slate-500 font-mono py-6 text-center">
                No trade history from /portfolio/history/trades
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-xs font-mono">
                  <thead>
                    <tr className="text-slate-500 border-b border-slate-700/60">
                      <th className="text-left pb-1.5 font-normal">Time</th>
                      <th className="text-left pb-1.5 font-normal">Sym</th>
                      <th className="text-left pb-1.5 font-normal">Side</th>
                      <th className="text-right pb-1.5 font-normal">Qty</th>
                      <th className="text-right pb-1.5 font-normal">Price</th>
                      <th className="text-right pb-1.5 font-normal">P&amp;L</th>
                    </tr>
                  </thead>
                  <tbody>
                    {trades.slice(0, 10).map((t, i) => (
                      <tr
                        key={i}
                        className="border-b border-slate-800/30 hover:bg-slate-800/20"
                      >
                        <td className="py-1 text-slate-500">
                          {fmtTime(t.timestamp)}
                        </td>
                        <td className="py-1 text-white font-bold">{t.symbol}</td>
                        <td className="py-1">
                          <span
                            className={
                              t.action === "BUY" || t.action === "LONG"
                                ? "text-green-400"
                                : "text-red-400"
                            }
                          >
                            {t.action}
                          </span>
                        </td>
                        <td className="py-1 text-right text-slate-300">
                          {t.quantity}
                        </td>
                        <td className="py-1 text-right text-white">
                          {t.price?.toFixed(2) ?? "—"}
                        </td>
                        <td className={`py-1 text-right ${pnlColor(t.pnl)}`}>
                          {t.pnl != null ? fmtUSD(t.pnl) : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Walk-Forward Monitor */}
        <Card className="bg-slate-900/60 border border-cyan-900/50">
          <CardHeader className="pb-2 pt-3 px-4">
            <CardTitle className="text-xs font-mono text-cyan-400 tracking-widest flex items-center gap-1.5">
              <RefreshCw className="w-3 h-3" />
              WALK-FORWARD EFFICIENCY MONITOR
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-3 space-y-4">
            {liveWfeRows.map((row) => (
              <div key={row.symbol}>
                <div className="flex justify-between items-center mb-1.5">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-sm text-white font-bold">
                      {row.symbol}
                    </span>
                    <span className="font-mono text-xs text-slate-500 bg-slate-800 px-1 rounded">
                      {row.tf}
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-base text-cyan-400 font-bold tabular-nums">
                      {row.wfe.toFixed(2)}
                    </span>
                    <Badge
                      className={`text-xs font-mono py-0 px-1.5 border ${
                        row.status === "PASS"
                          ? "bg-green-950 text-green-400 border-green-800"
                          : row.status === "OVERFIT"
                            ? "bg-orange-950 text-orange-400 border-orange-800"
                            : "bg-red-950 text-red-400 border-red-800"
                      }`}
                    >
                      {row.status}
                    </Badge>
                  </div>
                </div>
                <Progress
                  value={Math.min(row.wfe * 100, 100)}
                  className="h-2 bg-slate-800"
                />
                <div className="flex justify-between text-xs text-slate-600 font-mono mt-0.5">
                  <span>threshold: ≥{row.threshold}</span>
                  <span>{(row.wfe * 100).toFixed(0)}%</span>
                </div>
              </div>
            ))}

            <div className="pt-2 border-t border-slate-800/50 space-y-1.5">
              <div className="flex justify-between text-xs font-mono">
                <span className="text-slate-500">Next WFE Recalc</span>
                <span className="text-cyan-400">Sunday 06:00 CT</span>
              </div>
              <div className="flex justify-between text-xs font-mono">
                <span className="text-slate-500">Window</span>
                <span className="text-slate-300">180d IS / 60d OOS</span>
              </div>
              <div className="flex justify-between text-xs font-mono">
                <span className="text-slate-500">Method</span>
                <span className="text-slate-300">Regime-Adaptive STC</span>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* ═══════════════════════════════════════════════════════
          ROW 5 — OPTIONS + SCHEDULER + ENGINE HEALTH (3 columns)
      ═══════════════════════════════════════════════════════ */}
      <div className="grid grid-cols-3 gap-3">
        {/* Options Engine */}
        <Card className="bg-slate-900/60 border border-cyan-900/50">
          <CardHeader className="pb-2 pt-3 px-4">
            <CardTitle className="text-xs font-mono text-cyan-400 tracking-widest flex items-center gap-1.5">
              <Activity className="w-3 h-3" />
              OPTIONS ENGINE
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-3 space-y-2">
            <div className="flex justify-between items-center">
              <span className="text-xs text-slate-500">Status</span>
              <Badge className="text-xs font-mono py-0 bg-slate-800 text-slate-400 border border-slate-700">
                NOT ACTIVE
              </Badge>
            </div>
            <div className="flex justify-between items-baseline">
              <span className="text-xs text-slate-500">IV Proxy (VIX)</span>
              <span className="font-mono text-xs text-white">
                {macro?.vix != null ? macro.vix.toFixed(2) : "—"}
              </span>
            </div>
            <div className="flex justify-between items-baseline">
              <span className="text-xs text-slate-500">VIX Regime</span>
              <span
                className={`font-mono text-xs ${
                  macro?.vix_regime === "EXTREME_FEAR"
                    ? "text-red-400"
                    : macro?.vix_regime === "HIGH" ||
                        macro?.vix_regime === "FEAR"
                      ? "text-orange-400"
                      : macro?.vix_regime === "ELEVATED"
                        ? "text-yellow-400"
                        : "text-slate-400"
                }`}
              >
                {macro?.vix_regime ?? "—"}
              </span>
            </div>
            <div className="flex justify-between items-baseline">
              <span className="text-xs text-slate-500">Open Positions</span>
              <span className="font-mono text-xs text-slate-400">0</span>
            </div>
            <div className="mt-2 p-2 rounded bg-slate-800/50 border border-slate-700/40">
              <p className="text-xs text-slate-500 font-mono leading-relaxed">
                Engine built — awaiting activation.
                <br />
                IV surface + greek calcs ready.
              </p>
            </div>
          </CardContent>
        </Card>

        {/* Scheduler Status */}
        <Card className="bg-slate-900/60 border border-cyan-900/50">
          <CardHeader className="pb-2 pt-3 px-4">
            <CardTitle className="text-xs font-mono text-cyan-400 tracking-widest flex items-center gap-1.5">
              <Clock className="w-3 h-3" />
              SCHEDULER STATUS
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-3 space-y-2">
            <div className="flex justify-between items-center">
              <span className="text-xs text-slate-500">Scheduler</span>
              <Badge
                className={`text-xs font-mono py-0 border ${
                  scheduler?.running
                    ? "bg-green-950 text-green-400 border-green-800"
                    : "bg-slate-800 text-slate-500 border-slate-700"
                }`}
              >
                {scheduler?.running ? "● RUNNING" : "○ IDLE"}
              </Badge>
            </div>
            <div className="flex justify-between items-baseline">
              <span className="text-xs text-slate-500">Last Scan</span>
              <span className="font-mono text-xs text-white">
                {fmtTime(scheduler?.last_scan)}
              </span>
            </div>
            <div className="flex justify-between items-baseline">
              <span className="text-xs text-slate-500">Next Scan</span>
              <span className="font-mono text-xs text-cyan-400">
                {fmtTime(scheduler?.next_scan)}
              </span>
            </div>
            <div className="flex justify-between items-baseline">
              <span className="text-xs text-slate-500">Total Decisions</span>
              <span className="font-mono text-base text-cyan-400 font-bold tabular-nums">
                {scheduler?.total_decisions_logged ?? "—"}
              </span>
            </div>
            {scheduler?.jobs && scheduler.jobs.length > 0 && (
              <div className="mt-1 pt-2 border-t border-slate-800/50 space-y-1">
                {scheduler.jobs.slice(0, 4).map((job, i) => (
                  <div
                    key={i}
                    className="flex justify-between items-center text-xs font-mono"
                  >
                    <span className="text-slate-500 truncate max-w-[160px]">
                      {job.name}
                    </span>
                    <Badge
                      className={`text-xs py-0 px-1 border ${
                        job.running
                          ? "bg-green-950 text-green-400 border-green-800"
                          : "bg-slate-800 text-slate-500 border-slate-700"
                      }`}
                    >
                      {job.running ? "RUN" : "—"}
                    </Badge>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Engine Health */}
        <Card className="bg-slate-900/60 border border-cyan-900/50">
          <CardHeader className="pb-2 pt-3 px-4">
            <CardTitle className="text-xs font-mono text-cyan-400 tracking-widest flex items-center gap-1.5">
              <Database className="w-3 h-3" />
              ENGINE HEALTH
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-3 space-y-2">
            <div className="flex justify-between items-center">
              <span className="text-xs text-slate-500">Status</span>
              <Badge
                className={`text-xs font-mono py-0 border ${
                  engineOnline
                    ? "bg-green-950 text-green-400 border-green-800"
                    : "bg-red-950 text-red-400 border-red-800"
                }`}
              >
                {engineOnline ? "● ONLINE" : "● OFFLINE"}
              </Badge>
            </div>
            <div className="flex justify-between items-baseline">
              <span className="text-xs text-slate-500">Uptime</span>
              <span className="font-mono text-xs text-white">
                {health?.uptime_seconds != null
                  ? fmtUptime(health.uptime_seconds)
                  : "—"}
              </span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-xs text-slate-500">IBKR Gateway</span>
              <Badge
                className={`text-xs font-mono py-0 border ${
                  (health?.ibkr_execution_connected ?? health?.ibkr_connected)
                    ? "bg-green-950 text-green-400 border-green-800"
                    : "bg-red-950 text-red-400 border-red-800"
                }`}
                title="Reports execution-connector state when /health exposes ibkr_execution_connected; falls back to legacy ibkr_connected (OR of execution + data) on older engines."
              >
                {(health?.ibkr_execution_connected ?? health?.ibkr_connected) ? "CONNECTED" : "DISCONNECTED"}
              </Badge>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-xs text-slate-500">Database</span>
              <Badge
                className={`text-xs font-mono py-0 border ${
                  engineOnline
                    ? "bg-green-950 text-green-400 border-green-800"
                    : "bg-slate-800 text-slate-500 border-slate-700"
                }`}
              >
                {engineOnline ? "OK" : "—"}
              </Badge>
            </div>
            <div className="flex justify-between items-baseline">
              <span className="text-xs text-slate-500">Version</span>
              <span className="font-mono text-xs text-slate-400">
                {health?.version ?? "v2.7"}
              </span>
            </div>
            <Button
              onClick={() => mutateHealth()}
              variant="ghost"
              size="sm"
              className="w-full text-xs"
            >
              Refresh
            </Button>
          </CardContent>
        </Card>
      </div>

      {/* ═══════════════════════════════════════════════════════
          ROW 6 — JOURNAL REVIEW STATS
          Win Rate + EV/Trade: migrated to honest deduped source.
          Trades count + Diagnosis: kept from journalStats (LEGIT — not P&L aggregates).
      ═══════════════════════════════════════════════════════ */}
      <div className="mt-3 mb-3">
        <a href="/journal-review" className="block">
          <Card className="bg-slate-900/60 border border-cyan-900/50 hover:border-cyan-600/60 transition-colors cursor-pointer">
            <CardHeader className="pb-1.5 pt-3 px-4">
              <CardTitle className="text-xs font-mono text-cyan-400 tracking-widest flex items-center gap-1.5">
                <BookOpen className="w-3 h-3" />
                JOURNAL REVIEW
              </CardTitle>
            </CardHeader>
            <CardContent className="px-4 pb-3">
              {!journalStats ? (
                <span className="text-xs text-slate-500 font-mono">Loading…</span>
              ) : (
                <>
                  <div className="grid grid-cols-4 gap-4">
                    <div>
                      {/* Trades count from journalStats — LEGIT (not a P&L aggregate) */}
                      <div className="text-xs text-slate-500 mb-0.5">Trades</div>
                      <div className="font-mono text-sm text-white font-bold">
                        {journalStats.total_trades}
                      </div>
                    </div>
                    <div>
                      {/* Win Rate — migrated to honest deduped source */}
                      <div className="text-xs text-slate-500 mb-0.5">Win Rate</div>
                      {honestSet ? (
                        <div
                          className={`font-mono text-sm font-bold ${
                            honestSet.winRate >= 0.5
                              ? "text-green-400"
                              : honestSet.winRate >= 0.35
                              ? "text-yellow-400"
                              : "text-red-400"
                          }`}
                        >
                          {(honestSet.winRate * 100).toFixed(0)}%
                        </div>
                      ) : (
                        <div className="font-mono text-sm text-slate-500">—</div>
                      )}
                    </div>
                    <div>
                      {/* EV / Trade — migrated to honest deduped source (net / trade count) */}
                      <div className="text-xs text-slate-500 mb-0.5">EV / Trade</div>
                      {honestSet && honestSet.trades.length > 0 ? (
                        <div
                          className={`font-mono text-sm font-bold ${
                            honestSet.net / honestSet.trades.length >= 0
                              ? "text-green-400"
                              : "text-red-400"
                          }`}
                        >
                          {honestSet.net / honestSet.trades.length >= 0 ? "+" : ""}
                          {(honestSet.net / honestSet.trades.length).toFixed(0)}
                        </div>
                      ) : (
                        <div className="font-mono text-sm text-slate-500">—</div>
                      )}
                    </div>
                    <div>
                      {/* Diagnosis from journalStats — LEGIT (categorical field, not a P&L aggregate) */}
                      <div className="text-xs text-slate-500 mb-0.5">Diagnosis</div>
                      <Badge
                        className={`text-xs font-mono py-0 border ${
                          journalStats.diagnosis === "solid"
                            ? "bg-green-950 text-green-400 border-green-800"
                            : journalStats.diagnosis === "insufficient_data"
                            ? "bg-slate-800 text-slate-400 border-slate-700"
                            : "bg-red-950 text-red-400 border-red-800"
                        }`}
                      >
                        {journalStats.diagnosis.replace("_", " ").toUpperCase()}
                      </Badge>
                    </div>
                  </div>
                  {honestSet && (
                    <p className="mt-2 text-[10px] text-slate-600 font-mono">
                      {dedupCaveat(honestSet)} · win rate + EV sourced from deduped record
                    </p>
                  )}
                </>
              )}
            </CardContent>
          </Card>
        </a>
      </div>

      {/* ═══════════════════════════════════════════════════════
          ROW 7 — SIGNAL FEED (full width)
      ═══════════════════════════════════════════════════════ */}
      <div className="mt-3">
        <WidgetErrorBoundary name="Signal Feed">
          <SignalFeedWidget />
        </WidgetErrorBoundary>
      </div>
    </div>
  );
}
