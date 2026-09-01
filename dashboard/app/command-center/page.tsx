"use client";

import dynamic from "next/dynamic";
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
  type LucideIcon,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import {
  fetchCommandCenterBars,
  fetchCommandCenterDataIntegrity,
  fetchCommandCenterDecisions,
  fetchCommandCenterHealth,
  fetchCommandCenterJournalStats,
  fetchCommandCenterMacro,
  fetchCommandCenterPaperStatus,
  fetchCommandCenterPortfolio,
  fetchCommandCenterRegime,
  fetchCommandCenterSafety,
  fetchCommandCenterScheduler,
  fetchCommandCenterStrategyLedger,
  fetchCommandCenterTrades,
  setCommandCenterKillSwitch,
  type CommandCenterDataIntegrityResponse,
  type CommandCenterDecision,
  type CommandCenterHealthData,
  type CommandCenterMacroData,
  type CommandCenterPaperStatusRow,
  type CommandCenterPortfolioData,
  type CommandCenterSafetyData,
  type CommandCenterSchedulerData,
  type CommandCenterTrade,
  type JournalTradeStats,
  type LedgerResponse,
  type OHLCVBar,
} from "@/lib/commandCenterApi";
import { executionStatus, type ExecutionPathProbe } from "@/lib/executionPath";
import {
  fetchHonestTrades,
  type HonestTradeSet,
  dedupCaveat,
} from "@/lib/honestTrades";
import { INSTRUMENTS, WFE_ROWS } from "./constants";
import { SignalFeedWidget } from "@/components/SignalFeedWidget";
import LiveTradeReasoningWidget from "@/components/LiveTradeReasoningWidget";
import { DecisionLogWidget } from "@/components/DecisionLogWidget";
import ApprovalPanel from "@/components/ApprovalPanel";
import { PortfolioCorrelationWidget } from "@/components/PortfolioCorrelationWidget";
import { SessionBriefPanel } from "@/components/SessionBriefPanel";
import { ActionableBoardWidget } from "@/components/ActionableBoardWidget";
import PipelineFunnelCard from "@/components/command-center/PipelineFunnelCard";
import { WidgetErrorBoundary } from "@/components/WidgetErrorBoundary";
import { useToast } from "@/lib/toast-context";
import { useWebSocket, type WsEvent } from "@/hooks/useWebSocket";

// Candlestick chart (lightweight-charts) — only renders once bar data resolves, so
// load it on demand to keep lightweight-charts off the command-center landing critical path.
const CandlestickChart = dynamic(
  () =>
    import("@/components/command-center/charts/CandlestickChart").then((m) => ({
      default: m.CandlestickChart,
    })),
  { ssr: false, loading: () => <div className="h-[360px] animate-pulse rounded bg-slate-950/40" /> }
);

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

function shouldRevalidateCommandCenter(event: WsEvent): boolean {
  return (
    event.type === "order_fill" ||
    event.type === "pending_approval_created" ||
    event.type === "kill_switch" ||
    event.type === "safety_event" ||
    event.type === "circuit_breaker" ||
    event.type === "pipeline_complete"
  );
}

// ── Live per-instrument regime (PRB-34) ─────────────────────────────────────
// Ports /jarvis's RegimePulsePanel pattern: GET /analytics/regime/{symbol},
// same live source, same 60s poll cadence. Replaces the Signal Cards' hardcoded
// `regime` constant. lastSignal/atr have no equivalent live source from this
// endpoint (it returns only symbol/regime/current_regime/note/error) and stay
// static -- see constants.ts.
function useSymbolRegime(symbol: string) {
  const { data, error, isLoading } = useSWR(
    `/analytics/regime/${symbol}`,
    () => fetchCommandCenterRegime(symbol),
    { refreshInterval: 60_000, shouldRetryOnError: false }
  );
  return {
    regime: data?.current_regime ?? data?.regime ?? null,
    isLoading,
    error,
  };
}

function regimeColorClass(regime: string | null): string {
  if (!regime) return "text-slate-500";
  const r = regime.toUpperCase();
  if (r.includes("TREND") || r.includes("BULL")) return "text-green-400";
  if (r.includes("BEAR") || r.includes("CRASH")) return "text-red-400";
  if (r.includes("RANG") || r.includes("CHOP") || r === "UNKNOWN") return "text-yellow-400";
  return "text-cyan-400";
}

type ShellTone = "live" | "warn" | "offline" | "static";
type StatusTone = "ok" | "warn" | "bad" | "unknown";

interface ShellRegion {
  label: string;
  href: string;
  status: string;
  metric: string;
  detail: string;
  tone: ShellTone;
  Icon: LucideIcon;
}

function shellToneClass(tone: ShellTone): string {
  if (tone === "live") return "border-emerald-800/50 bg-emerald-950/10 text-emerald-300";
  if (tone === "warn") return "border-amber-800/50 bg-amber-950/10 text-amber-300";
  if (tone === "offline") return "border-red-800/50 bg-red-950/10 text-red-300";
  return "border-slate-800 bg-slate-900/60 text-slate-300";
}

function compactCount(value: number | undefined | null): string {
  return typeof value === "number" && Number.isFinite(value) ? String(value) : "—";
}

function statusToneClass(tone: StatusTone): string {
  if (tone === "ok") return "border-emerald-800 bg-emerald-950/25 text-emerald-300";
  if (tone === "warn") return "border-amber-800 bg-amber-950/25 text-amber-300";
  if (tone === "bad") return "border-red-800 bg-red-950/25 text-red-300";
  return "border-slate-800 bg-slate-900/70 text-slate-400";
}

function CommandCenterStatusStrip({
  engine,
  broker,
  safety,
  data,
}: {
  engine: { label: string; detail: string; tone: StatusTone };
  broker: { label: string; detail: string; tone: StatusTone };
  safety: { label: string; detail: string; tone: StatusTone };
  data: { label: string; detail: string; tone: StatusTone };
}) {
  const rows = [
    { title: "ENGINE", ...engine },
    { title: "BROKER", ...broker },
    { title: "SAFETY", ...safety },
    { title: "DATA", ...data },
  ];
  return (
    <section
      data-testid="command-center-status-strip"
      className="mb-4 grid grid-cols-1 gap-2 rounded-md border border-slate-800 bg-slate-950/60 p-2 md:grid-cols-2 xl:grid-cols-4"
      aria-label="Command Center independent status strip"
    >
      {rows.map((row) => (
        <div
          key={row.title}
          className={`rounded-md border px-3 py-2 ${statusToneClass(row.tone)}`}
        >
          <div className="flex items-center justify-between gap-3">
            <span className="text-[10px] font-mono font-bold tracking-widest text-slate-500">
              {row.title}
            </span>
            <span className="text-[10px] font-mono uppercase tracking-wider">
              {row.label}
            </span>
          </div>
          <p className="mt-1 truncate text-[11px] font-mono text-slate-500" title={row.detail}>
            {row.detail}
          </p>
        </div>
      ))}
    </section>
  );
}

function CommandCenterTradeQueuePanel({
  decisions,
  decisionsErr,
  portfolio,
  portfolioErr,
  trades,
  tradesErr,
  honestSet,
}: {
  decisions: CommandCenterDecision[] | undefined;
  decisionsErr: unknown;
  portfolio: CommandCenterPortfolioData | undefined;
  portfolioErr: unknown;
  trades: CommandCenterTrade[] | undefined;
  tradesErr: unknown;
  honestSet: HonestTradeSet | undefined;
}) {
  const decisionRows = Array.isArray(decisions) ? decisions : [];
  const positions = Array.isArray(portfolio?.positions) ? portfolio.positions : [];
  const fillRows = Array.isArray(trades) ? trades : [];
  const isDegraded = Boolean(decisionsErr || portfolioErr || tradesErr);
  const isEmpty = !isDegraded && decisionRows.length === 0 && positions.length === 0 && fillRows.length === 0;
  const stopState = portfolioErr
    ? "unknown"
    : positions.length > 0
      ? "contract needed"
      : "clear";
  const stopTone: StatusTone = portfolioErr ? "unknown" : positions.length > 0 ? "warn" : "ok";
  const journalLabel = honestSet ? dedupCaveat(honestSet) : "honest journal unavailable";

  const cells = [
    {
      title: "DECISIONS",
      label: decisionsErr ? "unknown" : `${decisionRows.length} recent`,
      detail: decisionsErr ? "decision endpoint unavailable" : "latest directional verdict rows",
      tone: decisionsErr ? "unknown" as const : "ok" as const,
    },
    {
      title: "POSITIONS",
      label: portfolioErr ? "unknown" : `${positions.length} open`,
      detail: portfolioErr ? "portfolio endpoint unavailable" : "paper portfolio source",
      tone: portfolioErr ? "unknown" as const : positions.length > 0 ? "warn" as const : "ok" as const,
    },
    {
      title: "STOP REVIEW",
      label: stopState,
      detail: positions.length > 0
        ? "stale-stop backend contract not mounted here"
        : "no open position stop check required",
      tone: stopTone,
    },
    {
      title: "JOURNAL",
      label: honestSet ? `${honestSet.trades.length} real` : "unknown",
      detail: journalLabel,
      tone: honestSet ? "ok" as const : "unknown" as const,
    },
  ];

  return (
    <section
      data-testid="command-center-trade-queue-panel"
      className="mb-4 rounded-md border border-slate-800 bg-slate-900/55 p-4"
      aria-label="Command Center trade queue panel"
    >
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Zap className="h-4 w-4 text-cyan-400" aria-hidden="true" />
          <h2 className="text-sm font-bold tracking-widest text-white">TRADE QUEUE PANEL</h2>
        </div>
        <Badge className="border border-slate-700 bg-slate-950 text-[10px] font-mono text-slate-400">
          ORDER ACTIONS DISABLED
        </Badge>
      </div>

      <div className="grid grid-cols-1 gap-2 md:grid-cols-2 xl:grid-cols-4">
        {cells.map((cell) => (
          <div key={cell.title} className={`rounded-md border px-3 py-2 ${statusToneClass(cell.tone)}`}>
            <div className="flex items-center justify-between gap-3">
              <span className="text-[10px] font-mono font-bold tracking-widest text-slate-500">
                {cell.title}
              </span>
              <span className="text-[10px] font-mono uppercase tracking-wider">
                {cell.label}
              </span>
            </div>
            <p className="mt-1 truncate text-[11px] font-mono text-slate-500" title={cell.detail}>
              {cell.detail}
            </p>
          </div>
        ))}
      </div>

      <div className="mt-3 rounded-md border border-slate-800 bg-slate-950/45 p-3">
        {isDegraded ? (
          <p className="text-xs font-mono text-amber-300">
            Queue degraded: one or more queue sources are unavailable.
          </p>
        ) : isEmpty ? (
          <p className="text-xs font-mono text-slate-400">
            No directional queue items, open paper positions, or recent fills are present.
          </p>
        ) : (
          <div className="space-y-2">
            {decisionRows.slice(0, 3).map((decision, index) => (
              <div
                key={`${decision.timestamp}-${decision.symbol}-${index}`}
                className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-b border-slate-800/60 pb-2 last:border-b-0 last:pb-0"
              >
                <span className="font-mono text-xs font-bold text-white">{decision.symbol}</span>
                <span className="font-mono text-xs text-cyan-300">{decision.action}</span>
                <span className="min-w-0 flex-1 truncate text-[11px] text-slate-500">
                  {decision.reason ?? decision.signal ?? "reason unavailable"}
                </span>
                <span className="font-mono text-[10px] text-slate-600">{fmtTime(decision.timestamp)}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

function stateBadgeClass(tone: StatusTone): string {
  if (tone === "ok") return "border-emerald-800 bg-emerald-950/30 text-emerald-300";
  if (tone === "warn") return "border-amber-800 bg-amber-950/30 text-amber-300";
  if (tone === "bad") return "border-red-800 bg-red-950/30 text-red-300";
  return "border-slate-700 bg-slate-950 text-slate-400";
}

function MiniStateBadge({ label, tone }: { label: string; tone: StatusTone }) {
  return (
    <span className={`rounded border px-1.5 py-0.5 text-[10px] font-mono uppercase tracking-wider ${stateBadgeClass(tone)}`}>
      {label}
    </span>
  );
}

function CommandCenterOperationsGrid({
  liveInstruments,
  paperStatus,
  ledger,
  ledgerReady,
  integrity,
  integrityReady,
}: {
  liveInstruments: Array<{ symbol: string; tf: string; status: "APPROVED" | "HALTED"; wfe: number }>;
  paperStatus: Record<string, CommandCenterPaperStatusRow> | undefined;
  ledger: LedgerResponse | undefined;
  ledgerReady: boolean;
  integrity: CommandCenterDataIntegrityResponse | undefined;
  integrityReady: boolean;
}) {
  const eligibilityRows = liveInstruments.map((inst) => {
    const row = paperStatus?.[`${inst.symbol}_${inst.tf}`];
    const raw = (row?.status ?? "").toUpperCase();
    const label = !paperStatus
      ? "stale"
      : raw === "ACTIVE" && inst.status === "APPROVED"
        ? "adopted"
        : raw === "NO-TRADE"
          ? "paused"
          : raw === "FAIL" || inst.status === "HALTED"
            ? "failed"
            : "research-only";
    const tone: StatusTone =
      label === "adopted" ? "ok" : label === "failed" ? "bad" : label === "paused" ? "warn" : "unknown";
    return {
      ...inst,
      label,
      tone,
      detail: row?.reason ?? row?.verdict ?? `DSR ${inst.wfe}`,
    };
  });

  const ledgerRows = Array.isArray(ledger?.entries) ? ledger.entries.slice(0, 4) : [];
  const integritySources = Array.isArray(integrity?.sources) ? integrity.sources : [];
  const staleSourceCount = integritySources.filter((src) => src.status === "stale").length;
  const dataRows = [
    {
      label: "CACHE AGE",
      state: integrityReady ? "reported" : "unknown",
      tone: integrityReady ? "ok" as const : "unknown" as const,
    },
    {
      label: "PROVIDER",
      state: integrityReady ? `${integrity?.count ?? integritySources.length} streams` : "unknown",
      tone: integrityReady ? "ok" as const : "unknown" as const,
    },
    {
      label: "BAR FRESHNESS",
      state: staleSourceCount > 0 ? `${staleSourceCount} stale` : integrityReady ? "current" : "unknown",
      tone: staleSourceCount > 0 ? "warn" as const : integrityReady ? "ok" as const : "unknown" as const,
    },
    {
      label: "SOURCE PARITY",
      state: "not wired",
      tone: "unknown" as const,
    },
  ];
  const researchRows = [
    { label: "PRS", state: "intake", detail: "keep / split / replace" },
    { label: "ISSUES", state: "intake", detail: "acceptance before code" },
    { label: "EXPERIMENTS", state: "research-only", detail: "no readiness promotion" },
    { label: "SPIKES", state: "reference", detail: "retire-to-archive when superseded" },
  ];

  return (
    <section
      data-testid="command-center-operations-grid"
      className="mb-4 grid grid-cols-1 gap-3 xl:grid-cols-4"
      aria-label="Command Center operations panels"
    >
      <Card className="bg-slate-900/60 border border-cyan-900/50">
        <CardHeader className="pb-2 pt-3 px-4">
          <CardTitle className="text-xs font-mono text-cyan-400 tracking-widest flex items-center gap-1.5">
            <CheckCircle className="w-3 h-3" />
            ELIGIBILITY PANEL
          </CardTitle>
        </CardHeader>
        <CardContent className="px-4 pb-3 space-y-2.5">
          <div className="flex flex-wrap gap-1">
            <MiniStateBadge label="adopted" tone="ok" />
            <MiniStateBadge label="paused" tone="warn" />
            <MiniStateBadge label="failed" tone="bad" />
            <MiniStateBadge label="stale" tone="unknown" />
            <MiniStateBadge label="research-only" tone="unknown" />
          </div>
          {eligibilityRows.map((row) => (
            <div key={`${row.symbol}-${row.tf}`} className="flex items-center justify-between gap-2">
              <span className="font-mono text-xs text-white">{row.symbol} {row.tf}</span>
              <MiniStateBadge label={row.label} tone={row.tone} />
            </div>
          ))}
        </CardContent>
      </Card>

      <Card className="bg-slate-900/60 border border-cyan-900/50">
        <CardHeader className="pb-2 pt-3 px-4">
          <CardTitle className="text-xs font-mono text-cyan-400 tracking-widest flex items-center gap-1.5">
            <TrendingUp className="w-3 h-3" />
            STRATEGY LEDGER PANEL
          </CardTitle>
        </CardHeader>
        <CardContent className="px-4 pb-3 space-y-2">
          {!ledgerReady ? (
            <p className="text-xs font-mono text-amber-300">Ledger unavailable.</p>
          ) : ledgerRows.length === 0 ? (
            <p className="text-xs font-mono text-slate-400">No strategy verdicts reported.</p>
          ) : (
            ledgerRows.map((row, index) => {
              const verdict = row.verdict ?? "UNKNOWN";
              const tone: StatusTone = verdict === "PASS" ? "ok" : verdict === "FAIL" ? "bad" : "unknown";
              const nextGate = verdict === "PASS" ? "forward proof" : verdict === "FAIL" ? "repair thesis" : "gate-v2 rerun";
              return (
                <div key={`${row.symbol}-${row.family}-${index}`} className="rounded border border-slate-800 bg-slate-950/40 p-2">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono text-xs text-white">{row.symbol ?? "—"} {row.family ?? "unknown"}</span>
                    <MiniStateBadge label={verdict} tone={tone} />
                  </div>
                  <p className="mt-1 text-[11px] font-mono text-slate-500">
                    next gate: {nextGate}
                  </p>
                </div>
              );
            })
          )}
        </CardContent>
      </Card>

      <Card className="bg-slate-900/60 border border-cyan-900/50">
        <CardHeader className="pb-2 pt-3 px-4">
          <CardTitle className="text-xs font-mono text-cyan-400 tracking-widest flex items-center gap-1.5">
            <Database className="w-3 h-3" />
            DATA INTEGRITY PANEL
          </CardTitle>
        </CardHeader>
        <CardContent className="px-4 pb-3 space-y-2">
          {dataRows.map((row) => (
            <div key={row.label} className="flex items-center justify-between gap-2">
              <span className="font-mono text-xs text-slate-500">{row.label}</span>
              <MiniStateBadge label={row.state} tone={row.tone} />
            </div>
          ))}
        </CardContent>
      </Card>

      <Card className="bg-slate-900/60 border border-cyan-900/50">
        <CardHeader className="pb-2 pt-3 px-4">
          <CardTitle className="text-xs font-mono text-cyan-400 tracking-widest flex items-center gap-1.5">
            <BookOpen className="w-3 h-3" />
            RESEARCH INTAKE PANEL
          </CardTitle>
        </CardHeader>
        <CardContent className="px-4 pb-3 space-y-2">
          {researchRows.map((row) => (
            <div key={row.label} className="rounded border border-slate-800 bg-slate-950/40 p-2">
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono text-xs text-white">{row.label}</span>
                <MiniStateBadge label={row.state} tone="unknown" />
              </div>
              <p className="mt-1 text-[11px] font-mono text-slate-500">{row.detail}</p>
            </div>
          ))}
        </CardContent>
      </Card>
    </section>
  );
}

function CanonicalShellMap({ regions }: { regions: ShellRegion[] }) {
  return (
    <section
      className="mb-4"
      aria-label="Command Center canonical sections"
      data-testid="canonical-shell"
    >
      <div className="mb-1.5 flex items-center justify-between">
        <span className="text-[10px] font-mono tracking-[0.2em] text-slate-500">
          CANONICAL SHELL
        </span>
        <span className="text-[10px] font-mono text-slate-600">
          {regions.filter((r) => r.tone === "live").length}/{regions.length} live
        </span>
      </div>
      <div className="grid grid-cols-1 gap-2 md:grid-cols-2 xl:grid-cols-6">
        {regions.map((region) => {
          const Icon = region.Icon;
          return (
            <a
              key={region.label}
              data-testid={`canonical-shell-${region.label.toLowerCase().replace(/\s+/g, "-")}`}
              href={region.href}
              className={`group min-h-[112px] rounded-md border p-3 transition-colors hover:border-cyan-700/70 ${shellToneClass(region.tone)}`}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="flex min-w-0 items-center gap-2">
                  <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                  <span className="truncate text-[11px] font-bold tracking-widest">
                    {region.label}
                  </span>
                </div>
                <ChevronRight className="h-3.5 w-3.5 shrink-0 opacity-40 transition-opacity group-hover:opacity-80" aria-hidden="true" />
              </div>
              <div className="mt-3 font-mono text-lg font-bold leading-none text-white tabular-nums">
                {region.metric}
              </div>
              <div className="mt-2 flex items-center justify-between gap-2">
                <span className="text-[10px] font-mono uppercase tracking-wider opacity-80">
                  {region.status}
                </span>
              </div>
              <p className="mt-2 line-clamp-2 text-[11px] leading-snug text-slate-500">
                {region.detail}
              </p>
            </a>
          );
        })}
      </div>
    </section>
  );
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
  const [retryCount, setRetryCount] = useState(0);
  const [isRetrying, setIsRetrying] = useState(false);

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
    () => fetchCommandCenterBars(chartSym),
    { refreshInterval: 60_000, revalidateOnFocus: false }
  );

  const { addToast } = useToast();

  const {
    data: health,
    error: healthErr,
    mutate: mutateHealth,
  } = useSWR<CommandCenterHealthData>("/health", fetchCommandCenterHealth, {
    refreshInterval,
    shouldRetryOnError: false,
  });

  const { data: safety, mutate: mutateSafety, error: safetyErr } = useSWR<CommandCenterSafetyData>("/safety/status", fetchCommandCenterSafety, {
    refreshInterval,
    shouldRetryOnError: false,
  });

  const { data: portfolio, mutate: mutatePortfolio, error: portfolioErr } = useSWR<CommandCenterPortfolioData>("/portfolio", fetchCommandCenterPortfolio, {
    refreshInterval,
    shouldRetryOnError: false,
  });

  const { data: decisions, mutate: mutateDecisions, error: decisionsErr } = useSWR<CommandCenterDecision[]>(
    "/decisions/recent?limit=5",
    fetchCommandCenterDecisions,
    { refreshInterval, shouldRetryOnError: false }
  );

  const { data: scheduler, mutate: mutateScheduler, error: schedulerErr } = useSWR<CommandCenterSchedulerData>(
    "/scheduler/status",
    fetchCommandCenterScheduler,
    { refreshInterval, shouldRetryOnError: false }
  );

  const { data: macro, mutate: mutateMacro } = useSWR<CommandCenterMacroData>("/macro/snapshot", fetchCommandCenterMacro, {
    refreshInterval: 120_000,
    shouldRetryOnError: false,
  });

  const { data: paperStatus, mutate: mutatePaperStatus } = useSWR<Record<string, CommandCenterPaperStatusRow>>(
    "/backtest/paper-status",
    fetchCommandCenterPaperStatus,
    { refreshInterval: 120_000, shouldRetryOnError: false }
  );

  const { data: ledger, error: ledgerErr, mutate: mutateLedger } = useSWR<LedgerResponse>(
    "strategy-ledger-command-center",
    fetchCommandCenterStrategyLedger,
    { refreshInterval, shouldRetryOnError: false }
  );

  const { data: integrity, error: integrityErr, mutate: mutateIntegrity } = useSWR<CommandCenterDataIntegrityResponse>(
    "/system/data-integrity",
    fetchCommandCenterDataIntegrity,
    { refreshInterval, shouldRetryOnError: false }
  );

  const { data: trades, mutate: mutateTrades, error: tradesErr } = useSWR<CommandCenterTrade[]>(
    "/portfolio/history/trades",
    fetchCommandCenterTrades,
    { refreshInterval, shouldRetryOnError: false }
  );

  const { data: journalStats, mutate: mutateJournalStats } = useSWR<JournalTradeStats>(
    "/journal/review/stats?limit=30",
    fetchCommandCenterJournalStats,
    { refreshInterval: 60_000, shouldRetryOnError: false }
  );

  // Honest deduped set for the journal HUD row (win_rate + EV/trade).
  // /journal/review/stats over-counts re-logged winners; fetchHonestTrades
  // applies dedup at read time. All other command-center cards are LEGIT.
  const { data: honestSet, mutate: mutateHonestSet } = useSWR<HonestTradeSet>(
    "honest-trades-cc",
    fetchHonestTrades,
    { refreshInterval: 5 * 60_000, shouldRetryOnError: false }
  );

  // Bounded retry/backoff for critical command-center data so transient engine
  // hiccups do not hammer the proxy or silently stale out the flagship page.
  useEffect(() => {
    if (!healthErr && !safetyErr && !portfolioErr && !decisionsErr && !schedulerErr && !tradesErr) {
      if (retryCount > 0) {
        setRetryCount(0);
        setIsRetrying(false);
      }
      return;
    }

    const hasError = healthErr || safetyErr || portfolioErr || decisionsErr || schedulerErr || tradesErr;
    if (!hasError || retryCount >= 3) {
      if (retryCount >= 3) setIsRetrying(false);
      return;
    }

    const backoffMs = Math.min(30_000, 2_000 * Math.pow(2, retryCount - 1));
    setIsRetrying(true);
    const timer = setTimeout(() => {
      mutateHealth();
      mutateSafety();
      mutatePortfolio();
      mutateDecisions();
      mutateScheduler();
      mutateTrades();
    }, backoffMs);

    return () => clearTimeout(timer);
  }, [healthErr, safetyErr, portfolioErr, decisionsErr, schedulerErr, tradesErr, retryCount, mutateHealth, mutateSafety, mutatePortfolio, mutateDecisions, mutateScheduler, mutateTrades]);

  useWebSocket(undefined, (event) => {
    if (!shouldRevalidateCommandCenter(event)) return;
    mutateHealth();
    mutateSafety();
    mutatePortfolio();
    mutateDecisions();
    mutateScheduler();
    mutateMacro();
    mutatePaperStatus();
    mutateLedger();
    mutateIntegrity();
    mutateTrades();
    mutateJournalStats();
    mutateHonestSet();
  });

  const engineOnline = !healthErr && !!health;
  const killSwitchActive = health?.kill_switch_active ?? false;
  // D3-01: derive the IBKR Gateway badge through the honesty layer — never
  // read ibkr_execution_connected directly (see @/lib/executionPath).
  const exec = executionStatus(health);

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

  const approvedInstruments = liveInstruments.filter((inst) => inst.status === "APPROVED").length;
  const haltedInstruments = liveInstruments.length - approvedInstruments;
  const staleFeeds = (integrity?.sources ?? []).filter((src) => src.status === "stale").length;
  const ledgerReady =
    Array.isArray(ledger?.entries) &&
    typeof ledger?.total === "number" &&
    typeof ledger?.n_pass === "number" &&
    typeof ledger?.n_fail === "number";
  const integrityReady =
    Array.isArray(integrity?.sources) || typeof integrity?.count === "number";
  const statusOrdersPerMin = safety?.orders_last_minute ?? 0;
  const statusOrdersLimit = safety?.orders_per_minute_limit ?? 10;
  const engineStatus = !health && !healthErr
    ? { label: "unknown", detail: "health probe pending", tone: "unknown" as const }
    : healthErr || !health
      ? { label: "offline", detail: "health endpoint unreachable", tone: "bad" as const }
      : health.status === "ok" || health.status === "healthy"
        ? { label: "online", detail: `version ${health.version ?? "unknown"}`, tone: "ok" as const }
        : { label: "degraded", detail: `status ${health.status ?? "unknown"}`, tone: "warn" as const };
  const brokerStatus = !health && !healthErr
    ? { label: "unknown", detail: "execution path pending", tone: "unknown" as const }
    : healthErr || !health
      ? { label: "unknown", detail: "engine offline; broker unprobed", tone: "unknown" as const }
      : exec.tone === "bull"
        ? { label: "verified", detail: exec.detail, tone: "ok" as const }
        : exec.tone === "warn"
          ? { label: "degraded", detail: exec.detail, tone: "warn" as const }
          : { label: "offline", detail: exec.detail, tone: "bad" as const };
  const safetyStatus = !safety && !safetyErr
    ? { label: "unknown", detail: "safety probe pending", tone: "unknown" as const }
    : safetyErr || !safety
      ? { label: "unknown", detail: "safety endpoint unavailable", tone: "unknown" as const }
      : killSwitchActive
        ? { label: "halted", detail: "kill switch active", tone: "bad" as const }
        : { label: "armed", detail: `${statusOrdersPerMin}/${statusOrdersLimit} orders per minute`, tone: "ok" as const };
  const dataStatus = integrityErr || !integrityReady
    ? { label: "unknown", detail: "data-integrity endpoint unavailable", tone: "unknown" as const }
    : staleFeeds > 0
      ? { label: "stale", detail: `${staleFeeds} stale feed${staleFeeds === 1 ? "" : "s"}`, tone: "warn" as const }
      : { label: "current", detail: `${compactCount(integrity?.count ?? integrity?.sources?.length)} streams`, tone: "ok" as const };
  const shellRegions: ShellRegion[] = [
    {
      label: "SYSTEM STATUS",
      href: "/health",
      status: engineOnline ? (killSwitchActive ? "halted" : "online") : "offline",
      metric: engineOnline ? (killSwitchActive ? "HALT" : "OK") : "DOWN",
      detail: `${health?.paper_trading === false ? "live flag observed" : "paper mode"} · ${exec.label}`,
      tone: engineOnline ? (killSwitchActive ? "warn" : "live") : "offline",
      Icon: Shield,
    },
    {
      label: "TRADE QUEUE",
      href: "/trades/pending-approvals",
      status: decisionsErr ? "degraded" : "mounted",
      metric: `${compactCount(decisions?.length)} recent`,
      detail: tradesErr ? "fills unavailable" : `${compactCount(trades?.length)} fill rows visible`,
      tone: decisionsErr || tradesErr ? "warn" : "live",
      Icon: Zap,
    },
    {
      label: "ELIGIBILITY",
      href: "/trading-eligibility",
      status: paperStatus ? "policy" : "fallback",
      metric: `${approvedInstruments}/${liveInstruments.length}`,
      detail: `${haltedInstruments} halted · gate-v2 authorization`,
      tone: paperStatus ? "live" : "warn",
      Icon: CheckCircle,
    },
    {
      label: "STRATEGY LEDGER",
      href: "/strategy-ledger",
      status: ledgerErr || !ledgerReady ? "degraded" : "gate-v2",
      metric: `${compactCount(ledger?.n_pass)} pass`,
      detail: ledgerReady
        ? `${compactCount(ledger?.n_fail)} fail · ${compactCount(ledger?.total)} verdicts`
        : "verdict ledger unavailable",
      tone: ledgerErr || !ledgerReady ? "warn" : "live",
      Icon: TrendingUp,
    },
    {
      label: "DATA INTEGRITY",
      href: "/data-integrity",
      status: integrityErr || !integrityReady ? "degraded" : "streams",
      metric: compactCount(integrity?.count ?? integrity?.sources?.length),
      detail: integrityReady
        ? staleFeeds > 0
          ? `${staleFeeds} stale feed${staleFeeds === 1 ? "" : "s"}`
          : "no stale feed reported"
        : "stream health unavailable",
      tone: integrityErr || !integrityReady ? "warn" : staleFeeds > 0 ? "warn" : "live",
      Icon: Database,
    },
    {
      label: "RESEARCH INTAKE",
      href: "/research-log",
      status: "planned",
      metric: "P7",
      detail: "candidate intake surface follows this shell",
      tone: "static",
      Icon: BookOpen,
    },
  ];

  // Risk gauge calculations
  const dailyPnlPct =
    portfolio?.total_equity && portfolio.total_equity > 0
      ? (portfolio.daily_pnl / portfolio.total_equity) * 100
      : 0;
  // Live limits from /safety/status (engine/config.py MAX_DAILY_LOSS_PCT /
  // MAX_DRAWDOWN_PCT / MAX_ORDERS_PER_MINUTE). Fallbacks only cover a missing
  // field (older engine build); the orders fallback matches the real config
  // default (10), not the previously-hardcoded-wrong value (40).
  const dailyLimitPctAbs =
    safety?.daily_limit_pct != null ? Math.abs(safety.daily_limit_pct) * 100 : 2;
  const drawdownLimitPctAbs =
    safety?.drawdown_limit_pct != null ? Math.abs(safety.drawdown_limit_pct) * 100 : 10;
  const ordersLimit = safety?.orders_per_minute_limit ?? 10;
  const dailyLossProgress = Math.min(
    (Math.abs(Math.min(dailyPnlPct, 0)) / dailyLimitPctAbs) * 100,
    100
  );
  const drawdownPct = safety?.drawdown_pct ?? 0;
  const drawdownProgress = Math.min(
    (Math.abs(drawdownPct) / drawdownLimitPctAbs) * 100,
    100
  );
  const consecutiveLosses = safety?.consecutive_losses ?? 0;
  const consecutiveLossProgress = Math.min((consecutiveLosses / 7) * 100, 100);
  const ordersPerMin = safety?.orders_last_minute ?? 0;
  const ordersProgress = Math.min((ordersPerMin / ordersLimit) * 100, 100);

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
      await setCommandCenterKillSwitch(activating);
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

      <CommandCenterStatusStrip
        engine={engineStatus}
        broker={brokerStatus}
        safety={safetyStatus}
        data={dataStatus}
      />

      <CanonicalShellMap regions={shellRegions} />

      <CommandCenterTradeQueuePanel
        decisions={decisions}
        decisionsErr={decisionsErr}
        portfolio={portfolio}
        portfolioErr={portfolioErr}
        trades={trades}
        tradesErr={tradesErr}
        honestSet={honestSet}
      />

      <CommandCenterOperationsGrid
        liveInstruments={liveInstruments}
        paperStatus={paperStatus}
        ledger={ledger}
        ledgerReady={ledgerReady}
        integrity={integrity}
        integrityReady={integrityReady}
      />

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
            <WidgetErrorBoundary name="Trade Approvals">
              <ApprovalPanel />
            </WidgetErrorBoundary>
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
          DECISION LOG — every pipeline verdict, including WAIT/HOLD/NO_ENTRY.
          Pipeline Reasoning above covers trades that fired; this covers the
          "why didn't we trade" case that had no dashboard home before.
      ═══════════════════════════════════════════════════════ */}
      <div className="mb-4">
        <WidgetErrorBoundary name="Decision Log">
          <DecisionLogWidget />
        </WidgetErrorBoundary>
      </div>

      {/* ═══════════════════════════════════════════════════════
          SESSION BRIEF — proactive advisor recommendations. Re-homed here from
          the dissolved kitchen-sink overview page (#274 feature preserved on the
          flagship HUD after the P2.1 redirect orphaned its old mount point).
      ═══════════════════════════════════════════════════════ */}
      <div className="mb-4">
        <WidgetErrorBoundary name="Session Brief">
          <SessionBriefPanel />
        </WidgetErrorBoundary>
      </div>

      {/* ═══════════════════════════════════════════════════════
          TRADE RECOMMENDATIONS — actionable board with entry/stop/T1
          (amo-arbitrage style). Live candidates + recently-resolved rows
          once the autonomous pipeline is armed. Mounted on the flagship HUD
          (2026-08-16) so recommendations are visible where Amo actually looks.
      ═══════════════════════════════════════════════════════ */}
      <div className="mb-4">
        <WidgetErrorBoundary name="Trade Recommendations">
          <ActionableBoardWidget />
        </WidgetErrorBoundary>
      </div>

      {/* ═══════════════════════════════════════════════════════
          PIPELINE FUNNEL — runs -> signals -> approved -> executed -> filled
          conversion (last 30/90d). Turns "not enough trades" into an
          inspectable funnel and surfaces regressions at each stage (T9).
      ═══════════════════════════════════════════════════════ */}
      <div className="mb-4">
        <WidgetErrorBoundary name="Pipeline Funnel">
          <PipelineFunnelCard />
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
                  {inst.status === "APPROVED" ? `DSR=${inst.wfe}` : "HALTED"}
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
                {fmtPct(dailyPnlPct)} / -{dailyLimitPctAbs.toFixed(0)}%
              </span>
            </div>
            <div className="flex justify-between items-baseline">
              <span className="text-xs text-slate-500">Drawdown</span>
              <span
                className={`font-mono text-xs ${drawdownPct < -5 ? "text-red-400" : "text-yellow-400"}`}
              >
                {fmtPct(drawdownPct)} / -{drawdownLimitPctAbs.toFixed(0)}%
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
          <WidgetErrorBoundary key={inst.symbol} name={`Signal Card: ${inst.symbol}`}>
            <SignalCard inst={inst} />
          </WidgetErrorBoundary>
        ))}
      </div>

      {/* ═══════════════════════════════════════════════════════
          ROW 3 — RISK GAUGES + PIPELINE FUNNEL + RECENT SIGNALS (3 columns)
      ═══════════════════════════════════════════════════════ */}
      <div className="grid grid-cols-3 gap-3 mb-4">
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
                  {fmtPct(dailyPnlPct)} / -{dailyLimitPctAbs.toFixed(2)}%
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
                  {fmtPct(drawdownPct)} / -{drawdownLimitPctAbs.toFixed(2)}%
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
                  {ordersPerMin} / {ordersLimit} limit
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
              <>
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
              <p className="text-[10px] text-amber-500/70 font-mono mt-2">
                Raw record (/portfolio/history/trades) — not deduped; per-trade
                P&amp;L may include re-logged duplicates.
              </p>
              </>
            )}
          </CardContent>
        </Card>

        {/* Walk-Forward Monitor */}
        <Card className="bg-slate-900/60 border border-cyan-900/50">
          <CardHeader className="pb-2 pt-3 px-4">
            <CardTitle className="text-xs font-mono text-cyan-400 tracking-widest flex items-center gap-1.5">
              <RefreshCw className="w-3 h-3" />
              GATE-V2 DEFLATED SHARPE MONITOR
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
              <p className="text-[10px] text-slate-600 italic">
                Configured schedule/method (static, not live-probed):
              </p>
              <div className="flex justify-between text-xs font-mono">
                <span className="text-slate-500">Next Recalc</span>
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
              <span className="font-mono text-xs text-slate-400">N/A — inactive</span>
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
                  exec.tone === "bull"
                    ? "bg-green-950 text-green-400 border-green-800"
                    : exec.tone === "warn"
                    ? "bg-yellow-950 text-yellow-400 border-yellow-800"
                    : "bg-red-950 text-red-400 border-red-800"
                }`}
                title={exec.detail}
              >
                {exec.label}
              </Badge>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-xs text-slate-500" title="Engine /health reachability — not a direct database probe.">
                Engine Reachable
              </span>
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

// ── SignalCard (PRB-34: live regime, static lastSignal/atr) ────────────────

function SignalCard({ inst }: { inst: (typeof INSTRUMENTS)[number] }) {
  const { regime: liveRegime, isLoading: regimeLoading } = useSymbolRegime(inst.symbol);

  return (
    <Card
      className={`bg-slate-900/60 border ${
        inst.status === "HALTED" ? "border-red-900/60" : "border-cyan-900/50"
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
              DSR={inst.wfe} — OVERFIT DETECTED
              <br />
              Regime-adaptive boost insufficient
            </span>
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-x-4 gap-y-3">
            <div>
              <div className="text-xs text-slate-500 mb-0.5">
                Deflated Sharpe
              </div>
              <div className="font-mono text-lg text-cyan-400 font-bold leading-none">
                {inst.wfe}
              </div>
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-0.5">Regime</div>
              {regimeLoading ? (
                <div className="h-4 w-16 animate-pulse rounded bg-slate-800" />
              ) : liveRegime ? (
                <div className={`font-mono text-sm font-bold ${regimeColorClass(liveRegime)}`}>
                  {liveRegime}
                </div>
              ) : (
                <div className="font-mono text-sm text-slate-600">unavailable</div>
              )}
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-0.5">
                Last Signal (static)
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
                ATR Approx (static)
              </div>
              <div className="font-mono text-sm text-white">
                {inst.atr}
              </div>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
