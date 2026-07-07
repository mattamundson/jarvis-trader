"use client";

import { useEffect, useState, useCallback } from "react";
import { ShieldOff, ShieldCheck, AlertTriangle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { fetchEngine } from "@/lib/api";


// ── Types ─────────────────────────────────────────────────────────────────────

// Field names match SafetyLayer.check_circuit_breakers() / GET /safety/circuit-breakers
// exactly (engine/risk/safety_layer.py:2027-2040). The previous interface read
// daily_loss_limit/max_drawdown_pct/current_drawdown_pct/drawdown_remaining_pct/
// daily_remaining -- none of which the API returns -- so every field silently
// resolved to `undefined` and fell back to a hardcoded default below, making this
// widget always display a fabricated "5% limit / 0% current / OK" regardless of
// real risk state. daily_remaining and drawdown_remaining_pct aren't in the API
// response at all; they're derived client-side from the real fields.
interface CircuitBreakerData {
  daily_limit?: number; // negative $, e.g. -500
  daily_pnl?: number;
  drawdown_limit_pct?: number; // negative fraction, e.g. -0.10
  drawdown_pct?: number; // negative fraction, current drawdown from peak
  kill_switch_active?: boolean;
  daily_limit_breached?: boolean;
  drawdown_breached?: boolean;
}

// ── Inline Progress Bar ───────────────────────────────────────────────────────

function RiskProgressBar({ pct }: { pct: number }) {
  const clamped = Math.min(100, Math.max(0, pct));
  return (
    <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
      <div
        className="h-full rounded-full transition-all duration-500"
        style={{
          width: `${clamped}%`,
          backgroundColor:
            clamped > 80
              ? "rgb(239 68 68)"
              : clamped > 50
              ? "rgb(234 179 8)"
              : "rgb(34 197 94)",
        }}
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
  rightColor,
}: {
  label: string;
  pct: number;
  leftValue: string;
  rightValue: string;
  rightColor?: string;
}) {
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-xs font-mono">
        <span style={{ color: "#888" }}>{label}</span>
        <div className="flex items-center gap-3">
          <span style={{ color: "#555" }}>{leftValue}</span>
          <span
            className="font-bold tabular-nums"
            style={{ color: rightColor ?? "#e0e0e0" }}
          >
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
      <div className="rounded-xl border border-[#1a1a2e] bg-[#0a0a0a] p-4 space-y-3 animate-pulse">
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
      <div className="rounded-xl border border-[#1a1a2e] bg-[#0a0a0a] p-4">
        <div className="flex items-center gap-2 font-mono text-xs" style={{ color: "#ff4444" }}>
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

  const dailyLossLimit = data.daily_limit ?? 0;            // e.g. -500
  const dailyPnl = data.daily_pnl ?? 0;                    // e.g. -123.50
  // Not returned by the API -- derive from the real fields.
  const dailyRemaining = Math.max(0, Math.abs(dailyLossLimit) - Math.max(0, -dailyPnl));

  // Both drawdown_limit_pct and drawdown_pct are negative-signed per SafetyLayer's
  // docstring; take the magnitude to keep the positive-fraction convention this
  // widget's formatting/color logic already assumes.
  const maxDrawdownPct = Math.abs(data.drawdown_limit_pct ?? -0.05);
  const currentDrawdownPct = Math.abs(data.drawdown_pct ?? 0);
  // Not returned by the API -- derive from the real fields.
  const drawdownRemainingPct = Math.max(0, maxDrawdownPct - currentDrawdownPct);

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

  const pnlColor =
    dailyPnl >= 0 ? "rgb(34 197 94)" : dailyUsedPct > 80 ? "rgb(239 68 68)" : "rgb(234 179 8)";

  const drawdownColor =
    drawdownUsedPct > 80
      ? "rgb(239 68 68)"
      : drawdownUsedPct > 50
      ? "rgb(234 179 8)"
      : "rgb(34 197 94)";

  // ── Render ──────────────────────────────────────────────────────────────────
  return (
    <div
      className="rounded-xl border bg-[#0a0a0a] p-4 space-y-3"
      style={{ borderColor: anyBreached ? "#ff444440" : "#1a1a2e" }}
    >
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          {killSwitchActive ? (
            <ShieldOff className="h-4 w-4" style={{ color: "#ff4444" }} />
          ) : (
            <ShieldCheck className="h-4 w-4" style={{ color: "#00ff88" }} />
          )}
          <span
            className="font-mono text-[10px] font-bold tracking-[0.2em] uppercase"
            style={{ color: "#00ff88" }}
          >
            RISK STATUS
          </span>
          <span
            className="font-mono text-[9px] px-1.5 py-0.5 rounded border"
            style={{
              borderColor: "#00d4ff33",
              backgroundColor: "#00d4ff10",
              color: "#00d4ff",
            }}
          >
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
        <div
          className="rounded-lg px-3 py-2 font-mono text-xs flex items-center gap-2"
          style={{
            backgroundColor: "#ff444410",
            border: "1px solid #ff444430",
            color: "#ff8888",
          }}
        >
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
        rightColor={pnlColor}
      />

      {/* Remaining daily budget */}
      <div className="flex items-center justify-between font-mono text-[10px]">
        <span style={{ color: "#555" }}>Remaining today</span>
        <span
          className="font-bold tabular-nums"
          style={{ color: dailyRemaining > 0 ? "rgb(34 197 94)" : "rgb(239 68 68)" }}
        >
          ${dailyRemaining.toFixed(2)}
        </span>
      </div>

      {/* Drawdown */}
      <MetricRow
        label="Max Drawdown"
        pct={drawdownUsedPct}
        leftValue={`limit: ${(maxDrawdownPct * 100).toFixed(1)}%`}
        rightValue={`${(currentDrawdownPct * 100).toFixed(2)}%`}
        rightColor={drawdownColor}
      />

      {/* Drawdown buffer remaining */}
      <div className="flex items-center justify-between font-mono text-[10px]">
        <span style={{ color: "#555" }}>Drawdown buffer</span>
        <span
          className="font-bold tabular-nums"
          style={{
            color:
              drawdownRemainingPct > 0.02
                ? "rgb(34 197 94)"
                : "rgb(239 68 68)",
          }}
        >
          {(drawdownRemainingPct * 100).toFixed(2)}% remaining
        </span>
      </div>

      {/* Last updated */}
      {lastUpdated && (
        <div className="text-right">
          <span className="font-mono text-[9px]" style={{ color: "#333" }}>
            Updated: {lastUpdated}
          </span>
        </div>
      )}
    </div>
  );
}
