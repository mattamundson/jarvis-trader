"use client";

import React, { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { Brain, ArrowLeft, Play, RefreshCw, CheckCircle, XCircle, Clock, Zap, Activity, Cpu, StopCircle } from "lucide-react";
import { fetchEngine, postEngine } from "@/lib/api";
import { SectionHeader } from "./SectionHeader";
import { HowItWorksPanel } from "./HowItWorksPanel";
import { StrategyDiscoveryBrowser } from "@/components/StrategyDiscoveryBrowser";

// ── Types ─────────────────────────────────────────────────────────────────────

interface TrainingStatus {
  running: boolean;
  symbol: string | null;
  started_at: string | null;
  progress_pct: number;
  error: string | null;
  last_result: TrainingResult | null;
  recent_runs?: RecentRun[];
}

interface TrainingResult {
  status: string;
  symbol: string;
  interval: string;
  timesteps: number;
  train_bars: number;
  test_bars: number;
  model_path: string;
  metrics: Metrics;
  training_summary: Record<string, unknown>;
  completed_at: string;
}

interface Metrics {
  profit_factor: number;
  sharpe_ratio: number;
  win_rate: number;
  n_trades: number;
  total_pnl: number;
  max_drawdown: number;
  hold_rate: number;
  flat_hold_rate?: number;
  avg_pnl: number;
  passes_validation: boolean;
  action_distribution?: Record<string, number>;
}

interface SavedModel {
  symbol: string;
  path: string;
  size_kb: number;
  metadata: Record<string, unknown>;
}

interface HealthStatus {
  gymnasium_available: boolean;
  stable_baselines3_available: boolean;
  trainer_initialized: boolean;
  ready: boolean;
}

// ── Executor Types ─────────────────────────────────────────────────────────────

interface ExecutorInfo {
  is_running: boolean;
  scheduler_running: boolean;
  symbol: string;
  model_path: string;
  last_action: "HOLD" | "BUY" | "SELL" | "CLOSE" | null;
  last_action_time: string | null;
  last_prediction_time: string | null;
  bars_executed: number;
  last_error: string | null;
  paper_position: number; // 1=long, 0=flat, -1=short
}

interface RecentRun {
  run_id: string;
  symbol: string;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  n_trades?: number;
  profit_factor?: number;
}

interface ExecutorStatusResponse {
  executors: Record<string, ExecutorInfo>;
}

// ── RL Executor Simplified Status Types (GET /strategies/rl/executor/status) ──

interface RLExecutorStatus {
  deployed: boolean;
  symbol: string | null;
  model_path: string | null;
  last_prediction: string | null;
  last_prediction_time: string | null;
  next_fire_time: string | null;
}

// ── Walk-Forward Grid Types (POST /strategies/rl/train-walkforward) ────────────

interface WalkForwardWindowMetricsGrid {
  profit_factor: number;
  win_rate: number;
  sharpe: number;
  max_drawdown: number;
  n_trades: number;
  hold_rate: number;
}

interface WalkForwardGridWindow {
  window: number;
  train_start: string;
  train_end: string;
  test_start: string;
  test_end: string;
  metrics: WalkForwardWindowMetricsGrid;
  passed: boolean;
}

// ── Walk-Forward Window Types ──────────────────────────────────────────────────

interface WalkForwardWindowMetrics {
  profit_factor: number;
  sharpe: number;
  win_rate: number;
  n_trades: number;
  max_drawdown: number;
  hold_rate: number;
}

interface WalkForwardWindow {
  window_idx: number;
  train_bars: number;
  test_bars: number;
  metrics: WalkForwardWindowMetrics;
  passes_validation: boolean;
  gates_passed: Record<string, boolean>;
}

interface WalkForwardStatusFields {
  walkforward_windows: WalkForwardWindow[];
  walkforward_complete: boolean;
  walkforward_all_pass: boolean;
}

// ── Validation Gate thresholds (mirrors rl_config.py) ─────────────────────────

const GATES = {
  min_profit_factor: 2.0,
  min_sharpe: 1.5,
  min_win_rate: 0.55,
  min_trades: 60,
  min_hold_rate: 0.50,
  max_drawdown: 0.15,
};

// ── Helpers ───────────────────────────────────────────────────────────────────

function metricColor(value: number, min: number, inverse = false): string {
  const pass = inverse ? value <= min : value >= min;
  if (pass) return "#00ff88";
  const close = inverse ? value <= min * 1.5 : value >= min * 0.75;
  return close ? "#ffcc00" : "#ff4444";
}

// Tailwind's JIT scanner only picks up literal class strings, so a companion of
// metricColor() that returns the equivalent text-color class (not a runtime hex
// piped through inline style) is needed anywhere the value drives a className.
function metricColorClass(value: number, min: number, inverse = false): string {
  const pass = inverse ? value <= min : value >= min;
  if (pass) return "text-[#00ff88]";
  const close = inverse ? value <= min * 1.5 : value >= min * 0.75;
  return close ? "text-[#ffcc00]" : "text-[#ff4444]";
}

function pct(v: number) {
  return `${(v * 100).toFixed(1)}%`;
}

// Closed palette of colors ever passed to Badge in this file — mapped to literal
// Tailwind arbitrary-value classes so the JIT scanner can see them (a dynamic
// `text-[${color}]` template string is invisible to the static extractor).
const BADGE_COLOR_CLASSES: Record<string, string> = {
  "#00ff88": "text-[#00ff88] bg-[#00ff8818] border-[#00ff8840]",
  "#ff4444": "text-[#ff4444] bg-[#ff444418] border-[#ff444440]",
  "#ffcc00": "text-[#ffcc00] bg-[#ffcc0018] border-[#ffcc0040]",
  "#00d4ff": "text-[#00d4ff] bg-[#00d4ff18] border-[#00d4ff40]",
  "#555": "text-[#555] bg-[#55518] border-[#55540]",
  "#888": "text-[#888] bg-[#88818] border-[#88840]",
};

function Badge({ label, color }: { label: string; color: string }) {
  return (
    <span
      className={`font-mono text-[10px] font-bold tracking-wider px-2 py-0.5 rounded border ${
        BADGE_COLOR_CLASSES[color] ?? "text-[#888] bg-[#88818] border-[#88840]"
      }`}
    >
      {label}
    </span>
  );
}

// ── Health Panel ──────────────────────────────────────────────────────────────

function HealthPanel({ health }: { health: HealthStatus | null }) {
  if (!health) {
    return (
      <section className="rounded-xl p-5 bg-panel border border-panel-border">
        <SectionHeader title="RL Module Health" />
        <p className="font-mono text-xs text-[#555]">Engine offline or not reachable.</p>
      </section>
    );
  }

  const items = [
    { label: "gymnasium", ok: health.gymnasium_available },
    { label: "stable-baselines3", ok: health.stable_baselines3_available },
    { label: "trainer initialized", ok: health.trainer_initialized },
  ];

  return (
    <section className="rounded-xl p-5 bg-panel border border-panel-border">
      <div className="flex items-center justify-between mb-4">
        <SectionHeader title="RL Module Health" subtitle="Dependencies and runtime availability" />
        <Badge label={health.ready ? "READY" : "NOT READY"} color={health.ready ? "#00ff88" : "#ff4444"} />
      </div>
      <div className="flex flex-wrap gap-4">
        {items.map(({ label, ok }) => (
          <div key={label} className="flex items-center gap-2">
            {ok
              ? <CheckCircle className="h-4 w-4 text-[#00ff88]" />
              : <XCircle className="h-4 w-4 text-[#ff4444]" />
            }
            <span className={`font-mono text-xs ${ok ? "text-[#e0e0e0]" : "text-[#ff4444]"}`}>{label}</span>
          </div>
        ))}
      </div>
      {!health.ready && (
        <div className="mt-4 rounded-lg p-3 font-mono text-xs bg-[#ff444410] border border-[#ff444430] text-[#ff9999]">
          Install missing deps: <span className="text-[#ffcc00]">pip install stable-baselines3 gymnasium</span>
        </div>
      )}
    </section>
  );
}

// ── Start Training Form ───────────────────────────────────────────────────────

function StartTrainingPanel({
  isRunning,
  onStart,
}: {
  isRunning: boolean;
  onStart: (symbol: string, interval: string, timesteps: number) => void;
}) {
  const [symbol, setSymbol] = useState("MES");
  const [barInterval, setBarInterval] = useState("1h");
  const [timesteps, setTimesteps] = useState(100_000);
  const [loading, setLoading] = useState(false);

  const selectCls = "font-mono text-xs rounded-lg px-3 py-2 outline-none cursor-pointer bg-[#111] border border-panel-border text-[#e0e0e0]";

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (isRunning || loading) return;
    setLoading(true);
    try {
      await onStart(symbol, barInterval, timesteps);
    } finally {
      setLoading(false);
    }
  }

  const TIMESTEP_OPTIONS = [
    { label: "10k  (smoke test ~30s)", value: 10_000 },
    { label: "100k (usable ~5min)", value: 100_000 },
    { label: "250k (good ~12min)", value: 250_000 },
    { label: "500k (production ~25min)", value: 500_000 },
  ];

  return (
    <section className="rounded-xl p-5 bg-panel border border-panel-border">
      <SectionHeader
        title="Start RL Training"
        subtitle="Trains PPO agent on historical OHLCV data. Runs in background — poll status below."
      />
      <form onSubmit={handleSubmit} className="flex flex-wrap items-end gap-4">
        <div className="flex flex-col gap-1.5">
          <label className="font-mono text-[10px] uppercase tracking-wider text-[#555]">Symbol</label>
          <select className={selectCls} value={symbol} onChange={(e) => setSymbol(e.target.value)}>
            {["MES", "MNQ", "MCL", "MGC"].map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>

        <div className="flex flex-col gap-1.5">
          <label className="font-mono text-[10px] uppercase tracking-wider text-[#555]">Interval</label>
          <select className={selectCls} value={barInterval} onChange={(e) => setBarInterval(e.target.value)}>
            {["1h", "4h", "1d"].map((i) => <option key={i} value={i}>{i}</option>)}
          </select>
        </div>

        <div className="flex flex-col gap-1.5">
          <label className="font-mono text-[10px] uppercase tracking-wider text-[#555]">Timesteps</label>
          <select
            className={`${selectCls} min-w-[200px]`}
            value={timesteps}
            onChange={(e) => setTimesteps(Number(e.target.value))}
          >
            {TIMESTEP_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </div>

        <button
          type="submit"
          disabled={isRunning || loading}
          className={`flex items-center gap-2 font-mono text-xs font-bold px-4 py-2 rounded-lg transition-all border ${
            isRunning
              ? "bg-panel-border border-[#333] text-[#555] cursor-not-allowed"
              : "bg-[#00ff8820] border-[#00ff8860] text-[#00ff88] cursor-pointer"
          }`}
        >
          {loading ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
          {isRunning ? "Training in progress..." : "Start Training"}
        </button>
      </form>
    </section>
  );
}

// ── Training Status Panel ─────────────────────────────────────────────────────

function TrainingStatusPanel({ status }: { status: TrainingStatus | null }) {
  if (!status) return null;

  const isRunning = status.running;
  const progressPct = status.progress_pct ?? 0;
  const result = status.last_result;

  return (
    <section className="rounded-xl p-5 bg-panel border border-panel-border">
      <div className="flex items-center justify-between mb-4">
        <SectionHeader title="Training Status" subtitle={isRunning ? `Training ${status.symbol ?? "..."} — polling every 3s` : "Last completed run"} />
        <Badge
          label={isRunning ? "RUNNING" : status.error ? "ERROR" : result ? "COMPLETE" : "IDLE"}
          color={isRunning ? "#00d4ff" : status.error ? "#ff4444" : result ? "#00ff88" : "#555"}
        />
      </div>

      {/* Progress bar (always visible when running or has result) */}
      {(isRunning || result) && (
        <div className="mb-5">
          <div className="flex items-center justify-between mb-1">
            <span className="font-mono text-[10px] text-[#555]">
              {isRunning ? `${status.symbol} — ${progressPct}%` : `${result?.symbol} ${result?.interval} — completed`}
            </span>
            {isRunning && status.started_at && (
              <span className="font-mono text-[10px] text-[#555]">
                <Clock className="inline h-3 w-3 mr-1" />
                {new Date(status.started_at).toLocaleTimeString()}
              </span>
            )}
          </div>
          <div className="h-2 rounded-full overflow-hidden bg-[#111]">
            <div
              className={`h-full rounded-full transition-all duration-500 ${isRunning ? "bg-[#00d4ff]" : "bg-[#00ff88]"}`}
              style={{ width: `${isRunning ? progressPct : 100}%` }}
            />
          </div>
        </div>
      )}

      {/* Error */}
      {status.error && (
        <div className="rounded-lg p-3 font-mono text-xs mb-4 bg-[#ff444410] border border-[#ff444430] text-[#ff9999]">
          {status.error}
        </div>
      )}

      {/* Last result summary */}
      {result?.metrics && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {[
            { label: "Profit Factor", value: result.metrics.profit_factor?.toFixed(2) ?? "—", gate: GATES.min_profit_factor, inv: false },
            { label: "Sharpe", value: result.metrics.sharpe_ratio?.toFixed(2) ?? "—", gate: GATES.min_sharpe, inv: false },
            { label: "Win Rate", value: pct(result.metrics.win_rate ?? 0), gate: GATES.min_win_rate, inv: false, raw: result.metrics.win_rate },
            { label: "Hold Rate", value: pct(result.metrics.hold_rate ?? 0), gate: GATES.min_hold_rate, inv: false, raw: result.metrics.hold_rate },
            ...(result.metrics.flat_hold_rate !== undefined ? [{ label: "Flat Hold Rate", value: pct(result.metrics.flat_hold_rate), gate: GATES.min_hold_rate, inv: false, raw: result.metrics.flat_hold_rate }] : []),
            { label: "Trades", value: String(result.metrics.n_trades ?? 0), gate: GATES.min_trades, inv: false, raw: result.metrics.n_trades },
            { label: "Max DD", value: pct(result.metrics.max_drawdown ?? 0), gate: GATES.max_drawdown, inv: true, raw: result.metrics.max_drawdown },
            { label: "Train Bars", value: String(result.train_bars ?? 0), gate: 0, inv: false },
            { label: "Test Bars", value: String(result.test_bars ?? 0), gate: 0, inv: false },
          ].map(({ label, value, gate, inv, raw }) => {
            const colorClass = gate > 0
              ? metricColorClass(raw ?? parseFloat(value), gate, inv)
              : "text-[#888]";
            return (
              <div
                key={label}
                className="rounded-lg p-3 bg-[#111] border border-panel-border"
              >
                <div className="font-mono text-[9px] uppercase tracking-wider mb-1 text-[#555]">{label}</div>
                <div className={`font-mono text-lg font-bold tabular-nums ${colorClass}`}>{value}</div>
              </div>
            );
          })}
        </div>
      )}

      {/* Validation verdict */}
      {result?.metrics && (
        <div className="mt-4 pt-3 flex items-center gap-3 border-t border-panel-border">
          <span className="font-mono text-[10px] text-[#555]">VALIDATION:</span>
          <Badge
            label={result.metrics.passes_validation ? "PASS ✓" : "FAIL ✗"}
            color={result.metrics.passes_validation ? "#00ff88" : "#ff4444"}
          />
          {result.completed_at && (
            <span className="font-mono text-[10px] ml-auto text-[#333]">
              completed {new Date(result.completed_at).toLocaleString()}
            </span>
          )}
        </div>
      )}
    </section>
  );
}

// ── Action Distribution ───────────────────────────────────────────────────────

function ActionDistributionPanel({ metrics }: { metrics: Metrics | null }) {
  if (!metrics?.action_distribution) return null;

  const dist = metrics.action_distribution;
  const total = Object.values(dist).reduce((a, b) => a + b, 0) || 1;

  const actions: { key: string; label: string; textClass: string; bgClass: string }[] = [
    { key: "HOLD", label: "HOLD", textClass: "text-[#888]", bgClass: "bg-[#888]" },
    { key: "BUY",  label: "BUY",  textClass: "text-[#00ff88]", bgClass: "bg-[#00ff88]" },
    { key: "SELL", label: "SELL", textClass: "text-[#ff4444]", bgClass: "bg-[#ff4444]" },
    { key: "CLOSE",label: "CLOSE",textClass: "text-[#00d4ff]", bgClass: "bg-[#00d4ff]" },
  ];

  return (
    <section className="rounded-xl p-5 bg-panel border border-panel-border">
      <SectionHeader
        title="Action Distribution"
        subtitle="RL agent action breakdown on OOS test set. HOLD ≥ 50% = quality signal."
      />
      <div className="space-y-3">
        {actions.map(({ key, label, textClass, bgClass }) => {
          const count = dist[key] ?? 0;
          const fraction = count / total;
          const isHold = key === "HOLD";
          const holdOk = isHold && fraction >= GATES.min_hold_rate;
          const barTextClass = isHold ? (holdOk ? "text-[#00ff88]" : "text-[#ff4444]") : textClass;
          const barBgClass = isHold ? (holdOk ? "bg-[#00ff88]" : "bg-[#ff4444]") : bgClass;

          return (
            <div key={key} className="flex items-center gap-3">
              <div className={`w-12 font-mono text-[11px] font-bold text-right ${textClass}`}>
                {label}
              </div>
              <div className="flex-1 h-5 rounded bg-[#111]">
                <div
                  className={`h-full rounded transition-all duration-700 opacity-75 ${barBgClass}`}
                  style={{ width: `${fraction * 100}%` }}
                />
              </div>
              <div className={`w-20 font-mono text-xs tabular-nums text-right ${barTextClass}`}>
                {pct(fraction)}
              </div>
              <div className="w-14 font-mono text-[10px] tabular-nums text-right text-[#555]">
                ({count.toLocaleString()})
              </div>
            </div>
          );
        })}
      </div>

      {/* Hold rate quality check */}
      <div className="mt-4 pt-3 flex items-center gap-2 border-t border-panel-border">
        <span className="font-mono text-[10px] text-[#555]">HOLD RATE GATE (≥50%):</span>
        {(() => {
          const holdPct = (dist["HOLD"] ?? 0) / total;
          return <Badge label={holdPct >= 0.5 ? `${pct(holdPct)} ✓` : `${pct(holdPct)} ✗`} color={holdPct >= 0.5 ? "#00ff88" : "#ff4444"} />;
        })()}
      </div>
    </section>
  );
}

// ── Validation Gates Panel ────────────────────────────────────────────────────

function ValidationGatesPanel({ metrics }: { metrics: Metrics | null }) {
  const gates = [
    { label: "Profit Factor",  target: `≥ ${GATES.min_profit_factor}`, actual: metrics?.profit_factor?.toFixed(2) ?? "—",  raw: metrics?.profit_factor,  min: GATES.min_profit_factor, inv: false },
    { label: "Sharpe Ratio",   target: `≥ ${GATES.min_sharpe}`,        actual: metrics?.sharpe_ratio?.toFixed(2) ?? "—",   raw: metrics?.sharpe_ratio,   min: GATES.min_sharpe,        inv: false },
    { label: "Win Rate",       target: "≥ 55%",                        actual: metrics ? pct(metrics.win_rate) : "—",      raw: metrics?.win_rate,       min: GATES.min_win_rate,      inv: false },
    { label: "Min Trades",     target: `≥ ${GATES.min_trades}`,        actual: String(metrics?.n_trades ?? "—"),           raw: metrics?.n_trades,       min: GATES.min_trades,        inv: false },
    { label: "Hold Rate",      target: "≥ 50%",                        actual: metrics ? pct(metrics.hold_rate) : "—",          raw: metrics?.hold_rate,       min: GATES.min_hold_rate, inv: false },
    ...(metrics?.flat_hold_rate !== undefined ? [{ label: "Flat Hold Rate", target: "≥ 50%", actual: pct(metrics.flat_hold_rate), raw: metrics.flat_hold_rate, min: GATES.min_hold_rate, inv: false }] : []),
    { label: "Max Drawdown",   target: "≤ 15%",                        actual: metrics ? pct(metrics.max_drawdown) : "—", raw: metrics?.max_drawdown,   min: GATES.max_drawdown,      inv: true  },
  ];

  return (
    <section className="rounded-xl p-5 bg-panel border border-panel-border">
      <SectionHeader
        title="Validation Gates"
        subtitle="All gates must pass before RL agent can paper trade. Same targets as existing STC pipeline."
      />
      <div className="overflow-x-auto">
        <table className="w-full font-mono text-xs">
          <thead>
            <tr className="border-b border-panel-border">
              {["Metric", "Target", "Actual", "Status"].map((h) => (
                <th
                  key={h}
                  className={`pb-2 px-3 font-semibold uppercase tracking-wider text-[10px] text-[#555] ${h === "Metric" ? "text-left" : "text-center"}`}
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {gates.map(({ label, target, actual, raw, min, inv }) => {
              const hasData = raw !== undefined && raw !== null;
              const passes = hasData ? (inv ? raw <= min : raw >= min) : null;
              const colorClass = !hasData ? "text-[#555]" : passes ? "text-[#00ff88]" : "text-[#ff4444]";
              return (
                <tr
                  key={label}
                  className="hover:bg-white/[0.02] transition-colors border-b border-[#111]"
                >
                  <td className="py-2.5 px-3 font-semibold text-[#e0e0e0]">{label}</td>
                  <td className="py-2.5 px-3 text-center tabular-nums text-[#888]">{target}</td>
                  <td className={`py-2.5 px-3 text-center tabular-nums font-bold ${colorClass}`}>{actual}</td>
                  <td className="py-2.5 px-3 text-center">
                    {passes === null
                      ? <span className="text-[#333]">—</span>
                      : passes
                        ? <CheckCircle className="inline h-4 w-4 text-[#00ff88]" />
                        : <XCircle className="inline h-4 w-4 text-[#ff4444]" />
                    }
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Overall verdict */}
      {metrics && (
        <div className="mt-4 pt-3 flex items-center gap-3 border-t border-panel-border">
          <span className="font-mono text-[10px] text-[#555]">OVERALL VERDICT:</span>
          <Badge
            label={metrics.passes_validation ? "APPROVED FOR PAPER TRADING" : "NOT YET APPROVED"}
            color={metrics.passes_validation ? "#00ff88" : "#ff4444"}
          />
        </div>
      )}
      {!metrics && (
        <div className="mt-4 pt-3 border-t border-panel-border">
          <p className="font-mono text-[10px] text-[#333]">
            No model evaluated yet. Run training to populate metrics.
          </p>
        </div>
      )}
    </section>
  );
}

// ── Walk-Forward Results Table ────────────────────────────────────────────────

interface WalkForwardRow {
  symbol: string;
  window: string;
  sharpe: number | null;
  profit_factor: number | null;
  win_rate: number | null;
  hold_rate: number | null;
  passes: boolean | null;
}

function WalkForwardResultsPanel({ models, latestResult }: { models: SavedModel[]; latestResult: TrainingResult | null }) {
  // Build rows: one per saved model, plus the latest in-memory result if not already represented
  const rows: WalkForwardRow[] = models.map((m) => {
    const meta = m.metadata as Record<string, unknown>;
    const mets = (meta?.metrics ?? {}) as Partial<Metrics>;
    const interval = (meta?.interval as string | undefined) ?? "—";
    const trainBars = (meta?.train_bars as number | undefined) ?? 0;
    const testBars = (meta?.test_bars as number | undefined) ?? 0;
    const window = trainBars && testBars
      ? `${trainBars}tr / ${testBars}te`
      : interval !== "—" ? interval : "—";
    return {
      symbol: m.symbol,
      window,
      sharpe: mets.sharpe_ratio ?? null,
      profit_factor: mets.profit_factor ?? null,
      win_rate: mets.win_rate ?? null,
      hold_rate: mets.hold_rate ?? null,
      passes: mets.passes_validation ?? null,
    };
  });

  // Prepend latest in-memory result if it isn't already in the models list
  if (latestResult?.metrics) {
    const already = rows.some((r) => r.symbol === latestResult.symbol);
    if (!already) {
      rows.unshift({
        symbol: latestResult.symbol,
        window: `${latestResult.train_bars}tr / ${latestResult.test_bars}te`,
        sharpe: latestResult.metrics.sharpe_ratio ?? null,
        profit_factor: latestResult.metrics.profit_factor ?? null,
        win_rate: latestResult.metrics.win_rate ?? null,
        hold_rate: latestResult.metrics.hold_rate ?? null,
        passes: latestResult.metrics.passes_validation ?? null,
      });
    }
  }

  const legend = [
    { label: "PF", target: "≥ 2.0" },
    { label: "Sharpe", target: "≥ 1.5" },
    { label: "WR", target: "≥ 55%" },
    { label: "HOLD", target: "≥ 50%" },
  ];

  return (
    <section className="rounded-xl p-5" style={{ backgroundColor: "#0a0a0a", border: "1px solid #1a1a2e" }}>
      <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
        <SectionHeader
          title="Walk-Forward Results"
          subtitle="OOS evaluation metrics per trained symbol. All 4 targets must pass for paper trading approval."
        />
        {/* Legend */}
        <div className="flex flex-wrap gap-3">
          {legend.map(({ label, target }) => (
            <span key={label} className="font-mono text-[10px]" style={{ color: "#555" }}>
              <span style={{ color: "#888" }}>{label}</span> {target}
            </span>
          ))}
        </div>
      </div>

      {rows.length === 0 ? (
        <p className="font-mono text-xs" style={{ color: "#333" }}>
          No walk-forward results yet. Train a symbol to populate this table.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full font-mono text-xs">
            <thead>
              <tr style={{ borderBottom: "1px solid #1a1a2e" }}>
                {["Symbol", "Window", "Sharpe", "Profit Factor", "Win Rate", "HOLD Rate", "Status"].map((h) => (
                  <th
                    key={h}
                    className={`pb-2 px-3 font-semibold uppercase tracking-wider ${h === "Symbol" ? "text-left" : "text-center"}`}
                    style={{ color: "#555", fontSize: "10px" }}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => {
                const allPass =
                  row.sharpe !== null && row.sharpe >= GATES.min_sharpe &&
                  row.profit_factor !== null && row.profit_factor >= GATES.min_profit_factor &&
                  row.win_rate !== null && row.win_rate >= GATES.min_win_rate &&
                  row.hold_rate !== null && row.hold_rate >= GATES.min_hold_rate;
                const anyData = row.sharpe !== null || row.profit_factor !== null;
                const marginal = anyData && !allPass && (
                  (row.sharpe ?? 0) >= GATES.min_sharpe * 0.75 ||
                  (row.profit_factor ?? 0) >= GATES.min_profit_factor * 0.75
                );
                const statusColor = !anyData ? "#555" : allPass ? "#00ff88" : marginal ? "#ffcc00" : "#ff4444";
                const statusLabel = !anyData ? "—" : allPass ? "PASS" : marginal ? "MARGINAL" : "FAIL";

                return (
                  <tr
                    key={i}
                    className="hover:bg-white/[0.02] transition-colors"
                    style={{ borderBottom: "1px solid #111" }}
                  >
                    <td className="py-2.5 px-3 font-bold" style={{ color: "#e0e0e0" }}>{row.symbol}</td>
                    <td className="py-2.5 px-3 text-center tabular-nums" style={{ color: "#666" }}>{row.window}</td>
                    <td className="py-2.5 px-3 text-center tabular-nums font-semibold" style={{ color: row.sharpe !== null ? metricColor(row.sharpe, GATES.min_sharpe) : "#555" }}>
                      {row.sharpe?.toFixed(2) ?? "—"}
                    </td>
                    <td className="py-2.5 px-3 text-center tabular-nums font-semibold" style={{ color: row.profit_factor !== null ? metricColor(row.profit_factor, GATES.min_profit_factor) : "#555" }}>
                      {row.profit_factor?.toFixed(2) ?? "—"}
                    </td>
                    <td className="py-2.5 px-3 text-center tabular-nums font-semibold" style={{ color: row.win_rate !== null ? metricColor(row.win_rate, GATES.min_win_rate) : "#555" }}>
                      {row.win_rate !== null ? pct(row.win_rate) : "—"}
                    </td>
                    <td className="py-2.5 px-3 text-center tabular-nums font-semibold" style={{ color: row.hold_rate !== null ? metricColor(row.hold_rate, GATES.min_hold_rate) : "#555" }}>
                      {row.hold_rate !== null ? pct(row.hold_rate) : "—"}
                    </td>
                    <td className="py-2.5 px-3 text-center">
                      <Badge label={statusLabel} color={statusColor} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

// ── RL vs STC Comparison ──────────────────────────────────────────────────────

// HARDCODED STC backtest benchmarks captured from a prior validated walk-forward.
// These are static constants, NOT recomputed live — keep them clearly labelled as
// such wherever they render next to live RL OOS metrics (no implied parity).
const STC_BENCHMARKS: Record<string, { pf: number; sharpe: number; wr: number; symbol: string; tf: string }> = {
  MNQ: { pf: 1.46, sharpe: 0.19, wr: 47.7, symbol: "MNQ", tf: "1h" },
  MCL: { pf: 1.83, sharpe: 0.15, wr: 60.0, symbol: "MCL", tf: "1h" },
  MGC: { pf: 2.60, sharpe: 2.04, wr: 51.1, symbol: "MGC", tf: "1d" },
  MES: { pf: 0.96, sharpe: -0.12, wr: 42.9, symbol: "MES", tf: "1h" },
};

function RLvsSTC({ latestResult }: { latestResult: TrainingResult | null }) {
  if (!latestResult?.metrics) {
    return (
      <section className="rounded-xl p-5" style={{ backgroundColor: "#0a0a0a", border: "1px solid #1a1a2e" }}>
        <SectionHeader
          title="RL vs STC Comparison"
          subtitle="Side-by-side: RL agent OOS metrics vs existing STC pipeline backtest benchmarks."
        />
        <p className="font-mono text-xs" style={{ color: "#333" }}>
          Train a symbol to see RL vs STC comparison. STC benchmarks are static constants from a prior validated walk-forward (not recomputed live).
        </p>
      </section>
    );
  }

  const sym = latestResult.symbol;
  const stc = STC_BENCHMARKS[sym] ?? null;
  const rl = latestResult.metrics;

  interface CompRow {
    metric: string;
    rl: string;
    stc: string;
    rlColor: string;
    stcColor: string;
    delta: string;
    deltaColor: string;
  }

  const rows: CompRow[] = [
    {
      metric: "Profit Factor",
      rl: rl.profit_factor?.toFixed(2) ?? "—",
      stc: stc ? stc.pf.toFixed(2) : "N/A",
      rlColor: rl.profit_factor ? metricColor(rl.profit_factor, GATES.min_profit_factor) : "#555",
      stcColor: stc ? metricColor(stc.pf, GATES.min_profit_factor) : "#555",
      delta: stc && rl.profit_factor ? (rl.profit_factor - stc.pf >= 0 ? "+" : "") + (rl.profit_factor - stc.pf).toFixed(2) : "—",
      deltaColor: stc && rl.profit_factor ? (rl.profit_factor >= stc.pf ? "#00ff88" : "#ff4444") : "#555",
    },
    {
      metric: "Sharpe Ratio",
      rl: rl.sharpe_ratio?.toFixed(2) ?? "—",
      stc: stc ? stc.sharpe.toFixed(2) : "N/A",
      rlColor: rl.sharpe_ratio ? metricColor(rl.sharpe_ratio, GATES.min_sharpe) : "#555",
      stcColor: stc ? metricColor(stc.sharpe, GATES.min_sharpe) : "#555",
      delta: stc && rl.sharpe_ratio ? (rl.sharpe_ratio - stc.sharpe >= 0 ? "+" : "") + (rl.sharpe_ratio - stc.sharpe).toFixed(2) : "—",
      deltaColor: stc && rl.sharpe_ratio ? (rl.sharpe_ratio >= stc.sharpe ? "#00ff88" : "#ff4444") : "#555",
    },
    {
      metric: "Win Rate",
      rl: pct(rl.win_rate ?? 0),
      stc: stc ? `${stc.wr.toFixed(1)}%` : "N/A",
      rlColor: rl.win_rate ? metricColor(rl.win_rate, GATES.min_win_rate) : "#555",
      stcColor: stc ? metricColor(stc.wr / 100, GATES.min_win_rate) : "#555",
      delta: stc && rl.win_rate ? (((rl.win_rate * 100) - stc.wr) >= 0 ? "+" : "") + ((rl.win_rate * 100) - stc.wr).toFixed(1) + "pp" : "—",
      deltaColor: stc && rl.win_rate ? (rl.win_rate * 100 >= stc.wr ? "#00ff88" : "#ff4444") : "#555",
    },
    {
      metric: "Max Drawdown",
      rl: pct(rl.max_drawdown ?? 0),
      stc: "N/A",
      rlColor: rl.max_drawdown !== undefined ? metricColor(rl.max_drawdown, GATES.max_drawdown, true) : "#555",
      stcColor: "#555",
      delta: "—",
      deltaColor: "#555",
    },
  ];

  const rlWins = rows.filter((r) => r.delta !== "—" && r.delta !== "N/A" && !r.delta.startsWith("-")).length;

  return (
    <section className="rounded-xl p-5" style={{ backgroundColor: "#0a0a0a", border: "1px solid #1a1a2e" }}>
      <div className="flex items-start justify-between mb-4 flex-wrap gap-3">
        <SectionHeader
          title="RL vs STC Comparison"
          subtitle={`${sym} — RL agent OOS metrics vs STC pipeline backtest benchmark${stc ? ` (${stc.tf} timeframe)` : ""}`}
        />
        {stc && (
          <span
            className="font-mono text-[10px] font-bold px-2 py-1 rounded"
            style={{ backgroundColor: "#00d4ff10", border: "1px solid #00d4ff30", color: "#00d4ff" }}
          >
            RL beats STC on {rlWins}/{rows.filter((r) => r.delta !== "—").length} metrics
          </span>
        )}
      </div>

      <div className="overflow-x-auto">
        <table className="w-full font-mono text-xs">
          <thead>
            <tr style={{ borderBottom: "1px solid #1a1a2e" }}>
              {["Metric", "RL Agent (OOS)", "STC Pipeline (static BT)", "Delta"].map((h) => (
                <th
                  key={h}
                  className={`pb-2 px-3 font-semibold uppercase tracking-wider ${h === "Metric" ? "text-left" : "text-center"}`}
                  style={{ color: "#555", fontSize: "10px" }}
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map(({ metric, rl: rlVal, stc: stcVal, rlColor, stcColor, delta, deltaColor }) => (
              <tr
                key={metric}
                className="hover:bg-white/[0.02] transition-colors"
                style={{ borderBottom: "1px solid #111" }}
              >
                <td className="py-2.5 px-3 font-semibold" style={{ color: "#e0e0e0" }}>{metric}</td>
                <td className="py-2.5 px-3 text-center tabular-nums font-bold" style={{ color: rlColor }}>{rlVal}</td>
                <td className="py-2.5 px-3 text-center tabular-nums" style={{ color: stcColor }}>{stcVal}</td>
                <td className="py-2.5 px-3 text-center tabular-nums font-semibold" style={{ color: deltaColor }}>{delta}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {!stc && (
        <div
          className="mt-3 rounded p-2 font-mono text-[10px]"
          style={{ backgroundColor: "#ffcc0010", border: "1px solid #ffcc0030", color: "#ffcc0099" }}
        >
          No STC benchmark data for {sym}. Add it to STC_BENCHMARKS once a backtest is run.
        </div>
      )}

      <div className="mt-4 pt-3 font-mono text-[10px]" style={{ borderTop: "1px solid #1a1a2e", color: "#333" }}>
        STC benchmark = historical backtest metrics. RL = OOS test set (held-out 6-month window). Direct comparison is approximate.
      </div>
    </section>
  );
}

// ── Models List ───────────────────────────────────────────────────────────────

function ModelsListPanel({ models }: { models: SavedModel[] }) {
  return (
    <section className="rounded-xl p-5" style={{ backgroundColor: "#0a0a0a", border: "1px solid #1a1a2e" }}>
      <div className="flex items-center justify-between mb-4">
        <SectionHeader title="Saved Models" subtitle="PPO checkpoints at data/rl_models/" />
        <span className="font-mono text-xs" style={{ color: "#555" }}>{models.length} model{models.length !== 1 ? "s" : ""}</span>
      </div>

      {models.length === 0 ? (
        <p className="font-mono text-xs" style={{ color: "#333" }}>
          No saved models yet. Train a symbol to generate the first checkpoint.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full font-mono text-xs">
            <thead>
              <tr style={{ borderBottom: "1px solid #1a1a2e" }}>
                {["Symbol", "Size", "PF", "Sharpe", "WR", "Validation", "Path"].map((h) => (
                  <th
                    key={h}
                    className={`pb-2 px-2 font-semibold uppercase tracking-wider ${h === "Path" ? "text-left" : "text-center"}`}
                    style={{ color: "#555", fontSize: "10px" }}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {models.map((m, i) => {
                const meta = m.metadata as Record<string, unknown>;
                const mets = (meta?.metrics ?? {}) as Partial<Metrics>;
                const passes = mets.passes_validation;
                return (
                  <tr
                    key={i}
                    className="hover:bg-white/[0.02] transition-colors"
                    style={{ borderBottom: "1px solid #111" }}
                  >
                    <td className="py-2 px-2 text-center font-bold" style={{ color: "#e0e0e0" }}>{m.symbol}</td>
                    <td className="py-2 px-2 text-center tabular-nums" style={{ color: "#888" }}>{m.size_kb}kb</td>
                    <td className="py-2 px-2 text-center tabular-nums" style={{ color: mets.profit_factor ? metricColor(mets.profit_factor, GATES.min_profit_factor) : "#555" }}>
                      {mets.profit_factor?.toFixed(2) ?? "—"}
                    </td>
                    <td className="py-2 px-2 text-center tabular-nums" style={{ color: mets.sharpe_ratio ? metricColor(mets.sharpe_ratio, GATES.min_sharpe) : "#555" }}>
                      {mets.sharpe_ratio?.toFixed(2) ?? "—"}
                    </td>
                    <td className="py-2 px-2 text-center tabular-nums" style={{ color: mets.win_rate ? metricColor(mets.win_rate, GATES.min_win_rate) : "#555" }}>
                      {mets.win_rate ? pct(mets.win_rate) : "—"}
                    </td>
                    <td className="py-2 px-2 text-center">
                      {passes === undefined
                        ? <span style={{ color: "#333" }}>—</span>
                        : passes
                          ? <Badge label="PASS" color="#00ff88" />
                          : <Badge label="FAIL" color="#ff4444" />
                      }
                    </td>
                    <td className="py-2 px-2 text-left max-w-xs truncate" style={{ color: "#444", fontSize: "10px" }}>
                      {m.path}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

// ── Training History Panel ────────────────────────────────────────────────────

const RUN_STATUS_COLORS: Record<string, string> = {
  complete:  "#00ff88",
  running:   "#00d4ff",
  error:     "#ff4444",
  queued:    "#ffcc00",
};

function TrainingHistoryPanel({ runs }: { runs: RecentRun[] }) {
  if (runs.length === 0) {
    return (
      <section className="rounded-xl p-5" style={{ backgroundColor: "#0a0a0a", border: "1px solid #1a1a2e" }}>
        <SectionHeader
          title="Training History"
          subtitle="Recent training runs this session. Clears on engine restart."
        />
        <p className="font-mono text-xs" style={{ color: "#333" }}>
          No runs recorded yet. Start training to see history here.
        </p>
      </section>
    );
  }

  return (
    <section className="rounded-xl p-5" style={{ backgroundColor: "#0a0a0a", border: "1px solid #1a1a2e" }}>
      <div className="flex items-center justify-between mb-4">
        <SectionHeader
          title="Training History"
          subtitle="Recent training runs this session (up to 5). Clears on engine restart."
        />
        <span className="font-mono text-xs" style={{ color: "#555" }}>
          {runs.length} run{runs.length !== 1 ? "s" : ""}
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full font-mono text-xs">
          <thead>
            <tr style={{ borderBottom: "1px solid #1a1a2e" }}>
              {["Run ID", "Symbol", "Status", "Trades", "Profit Factor", "Started", "Completed"].map((h) => (
                <th
                  key={h}
                  className={`pb-2 px-3 font-semibold uppercase tracking-wider ${h === "Run ID" ? "text-left" : "text-center"}`}
                  style={{ color: "#555", fontSize: "10px" }}
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {runs.map((run) => {
              const statusColor = RUN_STATUS_COLORS[run.status] ?? "#888";
              const pfColor = run.profit_factor !== undefined
                ? metricColor(run.profit_factor, GATES.min_profit_factor)
                : "#555";
              const tradesColor = run.n_trades !== undefined
                ? metricColor(run.n_trades, GATES.min_trades)
                : "#555";
              return (
                <tr
                  key={run.run_id}
                  className="hover:bg-white/[0.02] transition-colors"
                  style={{ borderBottom: "1px solid #111" }}
                >
                  <td className="py-2.5 px-3 text-left">
                    <span
                      className="font-mono tabular-nums"
                      style={{ color: "#444", fontSize: "9px" }}
                      title={run.run_id}
                    >
                      {run.run_id.slice(0, 8)}…
                    </span>
                  </td>
                  <td className="py-2.5 px-3 text-center font-bold" style={{ color: "#e0e0e0" }}>
                    {run.symbol}
                  </td>
                  <td className="py-2.5 px-3 text-center">
                    <Badge label={run.status.toUpperCase()} color={statusColor} />
                  </td>
                  <td className="py-2.5 px-3 text-center tabular-nums font-bold" style={{ color: tradesColor }}>
                    {run.n_trades !== undefined ? run.n_trades : "—"}
                  </td>
                  <td className="py-2.5 px-3 text-center tabular-nums font-bold" style={{ color: pfColor }}>
                    {run.profit_factor !== undefined ? run.profit_factor.toFixed(2) : "—"}
                  </td>
                  <td className="py-2.5 px-3 text-center tabular-nums" style={{ color: "#555" }}>
                    {run.started_at ? new Date(run.started_at).toLocaleTimeString() : "—"}
                  </td>
                  <td className="py-2.5 px-3 text-center tabular-nums" style={{ color: "#555" }}>
                    {run.completed_at ? new Date(run.completed_at).toLocaleTimeString() : run.status === "running" ? <span style={{ color: "#00d4ff" }}>in progress…</span> : "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

// ── Executor Status Panel ─────────────────────────────────────────────────────

const ACTION_COLORS: Record<string, string> = {
  HOLD:  "#888",
  BUY:   "#00ff88",
  SELL:  "#ff4444",
  CLOSE: "#00d4ff",
};

function positionLabel(p: number): { label: string; color: string } {
  if (p === 1)  return { label: "LONG",  color: "#00ff88" };
  if (p === -1) return { label: "SHORT", color: "#ff4444" };
  return          { label: "FLAT",  color: "#888" };
}

function basename(path: string): string {
  return path.split(/[/\\]/).pop() ?? path;
}

function ExecutorStatusPanel({
  executors,
  models,
  onDeploy,
  onUndeploy,
}: {
  executors: Record<string, ExecutorInfo>;
  models: SavedModel[];
  onDeploy: (symbol: string, model_path: string) => Promise<void>;
  onUndeploy: (symbol: string) => Promise<void>;
}) {
  const [showForm, setShowForm] = useState(false);
  const [deploySymbol, setDeploySymbol] = useState("MES");
  const [deployModel, setDeployModel] = useState("");
  const [deployLoading, setDeployLoading] = useState(false);

  const entries = Object.values(executors);

  const selectCls = "font-mono text-xs rounded-lg px-3 py-2 outline-none cursor-pointer";
  const selectStyle: React.CSSProperties = { backgroundColor: "#111", border: "1px solid #1a1a2e", color: "#e0e0e0" };

  async function handleDeploy(e: React.FormEvent) {
    e.preventDefault();
    if (!deployModel) return;
    setDeployLoading(true);
    try {
      await onDeploy(deploySymbol, deployModel);
      setShowForm(false);
    } finally {
      setDeployLoading(false);
    }
  }

  return (
    <section className="rounded-xl p-5" style={{ backgroundColor: "#0a0a0a", border: "1px solid #1a1a2e" }}>
      <div className="flex items-center justify-between mb-4">
        <SectionHeader
          title="Executor Status"
          subtitle="Deployed RL models running in paper-trading mode. Polls every 5s when active."
        />
        <div className="flex items-center gap-2">
          <span className="font-mono text-xs" style={{ color: "#555" }}>
            {entries.filter((e) => e.is_running).length} running
          </span>
          <button
            onClick={() => setShowForm((v) => !v)}
            className="flex items-center gap-1.5 font-mono text-xs font-bold px-3 py-1.5 rounded-lg transition-all"
            style={{
              backgroundColor: "#00ff8818",
              border: "1px solid #00ff8840",
              color: "#00ff88",
              cursor: "pointer",
            }}
          >
            <Cpu className="h-3.5 w-3.5" />
            Deploy Model
          </button>
        </div>
      </div>

      {/* Deploy form */}
      {showForm && (
        <form
          onSubmit={handleDeploy}
          className="mb-5 rounded-lg p-4 flex flex-wrap items-end gap-4"
          style={{ backgroundColor: "#111", border: "1px solid #1a1a2e" }}
        >
          <div className="flex flex-col gap-1.5">
            <label className="font-mono text-[10px] uppercase tracking-wider" style={{ color: "#555" }}>Symbol</label>
            <select
              className={selectCls}
              style={selectStyle}
              value={deploySymbol}
              onChange={(e) => setDeploySymbol(e.target.value)}
            >
              {["MES", "MNQ", "MCL", "MGC"].map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>

          <div className="flex flex-col gap-1.5 flex-1 min-w-[220px]">
            <label className="font-mono text-[10px] uppercase tracking-wider" style={{ color: "#555" }}>
              Model Path
            </label>
            {models.length > 0 ? (
              <select
                className={selectCls}
                style={{ ...selectStyle, minWidth: "220px" }}
                value={deployModel}
                onChange={(e) => setDeployModel(e.target.value)}
              >
                <option value="">— select model —</option>
                {models.map((m) => (
                  <option key={m.path} value={m.path}>
                    {m.symbol} — {basename(m.path)} ({m.size_kb}kb)
                  </option>
                ))}
              </select>
            ) : (
              <input
                className={selectCls}
                style={selectStyle}
                type="text"
                placeholder="data/rl_models/MES_ppo.zip"
                value={deployModel}
                onChange={(e) => setDeployModel(e.target.value)}
              />
            )}
          </div>

          <div className="flex gap-2">
            <button
              type="submit"
              disabled={deployLoading || !deployModel}
              className="flex items-center gap-1.5 font-mono text-xs font-bold px-4 py-2 rounded-lg transition-all"
              style={{
                backgroundColor: deployLoading || !deployModel ? "#1a1a2e" : "#00ff8820",
                border: `1px solid ${deployLoading || !deployModel ? "#333" : "#00ff8860"}`,
                color: deployLoading || !deployModel ? "#555" : "#00ff88",
                cursor: deployLoading || !deployModel ? "not-allowed" : "pointer",
              }}
            >
              {deployLoading ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
              Deploy
            </button>
            <button
              type="button"
              onClick={() => setShowForm(false)}
              className="font-mono text-xs px-3 py-2 rounded-lg"
              style={{ backgroundColor: "#1a1a2e", border: "1px solid #333", color: "#888", cursor: "pointer" }}
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      {/* Executor cards */}
      {entries.length === 0 ? (
        <div
          className="rounded-lg p-5 text-center font-mono text-xs"
          style={{ backgroundColor: "#111", border: "1px solid #1a1a2e", color: "#444" }}
        >
          <Activity className="h-5 w-5 mx-auto mb-2" style={{ color: "#333" }} />
          No models deployed. Click &quot;Deploy Model&quot; to start an executor.
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
          {entries.map((exec) => {
            const pos = positionLabel(exec.paper_position);
            const actionColor = exec.last_action ? (ACTION_COLORS[exec.last_action] ?? "#888") : "#555";

            return (
              <div
                key={exec.symbol}
                className="rounded-lg p-4 flex flex-col gap-3"
                style={{
                  backgroundColor: "#111",
                  border: `1px solid ${exec.is_running ? "#1a1a3e" : "#1a1a2e"}`,
                }}
              >
                {/* Header row */}
                <div className="flex items-center justify-between">
                  <Badge label={exec.symbol} color="#00d4ff" />
                  <div className="flex items-center gap-1.5">
                    <Badge
                      label={exec.is_running ? "RUNNING" : "STOPPED"}
                      color={exec.is_running ? "#00ff88" : "#555"}
                    />
                    {exec.is_running && (
                      <Badge
                        label={exec.scheduler_running ? "SCHED ON" : "SCHED OFF"}
                        color={exec.scheduler_running ? "#00d4ff" : "#ff4444"}
                      />
                    )}
                  </div>
                </div>

                {/* Model filename */}
                <div className="font-mono text-[10px] truncate" style={{ color: "#444" }} title={exec.model_path}>
                  {basename(exec.model_path)}
                </div>

                {/* Stats */}
                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <div className="font-mono text-[9px] uppercase tracking-wider mb-0.5" style={{ color: "#444" }}>
                      Last Action
                    </div>
                    <div className="font-mono text-sm font-bold" style={{ color: actionColor }}>
                      {exec.last_action ?? "—"}
                    </div>
                  </div>
                  <div>
                    <div className="font-mono text-[9px] uppercase tracking-wider mb-0.5" style={{ color: "#444" }}>
                      Position
                    </div>
                    <div className="font-mono text-sm font-bold" style={{ color: pos.color }}>
                      {pos.label}
                    </div>
                  </div>
                  <div>
                    <div className="font-mono text-[9px] uppercase tracking-wider mb-0.5" style={{ color: "#444" }}>
                      Bars Exec.
                    </div>
                    <div className="font-mono text-sm tabular-nums" style={{ color: "#888" }}>
                      {exec.bars_executed.toLocaleString()}
                    </div>
                  </div>
                  <div>
                    <div className="font-mono text-[9px] uppercase tracking-wider mb-0.5" style={{ color: "#444" }}>
                      Last Pred.
                    </div>
                    <div className="font-mono text-[10px] tabular-nums" style={{ color: "#555" }}>
                      {exec.last_prediction_time
                        ? new Date(exec.last_prediction_time).toLocaleTimeString()
                        : "—"}
                    </div>
                  </div>
                  <div>
                    <div className="font-mono text-[9px] uppercase tracking-wider mb-0.5" style={{ color: "#444" }}>
                      Scheduler
                    </div>
                    <div className="font-mono text-[10px] tabular-nums" style={{ color: exec.scheduler_running ? "#00d4ff" : "#555" }}>
                      {exec.scheduler_running ? "Active" : "Inactive"}
                    </div>
                  </div>
                  <div className="col-span-2">
                    <div className="font-mono text-[9px] uppercase tracking-wider mb-0.5" style={{ color: "#444" }}>
                      Next Scheduled Run
                    </div>
                    <div className="font-mono text-[10px]" style={{ color: exec.scheduler_running ? "#888" : "#444" }}>
                      {exec.scheduler_running
                        ? "Mon–Fri :59 (7:00–15:00 CT)"
                        : "—"}
                    </div>
                  </div>
                </div>

                {/* Error */}
                {exec.last_error && (
                  <div
                    className="rounded p-2 font-mono text-[10px]"
                    style={{ backgroundColor: "#ff444410", border: "1px solid #ff444330", color: "#ff9999" }}
                  >
                    {exec.last_error}
                  </div>
                )}

                {/* Undeploy button */}
                <button
                  onClick={() => onUndeploy(exec.symbol)}
                  className="flex items-center justify-center gap-1.5 font-mono text-[10px] font-bold px-3 py-1.5 rounded-lg transition-all mt-auto"
                  style={{
                    backgroundColor: "#ff444410",
                    border: "1px solid #ff444430",
                    color: "#ff6666",
                    cursor: "pointer",
                  }}
                >
                  <StopCircle className="h-3 w-3" />
                  Undeploy
                </button>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}

// ── Walk-Forward Windows Panel ────────────────────────────────────────────────

const WF_GATE_DEFS: Array<{ key: string; label: string; threshold: string; format: (v: number) => string; passes: (v: number) => boolean }> = [
  { key: "profit_factor", label: "Profit Factor", threshold: "≥ 2.0", format: (v) => v.toFixed(2), passes: (v) => v >= GATES.min_profit_factor },
  { key: "sharpe",        label: "Sharpe Ratio",  threshold: "≥ 1.5", format: (v) => v.toFixed(2), passes: (v) => v >= GATES.min_sharpe },
  { key: "win_rate",      label: "Win Rate",       threshold: "≥ 55%", format: (v) => pct(v),       passes: (v) => v >= GATES.min_win_rate },
  { key: "n_trades",      label: "Min Trades",     threshold: "≥ 60",  format: (v) => String(Math.round(v)), passes: (v) => v >= GATES.min_trades },
  { key: "hold_rate",     label: "Hold Rate",      threshold: "≥ 50%", format: (v) => pct(v),       passes: (v) => v >= GATES.min_hold_rate },
  { key: "max_drawdown",  label: "Max Drawdown",   threshold: "≤ 15%", format: (v) => pct(v),       passes: (v) => v <= GATES.max_drawdown },
];

function WalkForwardWindowsPanel({
  windows,
  complete,
  allPass,
}: {
  windows: WalkForwardWindow[];
  complete: boolean;
  allPass: boolean;
}) {
  if (windows.length === 0) return null;

  const passCount = windows.filter((w) => w.passes_validation).length;
  const total = windows.length;

  const overallColor = allPass ? "#00ff88" : !complete ? "#ffcc00" : "#ff4444";
  const overallLabel = allPass ? "ALL PASS" : !complete ? "IN PROGRESS" : "FAILED";

  return (
    <section className="rounded-xl p-5" style={{ backgroundColor: "#0a0a0a", border: "1px solid #1a1a2e" }}>
      <div className="flex items-center justify-between mb-5">
        <SectionHeader
          title="Walk-Forward Validation"
          subtitle={`${total}-window out-of-sample validation. All windows must pass all gates.`}
        />
        <div className="flex items-center gap-3">
          <span className="font-mono text-xs" style={{ color: "#555" }}>
            {passCount}/{total} windows pass
          </span>
          <Badge label={overallLabel} color={overallColor} />
        </div>
      </div>

      {/* Window grid — 4 per row on desktop */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {windows.map((win) => {
          const borderColor = win.passes_validation ? "#00ff8840" : "#ff444440";
          const headerColor = win.passes_validation ? "#00ff88" : "#ff4444";

          return (
            <div
              key={win.window_idx}
              className="rounded-lg p-4"
              style={{ backgroundColor: "#111", border: `1px solid ${borderColor}` }}
            >
              {/* Window header */}
              <div className="flex items-center justify-between mb-3">
                <span className="font-mono text-xs font-bold" style={{ color: "#e0e0e0" }}>
                  Window {win.window_idx + 1}
                </span>
                {win.passes_validation
                  ? <CheckCircle className="h-4 w-4" style={{ color: "#00ff88" }} />
                  : <XCircle className="h-4 w-4" style={{ color: "#ff4444" }} />
                }
              </div>

              {/* Bar info */}
              <div className="flex gap-3 mb-3">
                <span className="font-mono text-[9px] uppercase tracking-wider" style={{ color: "#444" }}>
                  Train: <span style={{ color: "#666" }}>{win.train_bars}</span>
                </span>
                <span className="font-mono text-[9px] uppercase tracking-wider" style={{ color: "#444" }}>
                  Test: <span style={{ color: "#666" }}>{win.test_bars}</span>
                </span>
              </div>

              {/* Gate rows */}
              <div className="space-y-1.5">
                {WF_GATE_DEFS.map((gate) => {
                  const raw = win.metrics[gate.key as keyof WalkForwardWindowMetrics];
                  const passed = raw !== undefined ? gate.passes(raw) : null;
                  const valueColor = passed === null ? "#555" : passed ? "#00ff88" : "#ff4444";
                  const gatePassed = win.gates_passed?.[gate.key];

                  return (
                    <div
                      key={gate.key}
                      className="flex items-center justify-between"
                    >
                      <span className="font-mono text-[9px]" style={{ color: "#555" }}>{gate.label}</span>
                      <div className="flex items-center gap-1.5">
                        <span className="font-mono text-[9px]" style={{ color: "#444" }}>{gate.threshold}</span>
                        <span className="font-mono text-[10px] font-bold tabular-nums" style={{ color: valueColor }}>
                          {raw !== undefined ? gate.format(raw) : "—"}
                        </span>
                        {gatePassed !== undefined
                          ? gatePassed
                            ? <CheckCircle className="h-3 w-3 flex-shrink-0" style={{ color: "#00ff88" }} />
                            : <XCircle    className="h-3 w-3 flex-shrink-0" style={{ color: "#ff4444" }} />
                          : passed !== null
                            ? passed
                              ? <CheckCircle className="h-3 w-3 flex-shrink-0" style={{ color: "#00ff88" }} />
                              : <XCircle    className="h-3 w-3 flex-shrink-0" style={{ color: "#ff4444" }} />
                            : <span style={{ color: "#333" }}>—</span>
                        }
                      </div>
                    </div>
                  );
                })}
              </div>

              {/* Window verdict bar */}
              <div
                className="mt-3 pt-2 font-mono text-[9px] font-bold text-center uppercase tracking-wider rounded"
                style={{
                  borderTop: "1px solid #1a1a2e",
                  color: headerColor,
                }}
              >
                {win.passes_validation ? "PASS" : "FAIL"}
              </div>
            </div>
          );
        })}
      </div>

      {/* Summary footer */}
      <div
        className="mt-5 pt-3 flex items-center justify-between"
        style={{ borderTop: "1px solid #1a1a2e" }}
      >
        <span className="font-mono text-[10px]" style={{ color: "#555" }}>
          SUMMARY: {passCount} of {total} windows pass all validation gates
        </span>
        <Badge
          label={complete ? (allPass ? "VALIDATED ✓" : `${passCount}/${total} PASS`) : "RUNNING..."}
          color={complete ? (allPass ? "#00ff88" : "#ff4444") : "#ffcc00"}
        />
      </div>
    </section>
  );
}

// ── RL Executor Status Card ───────────────────────────────────────────────────

function RLExecutorStatusCard({
  status: execStatus,
  models,
  onDeploy,
  onUndeploy,
}: {
  status: RLExecutorStatus | null;
  models: SavedModel[];
  onDeploy: (symbol: string, model_path: string) => Promise<void>;
  onUndeploy: () => Promise<void>;
}) {
  const [showDeployForm, setShowDeployForm] = useState(false);
  const [deploySymbol, setDeploySymbol] = useState("MES");
  const [deployModel, setDeployModel] = useState("");
  const [actionLoading, setActionLoading] = useState(false);

  const selectCls = "font-mono text-xs rounded-lg px-3 py-2 outline-none cursor-pointer";
  const selectStyle: React.CSSProperties = { backgroundColor: "#111", border: "1px solid #1a1a2e", color: "#e0e0e0" };

  async function handleDeploy(e: React.FormEvent) {
    e.preventDefault();
    if (!deployModel) return;
    setActionLoading(true);
    try {
      await onDeploy(deploySymbol, deployModel);
      setShowDeployForm(false);
    } finally {
      setActionLoading(false);
    }
  }

  async function handleUndeploy() {
    if (!confirm("Undeploy RL executor? This will stop live predictions.")) return;
    setActionLoading(true);
    try {
      await onUndeploy();
    } finally {
      setActionLoading(false);
    }
  }

  const deployed = execStatus?.deployed ?? false;
  const predAction = execStatus?.last_prediction ?? null;
  const predActionColor = predAction ? (ACTION_COLORS[predAction] ?? "#888") : "#555";

  return (
    <section className="rounded-xl p-5" style={{ backgroundColor: "#0a0a0a", border: "1px solid #1a1a2e" }}>
      <div className="flex items-center justify-between mb-5">
        <SectionHeader
          title="RL Executor"
          subtitle="APScheduler-based executor — deploys trained PPO model for live bar predictions. Auto-refreshes every 30s."
        />
        <div className="flex items-center gap-2">
          <Badge
            label={deployed ? "DEPLOYED" : "NOT DEPLOYED"}
            color={deployed ? "#00ff88" : "#555"}
          />
          {deployed ? (
            <button
              onClick={handleUndeploy}
              disabled={actionLoading}
              className="flex items-center gap-1.5 font-mono text-xs font-bold px-3 py-1.5 rounded-lg transition-all"
              style={{
                backgroundColor: "#ff444410",
                border: "1px solid #ff444430",
                color: actionLoading ? "#555" : "#ff6666",
                cursor: actionLoading ? "not-allowed" : "pointer",
              }}
            >
              {actionLoading ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <StopCircle className="h-3.5 w-3.5" />}
              Undeploy
            </button>
          ) : (
            <button
              onClick={() => setShowDeployForm((v) => !v)}
              className="flex items-center gap-1.5 font-mono text-xs font-bold px-3 py-1.5 rounded-lg transition-all"
              style={{
                backgroundColor: "#00ff8818",
                border: "1px solid #00ff8840",
                color: "#00ff88",
                cursor: "pointer",
              }}
            >
              <Cpu className="h-3.5 w-3.5" />
              Deploy
            </button>
          )}
        </div>
      </div>

      {/* Deploy form */}
      {showDeployForm && !deployed && (
        <form
          onSubmit={handleDeploy}
          className="mb-5 rounded-lg p-4 flex flex-wrap items-end gap-4"
          style={{ backgroundColor: "#111", border: "1px solid #1a1a2e" }}
        >
          <div className="flex flex-col gap-1.5">
            <label className="font-mono text-[10px] uppercase tracking-wider" style={{ color: "#555" }}>Symbol</label>
            <select
              className={selectCls}
              style={selectStyle}
              value={deploySymbol}
              onChange={(e) => setDeploySymbol(e.target.value)}
            >
              {["MES", "MNQ", "MCL", "MGC"].map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>

          <div className="flex flex-col gap-1.5 flex-1 min-w-[220px]">
            <label className="font-mono text-[10px] uppercase tracking-wider" style={{ color: "#555" }}>Model Path</label>
            {models.length > 0 ? (
              <select
                className={selectCls}
                style={{ ...selectStyle, minWidth: "220px" }}
                value={deployModel}
                onChange={(e) => setDeployModel(e.target.value)}
              >
                <option value="">— select model —</option>
                {models.map((m) => (
                  <option key={m.path} value={m.path}>
                    {m.symbol} — {basename(m.path)} ({m.size_kb}kb)
                  </option>
                ))}
              </select>
            ) : (
              <input
                className={selectCls}
                style={selectStyle}
                type="text"
                placeholder="data/rl_models/MES_ppo.zip"
                value={deployModel}
                onChange={(e) => setDeployModel(e.target.value)}
              />
            )}
          </div>

          <div className="flex gap-2">
            <button
              type="submit"
              disabled={actionLoading || !deployModel}
              className="flex items-center gap-1.5 font-mono text-xs font-bold px-4 py-2 rounded-lg transition-all"
              style={{
                backgroundColor: actionLoading || !deployModel ? "#1a1a2e" : "#00ff8820",
                border: `1px solid ${actionLoading || !deployModel ? "#333" : "#00ff8860"}`,
                color: actionLoading || !deployModel ? "#555" : "#00ff88",
                cursor: actionLoading || !deployModel ? "not-allowed" : "pointer",
              }}
            >
              {actionLoading ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
              Deploy
            </button>
            <button
              type="button"
              onClick={() => setShowDeployForm(false)}
              className="font-mono text-xs px-3 py-2 rounded-lg"
              style={{ backgroundColor: "#1a1a2e", border: "1px solid #333", color: "#888", cursor: "pointer" }}
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      {/* Status grid */}
      {execStatus ? (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <div className="rounded-lg p-3" style={{ backgroundColor: "#111", border: "1px solid #1a1a2e" }}>
            <div className="font-mono text-[9px] uppercase tracking-wider mb-1" style={{ color: "#555" }}>Symbol</div>
            <div className="font-mono text-sm font-bold" style={{ color: deployed ? "#00d4ff" : "#555" }}>
              {execStatus.symbol ?? "—"}
            </div>
          </div>

          <div className="rounded-lg p-3" style={{ backgroundColor: "#111", border: "1px solid #1a1a2e" }}>
            <div className="font-mono text-[9px] uppercase tracking-wider mb-1" style={{ color: "#555" }}>Last Prediction</div>
            <div className="font-mono text-sm font-bold" style={{ color: predActionColor }}>
              {predAction ?? "—"}
            </div>
          </div>

          <div className="rounded-lg p-3" style={{ backgroundColor: "#111", border: "1px solid #1a1a2e" }}>
            <div className="font-mono text-[9px] uppercase tracking-wider mb-1" style={{ color: "#555" }}>Prediction Time</div>
            <div className="font-mono text-xs tabular-nums" style={{ color: "#888" }}>
              {execStatus.last_prediction_time
                ? new Date(execStatus.last_prediction_time).toLocaleTimeString()
                : "—"}
            </div>
          </div>

          <div className="rounded-lg p-3" style={{ backgroundColor: "#111", border: "1px solid #1a1a2e" }}>
            <div className="font-mono text-[9px] uppercase tracking-wider mb-1" style={{ color: "#555" }}>Next Scheduled Run</div>
            <div className="font-mono text-xs tabular-nums" style={{ color: deployed ? "#ffcc00" : "#555" }}>
              {execStatus.next_fire_time
                ? new Date(execStatus.next_fire_time).toLocaleTimeString()
                : deployed ? "Waiting for scheduler…" : "—"}
            </div>
          </div>
        </div>
      ) : (
        <div
          className="rounded-lg p-4 text-center font-mono text-xs"
          style={{ backgroundColor: "#111", border: "1px solid #1a1a2e", color: "#444" }}
        >
          <Activity className="h-5 w-5 mx-auto mb-2" style={{ color: "#333" }} />
          Executor status unavailable — engine may be offline.
        </div>
      )}
    </section>
  );
}

// ── Walk-Forward Results Grid ─────────────────────────────────────────────────

const WF_GRID_GATE_DEFS = [
  { key: "profit_factor" as const, label: "PF",        threshold: "≥ 2.0", fmt: (v: number) => v.toFixed(2), passes: (v: number) => v >= GATES.min_profit_factor },
  { key: "win_rate"      as const, label: "Win Rate",  threshold: "≥ 55%", fmt: (v: number) => pct(v),       passes: (v: number) => v >= GATES.min_win_rate },
  { key: "hold_rate"     as const, label: "Hold Rate", threshold: "≥ 50%", fmt: (v: number) => pct(v),       passes: (v: number) => v >= GATES.min_hold_rate },
  { key: "sharpe"        as const, label: "Sharpe",    threshold: "≥ 1.5", fmt: (v: number) => v.toFixed(2), passes: (v: number) => v >= GATES.min_sharpe },
  { key: "max_drawdown"  as const, label: "Max DD",    threshold: "≤ 15%", fmt: (v: number) => pct(v),       passes: (v: number) => v <= GATES.max_drawdown },
];

function WalkForwardGridPanel({
  windows,
  wfRunning,
  onRunWalkForward,
}: {
  windows: WalkForwardGridWindow[];
  wfRunning: boolean;
  onRunWalkForward: (symbol: string, timesteps: number) => Promise<void>;
}) {
  const [symbol, setSymbol] = useState("MES");
  const [loading, setLoading] = useState(false);

  const selectCls = "font-mono text-xs rounded-lg px-3 py-2 outline-none cursor-pointer";
  const selectStyle: React.CSSProperties = { backgroundColor: "#111", border: "1px solid #1a1a2e", color: "#e0e0e0" };

  const passCount = windows.filter((w) => w.passed).length;
  const totalWindows = windows.length;

  async function handleRun(e: React.FormEvent) {
    e.preventDefault();
    if (loading || wfRunning) return;
    setLoading(true);
    try {
      await onRunWalkForward(symbol, 100_000);
    } finally {
      setLoading(false);
    }
  }

  const isRunning = loading || wfRunning;

  return (
    <section className="rounded-xl p-5" style={{ backgroundColor: "#0a0a0a", border: "1px solid #1a1a2e" }}>
      <div className="flex flex-wrap items-start justify-between gap-3 mb-5">
        <SectionHeader
          title="Walk-Forward Results Grid"
          subtitle="8-window rolling train/test validation. Green row = all gates pass. Takes ~20–40 min with 100k steps."
        />
        <form onSubmit={handleRun} className="flex items-center gap-3">
          <select
            className={selectCls}
            style={selectStyle}
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            disabled={isRunning}
          >
            {["MES", "MNQ", "MCL", "MGC"].map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <button
            type="submit"
            disabled={isRunning}
            className="flex items-center gap-1.5 font-mono text-xs font-bold px-4 py-2 rounded-lg transition-all"
            style={{
              backgroundColor: isRunning ? "#1a1a2e" : "#00ff8820",
              border: `1px solid ${isRunning ? "#333" : "#00ff8860"}`,
              color: isRunning ? "#555" : "#00ff88",
              cursor: isRunning ? "not-allowed" : "pointer",
              minWidth: "180px",
            }}
          >
            {isRunning ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
            {isRunning ? "Walk-Forward Running…" : "Run Walk-Forward"}
          </button>
        </form>
      </div>

      {/* Loading banner */}
      {isRunning && (
        <div
          className="mb-5 rounded-lg p-3 font-mono text-xs flex items-center gap-3"
          style={{ backgroundColor: "#ffcc0010", border: "1px solid #ffcc0030", color: "#ffcc00" }}
        >
          <RefreshCw className="h-4 w-4 animate-spin flex-shrink-0" />
          Walk-forward training in progress — 8 windows × 100k timesteps. This may take 20–40 minutes.
          Status auto-refreshes every 3s.
        </div>
      )}

      {windows.length === 0 ? (
        <div
          className="rounded-lg p-6 text-center font-mono text-xs"
          style={{ backgroundColor: "#111", border: "1px solid #1a1a2e", color: "#444" }}
        >
          No walk-forward results yet. Click &quot;Run Walk-Forward&quot; to start 8-window validation.
        </div>
      ) : (
        <>
          <div className="overflow-x-auto">
            <table className="w-full font-mono text-xs">
              <thead>
                <tr style={{ borderBottom: "1px solid #1a1a2e" }}>
                  {["Window", "Train Period", "Test Period", "Trades", "PF", "Win Rate", "Hold Rate", "Sharpe", "Max DD", "Result"].map((h) => (
                    <th
                      key={h}
                      className={`pb-2 px-3 font-semibold uppercase tracking-wider ${h === "Window" ? "text-left" : "text-center"}`}
                      style={{ color: "#555", fontSize: "10px" }}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {windows.map((win) => {
                  const rowBg = win.passed ? "#00ff8808" : "#ff444408";
                  const rowBorder = win.passed ? "#00ff8818" : "#ff444420";
                  const pfColor = metricColor(win.metrics.profit_factor, GATES.min_profit_factor);
                  const wrColor = metricColor(win.metrics.win_rate, GATES.min_win_rate);
                  const hrColor = metricColor(win.metrics.hold_rate, GATES.min_hold_rate);
                  const sharpeColor = metricColor(win.metrics.sharpe, GATES.min_sharpe);
                  const ddColor = metricColor(win.metrics.max_drawdown, GATES.max_drawdown, true);
                  const tradesColor = metricColor(win.metrics.n_trades, GATES.min_trades);

                  return (
                    <tr
                      key={win.window}
                      className="transition-colors"
                      style={{ backgroundColor: rowBg, borderBottom: `1px solid ${rowBorder}` }}
                    >
                      <td className="py-2.5 px-3 font-bold" style={{ color: "#e0e0e0" }}>#{win.window}</td>
                      <td className="py-2.5 px-3 text-center tabular-nums" style={{ color: "#666", fontSize: "10px" }}>
                        {win.train_start} → {win.train_end}
                      </td>
                      <td className="py-2.5 px-3 text-center tabular-nums" style={{ color: "#888", fontSize: "10px" }}>
                        {win.test_start} → {win.test_end}
                      </td>
                      <td className="py-2.5 px-3 text-center tabular-nums font-semibold" style={{ color: tradesColor }}>
                        {win.metrics.n_trades}
                      </td>
                      <td className="py-2.5 px-3 text-center tabular-nums font-semibold" style={{ color: pfColor }}>
                        {win.metrics.profit_factor.toFixed(2)}
                      </td>
                      <td className="py-2.5 px-3 text-center tabular-nums font-semibold" style={{ color: wrColor }}>
                        {pct(win.metrics.win_rate)}
                      </td>
                      <td className="py-2.5 px-3 text-center tabular-nums font-semibold" style={{ color: hrColor }}>
                        {win.metrics.hold_rate !== undefined ? pct(win.metrics.hold_rate) : "—"}
                      </td>
                      <td className="py-2.5 px-3 text-center tabular-nums font-semibold" style={{ color: sharpeColor }}>
                        {win.metrics.sharpe.toFixed(2)}
                      </td>
                      <td className="py-2.5 px-3 text-center tabular-nums font-semibold" style={{ color: ddColor }}>
                        {pct(win.metrics.max_drawdown)}
                      </td>
                      <td className="py-2.5 px-3 text-center">
                        {win.passed
                          ? <Badge label="PASS" color="#00ff88" />
                          : <Badge label="FAIL" color="#ff4444" />
                        }
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Summary row */}
          <div
            className="mt-4 pt-3 flex items-center justify-between"
            style={{ borderTop: "1px solid #1a1a2e" }}
          >
            <div className="flex items-center gap-3">
              <span className="font-mono text-[10px]" style={{ color: "#555" }}>
                SUMMARY:
              </span>
              <span
                className="font-mono text-sm font-bold tabular-nums"
                style={{ color: passCount === totalWindows ? "#00ff88" : passCount >= totalWindows / 2 ? "#ffcc00" : "#ff4444" }}
              >
                {passCount}/{totalWindows} windows passed
              </span>
            </div>
            <div className="flex items-center gap-2">
              {WF_GRID_GATE_DEFS.map(({ label, threshold }) => (
                <span key={label} className="font-mono text-[9px]" style={{ color: "#444" }}>
                  <span style={{ color: "#666" }}>{label}</span> {threshold}
                </span>
              ))}
            </div>
          </div>
        </>
      )}
    </section>
  );
}

// ── Nav ───────────────────────────────────────────────────────────────────────

const NAV_LINKS = [
  { href: "/", label: "Dashboard" },
  { href: "/analysis", label: "Analysis" },
  { href: "/backtest", label: "Backtest" },
  { href: "/performance", label: "Performance" },
  { href: "/validation", label: "Validation" },
  { href: "/journal", label: "Journal" },
  { href: "/paper", label: "Paper Trading" },
  { href: "/watchlist", label: "Watchlist" },
  { href: "/scorecard", label: "Scorecard" },
  { href: "/strategies", label: "RL Strategy" },
  { href: "/settings", label: "Settings" },
  { href: "/health", label: "Health" },
];

// ── Page ──────────────────────────────────────────────────────────────────────

export default function StrategiesPage() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [status, setStatus] = useState<TrainingStatus | null>(null);
  const [models, setModels] = useState<SavedModel[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [executors, setExecutors] = useState<Record<string, ExecutorInfo>>({});
  const [recentRuns, setRecentRuns] = useState<RecentRun[]>([]);
  const [wfWindows, setWfWindows] = useState<WalkForwardWindow[]>([]);
  const [wfComplete, setWfComplete] = useState(false);
  const [wfAllPass, setWfAllPass] = useState(false);
  const [rlExecutorStatus, setRlExecutorStatus] = useState<RLExecutorStatus | null>(null);
  const [wfGridWindows, setWfGridWindows] = useState<WalkForwardGridWindow[]>([]);
  const [wfGridRunning, setWfGridRunning] = useState(false);

  const fetchAll = useCallback(async () => {
    try {
      const [healthData, statusData, modelsData, executorData] = await Promise.allSettled([
        fetchEngine<HealthStatus>("/strategies/rl/health"),
        fetchEngine<TrainingStatus & WalkForwardStatusFields & { walk_forward_results?: WalkForwardGridWindow[] }>("/strategies/rl/status"),
        fetchEngine<{ models: SavedModel[] }>("/strategies/rl/models"),
        fetchEngine<ExecutorStatusResponse & Partial<RLExecutorStatus>>("/strategies/rl/executor/status"),
      ]);
      if (healthData.status === "fulfilled") setHealth(healthData.value);
      if (statusData.status === "fulfilled") {
        const s = statusData.value;
        setStatus(s);
        if (s.recent_runs) setRecentRuns(s.recent_runs);
        if (s.walkforward_windows) {
          setWfWindows(s.walkforward_windows);
          setWfComplete(s.walkforward_complete ?? false);
          setWfAllPass(s.walkforward_all_pass ?? false);
        }
        if (s.walk_forward_results) {
          setWfGridWindows(s.walk_forward_results);
        }
      }
      if (modelsData.status === "fulfilled") setModels(modelsData.value.models ?? []);
      if (executorData.status === "fulfilled") {
        const execResp = executorData.value;
        // Handle both response shapes: legacy {executors: {...}} and new {deployed: bool, ...}
        if ("executors" in execResp && execResp.executors) {
          setExecutors(execResp.executors);
        }
        if ("deployed" in execResp) {
          setRlExecutorStatus({
            deployed: execResp.deployed ?? false,
            symbol: execResp.symbol ?? null,
            model_path: execResp.model_path ?? null,
            last_prediction: execResp.last_prediction ?? null,
            last_prediction_time: execResp.last_prediction_time ?? null,
            next_fire_time: execResp.next_fire_time ?? null,
          });
        }
      }
      setError(null);
    } catch {
      setError("Engine offline — start the FastAPI engine and confirm the dashboard proxy can reach it.");
    }
  }, []);

  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

  // Poll every 3s when training is running
  useEffect(() => {
    if (!status?.running) return;
    const id = setInterval(fetchAll, 3000);
    return () => clearInterval(id);
  }, [status?.running, fetchAll]);

  // Poll every 5s when any executor is running
  useEffect(() => {
    const anyRunning = Object.values(executors).some((e) => e.is_running);
    if (!anyRunning) return;
    const id = setInterval(async () => {
      try {
        const data = await fetchEngine<ExecutorStatusResponse>("/strategies/rl/executor/status");
        setExecutors(data.executors ?? {});
      } catch {
        // silently ignore executor poll errors
      }
    }, 5000);
    return () => clearInterval(id);
  }, [executors]);

  // Poll every 30s for RL executor status card
  useEffect(() => {
    const id = setInterval(async () => {
      try {
        const data = await fetchEngine<RLExecutorStatus>("/strategies/rl/executor/status");
        if ("deployed" in data) setRlExecutorStatus(data as RLExecutorStatus);
      } catch {
        // silently ignore
      }
    }, 30_000);
    return () => clearInterval(id);
  }, []);

  async function handleStartTraining(symbol: string, interval: string, timesteps: number) {
    try {
      await postEngine("/strategies/rl/train", { symbol, interval, timesteps });
      setError(null);
      // Immediately poll status
      setTimeout(fetchAll, 500);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not reach engine");
    }
  }

  async function handleDeploy(symbol: string, model_path: string) {
    try {
      await postEngine("/strategies/rl/deploy", { symbol, model_path, active: true });
      setError(null);
      setTimeout(fetchAll, 500);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not deploy executor");
    }
  }

  async function handleUndeploy(symbol: string) {
    try {
      const exec = executors[symbol];
      await postEngine("/strategies/rl/deploy", { symbol, model_path: exec?.model_path ?? "", active: false });
      setError(null);
      setTimeout(fetchAll, 500);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not undeploy executor");
    }
  }

  async function handleSimpleDeploy(symbol: string, model_path: string) {
    try {
      await postEngine("/strategies/rl/deploy", { symbol, model_path });
      setError(null);
      setTimeout(fetchAll, 500);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not deploy executor");
    }
  }

  async function handleSimpleUndeploy() {
    try {
      const sym = rlExecutorStatus?.symbol ?? "";
      const mp = rlExecutorStatus?.model_path ?? "";
      await postEngine("/strategies/rl/deploy", { symbol: sym, model_path: mp, active: false });
      setError(null);
      setTimeout(fetchAll, 500);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not undeploy executor");
    }
  }

  async function handleRunWalkForward(symbol: string, timesteps: number) {
    try {
      setWfGridRunning(true);
      await postEngine("/strategies/rl/train-walkforward", { symbol, timesteps_per_window: timesteps });
      setError(null);
      // Poll every 3s until walk-forward results arrive (reuse training poll interval)
      const poll = setInterval(async () => {
        try {
          const data = await fetchEngine<TrainingStatus & { walk_forward_results?: WalkForwardGridWindow[] }>("/strategies/rl/status");
          if (data.walk_forward_results && data.walk_forward_results.length > 0) {
            setWfGridWindows(data.walk_forward_results);
            setWfGridRunning(false);
            clearInterval(poll);
          }
          if (!data.running) {
            setWfGridRunning(false);
            clearInterval(poll);
          }
        } catch {
          // silently ignore poll errors
        }
      }, 3000);
    } catch (err) {
      setWfGridRunning(false);
      setError(err instanceof Error ? err.message : "Could not start walk-forward training");
    }
  }

  const lastMetrics = status?.last_result?.metrics ?? null;

  return (
    <div className="min-h-screen" style={{ backgroundColor: "#050505" }}>
      {/* Header */}
      <header
        className="sticky top-0 z-50 backdrop-blur"
        style={{ backgroundColor: "rgba(5,5,5,0.95)", borderBottom: "1px solid #1a1a2e" }}
      >
        <div className="mx-auto max-w-[1920px] 2xl:max-w-[2400px] flex items-center justify-between px-6 py-3">
          <div className="flex items-center gap-3">
            <div
              className="flex h-8 w-8 items-center justify-center rounded-lg"
              style={{ backgroundColor: "#00d4ff15" }}
            >
              <Brain className="h-5 w-5" style={{ color: "#00d4ff" }} />
            </div>
            <div>
              <h1 className="font-bold tracking-tight" style={{ color: "#e0e0e0" }}>
                JARVIS TRADER
              </h1>
              <p className="text-xs" style={{ color: "#555" }}>
                IBKR Futures + Schwab Options
              </p>
            </div>
            <nav className="hidden lg:flex items-center gap-4 ml-6">
              {NAV_LINKS.map(({ href, label }) => (
                <a
                  key={href}
                  href={href}
                  className="text-xs transition-colors"
                  style={
                    href === "/strategies"
                      ? { color: "#e0e0e0", borderBottom: "1px solid #00d4ff", paddingBottom: "2px", fontWeight: 600 }
                      : href === "/paper"
                        ? { color: "#00ff88", fontWeight: 600 }
                        : { color: "#888" }
                  }
                >
                  {label}
                </a>
              ))}
            </nav>
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={fetchAll}
              className="flex items-center gap-1.5 font-mono text-xs transition-colors"
              style={{ color: "#555" }}
            >
              <RefreshCw className="h-3.5 w-3.5" />
              Refresh
            </button>
            <Link href="/" className="flex items-center gap-1.5 text-xs transition-colors" style={{ color: "#888" }}>
              <ArrowLeft className="h-3.5 w-3.5" />
              Back
            </Link>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1920px] 2xl:max-w-[2400px] px-6 py-6 space-y-6">

        {/* Page title */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <div>
            <h2 className="text-2xl font-bold tracking-tight font-mono" style={{ color: "#e0e0e0" }}>
              RL Strategy Discovery
            </h2>
            <p className="text-sm mt-1 font-mono" style={{ color: "#555" }}>
              PPO agent — discovers higher-conviction trading patterns from raw OHLCV data
            </p>
          </div>
          <div className="flex items-center gap-3">
            <span
              className="font-mono text-[10px] font-bold tracking-wider px-3 py-1.5 rounded flex items-center gap-1.5"
              style={{ backgroundColor: "#00d4ff10", border: "1px solid #00d4ff33", color: "#00d4ff" }}
            >
              <Zap className="h-3 w-3" />
              MES · MNQ · MCL · MGC
            </span>
          </div>
        </div>

        {/* Engine offline banner */}
        {error && (
          <div
            className="rounded-xl p-4 font-mono text-xs"
            style={{ backgroundColor: "#ff444410", border: "1px solid #ff444430", color: "#ff9999" }}
          >
            {error}
          </div>
        )}

        {/* Health */}
        <HealthPanel health={health} />

        {/* How it works */}
        <HowItWorksPanel />

        {/* Start training */}
        <StartTrainingPanel
          isRunning={status?.running ?? false}
          onStart={handleStartTraining}
        />

        {/* Training status */}
        <TrainingStatusPanel status={status} />

        {/* Training history */}
        <TrainingHistoryPanel runs={recentRuns} />

        {/* Walk-forward windows (from status endpoint) */}
        <WalkForwardWindowsPanel
          windows={wfWindows}
          complete={wfComplete}
          allPass={wfAllPass}
        />

        {/* Validation gates */}
        <ValidationGatesPanel metrics={lastMetrics} />

        {/* Action distribution */}
        <ActionDistributionPanel metrics={lastMetrics} />

        {/* Walk-forward results table */}
        <WalkForwardResultsPanel models={models} latestResult={status?.last_result ?? null} />

        {/* RL vs STC comparison */}
        <RLvsSTC latestResult={status?.last_result ?? null} />

        {/* Saved models */}
        <ModelsListPanel models={models} />

        {/* Executor status */}
        <ExecutorStatusPanel
          executors={executors}
          models={models}
          onDeploy={handleDeploy}
          onUndeploy={handleUndeploy}
        />

        {/* RL Executor Status Card (simplified single-executor view) */}
        <RLExecutorStatusCard
          status={rlExecutorStatus}
          models={models}
          onDeploy={handleSimpleDeploy}
          onUndeploy={handleSimpleUndeploy}
        />

        {/* Walk-Forward Results Grid (8-window date-based table) */}
        <WalkForwardGridPanel
          windows={wfGridWindows}
          wfRunning={wfGridRunning}
          onRunWalkForward={handleRunWalkForward}
        />

        {/* Strategy Discovery Browser */}
        <StrategyDiscoveryBrowser />

        {/* Footer */}
        <div className="pt-4 pb-8" style={{ borderTop: "1px solid #1a1a2e" }}>
          <p className="font-mono text-[10px]" style={{ color: "#333" }}>
            RL agent runs in parallel with existing STC pipeline — does NOT interfere with live paper trading.
            Models saved to data/rl_models/. Kill switch active = RL returns HOLD (safety enforced).
          </p>
        </div>
      </main>
    </div>
  );
}
