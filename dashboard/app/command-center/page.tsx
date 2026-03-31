"use client";

import React, { useEffect, useState, useCallback, useMemo } from "react";
import useSWR from "swr";
import { fetchEngine } from "@/lib/api";

// ── Types ──────────────────────────────────────────────────────────────────

interface HealthData {
  status: string;
  kill_switch_active: boolean;
  uptime_seconds: number;
  ibkr_connected: boolean;
  paper_trading?: boolean;
  version?: string;
  schwab_connected?: boolean;
}

interface SafetyData {
  daily_pnl: number;
  equity_peak: number;
  drawdown_pct: number;
  orders_last_minute: number;
  consecutive_losses?: number;
  kill_switch_active?: boolean;
  max_daily_loss?: number;
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
  margin_used?: number;
  margin_available?: number;
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

interface SchedulerJob {
  name: string;
  last_run: string | null;
  next_run: string | null;
  running: boolean;
  interval?: string;
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

interface Trade {
  timestamp: string;
  symbol: string;
  action: string;
  quantity: number;
  price: number;
  pnl?: number;
  commission?: number;
}

interface SignalData {
  direction: string | null;
  date: string;
  symbol: string;
  signal: string;
  regime: string | null;
  adaptive_stc_os: number;
  adaptive_stc_ob: number;
  entry_price: number | null;
  stop_level: number | null;
  target_1: number | null;
  atr: number | null;
  stc_val: number | null;
  stc_signal: string | null;
  ema_trend: string | null;
  confidence: number | null;
  error?: string;
}

// ── Constants ──────────────────────────────────────────────────────────────

const C = {
  bg: "#0a0f1e",
  bgCard: "#0d1424",
  bgCardHover: "#111b2e",
  cyan: "#00d4ff",
  cyanDim: "rgba(0, 212, 255, 0.15)",
  cyanBorder: "rgba(0, 212, 255, 0.2)",
  cyanGlow: "rgba(0, 212, 255, 0.08)",
  green: "#00ff88",
  greenDim: "rgba(0, 255, 136, 0.15)",
  red: "#ff4466",
  redDim: "rgba(255, 68, 102, 0.15)",
  yellow: "#ffcc00",
  yellowDim: "rgba(255, 204, 0, 0.15)",
  orange: "#ff8800",
  muted: "#8892a0",
  mutedDim: "#4a5568",
  textPrimary: "#e2e8f0",
  textBright: "#f8fafc",
  borderDim: "rgba(0, 212, 255, 0.08)",
} as const;

const WFE_VALUES: Record<string, number> = { MCL: 0.82, MNQ: 0.57, MGC: 0.14 };
const INSTRUMENT_STATUS: Record<string, string> = {
  MCL: "ACTIVE",
  MNQ: "ACTIVE",
  MGC: "HALTED",
};

// ── Helpers ────────────────────────────────────────────────────────────────

function fmtUSD(n: number | undefined | null): string {
  if (n == null || isNaN(n)) return "\u2014";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(n);
}

function fmtPct(n: number | undefined | null, decimals = 1): string {
  if (n == null || isNaN(n)) return "\u2014";
  return (n >= 0 ? "+" : "") + n.toFixed(decimals) + "%";
}

function fmtUptime(seconds: number): string {
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (d > 0) return `${d}d ${h}h ${m}m`;
  return `${h}h ${m}m ${s}s`;
}

function fmtTime(ts: string | null | undefined): string {
  if (!ts) return "\u2014";
  try {
    return new Date(ts).toLocaleTimeString("en-US", {
      hour12: false,
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return "\u2014";
  }
}

function fmtTimeAgo(ts: string | null | undefined): string {
  if (!ts) return "\u2014";
  try {
    const diff = Date.now() - new Date(ts).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return "just now";
    if (mins < 60) return `${mins}min ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    return `${Math.floor(hrs / 24)}d ago`;
  } catch {
    return "\u2014";
  }
}

function fetcher<T>(path: string): Promise<T> {
  return fetchEngine<T>(path);
}

// ── Market Session (Central Time) ──────────────────────────────────────────

interface SessionInfo {
  label: string;
  timeRange: string;
  color: string;
  isActive: boolean;
  dotColor: string;
}

function getMarketSession(): SessionInfo {
  const now = new Date();
  const month = now.getMonth();
  const isDST = month > 2 && month < 10;
  const ctOffsetHours = isDST ? -5 : -6;
  const ctTime = new Date(
    now.getTime() + (now.getTimezoneOffset() + ctOffsetHours * 60) * 60000
  );
  const totalMinutes = ctTime.getHours() * 60 + ctTime.getMinutes();
  const day = ctTime.getDay();

  if (day === 0 || day === 6) {
    return { label: "WEEKEND", timeRange: "Markets closed", color: C.mutedDim, isActive: false, dotColor: C.mutedDim };
  }
  if (totalMinutes < 480) {
    return { label: "OVERNIGHT", timeRange: "Pre-market prep", color: C.mutedDim, isActive: false, dotColor: C.mutedDim };
  }
  if (totalMinutes < 575) {
    return { label: "PRE-RTH", timeRange: "8:00\u201309:35 CT", color: C.yellow, isActive: false, dotColor: C.yellow };
  }
  if (totalMinutes < 690) {
    return { label: "RTH PRIMARY", timeRange: "9:35\u201311:30 CT", color: C.green, isActive: true, dotColor: C.green };
  }
  if (totalMinutes < 780) {
    return { label: "MIDDAY LULL", timeRange: "11:30\u201313:00 CT", color: C.yellow, isActive: false, dotColor: C.yellow };
  }
  if (totalMinutes < 930) {
    return { label: "RTH AFTERNOON", timeRange: "13:00\u201315:30 CT", color: C.cyan, isActive: true, dotColor: C.cyan };
  }
  if (totalMinutes < 1020) {
    return { label: "AFTER HOURS", timeRange: "15:30\u201317:00 CT", color: C.muted, isActive: false, dotColor: C.muted };
  }
  return { label: "CLOSED", timeRange: "Markets closed", color: C.mutedDim, isActive: false, dotColor: C.mutedDim };
}

// ── VIX Classification ────────────────────────────────────────────────────

function vixLabel(v: number | undefined | null): { text: string; color: string } {
  if (v == null) return { text: "\u2014", color: C.muted };
  if (v >= 30) return { text: "EXTREME", color: C.red };
  if (v >= 25) return { text: "HIGH", color: C.orange };
  if (v >= 20) return { text: "ELEVATED", color: C.yellow };
  return { text: "LOW", color: C.green };
}

// ════════════════════════════════════════════════════════════════════════════
// ── SUB-COMPONENTS ─────────────────────────────────────────────────────────
// ════════════════════════════════════════════════════════════════════════════

// ── HUD Panel (reusable card) ──────────────────────────────────────────────

function HudPanel({
  title,
  icon,
  children,
  accentColor = C.cyan,
  className = "",
  headerRight,
  danger = false,
}: {
  title: string;
  icon?: React.ReactNode;
  children: React.ReactNode;
  accentColor?: string;
  className?: string;
  headerRight?: React.ReactNode;
  danger?: boolean;
}) {
  const borderColor = danger ? C.red : accentColor;
  return (
    <div
      className={`relative overflow-hidden ${className}`}
      style={{
        background: `linear-gradient(135deg, ${C.bgCard} 0%, ${C.bg} 100%)`,
        border: `1px solid ${danger ? "rgba(255,68,102,0.4)" : C.cyanBorder}`,
        borderRadius: "8px",
      }}
    >
      {/* Top accent line */}
      <div
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          right: 0,
          height: "1px",
          background: `linear-gradient(90deg, transparent, ${borderColor}, transparent)`,
        }}
      />
      {/* Corner accent dots */}
      <div style={{ position: "absolute", top: "4px", left: "4px", width: "3px", height: "3px", borderRadius: "50%", background: borderColor, opacity: 0.6 }} />
      <div style={{ position: "absolute", top: "4px", right: "4px", width: "3px", height: "3px", borderRadius: "50%", background: borderColor, opacity: 0.6 }} />

      {/* Header */}
      <div
        style={{
          padding: "10px 14px 8px",
          borderBottom: `1px solid ${C.borderDim}`,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
          {icon && <span style={{ color: accentColor, fontSize: "11px" }}>{icon}</span>}
          <span
            style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: "10px",
              fontWeight: 700,
              letterSpacing: "0.15em",
              textTransform: "uppercase",
              color: accentColor,
            }}
          >
            {title}
          </span>
        </div>
        {headerRight}
      </div>

      {/* Content */}
      <div style={{ padding: "10px 14px 12px" }}>{children}</div>
    </div>
  );
}

// ── Status Dot ─────────────────────────────────────────────────────────────

function StatusDot({ color, pulse = false, size = 6 }: { color: string; pulse?: boolean; size?: number }) {
  return (
    <span style={{ position: "relative", display: "inline-flex", width: size, height: size }}>
      {pulse && (
        <span
          style={{
            position: "absolute",
            inset: 0,
            borderRadius: "50%",
            background: color,
            opacity: 0.4,
            animation: "ping 1.5s cubic-bezier(0,0,0.2,1) infinite",
          }}
        />
      )}
      <span
        style={{
          position: "relative",
          width: size,
          height: size,
          borderRadius: "50%",
          background: color,
          boxShadow: `0 0 ${size}px ${color}`,
        }}
      />
    </span>
  );
}

// ── Mini Badge ─────────────────────────────────────────────────────────────

function HudBadge({
  label,
  color,
  bgColor,
  pulse = false,
}: {
  label: string;
  color: string;
  bgColor?: string;
  pulse?: boolean;
}) {
  return (
    <span
      style={{
        fontFamily: "'JetBrains Mono', monospace",
        fontSize: "9px",
        fontWeight: 700,
        letterSpacing: "0.1em",
        padding: "2px 8px",
        borderRadius: "3px",
        border: `1px solid ${color}40`,
        background: bgColor || `${color}15`,
        color,
        animation: pulse ? "pulse 2s ease-in-out infinite" : undefined,
      }}
    >
      {label}
    </span>
  );
}

// ── Stat Row ───────────────────────────────────────────────────────────────

function StatRow({
  label,
  value,
  valueColor = C.textPrimary,
  sub,
}: {
  label: string;
  value: string;
  valueColor?: string;
  sub?: string;
}) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", padding: "3px 0" }}>
      <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "10px", color: C.muted }}>{label}</span>
      <div style={{ display: "flex", alignItems: "baseline", gap: "4px" }}>
        {sub && (
          <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "9px", color: C.mutedDim }}>{sub}</span>
        )}
        <span
          style={{
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: "12px",
            fontWeight: 700,
            color: valueColor,
            fontVariantNumeric: "tabular-nums",
          }}
        >
          {value}
        </span>
      </div>
    </div>
  );
}

// ── Risk Gauge (progress bar) ──────────────────────────────────────────────

function RiskGauge({
  label,
  value,
  max,
  unit = "%",
  invert = false,
}: {
  label: string;
  value: number;
  max: number;
  unit?: string;
  invert?: boolean;
}) {
  const ratio = max !== 0 ? Math.abs(value) / Math.abs(max) : 0;
  const pct = Math.min(ratio * 100, 100);

  let barColor = C.green;
  if (pct > 70) barColor = C.red;
  else if (pct > 40) barColor = C.yellow;

  const displayVal = invert ? value.toFixed(1) : value.toFixed(1);
  const displayMax = invert ? max.toFixed(1) : max.toFixed(1);

  return (
    <div style={{ marginBottom: "10px" }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: "4px",
        }}
      >
        <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "10px", color: C.muted }}>
          {label}
        </span>
        <span
          style={{
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: "10px",
            fontWeight: 600,
            color: barColor,
            fontVariantNumeric: "tabular-nums",
          }}
        >
          {displayVal}{unit} / {displayMax}{unit}
        </span>
      </div>
      <div
        style={{
          height: "6px",
          borderRadius: "3px",
          background: "rgba(255,255,255,0.05)",
          overflow: "hidden",
          position: "relative",
        }}
      >
        <div
          style={{
            height: "100%",
            width: `${pct}%`,
            borderRadius: "3px",
            background: `linear-gradient(90deg, ${barColor}cc, ${barColor})`,
            boxShadow: `0 0 8px ${barColor}40`,
            transition: "width 0.6s ease",
          }}
        />
        {/* Threshold marker at 50% */}
        <div
          style={{
            position: "absolute",
            top: 0,
            bottom: 0,
            left: "50%",
            width: "1px",
            background: "rgba(255,255,255,0.2)",
          }}
        />
      </div>
    </div>
  );
}

// ── WFE Bar ────────────────────────────────────────────────────────────────

function WfeBar({ symbol, wfe, status }: { symbol: string; wfe: number; status: string }) {
  const pct = Math.min(wfe * 100, 100);
  const isGood = wfe >= 0.50;
  const color = wfe >= 0.70 ? C.green : wfe >= 0.40 ? C.cyan : wfe >= 0.25 ? C.yellow : C.red;
  const statusColor = status === "ACTIVE" ? C.green : status === "HALTED" ? C.red : C.yellow;

  return (
    <div style={{ marginBottom: "12px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "5px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <span
            style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: "13px",
              fontWeight: 700,
              color: C.textBright,
            }}
          >
            {symbol}
          </span>
          <HudBadge label={status} color={statusColor} />
        </div>
        <span
          style={{
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: "16px",
            fontWeight: 700,
            color,
            fontVariantNumeric: "tabular-nums",
          }}
        >
          {wfe.toFixed(2)}
        </span>
      </div>
      <div
        style={{
          height: "8px",
          borderRadius: "4px",
          background: "rgba(255,255,255,0.04)",
          overflow: "hidden",
          position: "relative",
        }}
      >
        <div
          style={{
            height: "100%",
            width: `${pct}%`,
            borderRadius: "4px",
            background: `linear-gradient(90deg, ${color}88, ${color})`,
            boxShadow: `0 0 12px ${color}30`,
            transition: "width 0.8s ease",
          }}
        />
        {/* GOOD threshold line at 50% */}
        <div
          style={{
            position: "absolute",
            top: "-2px",
            bottom: "-2px",
            left: "50%",
            width: "2px",
            background: isGood ? C.green : "rgba(255,255,255,0.3)",
            borderRadius: "1px",
          }}
        />
      </div>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          marginTop: "3px",
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: "8px",
          color: C.mutedDim,
        }}
      >
        <span>0.00</span>
        <span style={{ color: "rgba(255,255,255,0.3)" }}>\u2191 0.50 GOOD</span>
        <span>1.00</span>
      </div>
    </div>
  );
}

// ── Signal Card ────────────────────────────────────────────────────────────

function SignalCard({ signal, symbol, fallbackTf }: { signal: SignalData | null; symbol: string; fallbackTf: string }) {
  const stc = signal?.stc_val;
  const regime = signal?.regime ?? "\u2014";
  const sig = signal?.signal ?? "HOLD";
  const atr = signal?.atr;
  const stcDir = stc != null ? (stc < 25 ? "\u25BC OVERSOLD" : stc > 75 ? "\u25B2 OVERBOUGHT" : "\u2014 NEUTRAL") : "\u2014";

  const sigColor = sig === "LONG" || sig === "BUY" ? C.green : sig === "SHORT" || sig === "SELL" ? C.red : C.muted;
  const regimeColor = regime === "TRENDING" ? C.green : regime === "RANGING" ? C.yellow : regime === "VOLATILE" ? C.red : C.muted;

  return (
    <div
      style={{
        background: `linear-gradient(135deg, ${C.bgCard} 0%, rgba(0,212,255,0.03) 100%)`,
        border: `1px solid ${C.cyanBorder}`,
        borderRadius: "6px",
        padding: "12px",
        flex: "1 1 0",
        minWidth: "220px",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "10px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
          <span
            style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: "14px",
              fontWeight: 700,
              color: C.textBright,
            }}
          >
            {symbol}
          </span>
          <span
            style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: "9px",
              color: C.mutedDim,
              background: "rgba(255,255,255,0.05)",
              padding: "1px 6px",
              borderRadius: "3px",
            }}
          >
            {fallbackTf}
          </span>
        </div>
        <HudBadge label={sig} color={sigColor} />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "6px 16px" }}>
        <div>
          <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "8px", color: C.mutedDim, textTransform: "uppercase", letterSpacing: "0.1em" }}>STC</div>
          <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "12px", fontWeight: 700, color: C.cyan }}>
            {stc != null ? stc.toFixed(1) : "\u2014"}{" "}
            <span style={{ fontSize: "9px", color: C.muted }}>{stcDir}</span>
          </div>
        </div>
        <div>
          <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "8px", color: C.mutedDim, textTransform: "uppercase", letterSpacing: "0.1em" }}>Regime</div>
          <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "12px", fontWeight: 700, color: regimeColor }}>{regime}</div>
        </div>
        <div>
          <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "8px", color: C.mutedDim, textTransform: "uppercase", letterSpacing: "0.1em" }}>Signal</div>
          <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "12px", fontWeight: 700, color: sigColor }}>{sig}</div>
        </div>
        <div>
          <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "8px", color: C.mutedDim, textTransform: "uppercase", letterSpacing: "0.1em" }}>ATR</div>
          <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "12px", fontWeight: 700, color: C.textPrimary }}>
            {atr != null ? atr.toFixed(2) : "\u2014"}
          </div>
        </div>
      </div>

      {signal?.confidence != null && (
        <div style={{ marginTop: "8px", paddingTop: "6px", borderTop: `1px solid ${C.borderDim}` }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "8px", color: C.mutedDim }}>CONFIDENCE</span>
            <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "11px", fontWeight: 700, color: C.cyan }}>
              {(signal.confidence * 100).toFixed(0)}%
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Mini Equity Curve (SVG) ────────────────────────────────────────────────

function EquityCurve({ trades }: { trades: Trade[] | undefined }) {
  const points = useMemo(() => {
    if (!trades || trades.length === 0) return [];
    let cumPnl = 0;
    const pts: { x: number; y: number }[] = [{ x: 0, y: 0 }];
    trades
      .slice()
      .reverse()
      .forEach((t, i) => {
        cumPnl += t.pnl ?? 0;
        pts.push({ x: i + 1, y: cumPnl });
      });
    return pts;
  }, [trades]);

  if (points.length < 2) {
    return (
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          height: "100%",
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: "11px",
          color: C.mutedDim,
        }}
      >
        No trade data for equity curve
      </div>
    );
  }

  const width = 400;
  const height = 140;
  const pad = 8;
  const minY = Math.min(...points.map((p) => p.y));
  const maxY = Math.max(...points.map((p) => p.y));
  const rangeY = maxY - minY || 1;
  const maxX = points[points.length - 1].x || 1;

  const toSvg = (p: { x: number; y: number }) => ({
    sx: pad + (p.x / maxX) * (width - pad * 2),
    sy: pad + (1 - (p.y - minY) / rangeY) * (height - pad * 2),
  });

  const pathD = points
    .map((p, i) => {
      const { sx, sy } = toSvg(p);
      return `${i === 0 ? "M" : "L"}${sx},${sy}`;
    })
    .join(" ");

  const lastPt = points[points.length - 1];
  const lineColor = lastPt.y >= 0 ? C.green : C.red;

  // Fill area
  const first = toSvg(points[0]);
  const last = toSvg(lastPt);
  const fillD = `${pathD} L${last.sx},${height - pad} L${first.sx},${height - pad} Z`;

  // Zero line
  const zeroY = pad + (1 - (0 - minY) / rangeY) * (height - pad * 2);

  return (
    <svg viewBox={`0 0 ${width} ${height}`} style={{ width: "100%", height: "100%" }}>
      <defs>
        <linearGradient id="eqFill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={lineColor} stopOpacity={0.25} />
          <stop offset="100%" stopColor={lineColor} stopOpacity={0.02} />
        </linearGradient>
        <filter id="glow">
          <feGaussianBlur stdDeviation="2" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>
      {/* Grid lines */}
      {[0.25, 0.5, 0.75].map((f) => (
        <line
          key={f}
          x1={pad}
          y1={pad + f * (height - pad * 2)}
          x2={width - pad}
          y2={pad + f * (height - pad * 2)}
          stroke="rgba(255,255,255,0.04)"
          strokeDasharray="4 4"
        />
      ))}
      {/* Zero line */}
      {minY <= 0 && maxY >= 0 && (
        <line x1={pad} y1={zeroY} x2={width - pad} y2={zeroY} stroke="rgba(255,255,255,0.15)" strokeDasharray="6 3" />
      )}
      {/* Fill */}
      <path d={fillD} fill="url(#eqFill)" />
      {/* Line */}
      <path d={pathD} fill="none" stroke={lineColor} strokeWidth={2} filter="url(#glow)" />
      {/* End dot */}
      <circle cx={last.sx} cy={last.sy} r={3} fill={lineColor} filter="url(#glow)" />
      {/* Labels */}
      <text x={width - pad} y={pad + 4} textAnchor="end" fill={C.mutedDim} fontSize={9} fontFamily="'JetBrains Mono', monospace">
        {fmtUSD(maxY)}
      </text>
      <text x={width - pad} y={height - pad + 2} textAnchor="end" fill={C.mutedDim} fontSize={9} fontFamily="'JetBrains Mono', monospace">
        {fmtUSD(minY)}
      </text>
    </svg>
  );
}

// ════════════════════════════════════════════════════════════════════════════
// ── MAIN PAGE COMPONENT ────────────────────────────────────────────────────
// ════════════════════════════════════════════════════════════════════════════

export default function CommandCenterPage() {
  const session = getMarketSession();
  const refreshInterval = session.isActive ? 30_000 : 5 * 60_000;

  const [now, setNow] = useState(new Date());
  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  // ── Data fetching ────────────────────────────────────────────────────────

  const { data: health, error: healthErr, mutate: mutateHealth } = useSWR<HealthData>(
    "/health",
    fetcher,
    { refreshInterval, shouldRetryOnError: false }
  );

  const { data: safety } = useSWR<SafetyData>("/safety/status", fetcher, {
    refreshInterval,
    shouldRetryOnError: false,
  });

  const { data: portfolio } = useSWR<PortfolioData>("/portfolio", fetcher, {
    refreshInterval,
    shouldRetryOnError: false,
  });

  const { data: decisions } = useSWR<Decision[]>("/decisions/recent?limit=10", fetcher, {
    refreshInterval,
    shouldRetryOnError: false,
  });

  const { data: scheduler } = useSWR<SchedulerData>("/scheduler/status", fetcher, {
    refreshInterval,
    shouldRetryOnError: false,
  });

  const { data: macro } = useSWR<MacroData>("/macro/snapshot", fetcher, {
    refreshInterval: 120_000,
    shouldRetryOnError: false,
  });

  const { data: trades } = useSWR<Trade[]>("/portfolio/history/trades", fetcher, {
    refreshInterval,
    shouldRetryOnError: false,
  });

  const { data: mclSignal } = useSWR<SignalData>("/paper/mcl-signal", fetcher, {
    refreshInterval,
    shouldRetryOnError: false,
  });

  const { data: mnqSignal } = useSWR<SignalData>("/paper/mnq-signal", fetcher, {
    refreshInterval,
    shouldRetryOnError: false,
  });

  const engineOnline = !healthErr && !!health;
  const killSwitchActive = health?.kill_switch_active ?? false;
  const isPaperMode = health?.paper_trading !== false;

  // Risk calculations
  const dailyPnl = portfolio?.daily_pnl ?? 0;
  const totalEquity = portfolio?.total_equity ?? 25000;
  const dailyPnlPct = totalEquity > 0 ? (dailyPnl / totalEquity) * 100 : 0;
  const drawdownPct = safety?.drawdown_pct ?? 0;
  const consecutiveLosses = safety?.consecutive_losses ?? 0;
  const marginUsedPct =
    portfolio?.margin_used != null && portfolio?.margin_available != null && (portfolio.margin_used + portfolio.margin_available) > 0
      ? (portfolio.margin_used / (portfolio.margin_used + portfolio.margin_available)) * 100
      : 0;

  const vix = macro?.vix;
  const vixInfo = vixLabel(vix);

  // Kill switch handler
  const handleKillSwitch = useCallback(async () => {
    if (!confirm("ACTIVATE KILL SWITCH?\n\nThis will IMMEDIATELY halt all trading.")) return;
    try {
      await fetchEngine("/safety/kill-switch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ activate: true }),
      });
      mutateHealth();
    } catch {
      // graceful
    }
  }, [mutateHealth]);

  // ── Render ───────────────────────────────────────────────────────────────

  return (
    <div
      style={{
        minHeight: "100vh",
        background: `radial-gradient(ellipse at 20% 0%, rgba(0,212,255,0.03) 0%, transparent 50%),
                      radial-gradient(ellipse at 80% 100%, rgba(0,255,136,0.02) 0%, transparent 50%),
                      ${C.bg}`,
        color: C.textPrimary,
        fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
        padding: "16px 20px",
      }}
    >
      {/* Keyframes */}
      <style>{`
        @keyframes ping { 0% { transform: scale(1); opacity: 0.6; } 75%, 100% { transform: scale(2); opacity: 0; } }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.7; } }
        @keyframes scanline { 0% { transform: translateY(-100%); } 100% { transform: translateY(100vh); } }
        @keyframes headerGlow { 0%, 100% { text-shadow: 0 0 20px rgba(0,212,255,0.3); } 50% { text-shadow: 0 0 40px rgba(0,212,255,0.6), 0 0 80px rgba(0,212,255,0.2); } }
      `}</style>

      {/* ═══════════════════════════════════════════════════════════
          HEADER BAR
      ═══════════════════════════════════════════════════════════ */}
      <header
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: "16px",
          paddingBottom: "12px",
          borderBottom: `1px solid ${C.cyanBorder}`,
          position: "relative",
        }}
      >
        {/* Scanline accent */}
        <div
          style={{
            position: "absolute",
            bottom: 0,
            left: 0,
            right: 0,
            height: "1px",
            background: `linear-gradient(90deg, transparent, ${C.cyan}60, ${C.cyan}, ${C.cyan}60, transparent)`,
          }}
        />

        <div>
          <h1
            style={{
              fontSize: "20px",
              fontWeight: 700,
              letterSpacing: "0.2em",
              margin: 0,
              background: `linear-gradient(90deg, ${C.cyan}, #66e0ff, ${C.cyan})`,
              WebkitBackgroundClip: "text",
              WebkitTextFillColor: "transparent",
              animation: "headerGlow 4s ease-in-out infinite",
            }}
          >
            {"\u26A1"} JARVIS TRADER {"\u2014"} COMMAND CENTER
          </h1>
          <div style={{ display: "flex", alignItems: "center", gap: "12px", marginTop: "4px" }}>
            <span style={{ fontSize: "9px", color: C.mutedDim, letterSpacing: "0.15em" }}>v2.7</span>
            <span style={{ color: C.mutedDim }}>{"\u00B7"}</span>
            <span style={{ fontSize: "9px", color: session.color, letterSpacing: "0.1em" }}>
              <StatusDot color={session.dotColor} pulse={session.isActive} size={5} />{" "}
              {session.label}
            </span>
            <span style={{ color: C.mutedDim }}>{"\u00B7"}</span>
            <span style={{ fontSize: "9px", color: C.mutedDim, letterSpacing: "0.1em" }}>
              REFRESH {refreshInterval / 1000}s
            </span>
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
          {/* Clock */}
          <div style={{ textAlign: "right" }}>
            <div
              style={{
                fontSize: "22px",
                fontWeight: 700,
                color: C.cyan,
                fontVariantNumeric: "tabular-nums",
                letterSpacing: "0.15em",
                textShadow: `0 0 20px ${C.cyan}40`,
              }}
            >
              {now.toLocaleTimeString("en-US", { hour12: false })}
            </div>
            <div style={{ fontSize: "9px", color: C.mutedDim }}>
              {now.toLocaleDateString("en-US", {
                weekday: "short",
                month: "short",
                day: "numeric",
              })}
            </div>
          </div>

          {/* Mode badges */}
          {isPaperMode && <HudBadge label="PAPER" color={C.yellow} />}
          {!isPaperMode && <HudBadge label="LIVE" color={C.green} pulse />}

          {/* Engine status */}
          <HudBadge
            label={engineOnline ? "ENGINE ONLINE" : "ENGINE OFFLINE"}
            color={engineOnline ? C.green : C.red}
            pulse={!engineOnline}
          />

          {/* Kill Switch */}
          <button
            onClick={handleKillSwitch}
            style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: "10px",
              fontWeight: 700,
              letterSpacing: "0.1em",
              padding: "6px 14px",
              borderRadius: "4px",
              border: `1px solid ${killSwitchActive ? C.red : "rgba(255,68,102,0.4)"}`,
              background: killSwitchActive
                ? `linear-gradient(135deg, rgba(255,68,102,0.3), rgba(255,68,102,0.15))`
                : "rgba(255,68,102,0.08)",
              color: killSwitchActive ? "#ff6680" : C.red,
              cursor: "pointer",
              animation: killSwitchActive ? "pulse 1.5s ease-in-out infinite" : undefined,
              transition: "all 0.2s",
            }}
            onMouseEnter={(e) => {
              (e.target as HTMLElement).style.background = "rgba(255,68,102,0.25)";
            }}
            onMouseLeave={(e) => {
              (e.target as HTMLElement).style.background = killSwitchActive
                ? "linear-gradient(135deg, rgba(255,68,102,0.3), rgba(255,68,102,0.15))"
                : "rgba(255,68,102,0.08)";
            }}
          >
            {killSwitchActive ? "\u26A0 KILL ACTIVE" : "KILL SWITCH"}
          </button>
        </div>
      </header>

      {/* ═══════════════════════════════════════════════════════════
          ROW 1 — STATUS OVERVIEW (4 columns)
      ═══════════════════════════════════════════════════════════ */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr", gap: "12px", marginBottom: "12px" }}>
        {/* ── PORTFOLIO ─────────────────────────────── */}
        <HudPanel title="PORTFOLIO" icon={"\u25B6"}>
          <div
            style={{
              fontSize: "24px",
              fontWeight: 700,
              color: C.textBright,
              fontVariantNumeric: "tabular-nums",
              marginBottom: "8px",
              textShadow: `0 0 20px rgba(255,255,255,0.1)`,
            }}
          >
            {fmtUSD(portfolio?.total_equity)}
          </div>
          <StatRow
            label="Daily P&L"
            value={fmtUSD(dailyPnl)}
            valueColor={dailyPnl >= 0 ? C.green : C.red}
            sub={`(${fmtPct(dailyPnlPct)})`}
          />
          <StatRow label="Open Positions" value={String(portfolio?.positions?.length ?? 0)} valueColor={C.textPrimary} />
          <StatRow label="Cash" value={fmtUSD(portfolio?.cash)} valueColor={C.muted} />
        </HudPanel>

        {/* ── INSTRUMENTS ───────────────────────────── */}
        <HudPanel title="INSTRUMENTS" icon={"\u25C8"}>
          {(["MCL", "MNQ", "MGC"] as const).map((sym) => {
            const status = INSTRUMENT_STATUS[sym];
            const wfe = WFE_VALUES[sym];
            const isActive = status === "ACTIVE";
            return (
              <div
                key={sym}
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  padding: "5px 0",
                  borderBottom: `1px solid ${C.borderDim}`,
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                  <StatusDot color={isActive ? C.green : C.red} size={5} />
                  <span style={{ fontSize: "12px", fontWeight: 700, color: C.textBright }}>{sym}</span>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                  <span
                    style={{
                      fontSize: "11px",
                      fontWeight: 700,
                      color: isActive ? C.cyan : C.red,
                      fontVariantNumeric: "tabular-nums",
                    }}
                  >
                    {wfe.toFixed(2)}
                  </span>
                  <HudBadge label={isActive ? "ACTIVE" : "HALT"} color={isActive ? C.green : C.red} />
                </div>
              </div>
            );
          })}
        </HudPanel>

        {/* ── SAFETY ────────────────────────────────── */}
        <HudPanel title="SAFETY LAYER" icon={"\u25C6"} danger={killSwitchActive}>
          <StatRow
            label="Kill Switch"
            value={killSwitchActive ? "ACTIVE" : "ARMED"}
            valueColor={killSwitchActive ? C.red : C.green}
          />
          <StatRow
            label="Drawdown"
            value={fmtPct(drawdownPct)}
            valueColor={Math.abs(drawdownPct) > 5 ? C.red : Math.abs(drawdownPct) > 2 ? C.yellow : C.green}
            sub="/ -10%"
          />
          <StatRow
            label="Daily Loss"
            value={fmtPct(dailyPnlPct)}
            valueColor={dailyPnlPct < -1 ? C.red : C.green}
            sub="/ -2%"
          />
          <StatRow
            label="Consec Losses"
            value={`${consecutiveLosses}/7`}
            valueColor={consecutiveLosses >= 4 ? C.red : consecutiveLosses >= 2 ? C.yellow : C.green}
          />
        </HudPanel>

        {/* ── MARKET SESSION ────────────────────────── */}
        <HudPanel title="MARKET SESSION" icon={"\u25CF"} accentColor={session.color}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "8px",
              marginBottom: "10px",
              padding: "6px 10px",
              borderRadius: "4px",
              background: `${session.color}10`,
              border: `1px solid ${session.color}30`,
            }}
          >
            <StatusDot color={session.dotColor} pulse={session.isActive} size={8} />
            <span style={{ fontSize: "12px", fontWeight: 700, color: session.color, letterSpacing: "0.08em" }}>
              {session.label}
            </span>
          </div>
          <StatRow label="Window" value={session.timeRange} valueColor={C.muted} />
          <StatRow
            label="VIX"
            value={vix != null ? vix.toFixed(1) : "\u2014"}
            valueColor={vixInfo.color}
          />
          <div style={{ display: "flex", justifyContent: "flex-end", marginTop: "2px" }}>
            <HudBadge label={vixInfo.text} color={vixInfo.color} />
          </div>
        </HudPanel>
      </div>

      {/* ═══════════════════════════════════════════════════════════
          ROW 2 — SIGNAL PANEL (full width, flex)
      ═══════════════════════════════════════════════════════════ */}
      <div style={{ marginBottom: "12px" }}>
        <div
          style={{
            fontSize: "10px",
            fontWeight: 700,
            letterSpacing: "0.2em",
            color: C.cyan,
            marginBottom: "8px",
            display: "flex",
            alignItems: "center",
            gap: "8px",
          }}
        >
          <span style={{ color: C.cyan }}>{"\u25C8"}</span>
          SIGNAL PANEL
          <div style={{ flex: 1, height: "1px", background: C.cyanBorder }} />
        </div>
        <div style={{ display: "flex", gap: "12px", flexWrap: "wrap" }}>
          <SignalCard signal={mclSignal ?? null} symbol="MCL" fallbackTf="1h" />
          <SignalCard signal={mnqSignal ?? null} symbol="MNQ" fallbackTf="1h" />
        </div>
      </div>

      {/* ═══════════════════════════════════════════════════════════
          ROW 3 — EQUITY CURVE + RISK GAUGES (2 columns)
      ═══════════════════════════════════════════════════════════ */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px", marginBottom: "12px" }}>
        {/* Equity Curve */}
        <HudPanel title="EQUITY CURVE" icon={"\u2197"}>
          <div style={{ height: "160px" }}>
            <EquityCurve trades={trades} />
          </div>
        </HudPanel>

        {/* Risk Gauges */}
        <HudPanel title="RISK GAUGES" icon={"\u26A0"}>
          <RiskGauge label="Daily P&L" value={Math.abs(Math.min(dailyPnlPct, 0))} max={2.0} />
          <RiskGauge label="Drawdown" value={Math.abs(drawdownPct)} max={10.0} />
          <RiskGauge label="Consecutive Losses" value={consecutiveLosses} max={7} unit="" />
          <RiskGauge label="Margin Utilization" value={marginUsedPct} max={40} />
        </HudPanel>
      </div>

      {/* ═══════════════════════════════════════════════════════════
          ROW 4 — RECENT TRADES + PIPELINE STATUS (2 columns)
      ═══════════════════════════════════════════════════════════ */}
      <div style={{ display: "grid", gridTemplateColumns: "3fr 2fr", gap: "12px", marginBottom: "12px" }}>
        {/* Recent Trades */}
        <HudPanel title="RECENT TRADES" icon={"\u25B7"} headerRight={
          <span style={{ fontSize: "9px", color: C.mutedDim }}>last 10</span>
        }>
          {!trades || trades.length === 0 ? (
            <div
              style={{
                textAlign: "center",
                padding: "24px",
                color: C.mutedDim,
                fontSize: "11px",
              }}
            >
              No trade history available
            </div>
          ) : (
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "10px" }}>
                <thead>
                  <tr style={{ borderBottom: `1px solid ${C.cyanBorder}` }}>
                    {["Time", "Symbol", "Side", "Qty", "Price", "P&L"].map((h) => (
                      <th
                        key={h}
                        style={{
                          textAlign: h === "Time" || h === "Symbol" || h === "Side" ? "left" : "right",
                          padding: "6px 4px",
                          color: C.mutedDim,
                          fontWeight: 600,
                          fontSize: "9px",
                          letterSpacing: "0.1em",
                          textTransform: "uppercase",
                        }}
                      >
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {trades.slice(0, 10).map((t, i) => {
                    const isBuy = t.action === "BUY" || t.action === "LONG";
                    return (
                      <tr
                        key={i}
                        style={{
                          borderBottom: `1px solid ${C.borderDim}`,
                          transition: "background 0.15s",
                        }}
                        onMouseEnter={(e) => {
                          (e.currentTarget as HTMLElement).style.background = C.cyanGlow;
                        }}
                        onMouseLeave={(e) => {
                          (e.currentTarget as HTMLElement).style.background = "transparent";
                        }}
                      >
                        <td style={{ padding: "5px 4px", color: C.muted }}>{fmtTime(t.timestamp)}</td>
                        <td style={{ padding: "5px 4px", color: C.textBright, fontWeight: 700 }}>{t.symbol}</td>
                        <td style={{ padding: "5px 4px", color: isBuy ? C.green : C.red, fontWeight: 600 }}>{t.action}</td>
                        <td style={{ padding: "5px 4px", textAlign: "right", color: C.textPrimary }}>{t.quantity}</td>
                        <td style={{ padding: "5px 4px", textAlign: "right", color: C.textPrimary, fontVariantNumeric: "tabular-nums" }}>
                          {t.price?.toFixed(2) ?? "\u2014"}
                        </td>
                        <td
                          style={{
                            padding: "5px 4px",
                            textAlign: "right",
                            fontWeight: 700,
                            fontVariantNumeric: "tabular-nums",
                            color: t.pnl != null ? (t.pnl >= 0 ? C.green : C.red) : C.muted,
                          }}
                        >
                          {t.pnl != null ? fmtUSD(t.pnl) : "\u2014"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </HudPanel>

        {/* Pipeline Status */}
        <HudPanel title="PIPELINE STATUS" icon={"\u2699"}>
          <StatRow
            label="Status"
            value={scheduler?.running ? "RUNNING" : "IDLE"}
            valueColor={scheduler?.running ? C.green : C.muted}
          />
          <StatRow
            label="Last Run"
            value={fmtTimeAgo(scheduler?.last_scan)}
            valueColor={C.textPrimary}
          />
          <StatRow
            label="Next Scan"
            value={fmtTime(scheduler?.next_scan)}
            valueColor={C.cyan}
          />
          <StatRow
            label="Total Decisions"
            value={String(scheduler?.total_decisions_logged ?? "\u2014")}
            valueColor={C.cyan}
          />

          {/* Last pipeline result */}
          {decisions && decisions.length > 0 && (
            <div
              style={{
                marginTop: "10px",
                paddingTop: "8px",
                borderTop: `1px solid ${C.borderDim}`,
              }}
            >
              <div style={{ fontSize: "8px", color: C.mutedDim, letterSpacing: "0.15em", textTransform: "uppercase", marginBottom: "6px" }}>
                LAST DECISION
              </div>
              <div
                style={{
                  background: `${C.cyanGlow}`,
                  border: `1