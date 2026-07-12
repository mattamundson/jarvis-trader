"use client";

import { useEffect, useState, useCallback } from "react";
import { ShieldOff, ShieldCheck, AlertTriangle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { fetchEngine } from "@/lib/api";


// ── Types ─────────────────────────────────────────────────────────────────────

interface CircuitBreakerData {
  daily_loss_limit?: number;
  daily_pnl?: number;
  daily_remaining?: number;
  max_drawdown_pct?: number;
  current_drawdown_pct?: number;
  drawdown_remaining_pct?: number;
  kill_switch_active?: boolean;
  daily_limit_breached?: boolean;
  drawdown_breached?: boolean;
}

// ── Inline Progress Bar ───────────────────────────────────────────────────────

function progressBarColorClass(pct: number) {
  return pct > 80 ? "bg-bear" : pct > 50 ? "bg-yellow-500" : "bg-bull";
}

function RiskProgressBar({ pct }: { pct: number }) {
  const clamped = Math.min(100, Math.max(0, pct));
  return (
    <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
      <div
        className={`h-full rounded-full transition-all duration-500 ${progressBarColorClass(clamped)}`}
        style={{ width: `${clamped}%` }}
      />
    </div>
  );
}

// ── Metric Row ────────────────────────────────────────────────────────────────

function MetricRow({
  label,
  pct,
  leftValue,
  rightValue,
  rightColorClass,
}: {
  label: string;
  pct: number;
  leftValue: string;
  rightValue: string;
  rightColorClass?: string;
}) {
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-xs font-mono">
        <span className="text-[#888]">{label}</span>
        <div className="flex items-center gap-3">
          <span className="text-[#555]">{leftValue}</span>
          <span className={`font-bold tabular-nums ${rightColorClass ?? "text-[#e0e0e0]"}`}>
            {rightValue}
          </span>
        </div>
      </div>
      <RiskProgressBar pct={pct} />
    </div>
  );
}

// ── Main Widget ───────────────────────────────────────────────────────────────

export function RiskStatusWidget() {
  const [data, setData] = useState<CircuitBreakerData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      const payload = await fetchEngine(`/safety/circuit-breakers`, {
        cache: "no-store",
      });
      setData(payload);
      setError(null);
      setLastUpdated(new Date().toLocaleTimeString());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unavailable");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const id = setInterval(fetchData, 30_000);
    return () => clearInterval(id);
  }, [fetchData]);

  // ── Loading skeleton ────────────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="rounded-xl border border-panel-border bg-panel p-4 space-y-3 animate-pulse">
        <div className="h-4 w-28 rounded bg-[#1a1a2e]" />
        <div className="h-8 w-full rounded-lg bg-[#1a1a2e]" />
        <div className="space-y-2">
          <div className="h-6 w-full rounded bg-[#1a1a2e]" />
          <div className="h-6 w-full rounded bg-[#1a1a2e]" />
        </div>
      </div>
    );
  }

  // ── Error state ─────────────────────────────────────────────────────────────
  if (error || !data) {
    return (
      <div className="rounded-xl border border-panel-border bg-panel p-4">
        <div className="flex items-center gap-2 font-mono text-xs text-[#ff4444]">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          <span>Risk data unavailable — engine offline or endpoint missing</span>
          {error && <span className="ml-1 text-[10px]">({error})</span>}
        </div>
      </div>
    );
  }

  // ── Derived values ──────────────────────────────────────────────────────────
  const killSwitchActive = data.kill_switch_active ?? false;
  const dailyLimitBreached = data.daily_limit_breached ?? false;
  const drawdownBreached = data.drawdown_breached ?? false;
  const anyBreached = dailyLimitBreached || drawdownBreached || killSwitchActive;

  const dailyLossLimit = data.daily_loss_limit ?? 0;       // e.g. -500
  const dailyPnl = data.daily_pnl ?? 0;                   // e.g. -123.50
  const dailyRemaining = data.daily_remaining ?? 0;        // e.g. 376.50

  const maxDrawdownPct = data.max_drawdown_pct ?? 0.05;
  const currentDrawdownPct = data.current_drawdown_pct ?? 0;
  const drawdownRemainingPct = data.drawdown_remaining_pct ?? 0;

  // Daily loss used pct: how much of the daily limit has been consumed (0–100)
  const dailyUsedPct =
    dailyLossLimit !== 0
      ? Math.abs(dailyPnl) / Math.abs(dailyLossLimit) * 100
      : 0;

  // Drawdown used pct (0–100)
  const drawdownUsedPct =
    maxDrawdownPct !== 0
      ? (currentDrawdownPct / maxDrawdownPct) * 100
      : 0;

  const pnlColorClass =
    dailyPnl >= 0 ? "text-bull" : dailyUsedPct > 80 ? "text-bear" : "text-yellow-500";

  const drawdownColorClass =
    drawdownUsedPct > 80
      ? "text-bear"
      : drawdownUsedPct > 50
      ? "text-yellow-500"
      : "text-bull";

  // ── Render ──────────────────────────────────────────────────────────────────
  return (
    <div
      className={`rounded-xl border bg-panel p-4 space-y-3 ${anyBreached ? "border-[#ff444440]" : "border-panel-border"}`}
    >
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          {killSwitchActive ? (
            <ShieldOff className="h-4 w-4 text-[#ff4444]" />
          ) : (
            <ShieldCheck className="h-4 w-4 text-[#00ff88]" />
          )}
          <span className="font-mono text-[10px] font-bold tracking-[0.2em] uppercase text-[#00ff88]">
            RISK STATUS
          </span>
          <span className="font-mono text-[9px] px-1.5 py-0.5 rounded border border-[#00d4ff33] bg-[#00d4ff10] text-[#00d4ff]">
            AUTO-REFRESH 30s
          </span>
        </div>
        <div className="flex items-center gap-2">
          {/* Kill Switch badge */}
          <Badge variant={killSwitchActive ? "bear" : "bull"}>
            KILL SWITCH: {killSwitchActive ? "ON" : "OFF"}
          </Badge>
          {/* Circuit Breaker status */}
          <Badge variant={anyBreached ? "bear" : "bull"}>
            {anyBreached ? "BREACHED" : "CLEAR"}
          </Badge>
        </div>
      </div>

      {/* Kill switch alert banner */}
      {killSwitchActive && (
        <div className="rounded-lg px-3 py-2 font-mono text-xs flex items-center gap-2 bg-[#ff444410] border border-[#ff444430] text-[#ff8888]">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
          Kill switch is <strong>ACTIVE</strong> — all trading halted
        </div>
      )}

      {/* Daily Loss Limit */}
      <MetricRow
        label="Daily Loss Limit"
        pct={dailyUsedPct}
        leftValue={`limit: $${Math.abs(dailyLossLimit).toFixed(0)}`}
        rightValue={
          dailyPnl >= 0
            ? `+$${dailyPnl.toFixed(2)}`
            : `-$${Math.abs(dailyPnl).toFixed(2)}`
        }
        rightColorClass={pnlColorClass}
      />

      {/* Remaining daily budget */}
      <div className="flex items-center justify-between font-mono text-[10px]">
        <span className="text-[#555]">Remaining today</span>
        <span className={`font-bold tabular-nums ${dailyRemaining > 0 ? "text-bull" : "text-bear"}`}>
          ${dailyRemaining.toFixed(2)}
        </span>
      </div>

      {/* Drawdown */}
      <MetricRow
        label="Max Drawdown"
        pct={drawdownUsedPct}
        leftValue={`limit: ${(maxDrawdownPct * 100).toFixed(1)}%`}
        rightValue={`${(currentDrawdownPct * 100).toFixed(2)}%`}
        rightColorClass={drawdownColorClass}
      />

      {/* Drawdown buffer remaining */}
      <div className="flex items-center justify-between font-mono text-[10px]">
        <span className="text-[#555]">Drawdown buffer</span>
        <span className={`font-bold tabular-nums ${drawdownRemainingPct > 0.02 ? "text-bull" : "text-bear"}`}>
          {(drawdownRemainingPct * 100).toFixed(2)}% remaining
        </span>
      </div>

      {/* Last updated */}
      {lastUpdated && (
        <div className="text-right">
          <span className="font-mono text-[9px] text-[#333]">
            Updated: {lastUpdated}
          </span>
        </div>
      )}
    </div>
  );
}
