"use client";

import React, { useState, useCallback } from "react";
import useSWR from "swr";
import { Activity, ArrowLeft, RefreshCw, Send, AlertTriangle, TrendingUp, TrendingDown, Minus } from "lucide-react";
import { fetchEngine, postEngine } from "@/lib/api";
import type { MGCSignalResponse, PendingSignal, MGCPerformanceResponse, PaperTradePayload } from "@/lib/api";

function fetcher<T = unknown>(url: string): Promise<T> {
  return fetchEngine<T>(url);
}

// ── Main Page ────────────────────────────────────────────────────────────────
export default function PaperTradingPage() {
  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="sticky top-0 z-50 border-b border-border bg-background/95 backdrop-blur">
        <div className="mx-auto max-w-[1600px] flex items-center justify-between px-6 py-3">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent/10">
              <Activity className="h-5 w-5 text-accent" />
            </div>
            <div>
              <h1 className="font-bold text-foreground tracking-tight">
                JARVIS TRADER
              </h1>
              <p className="text-xs text-muted-foreground">
                MGC Daily Paper Trading
              </p>
            </div>
            <nav className="hidden lg:flex items-center gap-4 ml-6">
              <a href="/" className="text-xs text-muted-foreground hover:text-foreground transition-colors flex items-center gap-1">
                <ArrowLeft className="h-3 w-3" />
                Dashboard
              </a>
              <a href="/analysis" className="text-xs text-muted-foreground hover:text-foreground transition-colors">
                Analysis
              </a>
              <a href="/backtest" className="text-xs text-muted-foreground hover:text-foreground transition-colors">
                Backtest
              </a>
              <a href="/paper" className="text-xs text-accent font-semibold transition-colors">
                Paper Trading
              </a>
            </nav>
          </div>
          <div className="flex items-center gap-2">
            <span className="font-mono text-[9px] px-1.5 py-0.5 rounded border"
              style={{ borderColor: "#00ff8833", backgroundColor: "#00ff8810", color: "#00ff88" }}>
              PAPER MODE
            </span>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1600px] px-6 py-4 space-y-4">
        {/* Top row: Signal + Performance */}
        <div className="grid grid-cols-12 gap-4">
          <div className="col-span-12 lg:col-span-6">
            <LiveSignalPanel />
          </div>
          <div className="col-span-12 lg:col-span-6">
            <PerformanceMetricsPanel />
          </div>
        </div>

        {/* Middle: Pending Signals Queue */}
        <PendingSignalsPanel />

        {/* Bottom: Trade Logger */}
        <TradeLoggerPanel />
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


// ── Section 2: Pending Signals Queue ─────────────────────────────────────────

function PendingSignalsPanel() {
  const { data: signals, error } = useSWR<PendingSignal[]>(
    "/paper/pending-signals",
    fetcher,
    { refreshInterval: 60_000, shouldRetryOnError: false }
  );

  // Normalize: the endpoint may return an array directly or { signals: [...] }
  const items: PendingSignal[] = Array.isArray(signals) ? signals : [];

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
          <span className="font-mono text-[10px] font-bold tracking-[0.2em] uppercase" style={{ color: "#00ff88" }}>
            PENDING SIGNALS QUEUE
          </span>
          <span className="font-mono text-[9px] px-1.5 py-0.5 rounded border"
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

      {items.length > 0 ? (
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
          {items.map((sig, idx) => {
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
            No pending signals — scheduler runs 18:00 ET weekdays
          </span>
        </div>
      )}
    </div>
  );
}


// ── Section 3: Performance Metrics ───────────────────────────────────────────

function PerformanceMetricsPanel() {
  const { data: perf, error } = useSWR<MGCPerformanceResponse>(
    "/paper/mgc-performance",
    fetcher,
    { refreshInterval: 30_000, shouldRetryOnError: false }
  );

  const pfColor = (pf: number | null | undefined) => {
    if (pf == null) return "#555";
    if (pf >= 1.5) return "#00ff88";
    if (pf >= 1.0) return "#ffcc00";
    return "#ff4444";
  };

  const killActive = perf?.kill_switch_active ?? false;

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
        </div>
        {/* Kill Switch Status */}
        <span className="font-mono text-[9px] px-2 py-0.5 rounded border font-bold"
          style={{
            borderColor: killActive ? "#ff444440" : "#00ff8840",
            backgroundColor: killActive ? "#ff444415" : "#00ff8815",
            color: killActive ? "#ff4444" : "#00ff88",
          }}>
          KILL SWITCH: {killActive ? "TRIGGERED" : "ACTIVE"}
        </span>
      </div>

      {error && !perf && (
        <div className="rounded-lg p-3 mb-3 font-mono text-xs" style={{ backgroundColor: "#ff444410", color: "#ff4444" }}>
          Engine offline — performance data unavailable
        </div>
      )}

      {/* Metrics Grid */}
      <div className="grid grid-cols-5 gap-2 mb-4">
        <MetricCard label="Total Trades" value={perf?.total_trades != null ? String(perf.total_trades) : "--"} />
        <MetricCard label="Win Rate"
          value={perf?.win_rate != null ? `${(perf.win_rate * 100).toFixed(1)}%` : "--"}
          color={perf?.win_rate != null && perf.win_rate >= 0.5 ? "#00ff88" : "#ffcc00"} />
        <MetricCard label="Profit Factor"
          value={perf?.profit_factor != null ? perf.profit_factor.toFixed(2) : "--"}
          color={pfColor(perf?.profit_factor)} />
        <MetricCard label="Net P&L"
          value={perf?.net_pnl != null ? `$${perf.net_pnl.toFixed(2)}` : "--"}
          color={perf?.net_pnl != null ? (perf.net_pnl >= 0 ? "#00ff88" : "#ff4444") : undefined} />
        <MetricCard label="Max Drawdown"
          value={perf?.max_drawdown != null ? `${(perf.max_drawdown * 100).toFixed(1)}%` : "--"}
          color={perf?.max_drawdown != null && perf.max_drawdown > 0.05 ? "#ff4444" : "#ffcc00"} />
      </div>

      {/* Monthly Breakdown */}
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

      {!perf && !error && (
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

          {/* Contracts */}
          <div>
            <label className="block font-mono text-[9px] uppercase tracking-wider mb-1" style={{ color: "#555" }}>
              Contracts
            </label>
            <input
              type="number"
              min={1}
              value={form.contracts}
              onChange={(e) => updateField("contracts", parseInt(e.target.value) || 1)}
              className="w-full rounded-lg border px-3 py-2 font-mono text-xs focus:outline-none focus:ring-1"
              style={{ backgroundColor: "#0d0d1a", borderColor: "#1a1a2e", color: "#e0e0e0" }}
              required
            />
          </div>
        </div>

        <button
          type="submit"
          disabled={submitting || form.entry_price <= 0}
          className="flex items-center gap-2 rounded-lg px-4 py-2 font-mono text-xs font-bold uppercase tracking-wider transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          style={{ backgroundColor: "#00ff8820", color: "#00ff88", border: "1px solid #00ff8840" }}
        >
          <Send className="h-3.5 w-3.5" />
          {submitting ? "Submitting..." : "Log Trade"}
        </button>
      </form>
    </div>
  );
}
