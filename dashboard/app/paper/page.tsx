"use client";

import React, { useState, useCallback, useEffect } from "react";
import Link from "next/link";
import useSWR from "swr";
import { Activity, ArrowLeft, RefreshCw, Send, AlertTriangle, TrendingUp, TrendingDown, Minus, ShieldOff, ShieldCheck, Trash2 } from "lucide-react";
import { fetchEngine, postEngine, toggleKillSwitch, resetPendingSignals, fetchKillSwitchStatus } from "@/lib/api";
import type { MGCSignalResponse, PendingSignal, MGCPerformanceResponse, PaperTradePayload, KillSwitchStatus } from "@/lib/api";
import {
  fetchHonestTrades,
  equityCurve,
  dedupCaveat,
  type HonestTradeSet,
} from "@/lib/honestTrades";
import { OpenPositionsWidget } from "@/components/OpenPositionsWidget";
import { RiskStatusWidget } from "@/components/RiskStatusWidget";
import { CircuitBreakerWidget } from "@/components/CircuitBreakerWidget";
import { RecentSignalsWidget } from "@/components/RecentSignalsWidget";
import { MarketRegimeWidget } from "@/components/MarketRegimeWidget";
import { RecentDecisionsWidget } from "@/components/RecentDecisionsWidget";
import { SessionSummaryWidget } from "@/components/SessionSummaryWidget";
import { TodaySummaryWidget } from "@/components/TodaySummaryWidget";
import { PositionSizingWidget } from "@/components/PositionSizingWidget";
import { SignalQueueWidget } from "@/components/SignalQueueWidget";
import { PaperApprovedValidationWidget } from "@/components/PaperApprovedValidationWidget";
import ValidationCheckpointWidget from "@/components/ValidationCheckpointWidget";
import { WidgetErrorBoundary } from "@/components/WidgetErrorBoundary";

function fetcher<T = unknown>(url: string): Promise<T> {
  return fetchEngine<T>(url);
}

type EngineHealthPayload = { status?: string };

// ── Shared direction/tone class helpers ─────────────────────────────────────
type DirectionKey = "long" | "short" | "flat";

const DIRECTION_TEXT_CLASS: Record<DirectionKey, string> = {
  long: "text-[#00ff88]",
  short: "text-[#ff4444]",
  flat: "text-[#ffcc00]",
};
const DIRECTION_BADGE_CLASS: Record<DirectionKey, string> = {
  long: "bg-[#00ff8808] border-[#00ff8825]",
  short: "bg-[#ff444408] border-[#ff444425]",
  flat: "bg-[#ffcc0008] border-[#ffcc0025]",
};

function directionKey(dir: string | undefined): DirectionKey {
  const d = (dir ?? "").toUpperCase();
  if (d === "LONG" || d === "BUY") return "long";
  if (d === "SHORT" || d === "SELL") return "short";
  return "flat";
}

function confidenceBarClass(confidence: number): string {
  if (confidence >= 0.7) return "bg-[#00ff88]";
  if (confidence >= 0.4) return "bg-[#ffcc00]";
  return "bg-[#ff4444]";
}

function pfColorClass(pf: number | null | undefined): string {
  if (pf == null) return "text-[#555]";
  if (pf >= 1.5) return "text-[#00ff88]";
  if (pf >= 1.0) return "text-[#ffcc00]";
  return "text-[#ff4444]";
}

function statusClasses(status: string | undefined): { bg: string; border: string; text: string } {
  const s = (status ?? "pending").toLowerCase();
  if (s === "entered" || s === "filled") return { bg: "bg-[#00ff8815]", border: "border-[#00ff8830]", text: "text-[#00ff88]" };
  if (s === "expired" || s === "cancelled") return { bg: "bg-[#55555515]", border: "border-[#55555530]", text: "text-[#555]" };
  return { bg: "bg-[#ffcc0015]", border: "border-[#ffcc0030]", text: "text-[#ffcc00]" };
}

// ── Main Page ────────────────────────────────────────────────────────────────
export default function PaperTradingPage() {
  const { data: health, error: healthError, isLoading: healthLoading } = useSWR<EngineHealthPayload>(
    "/health",
    fetcher,
    { refreshInterval: 30_000, revalidateOnFocus: true }
  );

  let engineHealthLabel = "ENGINE …";
  let engineHealthClass = "border-[#88888844] bg-[#88888810] text-[#888888]";
  if (healthError) {
    engineHealthLabel = "ENGINE offline";
    engineHealthClass = "border-[#ff444466] bg-[#ff444410] text-[#ff6666]";
  } else if (!healthLoading && health) {
    if (health.status === "ok") {
      engineHealthLabel = "ENGINE ok";
      engineHealthClass = "border-[#00aaff44] bg-[#00aaff12] text-[#00ccff]";
    } else {
      engineHealthLabel = `ENGINE ${health.status ?? "?"}`;
      engineHealthClass = "border-[#ffaa0044] bg-[#ffaa0010] text-[#ffcc66]";
    }
  }

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="sticky top-0 z-50 border-b border-border bg-background/95 backdrop-blur">
        <div className="mx-auto max-w-[1920px] 2xl:max-w-[2400px] flex items-center justify-between px-6 py-3">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent/10">
              <Activity className="h-5 w-5 text-accent" />
            </div>
            <div>
              <h1 className="font-bold text-foreground tracking-tight">
                JARVIS TRADER
              </h1>
              <p className="text-xs text-muted-foreground">
                MGC Daily Paper Trading — SUSPENDED
              </p>
            </div>
            <nav className="hidden lg:flex items-center gap-4 ml-6">
              <Link href="/" className="text-xs text-muted-foreground hover:text-foreground transition-colors flex items-center gap-1">
                <ArrowLeft className="h-3 w-3" />
                Dashboard
              </Link>
              <Link href="/analysis" className="text-xs text-muted-foreground hover:text-foreground transition-colors">
                Analysis
              </Link>
              <Link href="/backtest" className="text-xs text-muted-foreground hover:text-foreground transition-colors">
                Backtest
              </Link>
              <Link href="/paper" className="text-xs text-accent font-semibold transition-colors">
                Paper Trading
              </Link>
            </nav>
          </div>
          <div className="flex items-center gap-2">
            <span
              className={`font-mono text-[9px] px-1.5 py-0.5 rounded border ${engineHealthClass}`}
              title="GET /health — same check as WORKING_TODAY smoke"
            >
              {engineHealthLabel}
            </span>
            <span className="font-mono text-[9px] px-1.5 py-0.5 rounded border border-[#00ff8833] bg-[#00ff8810] text-[#00ff88]">
              PAPER MODE
            </span>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1920px] 2xl:max-w-[2400px] px-6 py-4 space-y-4">
        {/* WFE Halt Banner */}
        <div className="rounded-xl p-4 font-mono bg-[#ff444410] border border-[#ff444440]">
          <div className="flex items-start gap-3">
            <span className="text-[11px] font-bold tracking-wider text-[#ff4444]">
              PAPER TRADING SUSPENDED
            </span>
            <span className="text-[10px] text-[#ff8888]">
              MGC 1d WFE corrected to 0.14 (was 0.27) — below 0.30 threshold. Status: OVERFIT.
              Paper trading suspended pending MTF filter validation.
            </span>
          </div>
        </div>

        {/* Open Positions — safety-critical, first widget at top of page */}
        <WidgetErrorBoundary name="Open Positions">
          <OpenPositionsWidget />
        </WidgetErrorBoundary>

        {/* Risk Status — always visible at top of page */}
        <WidgetErrorBoundary name="Risk Status">
          <RiskStatusWidget />
        </WidgetErrorBoundary>

        {/* MCL / MNQ validation gates vs project thresholds (SQLite closed trades) */}
        <WidgetErrorBoundary name="Paper Approved Validation">
          <PaperApprovedValidationWidget />
        </WidgetErrorBoundary>

        {/* Overall validation checkpoint (30-day window progress) */}
        <WidgetErrorBoundary name="Validation Checkpoint">
          <ValidationCheckpointWidget />
        </WidgetErrorBoundary>

        {/* Circuit breaker / safety status */}
        <WidgetErrorBoundary name="Circuit Breaker">
          <CircuitBreakerWidget />
        </WidgetErrorBoundary>

        {/* Today's session summary */}
        <WidgetErrorBoundary name="Today Summary">
          <TodaySummaryWidget />
        </WidgetErrorBoundary>

        {/* ATR-based position sizing */}
        <WidgetErrorBoundary name="Position Sizing">
          <PositionSizingWidget />
        </WidgetErrorBoundary>

        {/* Current signal state: entry signal, direction, regime, STC, ATR levels */}
        <WidgetErrorBoundary name="Signal Queue">
          <SignalQueueWidget />
        </WidgetErrorBoundary>

        {/* Recent pipeline signals */}
        <WidgetErrorBoundary name="Recent Signals">
          <RecentSignalsWidget />
        </WidgetErrorBoundary>

        {/* Market regime / MTF analysis */}
        <WidgetErrorBoundary name="Market Regime">
          <MarketRegimeWidget />
        </WidgetErrorBoundary>

        {/* Top row: Signal + Performance */}
        <div className="grid grid-cols-12 gap-4">
          <div className="col-span-12 lg:col-span-6">
            <LiveSignalPanel />
          </div>
          <div className="col-span-12 lg:col-span-6">
            <PerformanceMetricsPanel />
          </div>
        </div>

        {/* Kill Switch + Reset Controls */}
        <KillSwitchPanel />

        {/* Middle: Pending Signals Queue with History Tab */}
        <SignalQueuePanel />

        {/* Bottom: Trade Logger */}
        <TradeLoggerPanel />

        {/* Recent AI Decisions */}
        <WidgetErrorBoundary name="Recent Decisions">
          <RecentDecisionsWidget />
        </WidgetErrorBoundary>

        {/* Today's session summary (P&L, trades, win rate, best/worst trade) */}
        <WidgetErrorBoundary name="Session Summary">
          <SessionSummaryWidget />
        </WidgetErrorBoundary>
      </main>
    </div>
  );
}

// ── Section 1: Live Signal Panel ─────────────────────────────────────────────

function LiveSignalPanel() {
  const [signal, setSignal] = useState<MGCSignalResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastFetch, setLastFetch] = useState<string | null>(null);

  const fetchSignal = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchEngine<MGCSignalResponse>("/paper/mgc-signal");
      setSignal(data);
      setLastFetch(new Date().toLocaleTimeString());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to fetch signal");
    } finally {
      setLoading(false);
    }
  }, []);

  const DirectionIcon = ({ direction }: { direction: string | undefined }) => {
    const key = directionKey(direction);
    const cls = `h-5 w-5 ${DIRECTION_TEXT_CLASS[key]}`;
    if (key === "long") return <TrendingUp className={cls} />;
    if (key === "short") return <TrendingDown className={cls} />;
    return <Minus className={cls} />;
  };

  const dKey = directionKey(signal?.direction ?? undefined);

  return (
    <div className="rounded-xl border border-[#1a1a2e] bg-[#0a0a0a] p-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <span className="font-mono text-[10px] font-bold tracking-[0.2em] uppercase text-[#00ff88]">
            MGC DAILY SIGNAL
          </span>
          <span className="font-mono text-[9px] px-1.5 py-0.5 rounded border border-[#00d4ff33] bg-[#00d4ff10] text-[#00d4ff]">
            GC=F
          </span>
        </div>
        <button
          onClick={fetchSignal}
          disabled={loading}
          className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-mono font-semibold transition-colors disabled:opacity-40 bg-[#00ff8820] text-[#00ff88] border border-[#00ff8840]"
        >
          <RefreshCw className={`h-3 w-3 ${loading ? "animate-spin" : ""}`} />
          {loading ? "Fetching..." : "Fetch Signal"}
        </button>
      </div>

      {/* Error State */}
      {error && (
        <div className="rounded-lg p-3 mb-3 font-mono text-xs flex items-center gap-2 bg-[#ff444415] border border-[#ff444430] text-[#ff4444]">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
          {error}
        </div>
      )}

      {/* Signal Content */}
      {signal ? (
        <div className="space-y-3">
          {/* Direction Badge */}
          <div className={`flex items-center gap-3 rounded-lg p-3 border ${DIRECTION_BADGE_CLASS[dKey]}`}>
            <DirectionIcon direction={signal.direction ?? undefined} />
            <span className={`font-mono text-2xl font-bold tracking-wider ${DIRECTION_TEXT_CLASS[dKey]}`}>
              {(signal.direction ?? "FLAT").toUpperCase()}
            </span>
          </div>

          {/* Price Levels Grid */}
          <div className="grid grid-cols-2 gap-2">
            <SignalStat label="Entry Price" value={signal.entry_price != null ? `$${signal.entry_price.toFixed(2)}` : "--"} />
            <SignalStat label="Stop Level" value={signal.stop_level != null ? `$${signal.stop_level.toFixed(2)}` : "--"} colorClass="text-[#ff4444]" />
            <SignalStat label="Target 1" value={signal.target_1 != null ? `$${signal.target_1.toFixed(2)}` : "--"} colorClass="text-[#00ff88]" />
            <SignalStat label="Regime" value={signal.regime ?? "--"} colorClass="text-[#00d4ff]" />
          </div>

          {/* Confidence / Extra Info */}
          {signal.confidence != null && (
            <div className="flex items-center gap-2 pt-1">
              <span className="font-mono text-[10px] uppercase tracking-wider text-[#555]">Confidence</span>
              <span className="font-mono text-xs font-bold tabular-nums text-[#e0e0e0]">
                {(signal.confidence * 100).toFixed(0)}%
              </span>
              <div className="flex-1 h-1 rounded-full overflow-hidden bg-panel-border">
                <div
                  className={`h-full rounded-full transition-all ${confidenceBarClass(signal.confidence)}`}
                  style={{ width: `${signal.confidence * 100}%` }}
                />
              </div>
            </div>
          )}

          {/* Last Fetch */}
          {lastFetch && (
            <div className="text-right">
              <span className="font-mono text-[9px] text-[#444]">
                Last fetched: {lastFetch}
              </span>
            </div>
          )}
        </div>
      ) : (
        <div className="rounded-lg p-8 text-center bg-panel-alt">
          <span className="font-mono text-xs text-[#555]">
            Click "Fetch Signal" to get the latest MGC daily signal
          </span>
        </div>
      )}
    </div>
  );
}

function SignalStat({ label, value, colorClass }: { label: string; value: string; colorClass?: string }) {
  return (
    <div className="rounded-lg p-2.5 bg-panel-alt border border-panel-border">
      <div className="font-mono text-[9px] uppercase tracking-wider mb-1 text-[#555]">{label}</div>
      <div className={`font-mono text-sm font-bold tabular-nums ${colorClass ?? "text-[#e0e0e0]"}`}>{value}</div>
    </div>
  );
}


// ── Section 2a: Kill Switch Control Panel ────────────────────────────────────

function KillSwitchPanel() {
  const { data: ks, error, mutate } = useSWR<KillSwitchStatus>(
    "kill-switch-status",
    fetchKillSwitchStatus,
    { refreshInterval: 30_000, shouldRetryOnError: false }
  );
  const [acting, setActing] = useState(false);
  const [resetResult, setResetResult] = useState<string | null>(null);

  const isActive = ks?.active ?? false;

  const handleToggle = useCallback(async () => {
    if (isActive) {
      // Deactivate — no confirmation needed
      setActing(true);
      try {
        await toggleKillSwitch("deactivate");
        await mutate();
      } finally {
        setActing(false);
      }
    } else {
      // Activate — confirm first
      const confirmed = confirm(
        "ACTIVATE KILL SWITCH?\n\nThis will block all new signals and pause the scheduler. Manual deactivation required to resume."
      );
      if (!confirmed) return;
      setActing(true);
      try {
        await toggleKillSwitch("activate", "manual");
        await mutate();
      } finally {
        setActing(false);
      }
    }
  }, [isActive, mutate]);

  const handleReset = useCallback(async () => {
    const confirmed = confirm(
      "RESET PENDING SIGNALS?\n\nThis will clear the entire pending signal queue. This action cannot be undone."
    );
    if (!confirmed) return;
    setActing(true);
    setResetResult(null);
    try {
      const result = await resetPendingSignals();
      setResetResult(`Cleared ${result.cleared} signal(s)`);
      setTimeout(() => setResetResult(null), 4000);
    } catch (err) {
      setResetResult(err instanceof Error ? err.message : "Reset failed");
      setTimeout(() => setResetResult(null), 5000);
    } finally {
      setActing(false);
    }
  }, []);

  return (
    <div className={`rounded-xl border bg-[#0a0a0a] p-4 ${isActive ? "border-[#ff444440]" : "border-panel-border"}`}>
      {/* Header row */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          {isActive
            ? <ShieldOff className="h-4 w-4 text-[#ff4444]" />
            : <ShieldCheck className="h-4 w-4 text-[#00ff88]" />}
          <span className="font-mono text-[10px] font-bold tracking-[0.2em] uppercase text-[#00ff88]">
            KILL SWITCH
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className="relative flex h-2.5 w-2.5">
            <span className={`absolute inline-flex h-full w-full rounded-full opacity-75 animate-ping ${isActive ? "bg-[#ff4444]" : "bg-[#00ff88]"}`} />
            <span className={`relative inline-flex h-2.5 w-2.5 rounded-full ${isActive ? "bg-[#ff4444]" : "bg-[#00ff88]"}`} />
          </span>
          <span className={`font-mono text-[10px] font-bold uppercase tracking-wider ${isActive ? "text-[#ff4444]" : "text-[#00ff88]"}`}>
            {isActive ? "ACTIVE — TRADING HALTED" : "INACTIVE"}
          </span>
        </div>
      </div>

      {/* Status message */}
      <div className={`rounded-lg p-3 mb-3 font-mono text-xs border ${isActive ? "bg-[#ff444408] border-[#ff444420] text-[#ff8888]" : "bg-[#00ff8808] border-[#00ff8820] text-[#88ffbb]"}`}>
        {isActive ? (
          <>
            Paper trading is <strong>HALTED</strong>.
            {ks?.reason && <> Reason: <strong>{ks.reason}</strong>.</>}
            {ks?.activated_at && <> Activated: <span className="tabular-nums">{new Date(ks.activated_at).toLocaleString()}</span>.</>}
            {" "}Manual deactivation required to resume.
          </>
        ) : (
          <>Paper trading is <strong>ACTIVE</strong>. New signals will be processed normally.</>
        )}
      </div>

      {error && !ks && (
        <div className="rounded-lg p-3 mb-3 font-mono text-xs bg-[#ff444410] text-[#ff4444]">
          Engine offline — kill switch status unavailable
        </div>
      )}

      {/* Reset result toast */}
      {resetResult && (
        <div className="rounded-lg p-3 mb-3 font-mono text-xs bg-[#00d4ff10] border border-[#00d4ff30] text-[#00d4ff]">
          {resetResult}
        </div>
      )}

      {/* Action buttons */}
      <div className="flex items-center gap-3">
        <button
          onClick={handleToggle}
          disabled={acting}
          className={`flex items-center gap-2 rounded-lg px-4 py-2 font-mono text-xs font-bold uppercase tracking-wider transition-all disabled:opacity-40 border ${
            isActive
              ? "bg-[#00ff8820] text-[#00ff88] border-[#00ff8840]"
              : "bg-[#ff444420] text-[#ff4444] border-[#ff444440]"
          }`}>
          {isActive
            ? <><ShieldCheck className="h-3.5 w-3.5" /> {acting ? "Deactivating..." : "Deactivate Kill Switch"}</>
            : <><ShieldOff className="h-3.5 w-3.5" /> {acting ? "Activating..." : "Activate Kill Switch"}</>}
        </button>

        <button
          onClick={handleReset}
          disabled={acting}
          className="flex items-center gap-2 rounded-lg px-4 py-2 font-mono text-xs font-bold uppercase tracking-wider transition-all disabled:opacity-40 bg-[#ffcc0015] text-[#ffcc00] border border-[#ffcc0030]">
          <Trash2 className="h-3.5 w-3.5" />
          {acting ? "Resetting..." : "Reset Signals"}
        </button>

        <span className="font-mono text-[9px] ml-auto text-[#444]">
          When activated: new signals blocked, scheduler paused. Manual deactivation required.
        </span>
      </div>
    </div>
  );
}


// ── Section 2b: Signal Queue with Pending / History Tabs ─────────────────────

function SignalQueuePanel() {
  const [tab, setTab] = useState<"pending" | "history">("pending");

  const { data: signals, error } = useSWR<PendingSignal[]>(
    "/paper/pending-signals",
    fetcher,
    { refreshInterval: 60_000, shouldRetryOnError: false }
  );

  const allItems: PendingSignal[] = Array.isArray(signals) ? signals : [];
  const pendingItems = allItems.filter(
    (s) => (s.status ?? "pending").toLowerCase() === "pending"
  );
  const historyItems = [...allItems].sort((a, b) => {
    const da = a.date ?? "";
    const db = b.date ?? "";
    return db.localeCompare(da);
  }).slice(0, 10);

  const displayItems = tab === "pending" ? pendingItems : historyItems;

  return (
    <div className="rounded-xl border border-[#1a1a2e] bg-[#0a0a0a] p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          {/* Tab buttons */}
          <button
            onClick={() => setTab("pending")}
            className={`font-mono text-[10px] font-bold tracking-[0.2em] uppercase px-3 py-1 rounded-lg transition-colors border ${
              tab === "pending"
                ? "bg-[#00ff8818] text-[#00ff88] border-[#00ff8830]"
                : "bg-transparent text-[#555] border-transparent"
            }`}>
            PENDING
            {pendingItems.length > 0 && (
              <span className="ml-1.5 inline-flex items-center justify-center h-4 min-w-[16px] rounded-full text-[8px] font-bold px-1 bg-[#ffcc0025] text-[#ffcc00]">
                {pendingItems.length}
              </span>
            )}
          </button>
          <button
            onClick={() => setTab("history")}
            className={`font-mono text-[10px] font-bold tracking-[0.2em] uppercase px-3 py-1 rounded-lg transition-colors border ${
              tab === "history"
                ? "bg-[#00d4ff18] text-[#00d4ff] border-[#00d4ff30]"
                : "bg-transparent text-[#555] border-transparent"
            }`}>
            HISTORY
            {allItems.length > 0 && (
              <span className="ml-1.5 inline-flex items-center justify-center h-4 min-w-[16px] rounded-full text-[8px] font-bold px-1 bg-[#00d4ff25] text-[#00d4ff]">
                {Math.min(allItems.length, 10)}
              </span>
            )}
          </button>

          <span className="font-mono text-[9px] px-1.5 py-0.5 rounded border ml-2 border-[#ffcc0033] bg-[#ffcc0010] text-[#ffcc00]">
            AUTO-REFRESH 60s
          </span>
        </div>
        {error && (
          <span className="font-mono text-[9px] text-[#ff4444]">
            Error loading signals
          </span>
        )}
      </div>

      {displayItems.length > 0 ? (
        <div className="font-mono text-xs">
          {/* Table Header */}
          <div className="grid grid-cols-8 gap-2 pb-2 mb-2 border-b border-panel-border">
            <span className="text-[10px] uppercase tracking-wider text-[#555]">Date</span>
            <span className="text-[10px] uppercase tracking-wider text-[#555]">Symbol</span>
            <span className="text-[10px] uppercase tracking-wider text-center text-[#555]">Direction</span>
            <span className="text-[10px] uppercase tracking-wider text-right text-[#555]">Entry Est.</span>
            <span className="text-[10px] uppercase tracking-wider text-right text-[#555]">Stop</span>
            <span className="text-[10px] uppercase tracking-wider text-right text-[#555]">T1</span>
            <span className="text-[10px] uppercase tracking-wider text-center text-[#555]">Regime</span>
            <span className="text-[10px] uppercase tracking-wider text-center text-[#555]">Status</span>
          </div>

          {/* Rows */}
          {displayItems.map((sig, idx) => {
            const ss = statusClasses(sig.status ?? undefined);
            const dKey = directionKey(sig.direction ?? undefined);

            return (
              <div key={idx} className="grid grid-cols-8 gap-2 py-1.5 items-center border-b border-[#111]">
                <span className="text-[#888]">{sig.date ?? "--"}</span>
                <span className="font-semibold text-[#e0e0e0]">{sig.symbol ?? "MGC"}</span>
                <span className={`text-center font-bold ${DIRECTION_TEXT_CLASS[dKey]}`}>
                  {(sig.direction ?? "--").toUpperCase()}
                </span>
                <span className="text-right tabular-nums text-[#e0e0e0]">
                  {sig.entry_price != null ? `$${sig.entry_price.toFixed(2)}` : "--"}
                </span>
                <span className="text-right tabular-nums text-[#ff4444]">
                  {sig.stop_level != null ? `$${sig.stop_level.toFixed(2)}` : "--"}
                </span>
                <span className="text-right tabular-nums text-[#00ff88]">
                  {sig.target_1 != null ? `$${sig.target_1.toFixed(2)}` : "--"}
                </span>
                <span className="text-center text-[#00d4ff]">{sig.regime ?? "--"}</span>
                <span className="text-center">
                  <span className={`inline-block px-2 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider border ${ss.bg} ${ss.border} ${ss.text}`}>
                    {sig.status ?? "PENDING"}
                  </span>
                </span>
              </div>
            );
          })}
        </div>
      ) : (
        <div className="rounded-lg p-6 text-center bg-panel-alt">
          <span className="font-mono text-xs text-[#555]">
            {tab === "pending"
              ? "No pending signals — scheduler runs 18:00 ET weekdays"
              : "No signal history yet"}
          </span>
        </div>
      )}
    </div>
  );
}


// ── Section 3: Performance Metrics ───────────────────────────────────────────

function PerformanceMetricsPanel() {
  // Kill switch + monthly breakdown still from the raw endpoint (legit data)
  const { data: perf, error: perfError } = useSWR<MGCPerformanceResponse>(
    "/paper/mgc-performance",
    fetcher,
    { refreshInterval: 30_000, shouldRetryOnError: false }
  );

  // Honest deduped trade record — source of truth for aggregate metrics
  const [honest, setHonest] = useState<HonestTradeSet | null>(null);
  const [honestError, setHonestError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchHonestTrades()
      .then((set) => {
        if (!cancelled) setHonest(set);
      })
      .catch((e) => {
        if (!cancelled)
          setHonestError(e instanceof Error ? e.message : "honest record unavailable");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Filter to MGC only — the panel is explicitly MGC-scoped
  const mgcTrades = honest ? honest.trades.filter((t) => t.symbol === "MGC") : null;

  // Derive MGC-scoped metrics from the honest subset
  const mgcNet = mgcTrades ? mgcTrades.reduce((s, t) => s + t.pnl, 0) : null;
  const mgcWins = mgcTrades ? mgcTrades.filter((t) => t.pnl > 0).length : null;
  const mgcCount = mgcTrades ? mgcTrades.length : null;
  const mgcWr = mgcCount != null && mgcCount > 0 && mgcWins != null ? mgcWins / mgcCount : null;
  const mgcGrossWin = mgcTrades
    ? mgcTrades.filter((t) => t.pnl > 0).reduce((s, t) => s + t.pnl, 0)
    : null;
  const mgcGrossLoss = mgcTrades
    ? Math.abs(mgcTrades.filter((t) => t.pnl < 0).reduce((s, t) => s + t.pnl, 0))
    : null;
  const mgcPf =
    mgcGrossLoss != null && mgcGrossLoss > 0 && mgcGrossWin != null
      ? mgcGrossWin / mgcGrossLoss
      : null;

  // Max drawdown from equity curve on the MGC subset
  const mgcCurve = mgcTrades ? equityCurve(mgcTrades) : null;
  const mgcMaxDd =
    mgcCurve && mgcCurve.length > 0
      ? Math.abs(Math.min(...mgcCurve.map((p) => p.drawdown)))
      : null;

  // Derive peak for percentage expression
  const mgcPeak =
    mgcCurve && mgcCurve.length > 0
      ? Math.max(...mgcCurve.map((p) => p.equity), 0)
      : null;
  const mgcMaxDdPct =
    mgcMaxDd != null && mgcPeak != null && mgcPeak > 0
      ? mgcMaxDd / mgcPeak
      : null;

  const caveat = honest
    ? `MGC subset · ${dedupCaveat({ ...honest, trades: mgcTrades ?? [] })}`
    : null;

  const killActive = perf?.kill_switch_active ?? false;

  const anyError = honestError ?? (perfError && !perf ? "Engine offline" : null);

  return (
    <div className="rounded-xl border border-[#1a1a2e] bg-[#0a0a0a] p-4">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <span className="font-mono text-[10px] font-bold tracking-[0.2em] uppercase text-[#00ff88]">
            PERFORMANCE METRICS
          </span>
          <span className="font-mono text-[9px] px-1.5 py-0.5 rounded border border-[#00d4ff33] bg-[#00d4ff10] text-[#00d4ff]">
            MGC 1D
          </span>
          <span className="font-mono text-[9px] px-1.5 py-0.5 rounded border border-[#88888833] bg-[#88888810] text-[#888]">
            DEDUPED
          </span>
        </div>
        {/* Kill Switch Status — from raw endpoint (legit, not over-counted) */}
        <span className={`font-mono text-[9px] px-2 py-0.5 rounded border font-bold ${
          killActive
            ? "border-[#ff444440] bg-[#ff444415] text-[#ff4444]"
            : "border-[#00ff8840] bg-[#00ff8815] text-[#00ff88]"
        }`}>
          KILL SWITCH: {killActive ? "TRIGGERED" : "INACTIVE"}
        </span>
      </div>

      {anyError && (
        <div className="rounded-lg p-3 mb-3 font-mono text-xs bg-[#ff444410] text-[#ff4444]">
          {anyError} — performance data unavailable
        </div>
      )}

      {/* Metrics Grid — honest deduped values (MGC subset) */}
      <div className="grid grid-cols-5 gap-2 mb-4">
        <MetricCard
          label="Total Trades"
          value={mgcCount != null ? String(mgcCount) : "--"}
        />
        <MetricCard
          label="Win Rate"
          value={mgcWr != null ? `${(mgcWr * 100).toFixed(1)}%` : "--"}
          colorClass={mgcWr != null && mgcWr >= 0.5 ? "text-[#00ff88]" : "text-[#ffcc00]"}
        />
        <MetricCard
          label="Profit Factor"
          value={mgcPf != null ? mgcPf.toFixed(2) : "--"}
          colorClass={pfColorClass(mgcPf)}
        />
        <MetricCard
          label="Net P&L"
          value={mgcNet != null ? `$${mgcNet.toFixed(2)}` : "--"}
          colorClass={mgcNet != null ? (mgcNet >= 0 ? "text-[#00ff88]" : "text-[#ff4444]") : undefined}
        />
        <MetricCard
          label="Max Drawdown"
          value={
            mgcMaxDdPct != null
              ? `${(mgcMaxDdPct * 100).toFixed(1)}%`
              : mgcMaxDd != null
              ? `$${mgcMaxDd.toFixed(0)}`
              : "--"
          }
          colorClass={
            mgcMaxDdPct != null && mgcMaxDdPct > 0.05
              ? "text-[#ff4444]"
              : "text-[#ffcc00]"
          }
        />
      </div>

      {/* Dedup caveat */}
      {caveat && (
        <p className="font-mono text-[9px] mb-3 text-[#666]">
          {caveat}
          {honest && honest.caveats.length > 0 && " · " + honest.caveats.join(" · ")}
        </p>
      )}

      {/* Monthly Breakdown — from raw endpoint (structural, not aggregate metrics) */}
      {perf?.monthly_breakdown && perf.monthly_breakdown.length > 0 && (
        <div className="font-mono text-xs">
          <div className="mb-2">
            <span className="text-[10px] uppercase tracking-wider font-bold text-[#555]">
              Monthly Breakdown
            </span>
          </div>
          <div className="grid grid-cols-4 gap-2 pb-2 mb-2 border-b border-panel-border">
            <span className="text-[9px] uppercase tracking-wider text-[#555]">Month</span>
            <span className="text-[9px] uppercase tracking-wider text-right text-[#555]">Trades</span>
            <span className="text-[9px] uppercase tracking-wider text-right text-[#555]">P&L</span>
            <span className="text-[9px] uppercase tracking-wider text-right text-[#555]">Win Rate</span>
          </div>
          {perf.monthly_breakdown.map((m, idx) => (
            <div key={idx} className="grid grid-cols-4 gap-2 py-1 border-b border-[#111]">
              <span className="text-[#888]">{m.month}</span>
              <span className="text-right tabular-nums text-[#e0e0e0]">{m.trades}</span>
              <span className={`text-right tabular-nums font-bold ${m.pnl >= 0 ? "text-[#00ff88]" : "text-[#ff4444]"}`}>
                ${m.pnl.toFixed(2)}
              </span>
              <span className="text-right tabular-nums text-[#e0e0e0]">
                {m.win_rate != null ? `${(m.win_rate * 100).toFixed(0)}%` : "--"}
              </span>
            </div>
          ))}
        </div>
      )}

      {!honest && !anyError && (
        <div className="rounded-lg p-6 text-center bg-panel-alt">
          <span className="font-mono text-xs text-[#555]">
            Loading performance metrics...
          </span>
        </div>
      )}
    </div>
  );
}

function MetricCard({ label, value, colorClass }: { label: string; value: string; colorClass?: string }) {
  return (
    <div className="rounded-lg p-3 text-center bg-panel-alt border border-panel-border">
      <div className="font-mono text-[9px] uppercase tracking-wider mb-1.5 text-[#555]">{label}</div>
      <div className={`font-mono text-base font-bold tabular-nums ${colorClass ?? "text-[#e0e0e0]"}`}>{value}</div>
    </div>
  );
}


// ── Section 4: Trade Logger ──────────────────────────────────────────────────

function TradeLoggerPanel() {
  const [form, setForm] = useState<PaperTradePayload>({
    entry_date: new Date().toISOString().slice(0, 10),
    exit_date: "",
    direction: "LONG",
    entry_price: 0,
    exit_price: 0,
    contracts: 1,
  });
  const [submitting, setSubmitting] = useState(false);
  const [toast, setToast] = useState<{ message: string; type: "success" | "error" } | null>(null);

  const handleSubmit = useCallback(async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setToast(null);
    try {
      await postEngine("/paper/mgc-log-trade", form);
      setToast({ message: "Trade logged successfully", type: "success" });
      // Reset prices
      setForm(prev => ({ ...prev, entry_price: 0, exit_price: 0 }));
      // Clear toast after 4s
      setTimeout(() => setToast(null), 4000);
    } catch (err) {
      setToast({ message: err instanceof Error ? err.message : "Failed to log trade", type: "error" });
      setTimeout(() => setToast(null), 5000);
    } finally {
      setSubmitting(false);
    }
  }, [form]);

  const updateField = (field: keyof PaperTradePayload, value: string | number) => {
    setForm(prev => ({ ...prev, [field]: value }));
  };

  return (
    <div className="rounded-xl border border-[#1a1a2e] bg-[#0a0a0a] p-4">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <span className="font-mono text-[10px] font-bold tracking-[0.2em] uppercase text-[#00ff88]">
            TRADE LOGGER
          </span>
          <span className="font-mono text-[9px] px-1.5 py-0.5 rounded border border-[#ffcc0033] bg-[#ffcc0010] text-[#ffcc00]">
            MANUAL ENTRY
          </span>
        </div>
      </div>

      {/* Toast */}
      {toast && (
        <div className={`rounded-lg p-3 mb-3 font-mono text-xs flex items-center gap-2 transition-all border ${
          toast.type === "success"
            ? "bg-[#00ff8815] border-[#00ff8830] text-[#00ff88]"
            : "bg-[#ff444415] border-[#ff444430] text-[#ff4444]"
        }`}>
          {toast.type === "success" ? "OK" : "ERR"} — {toast.message}
        </div>
      )}

      <form onSubmit={handleSubmit}>
        <div className="grid grid-cols-6 gap-3 mb-4">
          {/* Entry Date */}
          <div>
            <label className="block font-mono text-[9px] uppercase tracking-wider mb-1 text-[#555]">
              Entry Date
            </label>
            <input
              type="date"
              value={form.entry_date}
              onChange={(e) => updateField("entry_date", e.target.value)}
              className="w-full rounded-lg border px-3 py-2 font-mono text-xs focus:outline-none focus:ring-1 bg-panel-alt border-panel-border text-[#e0e0e0]"
              required
            />
          </div>

          {/* Exit Date */}
          <div>
            <label className="block font-mono text-[9px] uppercase tracking-wider mb-1 text-[#555]">
              Exit Date
            </label>
            <input
              type="date"
              value={form.exit_date}
              onChange={(e) => updateField("exit_date", e.target.value)}
              className="w-full rounded-lg border px-3 py-2 font-mono text-xs focus:outline-none focus:ring-1 bg-panel-alt border-panel-border text-[#e0e0e0]"
            />
          </div>

          {/* Direction */}
          <div>
            <label className="block font-mono text-[9px] uppercase tracking-wider mb-1 text-[#555]">
              Direction
            </label>
            <select
              value={form.direction}
              onChange={(e) => updateField("direction", e.target.value)}
              className="w-full rounded-lg border px-3 py-2 font-mono text-xs focus:outline-none focus:ring-1 bg-panel-alt border-panel-border text-[#e0e0e0]"
            >
              <option value="LONG">LONG</option>
              <option value="SHORT">SHORT</option>
            </select>
          </div>

          {/* Entry Price */}
          <div>
            <label className="block font-mono text-[9px] uppercase tracking-wider mb-1 text-[#555]">
              Entry Price
            </label>
            <input
              type="number"
              step="0.01"
              value={form.entry_price || ""}
              onChange={(e) => updateField("entry_price", parseFloat(e.target.value) || 0)}
              placeholder="0.00"
              className="w-full rounded-lg border px-3 py-2 font-mono text-xs focus:outline-none focus:ring-1 bg-panel-alt border-panel-border text-[#e0e0e0]"
              required
            />
          </div>

          {/* Exit Price */}
          <div>
            <label className="block font-mono text-[9px] uppercase tracking-wider mb-1 text-[#555]">
              Exit Price
            </label>
            <input
              type="number"
              step="0.01"
              value={form.exit_price || ""}
              onChange={(e) => updateField("exit_price", parseFloat(e.target.value) || 0)}
              placeholder="0.00"
              className="w-full rounded-lg border px-3 py-2 font-mono text-xs focus:outline-none focus:ring-1 bg-panel-alt border-panel-border text-[#e0e0e0]"
            />
          </div>
        </div>

        {/* Action buttons */}
        <div className="flex gap-3 mt-4">
          <button
            onClick={handleSubmit}
            disabled={submitting}
            className="flex-1 rounded-lg px-4 py-2 font-mono text-xs font-semibold text-white transition-colors focus:outline-none focus:ring-2 focus:ring-offset-2 bg-[#00ff88] disabled:cursor-not-allowed disabled:opacity-60"
          >
            {submitting ? "Processing…" : "Record Trade"}
          </button>
          <button
            type="button"
            onClick={() => setForm({ entry_date: "", exit_date: "", direction: "BUY", entry_price: 0, exit_price: 0, contracts: 1 })}
            disabled={submitting}
            className="flex-1 rounded-lg border px-4 py-2 font-mono text-xs font-semibold transition-colors border-[#555] text-[#aaa] disabled:cursor-not-allowed disabled:opacity-60"
          >
            Reset
          </button>
        </div>
      </form>
    </div>
  );
}
