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
  DEFAULT_STARTING_CAPITAL,
  type HonestTradeSet,
} from "@/lib/honestTrades";
import { OpenPositionsWidget } from "@/components/OpenPositionsWidget";
import { CircuitBreakerWidget } from "@/components/CircuitBreakerWidget";
import { RecentSignalsWidget } from "@/components/RecentSignalsWidget";
import { MarketRegimeWidget } from "@/components/MarketRegimeWidget";
import { RecentDecisionsWidget } from "@/components/RecentDecisionsWidget";
import { SessionSummaryWidget } from "@/components/SessionSummaryWidget";
import { TodaySummaryWidget } from "@/components/TodaySummaryWidget";
import { PositionSizingWidget } from "@/components/PositionSizingWidget";
import { SignalQueueWidget } from "@/components/SignalQueueWidget";
<<<<<<< HEAD
=======
import { ActionableBoardWidget } from "@/components/ActionableBoardWidget";
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
import { PaperApprovedValidationWidget } from "@/components/PaperApprovedValidationWidget";
import ValidationCheckpointWidget from "@/components/ValidationCheckpointWidget";
import { WidgetErrorBoundary } from "@/components/WidgetErrorBoundary";

function fetcher<T = unknown>(url: string): Promise<T> {
  return fetchEngine<T>(url);
}

type EngineHealthPayload = { status?: string };

// ── Main Page ────────────────────────────────────────────────────────────────
export default function PaperTradingPage() {
  const { data: health, error: healthError, isLoading: healthLoading } = useSWR<EngineHealthPayload>(
    "/health",
    fetcher,
    { refreshInterval: 30_000, revalidateOnFocus: true, shouldRetryOnError: false }
  );

  // Same live source that gates MGC's ACTIVE/HALTED badge on /command-center —
  // drives the suspension banner below instead of a static hardcoded WFE value.
  const { data: paperStatus, error: paperStatusError } = useSWR<
    Record<string, { status?: string; wfe?: number; reason?: string }>
  >("/backtest/paper-status", fetcher, { refreshInterval: 120_000, shouldRetryOnError: false });
  const mgcStatus = paperStatus?.["MGC_1d"];
  const mgcHalted = (mgcStatus?.status || "").toUpperCase() !== "ACTIVE";

  let engineHealthLabel = "ENGINE …";
  let engineHealthStyle: React.CSSProperties = {
    borderColor: "#88888844",
    backgroundColor: "#88888810",
    color: "#888888",
  };
  if (healthError) {
    engineHealthLabel = "ENGINE offline";
    engineHealthStyle = {
      borderColor: "#ff444466",
      backgroundColor: "#ff444410",
      color: "#ff6666",
    };
  } else if (!healthLoading && health) {
    if (health.status === "ok") {
      engineHealthLabel = "ENGINE ok";
      engineHealthStyle = {
        borderColor: "#00aaff44",
        backgroundColor: "#00aaff12",
        color: "#00ccff",
      };
    } else {
      engineHealthLabel = `ENGINE ${health.status ?? "?"}`;
      engineHealthStyle = {
        borderColor: "#ffaa0044",
        backgroundColor: "#ffaa0010",
        color: "#ffcc66",
      };
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
                MGC Daily Paper Trading{mgcHalted ? " — SUSPENDED" : ""}
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
              className="font-mono text-[9px] px-1.5 py-0.5 rounded border"
              style={engineHealthStyle}
              title="GET /health — same check as WORKING_TODAY smoke"
            >
              {engineHealthLabel}
            </span>
            <span className="font-mono text-[9px] px-1.5 py-0.5 rounded border"
              style={{ borderColor: "#00ff8833", backgroundColor: "#00ff8810", color: "#00ff88" }}>
              PAPER MODE
            </span>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1920px] 2xl:max-w-[2400px] px-6 py-4 space-y-4">
        {/* Halt banner — driven by the live /backtest/paper-status MGC_1d row
            (the same source that gates the MGC ACTIVE/HALTED badge on
            /command-center), not a hardcoded WFE value. */}
        {mgcHalted && (
          <div className="rounded-xl p-4 font-mono"
            style={{ backgroundColor: "#ff444410", border: "1px solid #ff444440" }}>
            <div className="flex items-start gap-3">
              <span className="text-[11px] font-bold tracking-wider" style={{ color: "#ff4444" }}>
                PAPER TRADING SUSPENDED
              </span>
              <span className="text-[10px]" style={{ color: "#ff8888" }}>
                {paperStatusError
                  ? "Could not reach /backtest/paper-status to confirm trading status."
                  : mgcStatus
                    ? `MGC 1d — ${mgcStatus.reason || `status="${mgcStatus.status}"`}${
                        typeof mgcStatus.wfe === "number" ? ` (wfe=${mgcStatus.wfe})` : ""
                      }.`
                    : "MGC 1d status unavailable from the engine."}
              </span>
            </div>
          </div>
        )}

        {/* Open Positions — safety-critical, first widget at top of page */}
        <WidgetErrorBoundary name="Open Positions">
          <OpenPositionsWidget />
        </WidgetErrorBoundary>

<<<<<<< HEAD
=======
        {/* Trade Recommendations — entry/stop/T1 cards from the pipeline
            actionable board (the amo-arbitrage style surface). Shows live
            candidates + recently-resolved rows with target/stops once the
            autonomous loop is armed. */}
        <WidgetErrorBoundary name="Trade Recommendations">
          <ActionableBoardWidget />
        </WidgetErrorBoundary>

>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
        {/* MCL / MNQ validation gates vs project thresholds (SQLite closed trades) */}
        <WidgetErrorBoundary name="Paper Approved Validation">
          <PaperApprovedValidationWidget />
        </WidgetErrorBoundary>

        {/* Overall validation checkpoint (30-day window progress) */}
        <WidgetErrorBoundary name="Validation Checkpoint">
          <ValidationCheckpointWidget />
        </WidgetErrorBoundary>

        {/* Risk status / circuit breaker — sole panel for /safety/circuit-breakers
            (was previously duplicated with RiskStatusWidget, which read the same
            endpoint; RiskStatusWidget mount removed as redundant, T3-22). */}
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
<<<<<<< HEAD
            <LiveSignalPanel />
          </div>
          <div className="col-span-12 lg:col-span-6">
            <PerformanceMetricsPanel />
=======
            <WidgetErrorBoundary name="Live Signal">
              <LiveSignalPanel />
            </WidgetErrorBoundary>
          </div>
          <div className="col-span-12 lg:col-span-6">
            <WidgetErrorBoundary name="Performance Metrics">
              <PerformanceMetricsPanel />
            </WidgetErrorBoundary>
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
          </div>
        </div>

        {/* Kill Switch + Reset Controls */}
<<<<<<< HEAD
        <KillSwitchPanel />

        {/* Middle: Pending Signals Queue with History Tab */}
        <SignalQueuePanel />

        {/* Bottom: Trade Logger */}
        <TradeLoggerPanel />
=======
        <WidgetErrorBoundary name="Kill Switch">
          <KillSwitchPanel />
        </WidgetErrorBoundary>

        {/* Middle: Pending Signals Queue with History Tab */}
        <WidgetErrorBoundary name="Pending Signals Queue">
          <SignalQueuePanel />
        </WidgetErrorBoundary>

        {/* Bottom: Trade Logger */}
        <WidgetErrorBoundary name="Trade Logger">
          <TradeLoggerPanel />
        </WidgetErrorBoundary>
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2

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

  const directionColor = (dir: string | undefined) => {
    if (!dir) return "#ffcc00";
    const d = dir.toUpperCase();
    if (d === "LONG" || d === "BUY") return "#00ff88";
    if (d === "SHORT" || d === "SELL") return "#ff4444";
    return "#ffcc00";
  };

  const DirectionIcon = ({ direction }: { direction: string | undefined }) => {
    if (!direction) return <Minus className="h-5 w-5" style={{ color: "#ffcc00" }} />;
    const d = direction.toUpperCase();
    if (d === "LONG" || d === "BUY") return <TrendingUp className="h-5 w-5" style={{ color: "#00ff88" }} />;
    if (d === "SHORT" || d === "SELL") return <TrendingDown className="h-5 w-5" style={{ color: "#ff4444" }} />;
    return <Minus className="h-5 w-5" style={{ color: "#ffcc00" }} />;
  };

  return (
    <div className="rounded-xl border border-[#1a1a2e] bg-[#0a0a0a] p-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <span className="font-mono text-[10px] font-bold tracking-[0.2em] uppercase" style={{ color: "#00ff88" }}>
            MGC DAILY SIGNAL
          </span>
          <span className="font-mono text-[9px] px-1.5 py-0.5 rounded border"
            style={{ borderColor: "#00d4ff33", backgroundColor: "#00d4ff10", color: "#00d4ff" }}>
            GC=F
          </span>
        </div>
        <button
          onClick={fetchSignal}
          disabled={loading}
          className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-mono font-semibold transition-colors disabled:opacity-40"
          style={{ backgroundColor: "#00ff8820", color: "#00ff88", border: "1px solid #00ff8840" }}
        >
          <RefreshCw className={`h-3 w-3 ${loading ? "animate-spin" : ""}`} />
          {loading ? "Fetching..." : "Fetch Signal"}
        </button>
      </div>

      {/* Error State */}
      {error && (
        <div className="rounded-lg p-3 mb-3 font-mono text-xs flex items-center gap-2"
          style={{ backgroundColor: "#ff444415", border: "1px solid #ff444430", color: "#ff4444" }}>
          <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
          {error}
        </div>
      )}

      {/* Signal Content */}
      {signal ? (
        <div className="space-y-3">
          {/* Direction Badge */}
          <div className="flex items-center gap-3 rounded-lg p-3"
            style={{ backgroundColor: `${directionColor(signal.direction ?? undefined)}08`, border: `1px solid ${directionColor(signal.direction ?? undefined)}25` }}>
            <DirectionIcon direction={signal.direction ?? undefined} />
            <span className="font-mono text-2xl font-bold tracking-wider"
              style={{ color: directionColor(signal.direction ?? undefined) }}>
              {(signal.direction ?? "FLAT").toUpperCase()}
            </span>
          </div>

          {/* Price Levels Grid */}
          <div className="grid grid-cols-2 gap-2">
            <SignalStat label="Entry Price" value={signal.entry_price != null ? `$${signal.entry_price.toFixed(2)}` : "--"} />
            <SignalStat label="Stop Level" value={signal.stop_level != null ? `$${signal.stop_level.toFixed(2)}` : "--"} color="#ff4444" />
            <SignalStat label="Target 1" value={signal.target_1 != null ? `$${signal.target_1.toFixed(2)}` : "--"} color="#00ff88" />
            <SignalStat label="Regime" value={signal.regime ?? "--"} color="#00d4ff" />
          </div>

          {/* Confidence / Extra Info */}
          {signal.confidence != null && (
            <div className="flex items-center gap-2 pt-1">
              <span className="font-mono text-[10px] uppercase tracking-wider" style={{ color: "#555" }}>Confidence</span>
              <span className="font-mono text-xs font-bold tabular-nums" style={{ color: "#e0e0e0" }}>
                {(signal.confidence * 100).toFixed(0)}%
              </span>
              <div className="flex-1 h-1 rounded-full overflow-hidden" style={{ backgroundColor: "#1a1a2e" }}>
                <div className="h-full rounded-full transition-all"
                  style={{
                    width: `${(signal.confidence * 100)}%`,
                    backgroundColor: signal.confidence >= 0.7 ? "#00ff88" : signal.confidence >= 0.4 ? "#ffcc00" : "#ff4444"
                  }} />
              </div>
            </div>
          )}

          {/* Last Fetch */}
          {lastFetch && (
            <div className="text-right">
              <span className="font-mono text-[9px]" style={{ color: "#444" }}>
                Last fetched: {lastFetch}
              </span>
            </div>
          )}
        </div>
      ) : (
        <div className="rounded-lg p-8 text-center" style={{ backgroundColor: "#0d0d1a" }}>
          <span className="font-mono text-xs" style={{ color: "#555" }}>
            Click "Fetch Signal" to get the latest MGC daily signal
          </span>
        </div>
      )}
    </div>
  );
}

function SignalStat({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="rounded-lg p-2.5" style={{ backgroundColor: "#0d0d1a", border: "1px solid #1a1a2e" }}>
      <div className="font-mono text-[9px] uppercase tracking-wider mb-1" style={{ color: "#555" }}>{label}</div>
      <div className="font-mono text-sm font-bold tabular-nums" style={{ color: color ?? "#e0e0e0" }}>{value}</div>
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
    <div className="rounded-xl border bg-[#0a0a0a] p-4"
      style={{ borderColor: isActive ? "#ff444440" : "#1a1a2e" }}>
      {/* Header row */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          {isActive
            ? <ShieldOff className="h-4 w-4" style={{ color: "#ff4444" }} />
            : <ShieldCheck className="h-4 w-4" style={{ color: "#00ff88" }} />}
          <span className="font-mono text-[10px] font-bold tracking-[0.2em] uppercase" style={{ color: "#00ff88" }}>
            KILL SWITCH
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className="relative flex h-2.5 w-2.5">
            <span className="absolute inline-flex h-full w-full rounded-full opacity-75 animate-ping"
              style={{ backgroundColor: isActive ? "#ff4444" : "#00ff88" }} />
            <span className="relative inline-flex h-2.5 w-2.5 rounded-full"
              style={{ backgroundColor: isActive ? "#ff4444" : "#00ff88" }} />
          </span>
          <span className="font-mono text-[10px] font-bold uppercase tracking-wider"
            style={{ color: isActive ? "#ff4444" : "#00ff88" }}>
            {isActive ? "ACTIVE — TRADING HALTED" : "INACTIVE"}
          </span>
        </div>
      </div>

      {/* Status message */}
      <div className="rounded-lg p-3 mb-3 font-mono text-xs"
        style={{
          backgroundColor: isActive ? "#ff444408" : "#00ff8808",
          border: `1px solid ${isActive ? "#ff444420" : "#00ff8820"}`,
          color: isActive ? "#ff8888" : "#88ffbb",
        }}>
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
        <div className="rounded-lg p-3 mb-3 font-mono text-xs"
          style={{ backgroundColor: "#ff444410", color: "#ff4444" }}>
          Engine offline — kill switch status unavailable
        </div>
      )}

      {/* Reset result toast */}
      {resetResult && (
        <div className="rounded-lg p-3 mb-3 font-mono text-xs"
          style={{ backgroundColor: "#00d4ff10", border: "1px solid #00d4ff30", color: "#00d4ff" }}>
          {resetResult}
        </div>
      )}

      {/* Action buttons */}
      <div className="flex items-center gap-3">
        <button
          onClick={handleToggle}
          disabled={acting}
          className="flex items-center gap-2 rounded-lg px-4 py-2 font-mono text-xs font-bold uppercase tracking-wider transition-all disabled:opacity-40"
          style={isActive ? {
            backgroundColor: "#00ff8820", color: "#00ff88", border: "1px solid #00ff8840",
          } : {
            backgroundColor: "#ff444420", color: "#ff4444", border: "1px solid #ff444440",
          }}>
          {isActive
            ? <><ShieldCheck className="h-3.5 w-3.5" /> {acting ? "Deactivating..." : "Deactivate Kill Switch"}</>
            : <><ShieldOff className="h-3.5 w-3.5" /> {acting ? "Activating..." : "Activate Kill Switch"}</>}
        </button>

        <button
          onClick={handleReset}
          disabled={acting}
          className="flex items-center gap-2 rounded-lg px-4 py-2 font-mono text-xs font-bold uppercase tracking-wider transition-all disabled:opacity-40"
          style={{ backgroundColor: "#ffcc0015", color: "#ffcc00", border: "1px solid #ffcc0030" }}>
          <Trash2 className="h-3.5 w-3.5" />
          {acting ? "Resetting..." : "Reset Signals"}
        </button>

        <span className="font-mono text-[9px] ml-auto" style={{ color: "#444" }}>
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

  const statusStyle = (status: string | undefined) => {
    const s = (status ?? "pending").toLowerCase();
    if (s === "entered" || s === "filled") return { bg: "#00ff8815", border: "#00ff8830", color: "#00ff88" };
    if (s === "expired" || s === "cancelled") return { bg: "#55555515", border: "#55555530", color: "#555" };
    return { bg: "#ffcc0015", border: "#ffcc0030", color: "#ffcc00" };
  };

  return (
    <div className="rounded-xl border border-[#1a1a2e] bg-[#0a0a0a] p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          {/* Tab buttons */}
          <button
            onClick={() => setTab("pending")}
            className="font-mono text-[10px] font-bold tracking-[0.2em] uppercase px-3 py-1 rounded-lg transition-colors"
            style={tab === "pending" ? {
              backgroundColor: "#00ff8818", color: "#00ff88", border: "1px solid #00ff8830",
            } : {
              backgroundColor: "transparent", color: "#555", border: "1px solid transparent",
            }}>
            PENDING
            {pendingItems.length > 0 && (
              <span className="ml-1.5 inline-flex items-center justify-center h-4 min-w-[16px] rounded-full text-[8px] font-bold px-1"
                style={{ backgroundColor: "#ffcc0025", color: "#ffcc00" }}>
                {pendingItems.length}
              </span>
            )}
          </button>
          <button
            onClick={() => setTab("history")}
            className="font-mono text-[10px] font-bold tracking-[0.2em] uppercase px-3 py-1 rounded-lg transition-colors"
            style={tab === "history" ? {
              backgroundColor: "#00d4ff18", color: "#00d4ff", border: "1px solid #00d4ff30",
            } : {
              backgroundColor: "transparent", color: "#555", border: "1px solid transparent",
            }}>
            HISTORY
            {allItems.length > 0 && (
              <span className="ml-1.5 inline-flex items-center justify-center h-4 min-w-[16px] rounded-full text-[8px] font-bold px-1"
                style={{ backgroundColor: "#00d4ff25", color: "#00d4ff" }}>
                {Math.min(allItems.length, 10)}
              </span>
            )}
          </button>

          <span className="font-mono text-[9px] px-1.5 py-0.5 rounded border ml-2"
            style={{ borderColor: "#ffcc0033", backgroundColor: "#ffcc0010", color: "#ffcc00" }}>
            AUTO-REFRESH 60s
          </span>
        </div>
        {error && (
          <span className="font-mono text-[9px]" style={{ color: "#ff4444" }}>
            Error loading signals
          </span>
        )}
      </div>

      {displayItems.length > 0 ? (
        <div className="font-mono text-xs">
          {/* Table Header */}
          <div className="grid grid-cols-8 gap-2 pb-2 mb-2" style={{ borderBottom: "1px solid #1a1a2e" }}>
            <span className="text-[10px] uppercase tracking-wider" style={{ color: "#555" }}>Date</span>
            <span className="text-[10px] uppercase tracking-wider" style={{ color: "#555" }}>Symbol</span>
            <span className="text-[10px] uppercase tracking-wider text-center" style={{ color: "#555" }}>Direction</span>
            <span className="text-[10px] uppercase tracking-wider text-right" style={{ color: "#555" }}>Entry Est.</span>
            <span className="text-[10px] uppercase tracking-wider text-right" style={{ color: "#555" }}>Stop</span>
            <span className="text-[10px] uppercase tracking-wider text-right" style={{ color: "#555" }}>T1</span>
            <span className="text-[10px] uppercase tracking-wider text-center" style={{ color: "#555" }}>Regime</span>
            <span className="text-[10px] uppercase tracking-wider text-center" style={{ color: "#555" }}>Status</span>
          </div>

          {/* Rows */}
          {displayItems.map((sig, idx) => {
            const ss = statusStyle(sig.status ?? undefined);
            const dirColor = (sig.direction ?? "").toUpperCase() === "LONG" ? "#00ff88"
              : (sig.direction ?? "").toUpperCase() === "SHORT" ? "#ff4444" : "#ffcc00";

            return (
              <div key={idx} className="grid grid-cols-8 gap-2 py-1.5 items-center"
                style={{ borderBottom: "1px solid #111" }}>
                <span style={{ color: "#888" }}>{sig.date ?? "--"}</span>
                <span className="font-semibold" style={{ color: "#e0e0e0" }}>{sig.symbol ?? "MGC"}</span>
                <span className="text-center font-bold" style={{ color: dirColor }}>
                  {(sig.direction ?? "--").toUpperCase()}
                </span>
                <span className="text-right tabular-nums" style={{ color: "#e0e0e0" }}>
                  {sig.entry_price != null ? `$${sig.entry_price.toFixed(2)}` : "--"}
                </span>
                <span className="text-right tabular-nums" style={{ color: "#ff4444" }}>
                  {sig.stop_level != null ? `$${sig.stop_level.toFixed(2)}` : "--"}
                </span>
                <span className="text-right tabular-nums" style={{ color: "#00ff88" }}>
                  {sig.target_1 != null ? `$${sig.target_1.toFixed(2)}` : "--"}
                </span>
                <span className="text-center" style={{ color: "#00d4ff" }}>{sig.regime ?? "--"}</span>
                <span className="text-center">
                  <span className="inline-block px-2 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider"
                    style={{ backgroundColor: ss.bg, border: `1px solid ${ss.border}`, color: ss.color }}>
                    {sig.status ?? "PENDING"}
                  </span>
                </span>
              </div>
            );
          })}
        </div>
      ) : (
        <div className="rounded-lg p-6 text-center" style={{ backgroundColor: "#0d0d1a" }}>
          <span className="font-mono text-xs" style={{ color: "#555" }}>
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

  // Derive peak for percentage expression. Floored at DEFAULT_STARTING_CAPITAL
  // so a tiny-but-positive peak (e.g. one small early MGC win) can't divide a
  // later large-dollar loss into an absurd percentage -- denominate against
  // account starting capital instead, same fix as lib/honestTrades.ts's
  // maxDrawdownPct().
  const mgcPeak =
    mgcCurve && mgcCurve.length > 0
      ? Math.max(...mgcCurve.map((p) => p.equity), 0, DEFAULT_STARTING_CAPITAL)
      : null;
  const mgcMaxDdPct =
    mgcMaxDd != null && mgcPeak != null && mgcPeak > 0
      ? mgcMaxDd / mgcPeak
      : null;

  const caveat = honest
    ? `MGC subset · ${dedupCaveat({ ...honest, trades: mgcTrades ?? [] })}`
    : null;

  const pfColor = (pf: number | null | undefined) => {
    if (pf == null) return "#555";
    if (pf >= 1.5) return "#00ff88";
    if (pf >= 1.0) return "#ffcc00";
    return "#ff4444";
  };

  const killActive = perf?.kill_switch_active ?? false;

  const anyError = honestError ?? (perfError && !perf ? "Engine offline" : null);

  return (
    <div className="rounded-xl border border-[#1a1a2e] bg-[#0a0a0a] p-4">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <span className="font-mono text-[10px] font-bold tracking-[0.2em] uppercase" style={{ color: "#00ff88" }}>
            PERFORMANCE METRICS
          </span>
          <span className="font-mono text-[9px] px-1.5 py-0.5 rounded border"
            style={{ borderColor: "#00d4ff33", backgroundColor: "#00d4ff10", color: "#00d4ff" }}>
            MGC 1D
          </span>
          <span className="font-mono text-[9px] px-1.5 py-0.5 rounded border"
            style={{ borderColor: "#88888833", backgroundColor: "#88888810", color: "#888" }}>
            DEDUPED
          </span>
        </div>
        {/* Kill Switch Status — from raw endpoint (legit, not over-counted) */}
        <span className="font-mono text-[9px] px-2 py-0.5 rounded border font-bold"
          style={{
            borderColor: killActive ? "#ff444440" : "#00ff8840",
            backgroundColor: killActive ? "#ff444415" : "#00ff8815",
            color: killActive ? "#ff4444" : "#00ff88",
          }}>
          KILL SWITCH: {killActive ? "TRIGGERED" : "INACTIVE"}
        </span>
      </div>

      {anyError && (
        <div className="rounded-lg p-3 mb-3 font-mono text-xs" style={{ backgroundColor: "#ff444410", color: "#ff4444" }}>
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
          color={mgcWr != null && mgcWr >= 0.5 ? "#00ff88" : "#ffcc00"}
        />
        <MetricCard
          label="Profit Factor"
          value={mgcPf != null ? mgcPf.toFixed(2) : "--"}
          color={pfColor(mgcPf)}
        />
        <MetricCard
          label="Net P&L"
          value={mgcNet != null ? `$${mgcNet.toFixed(2)}` : "--"}
          color={mgcNet != null ? (mgcNet >= 0 ? "#00ff88" : "#ff4444") : undefined}
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
          color={
            mgcMaxDdPct != null && mgcMaxDdPct > 0.05
              ? "#ff4444"
              : "#ffcc00"
          }
        />
      </div>

      {/* Dedup caveat */}
      {caveat && (
        <p className="font-mono text-[9px] mb-3" style={{ color: "#666" }}>
          {caveat}
          {honest && honest.caveats.length > 0 && " · " + honest.caveats.join(" · ")}
        </p>
      )}

      {/* Monthly Breakdown — from raw endpoint (structural, not aggregate metrics) */}
      {perf?.monthly_breakdown && perf.monthly_breakdown.length > 0 && (
        <div className="font-mono text-xs">
          <div className="mb-2">
            <span className="text-[10px] uppercase tracking-wider font-bold" style={{ color: "#555" }}>
              Monthly Breakdown
            </span>
          </div>
          <div className="grid grid-cols-4 gap-2 pb-2 mb-2" style={{ borderBottom: "1px solid #1a1a2e" }}>
            <span className="text-[9px] uppercase tracking-wider" style={{ color: "#555" }}>Month</span>
            <span className="text-[9px] uppercase tracking-wider text-right" style={{ color: "#555" }}>Trades</span>
            <span className="text-[9px] uppercase tracking-wider text-right" style={{ color: "#555" }}>P&L</span>
            <span className="text-[9px] uppercase tracking-wider text-right" style={{ color: "#555" }}>Win Rate</span>
          </div>
          {perf.monthly_breakdown.map((m, idx) => (
            <div key={idx} className="grid grid-cols-4 gap-2 py-1" style={{ borderBottom: "1px solid #111" }}>
              <span style={{ color: "#888" }}>{m.month}</span>
              <span className="text-right tabular-nums" style={{ color: "#e0e0e0" }}>{m.trades}</span>
              <span className="text-right tabular-nums font-bold"
                style={{ color: m.pnl >= 0 ? "#00ff88" : "#ff4444" }}>
                ${m.pnl.toFixed(2)}
              </span>
              <span className="text-right tabular-nums" style={{ color: "#e0e0e0" }}>
                {m.win_rate != null ? `${(m.win_rate * 100).toFixed(0)}%` : "--"}
              </span>
            </div>
          ))}
        </div>
      )}

      {!honest && !anyError && (
        <div className="rounded-lg p-6 text-center" style={{ backgroundColor: "#0d0d1a" }}>
          <span className="font-mono text-xs" style={{ color: "#555" }}>
            Loading performance metrics...
          </span>
        </div>
      )}
    </div>
  );
}

function MetricCard({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="rounded-lg p-3 text-center" style={{ backgroundColor: "#0d0d1a", border: "1px solid #1a1a2e" }}>
      <div className="font-mono text-[9px] uppercase tracking-wider mb-1.5" style={{ color: "#555" }}>{label}</div>
      <div className="font-mono text-base font-bold tabular-nums" style={{ color: color ?? "#e0e0e0" }}>{value}</div>
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
          <span className="font-mono text-[10px] font-bold tracking-[0.2em] uppercase" style={{ color: "#00ff88" }}>
            TRADE LOGGER
          </span>
          <span className="font-mono text-[9px] px-1.5 py-0.5 rounded border"
            style={{ borderColor: "#ffcc0033", backgroundColor: "#ffcc0010", color: "#ffcc00" }}>
            MANUAL ENTRY
          </span>
        </div>
      </div>

      {/* Toast */}
      {toast && (
        <div className="rounded-lg p-3 mb-3 font-mono text-xs flex items-center gap-2 transition-all"
          style={{
            backgroundColor: toast.type === "success" ? "#00ff8815" : "#ff444415",
            border: `1px solid ${toast.type === "success" ? "#00ff8830" : "#ff444430"}`,
            color: toast.type === "success" ? "#00ff88" : "#ff4444",
          }}>
          {toast.type === "success" ? "OK" : "ERR"} — {toast.message}
        </div>
      )}

      <form onSubmit={handleSubmit}>
        <div className="grid grid-cols-6 gap-3 mb-4">
          {/* Entry Date */}
          <div>
            <label className="block font-mono text-[9px] uppercase tracking-wider mb-1" style={{ color: "#555" }}>
              Entry Date
            </label>
            <input
              type="date"
              value={form.entry_date}
              onChange={(e) => updateField("entry_date", e.target.value)}
              className="w-full rounded-lg border px-3 py-2 font-mono text-xs focus:outline-none focus:ring-1"
              style={{ backgroundColor: "#0d0d1a", borderColor: "#1a1a2e", color: "#e0e0e0" }}
              required
            />
          </div>

          {/* Exit Date */}
          <div>
            <label className="block font-mono text-[9px] uppercase tracking-wider mb-1" style={{ color: "#555" }}>
              Exit Date
            </label>
            <input
              type="date"
              value={form.exit_date}
              onChange={(e) => updateField("exit_date", e.target.value)}
              className="w-full rounded-lg border px-3 py-2 font-mono text-xs focus:outline-none focus:ring-1"
              style={{ backgroundColor: "#0d0d1a", borderColor: "#1a1a2e", color: "#e0e0e0" }}
            />
          </div>

          {/* Direction */}
          <div>
            <label className="block font-mono text-[9px] uppercase tracking-wider mb-1" style={{ color: "#555" }}>
              Direction
            </label>
            <select
              value={form.direction}
              onChange={(e) => updateField("direction", e.target.value)}
              className="w-full rounded-lg border px-3 py-2 font-mono text-xs focus:outline-none focus:ring-1"
              style={{ backgroundColor: "#0d0d1a", borderColor: "#1a1a2e", color: "#e0e0e0" }}
            >
              <option value="LONG">LONG</option>
              <option value="SHORT">SHORT</option>
            </select>
          </div>

          {/* Entry Price */}
          <div>
            <label className="block font-mono text-[9px] uppercase tracking-wider mb-1" style={{ color: "#555" }}>
              Entry Price
            </label>
            <input
              type="number"
              step="0.01"
              value={form.entry_price || ""}
              onChange={(e) => updateField("entry_price", parseFloat(e.target.value) || 0)}
              placeholder="0.00"
              className="w-full rounded-lg border px-3 py-2 font-mono text-xs focus:outline-none focus:ring-1"
              style={{ backgroundColor: "#0d0d1a", borderColor: "#1a1a2e", color: "#e0e0e0" }}
              required
            />
          </div>

          {/* Exit Price */}
          <div>
            <label className="block font-mono text-[9px] uppercase tracking-wider mb-1" style={{ color: "#555" }}>
              Exit Price
            </label>
            <input
              type="number"
              step="0.01"
              value={form.exit_price || ""}
              onChange={(e) => updateField("exit_price", parseFloat(e.target.value) || 0)}
              placeholder="0.00"
              className="w-full rounded-lg border px-3 py-2 font-mono text-xs focus:outline-none focus:ring-1"
              style={{ backgroundColor: "#0d0d1a", borderColor: "#1a1a2e", color: "#e0e0e0" }}
            />
          </div>
        </div>

        {/* Action buttons */}
        <div className="flex gap-3 mt-4">
          <button
            onClick={handleSubmit}
            disabled={submitting}
            className="flex-1 rounded-lg px-4 py-2 font-mono text-xs font-semibold text-white transition-colors focus:outline-none focus:ring-2 focus:ring-offset-2"
            style={{ backgroundColor: "#00ff88", cursor: submitting ? "not-allowed" : "pointer", opacity: submitting ? 0.6 : 1 }}
          >
            {submitting ? "Processing…" : "Record Trade"}
          </button>
          <button
            type="button"
            onClick={() => setForm({ entry_date: "", exit_date: "", direction: "BUY", entry_price: 0, exit_price: 0, contracts: 1 })}
            disabled={submitting}
            className="flex-1 rounded-lg border px-4 py-2 font-mono text-xs font-semibold transition-colors"
            style={{ borderColor: "#555", color: "#aaa", cursor: submitting ? "not-allowed" : "pointer", opacity: submitting ? 0.6 : 1 }}
          >
            Reset
          </button>
        </div>
      </form>
    </div>
  );
}
   