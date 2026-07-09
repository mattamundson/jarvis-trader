"use client";

import React, { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import {
  TrendingUp,
  TrendingDown,
  Activity,
  BarChart2,
  Shield,
  RefreshCw,
  ArrowLeft,
  AlertTriangle,
  CheckCircle,
  Clock,
  Zap,
  Target,
  Layers,
} from "lucide-react";
import { fetchEngine, postEngine } from "@/lib/api";
import { Badge } from "@/components/ui/badge";

// ── Types ─────────────────────────────────────────────────────────────────────

interface LiveSignal {
  generated_at: string;
  strategy: string;
  effective_date: string;
  execution_note: string;
  holdings: Record<string, number>;
  combined_scale: number;
  layers: {
    momentum_signal: {
      raw_holdings: Record<string, number>;
      risk_regime: string;
      absolute_mom_pass: boolean;
    };
    vol_targeting: {
      scale: number;
      realized_vol_pct: number;
      vol_target_pct: number;
      vol_regime: string;
    };
    vix_composite: {
      vix: number;
      vix_regime: string;
      composite_score: number;
      position_multiplier: number;
      level_score: number;
      mom_score: number;
      ma_score: number;
      fear_score: number;
    };
    macro_filter: {
      yield_curve: number;
      fed_funds: number;
      multiplier: number;
      total_adj: number;
      source: string;
    };
  };
  ibkr_instructions: {
    account: string;
    mode: string;
    gateway_port: number;
    execution_timing: string;
    orders: Array<{
      symbol: string;
      action: string;
      weight_pct: number;
      order_type: string;
      tif: string;
    }>;
    rebalance_required: boolean;
  };
  _meta?: {
    signal_age_hours: number;
    stale: boolean;
  };
}

interface Metrics {
  full_period?: {
    cagr: number;
    sharpe: number;
    sortino: number;
    max_drawdown: number;
    volatility: number;
    win_rate: number;
    calmar: number;
    final_equity: number;
    n_weeks: number;
  };
  in_sample?: {
    cagr: number;
    sharpe: number;
    max_drawdown: number;
    start: string;
    end: string;
  };
  out_of_sample?: {
    cagr: number;
    sharpe: number;
    max_drawdown: number;
    sharpe_retention: number;
    cagr_retention: number;
    start: string;
    end: string;
  };
  optimal_params?: Record<string, unknown>;
  deflated_sharpe?: {
    p_value: number;
    verdict: string;
  };
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtPct(v: number | null | undefined, decimals = 1): string {
  if (v == null) return "—";
  return `${(v * 100).toFixed(decimals)}%`;
}

function fmtNum(v: number | null | undefined, decimals = 2): string {
  if (v == null) return "—";
  return v.toFixed(decimals);
}

function fmtAge(hours: number | null | undefined): string {
  if (hours == null) return "—";
  if (hours < 1) return "< 1 hour ago";
  if (hours < 24) return `${Math.round(hours)}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

function regimeColor(regime: string): string {
  if (regime === "RISK_ON") return "text-emerald-400";
  if (regime === "RISK_OFF") return "text-rose-400";
  return "text-yellow-400";
}

function vixRegimeColor(regime: string): string {
  if (regime === "CALM") return "text-emerald-400";
  if (regime === "NORMAL") return "text-sky-400";
  if (regime === "ELEVATED") return "text-yellow-400";
  if (regime === "CRISIS" || regime === "EXTREME") return "text-rose-400";
  return "text-slate-400";
}

function scaleBar(scale: number): string {
  const filled = Math.round(scale * 20);
  return "█".repeat(filled) + "░".repeat(20 - filled);
}

// ── Ticker badge colours ──────────────────────────────────────────────────────
const TICKER_COLORS: Record<string, string> = {
  QQQ: "bg-violet-900/60 border-violet-500/40 text-violet-200",
  SPY: "bg-blue-900/60 border-blue-500/40 text-blue-200",
  XLK: "bg-cyan-900/60 border-cyan-500/40 text-cyan-200",
  XLV: "bg-teal-900/60 border-teal-500/40 text-teal-200",
  USMV: "bg-indigo-900/60 border-indigo-500/40 text-indigo-200",
  MTUM: "bg-purple-900/60 border-purple-500/40 text-purple-200",
  EFA: "bg-orange-900/60 border-orange-500/40 text-orange-200",
  IEF: "bg-slate-800/80 border-slate-500/40 text-slate-300",
  SHY: "bg-slate-800/80 border-slate-400/40 text-slate-300",
};

function tickerClass(symbol: string): string {
  return TICKER_COLORS[symbol] ?? "bg-slate-700/60 border-slate-500/40 text-slate-200";
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function StrategyCPage() {
  const [signal, setSignal] = useState<LiveSignal | null>(null);
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date());

  const loadData = useCallback(async () => {
    try {
      const [sig, met] = await Promise.all([
        fetchEngine<LiveSignal>("/v1/strategy_c/signal"),
        fetchEngine<Metrics>("/v1/strategy_c/metrics").catch(() => null),
      ]);
      setSignal(sig);
      setMetrics(met);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load Strategy C+ data");
    } finally {
      setLoading(false);
      setLastRefresh(new Date());
    }
  }, []);

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      await postEngine("/v1/strategy_c/refresh", {});
      // Wait a moment then reload
      setTimeout(async () => {
        await loadData();
        setRefreshing(false);
      }, 5000);
    } catch {
      setRefreshing(false);
      await loadData();
    }
  };

  useEffect(() => {
    loadData();
    // Auto-refresh every 5 minutes
    const interval = setInterval(loadData, 5 * 60 * 1000);
    return () => clearInterval(interval);
  }, [loadData]);

  // ── Loading State ─────────────────────────────────────────────────────────

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-950 flex items-center justify-center">
        <div className="text-center">
          <Activity className="w-12 h-12 text-violet-400 animate-pulse mx-auto mb-4" />
          <p className="text-slate-400 text-sm">Loading Strategy C+ signal…</p>
        </div>
      </div>
    );
  }

  // ── Error State ───────────────────────────────────────────────────────────

  if (error && !signal) {
    return (
      <div className="min-h-screen bg-slate-950 flex items-center justify-center p-6">
        <div className="max-w-md text-center">
          <AlertTriangle className="w-12 h-12 text-rose-400 mx-auto mb-4" />
          <h2 className="text-white font-semibold mb-2">Signal Unavailable</h2>
          <p className="text-slate-400 text-sm mb-4">{error}</p>
          <p className="text-slate-500 text-xs">
            Run: <code className="text-violet-400">python -m engine.strategy_c.live_signal</code>
          </p>
          <button
            onClick={loadData}
            className="mt-4 px-4 py-2 bg-violet-600 hover:bg-violet-500 text-white rounded-lg text-sm transition-colors"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  if (!signal) return null;

  // Guard against a partial /v1/strategy_c/signal payload — every panel below
  // destructures these nested layers, so a missing one would crash the page.
  if (
    !signal.layers ||
    !signal.holdings ||
    !signal.layers.momentum_signal ||
    !signal.layers.vol_targeting ||
    !signal.layers.vix_composite ||
    !signal.layers.macro_filter
  ) {
    return (
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 m-4 text-sm text-slate-400">
        Strategy-C signal payload is incomplete — the engine returned a partial
        response (missing layer or holdings data). Showing nothing rather than
        crashing; retry after the next refresh.
      </div>
    );
  }

  const layers = signal.layers;
  const mom = layers.momentum_signal;
  const vol = layers.vol_targeting;
  const vix = layers.vix_composite;
  const macro = layers.macro_filter;
  const scale = signal.combined_scale;
  const isRiskOn = mom.risk_regime === "RISK_ON";
  const isStale = signal._meta?.stale ?? false;

  // Sort holdings by weight descending
  const holdings = Object.entries(signal.holdings)
    .filter(([, w]) => w > 0.005)
    .sort((a, b) => b[1] - a[1]);

  // Separate risk-on from cash positions
  const cashSymbols = ["IEF", "SHY", "BIL", "SGOV"];
  const riskOnHoldings = holdings.filter(([sym]) => !cashSymbols.includes(sym));
  const cashHoldings = holdings.filter(([sym]) => cashSymbols.includes(sym));

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 font-sans">
      {/* ── Header ───────────────────────────────────────────────────────── */}
      <div className="border-b border-slate-800 px-6 py-4">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Link
              href="/"
              className="flex items-center gap-1.5 text-slate-400 hover:text-white transition-colors text-sm"
            >
              <ArrowLeft className="w-4 h-4" />
              Dashboard
            </Link>
            <div className="w-px h-4 bg-slate-700" />
            <div className="flex items-center gap-2">
              <Layers className="w-5 h-5 text-violet-400" />
              <span className="font-semibold text-white">Strategy C+</span>
              <span className="text-xs px-2 py-0.5 rounded-full bg-violet-900/60 border border-violet-500/30 text-violet-300">
                PAPER
              </span>
            </div>
          </div>

          <div className="flex items-center gap-3">
            {isStale && (
              <div className="flex items-center gap-1.5 text-amber-400 text-xs">
                <AlertTriangle className="w-3.5 h-3.5" />
                Signal stale
              </div>
            )}
            <span className="text-slate-500 text-xs">
              Refreshed {lastRefresh.toLocaleTimeString()}
            </span>
            <button
              onClick={handleRefresh}
              disabled={refreshing}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-800 hover:bg-slate-700 border border-slate-700 rounded-lg text-sm text-slate-300 transition-colors disabled:opacity-50"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${refreshing ? "animate-spin" : ""}`} />
              {refreshing ? "Generating…" : "Refresh Signal"}
            </button>
          </div>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-6 py-6 space-y-6">
        {/* ── Top KPI Row ───────────────────────────────────────────────────── */}
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
          {/* Regime */}
          <div className="col-span-2 bg-slate-900 border border-slate-800 rounded-xl p-4 flex items-center gap-4">
            {isRiskOn ? (
              <TrendingUp className="w-8 h-8 text-emerald-400 flex-shrink-0" />
            ) : (
              <Shield className="w-8 h-8 text-rose-400 flex-shrink-0" />
            )}
            <div>
              <p className="text-xs text-slate-500 uppercase tracking-wide mb-0.5">Regime</p>
              <p className={`text-xl font-bold ${regimeColor(mom.risk_regime)}`}>
                {mom.risk_regime.replace("_", " ")}
              </p>
              <p className="text-xs text-slate-500 mt-0.5">
                Abs. momentum: {mom.absolute_mom_pass ? "✓ pass" : "✗ fail"}
              </p>
            </div>
          </div>

          {/* Combined Scale */}
          <div className="col-span-2 bg-slate-900 border border-slate-800 rounded-xl p-4">
            <p className="text-xs text-slate-500 uppercase tracking-wide mb-1">Combined Scale</p>
            <p className="text-3xl font-bold text-white mb-1">
              {(scale * 100).toFixed(1)}%
            </p>
            <div className="font-mono text-xs text-violet-400 tracking-tighter overflow-hidden">
              {scaleBar(scale)}
            </div>
          </div>

          {/* VIX */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
            <p className="text-xs text-slate-500 uppercase tracking-wide mb-1">VIX</p>
            <p className="text-2xl font-bold text-white">{vix.vix.toFixed(1)}</p>
            <p className={`text-xs font-medium mt-0.5 ${vixRegimeColor(vix.vix_regime)}`}>
              {vix.vix_regime}
            </p>
          </div>

          {/* Vol Regime */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
            <p className="text-xs text-slate-500 uppercase tracking-wide mb-1">Realized Vol</p>
            <p className="text-2xl font-bold text-white">{vol.realized_vol_pct.toFixed(1)}%</p>
            <p className={`text-xs mt-0.5 ${
              vol.vol_regime === "CALM"
                ? "text-emerald-400"
                : vol.vol_regime === "NORMAL"
                ? "text-sky-400"
                : "text-amber-400"
            }`}>
              {vol.vol_regime} · target {vol.vol_target_pct}%
            </p>
          </div>

          {/* Signal Age */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
            <p className="text-xs text-slate-500 uppercase tracking-wide mb-1">Signal Age</p>
            <p className="text-lg font-bold text-white">
              {fmtAge(signal._meta?.signal_age_hours)}
            </p>
            <p className="text-xs text-slate-500 mt-0.5 truncate">
              {new Date(signal.generated_at).toLocaleDateString()}
            </p>
          </div>
        </div>

        {/* ── Holdings + Signal Layers ─────────────────────────────────────── */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* Holdings */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
            <div className="flex items-center justify-between mb-4">
              <h2 className="font-semibold text-white flex items-center gap-2">
                <Target className="w-4 h-4 text-violet-400" />
                Current Holdings
              </h2>
              <span className="text-xs text-slate-500">
                {signal.effective_date} · T+1 MOO
              </span>
            </div>

            <div className="space-y-2.5">
              {riskOnHoldings.map(([sym, wt]) => (
                <div key={sym} className="flex items-center gap-3">
                  <span className={`text-xs font-mono font-bold px-2 py-0.5 rounded border ${tickerClass(sym)} w-14 text-center flex-shrink-0`}>
                    {sym}
                  </span>
                  <div className="flex-1">
                    <div className="h-2 bg-slate-800 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-violet-500 rounded-full"
                        style={{ width: `${wt * 100}%` }}
                      />
                    </div>
                  </div>
                  <span className="text-sm font-semibold text-white w-12 text-right">
                    {(wt * 100).toFixed(1)}%
                  </span>
                </div>
              ))}

              {cashHoldings.length > 0 && (
                <>
                  <div className="border-t border-slate-800 pt-2 mt-1">
                    <p className="text-xs text-slate-600 mb-2">Cash / Defensive</p>
                  </div>
                  {cashHoldings.map(([sym, wt]) => (
                    <div key={sym} className="flex items-center gap-3">
                      <span className={`text-xs font-mono font-bold px-2 py-0.5 rounded border ${tickerClass(sym)} w-14 text-center flex-shrink-0`}>
                        {sym}
                      </span>
                      <div className="flex-1">
                        <div className="h-2 bg-slate-800 rounded-full overflow-hidden">
                          <div
                            className="h-full bg-slate-500 rounded-full"
                            style={{ width: `${wt * 100}%` }}
                          />
                        </div>
                      </div>
                      <span className="text-sm font-semibold text-slate-300 w-12 text-right">
                        {(wt * 100).toFixed(1)}%
                      </span>
                    </div>
                  ))}
                </>
              )}
            </div>

            {/* IBKR execution info */}
            <div className="mt-4 pt-3 border-t border-slate-800">
              <p className="text-xs text-slate-500 mb-2">Execution Instructions</p>
              <div className="grid grid-cols-3 gap-2 text-xs">
                <div>
                  <p className="text-slate-600">Account</p>
                  <p className="text-slate-300 font-mono">{signal.ibkr_instructions.account}</p>
                </div>
                <div>
                  <p className="text-slate-600">Mode</p>
                  <p className="text-amber-400 font-semibold">{signal.ibkr_instructions.mode}</p>
                </div>
                <div>
                  <p className="text-slate-600">Timing</p>
                  <p className="text-slate-300">Mon MOO</p>
                </div>
              </div>
              <div className="mt-2 flex items-center gap-1.5">
                {signal.ibkr_instructions.rebalance_required ? (
                  <>
                    <AlertTriangle className="w-3.5 h-3.5 text-amber-400" />
                    <p className="text-amber-400 text-xs">Rebalance required</p>
                  </>
                ) : (
                  <>
                    <CheckCircle className="w-3.5 h-3.5 text-emerald-400" />
                    <p className="text-emerald-400 text-xs">No rebalance needed</p>
                  </>
                )}
              </div>
            </div>
          </div>

          {/* Signal Layers */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
            <h2 className="font-semibold text-white flex items-center gap-2 mb-4">
              <Layers className="w-4 h-4 text-violet-400" />
              Signal Stack
            </h2>

            <div className="space-y-3">
              {/* Layer 1: Momentum */}
              <div className="bg-slate-800/50 rounded-lg p-3">
                <div className="flex items-center justify-between mb-1.5">
                  <p className="text-xs font-semibold text-slate-300">
                    L1 · Dual Momentum + Factor Tilt
                  </p>
                  <span className={`text-xs font-bold ${regimeColor(mom.risk_regime)}`}>
                    {mom.risk_regime.replace("_", " ")}
                  </span>
                </div>
                <div className="flex gap-1.5 flex-wrap">
                  {Object.entries(mom.raw_holdings).map(([sym, wt]) => (
                    <span key={sym} className={`text-xs px-1.5 py-0.5 rounded border ${tickerClass(sym)}`}>
                      {sym} {(wt * 100).toFixed(0)}%
                    </span>
                  ))}
                </div>
              </div>

              {/* Layer 2: Vol Targeting */}
              <div className="bg-slate-800/50 rounded-lg p-3">
                <div className="flex items-center justify-between mb-1.5">
                  <p className="text-xs font-semibold text-slate-300">
                    L2 · ES/NQ Vol Targeting
                  </p>
                  <span className="text-xs font-bold text-sky-400">
                    {(vol.scale * 100).toFixed(1)}% scale
                  </span>
                </div>
                <div className="grid grid-cols-3 gap-2 text-xs text-slate-400">
                  <div>Realized: <span className="text-white">{vol.realized_vol_pct.toFixed(1)}%</span></div>
                  <div>Target: <span className="text-white">{vol.vol_target_pct}%</span></div>
                  <div>Regime: <span className={vixRegimeColor(vol.vol_regime)}>{vol.vol_regime}</span></div>
                </div>
              </div>

              {/* Layer 3: VIX Composite */}
              <div className="bg-slate-800/50 rounded-lg p-3">
                <div className="flex items-center justify-between mb-1.5">
                  <p className="text-xs font-semibold text-slate-300">
                    L3 · VIX Composite (4-factor)
                  </p>
                  <span className={`text-xs font-bold ${vixRegimeColor(vix.vix_regime)}`}>
                    {vix.composite_score.toFixed(3)} score
                  </span>
                </div>
                <div className="grid grid-cols-4 gap-1.5 text-xs">
                  {[
                    { label: "Level", val: vix.level_score, pct: "40%" },
                    { label: "Mom", val: vix.mom_score, pct: "25%" },
                    { label: "MA", val: vix.ma_score, pct: "20%" },
                    { label: "Fear", val: vix.fear_score, pct: "15%" },
                  ].map((f) => (
                    <div key={f.label} className="bg-slate-900/60 rounded p-1.5 text-center">
                      <p className="text-slate-500 text-[10px]">{f.label} ({f.pct})</p>
                      <p className={`font-semibold ${f.val > 0.7 ? "text-emerald-400" : f.val > 0.4 ? "text-yellow-400" : "text-rose-400"}`}>
                        {f.val.toFixed(2)}
                      </p>
                    </div>
                  ))}
                </div>
              </div>

              {/* Layer 4: Macro */}
              <div className="bg-slate-800/50 rounded-lg p-3">
                <div className="flex items-center justify-between mb-1.5">
                  <p className="text-xs font-semibold text-slate-300">
                    L4 · FRED Macro + CoT
                  </p>
                  <span className="text-xs text-slate-400">
                    ×{macro.multiplier.toFixed(2)} mult.
                  </span>
                </div>
                <div className="grid grid-cols-3 gap-2 text-xs text-slate-400">
                  <div>Yield curve: <span className="text-white">{macro.yield_curve.toFixed(2)}%</span></div>
                  <div>Fed funds: <span className="text-white">{macro.fed_funds.toFixed(2)}%</span></div>
                  <div>Adj total: <span className={macro.total_adj >= 0 ? "text-emerald-400" : "text-rose-400"}>{macro.total_adj >= 0 ? "+" : ""}{(macro.total_adj * 100).toFixed(1)}%</span></div>
                </div>
                <p className="text-xs text-slate-600 mt-1">
                  Source: {macro.source}
                </p>
              </div>
            </div>
          </div>
        </div>

        {/* ── Performance Metrics ──────────────────────────────────────────── */}
        {metrics && (
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
            <h2 className="font-semibold text-white flex items-center gap-2 mb-4">
              <BarChart2 className="w-4 h-4 text-violet-400" />
              Backtest Performance (2017–2026)
            </h2>

            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
              {[
                {
                  label: "CAGR",
                  live: metrics.full_period?.cagr != null,
                  value: metrics.full_period?.cagr != null ? fmtPct(metrics.full_period.cagr) : "17.09%",
                  target: "17.4%",
                  good: true,
                },
                {
                  label: "Sharpe",
                  live: metrics.full_period?.sharpe != null,
                  value: metrics.full_period?.sharpe != null ? fmtNum(metrics.full_period.sharpe) : "2.12",
                  target: "2.13",
                  good: true,
                },
                {
                  label: "Max DD",
                  live: metrics.full_period?.max_drawdown != null,
                  value: metrics.full_period?.max_drawdown != null ? fmtPct(metrics.full_period.max_drawdown) : "-8.16%",
                  target: "-7.7%",
                  good: false,
                },
                {
                  label: "Volatility",
                  live: metrics.full_period?.volatility != null,
                  value: metrics.full_period?.volatility != null ? fmtPct(metrics.full_period.volatility) : "7.57%",
                  target: "7.7%",
                  good: true,
                },
              ].map((m) => (
                <div key={m.label} className="bg-slate-800/50 rounded-lg p-3">
                  <div className="flex items-center justify-between gap-1 mb-1">
                    <p className="text-xs text-slate-500">{m.label}</p>
                    {!m.live && (
                      <Badge
                        variant="static"
                        className="text-[10px] px-1.5 py-0 leading-4 shrink-0"
                        title="Engine metrics endpoint did not return this field — showing a placeholder value, not live backtest output."
                      >
                        Static
                      </Badge>
                    )}
                  </div>
                  <p className="text-2xl font-bold text-white">{m.value}</p>
                  <p className="text-xs text-slate-500 mt-0.5">
                    Target: {m.target}
                  </p>
                </div>
              ))}
            </div>

            {/* IS vs OOS */}
            {metrics.in_sample && metrics.out_of_sample && (
              <div className="grid grid-cols-2 gap-3">
                <div className="bg-slate-800/50 rounded-lg p-3">
                  <p className="text-xs font-semibold text-slate-400 mb-2">
                    In-Sample ({metrics.in_sample.start?.substring(0, 4)}–{metrics.in_sample.end?.substring(0, 4)})
                  </p>
                  <div className="grid grid-cols-3 gap-2 text-xs">
                    <div>CAGR <span className="block text-white font-semibold">{fmtPct(metrics.in_sample.cagr)}</span></div>
                    <div>Sharpe <span className="block text-white font-semibold">{fmtNum(metrics.in_sample.sharpe)}</span></div>
                    <div>MDD <span className="block text-rose-400 font-semibold">{fmtPct(metrics.in_sample.max_drawdown)}</span></div>
                  </div>
                </div>
                <div className="bg-slate-800/50 rounded-lg p-3">
                  <p className="text-xs font-semibold text-slate-400 mb-2">
                    Out-of-Sample ({metrics.out_of_sample.start?.substring(0, 4)}–{metrics.out_of_sample.end?.substring(0, 4)})
                  </p>
                  <div className="grid grid-cols-3 gap-2 text-xs">
                    <div>CAGR <span className="block text-white font-semibold">{fmtPct(metrics.out_of_sample.cagr)}</span></div>
                    <div>Sharpe <span className="block text-white font-semibold">{fmtNum(metrics.out_of_sample.sharpe)}</span></div>
                    <div>Retention <span className="block text-emerald-400 font-semibold">{fmtPct(metrics.out_of_sample.sharpe_retention)}</span></div>
                  </div>
                </div>
              </div>
            )}

            {/* Additional metrics row */}
            <div className="grid grid-cols-4 gap-3 mt-3">
              {[
                {
                  label: "Sortino",
                  live: metrics.full_period?.sortino != null,
                  value: metrics.full_period?.sortino != null ? fmtNum(metrics.full_period.sortino) : "3.75",
                },
                {
                  label: "Calmar",
                  live: metrics.full_period?.calmar != null,
                  value: metrics.full_period?.calmar != null ? fmtNum(metrics.full_period.calmar) : "2.09",
                },
                {
                  label: "Win Rate",
                  live: metrics.full_period?.win_rate != null,
                  value: metrics.full_period?.win_rate != null ? fmtPct(metrics.full_period.win_rate) : "57.6%",
                },
                {
                  label: "Final Equity",
                  live: metrics.full_period?.final_equity != null,
                  value: metrics.full_period?.final_equity != null ? `${fmtNum(metrics.full_period.final_equity)}×` : "4.12×",
                },
              ].map((m) => (
                <div key={m.label} className="bg-slate-800/30 rounded-lg p-2.5 text-center">
                  <div className="flex items-center justify-center gap-1 mb-1">
                    <p className="text-xs text-slate-500">{m.label}</p>
                    {!m.live && (
                      <Badge
                        variant="static"
                        className="text-[10px] px-1.5 py-0 leading-4 shrink-0"
                        title="Engine metrics endpoint did not return this field — showing a placeholder value, not live backtest output."
                      >
                        Static
                      </Badge>
                    )}
                  </div>
                  <p className="text-lg font-bold text-white">{m.value}</p>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ── Footer ─────────────────────────────────────────────────────────── */}
        <div className="flex items-center justify-between text-xs text-slate-600 pb-4">
          <div className="flex items-center gap-1.5">
            <Clock className="w-3.5 h-3.5" />
            Signal generated {new Date(signal.generated_at).toLocaleString()}
          </div>
          <div className="flex items-center gap-1.5">
            <Zap className="w-3.5 h-3.5" />
            Weekly cron: Fridays 4:05pm CT
          </div>
          <div>
            Engine: <span className="font-mono">localhost:8010</span>
          </div>
        </div>
      </div>
    </div>
  );
}
