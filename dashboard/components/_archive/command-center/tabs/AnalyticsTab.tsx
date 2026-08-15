"use client";

import React, { useState, useEffect } from "react";
import {
  PieChart,
  Pie,
  Cell,
  ResponsiveContainer,
  Tooltip,
} from "recharts";
import { cn } from "@/lib/utils";
<<<<<<< HEAD:dashboard/components/command-center/tabs/AnalyticsTab.tsx
import { symbolTradeStatus } from "@/lib/approvedSymbols";
=======
import {
  WINDOW_DAYS,
  START_DATE_STORAGE_KEY,
  resolveStartDate,
  trackerStatsFor,
  buildCalendarCells,
} from "@/lib/thirtyDayTracker";
>>>>>>> origin/master:dashboard/components/_archive/command-center/tabs/AnalyticsTab.tsx

// ── Types ──────────────────────────────────────────────────────────────────

interface MacroData {
  vix?: number | null;
  vix_regime?: string | null;
  regime?: string | null;
  timestamp?: string;
}

interface CommandCenterData {
  macro?: {
    data?: MacroData;
  };
}

interface AnalyticsTabProps {
  data: CommandCenterData;
}

// ── Static Data ────────────────────────────────────────────────────────────

// D2-02: `status` used to be hand-maintained here and drifted backwards
// (MCL/MNQ shown APPROVED, MGC shown HALTED). Status is now always derived
// from symbolTradeStatus() at render time — never hardcode it in this list again.
const WFE_INSTRUMENTS = [
  {
    symbol: "MCL",
    tf: "1h",
    wfe: 0.82,
    label: "Micro Crude Oil",
    detail: "Static params · regime_filter=ON",
    color: "#00ff88",
    gradFrom: "#10b981",
    gradTo: "#00ff88",
  },
  {
    symbol: "MNQ",
    tf: "1h",
    wfe: 0.57,
    label: "Micro Nasdaq",
    detail: "adaptive_regime=ON · no MTF · no volume",
    color: "#00d4ff",
    gradFrom: "#0891b2",
    gradTo: "#06b6d4",
  },
  {
    symbol: "MGC",
    tf: "1d",
    wfe: 0.14,
    label: "Micro Gold",
    detail: "Overfit detected · small-sample bias",
    color: "#ff3b5c",
    gradFrom: "#dc2626",
    gradTo: "#ff3b5c",
  },
];

const PHASES = [
  { name: "Architecture", value: 100, color: "#10b981" },
  { name: "Strategy", value: 100, color: "#00d4ff" },
  { name: "WFE", value: 100, color: "#00ff88" },
  { name: "Options", value: 100, color: "#a78bfa" },
  { name: "Dashboard", value: 95, color: "#f59e0b" },
  { name: "Go-Live", value: 40, color: "#64748b" },
];

const OVERALL_PCT = Math.round(
  PHASES.reduce((s, p) => s + p.value, 0) / PHASES.length
);

const VIX_TIERS = [
  { label: "VERY_LOW", range: "< 12", color: "#00ff88", min: 0, max: 12 },
  { label: "LOW", range: "12–16", color: "#34d399", min: 12, max: 16 },
  { label: "NORMAL", range: "16–20", color: "#00d4ff", min: 16, max: 20 },
  { label: "ELEVATED", range: "20–25", color: "#fbbf24", min: 20, max: 25 },
  { label: "HIGH", range: "25–30", color: "#f97316", min: 25, max: 30 },
  { label: "EXTREME", range: "> 30", color: "#ff3b5c", min: 30, max: Infinity },
];

const PRIORITY_ITEMS = [
  {
    priority: "P1",
    text: "Configure FRED_API_KEY for macro data",
    status: "FAIL",
    priorityColor: "#ff3b5c",
    statusColor: "#ff3b5c",
    statusBg: "rgba(255,59,92,0.12)",
  },
  {
    priority: "P2",
    text: "Set up rolling WFE recalculation scheduler",
    status: "PENDING",
    priorityColor: "#fbbf24",
    statusColor: "#fbbf24",
    statusBg: "rgba(251,191,36,0.12)",
  },
  {
    priority: "P3",
    text: "Run SPY 1h walk-forward (WFE TBD)",
    status: "PENDING",
    priorityColor: "#fbbf24",
    statusColor: "#fbbf24",
    statusBg: "rgba(251,191,36,0.12)",
  },
  {
    priority: "P4",
    text: "Revoke exposed API keys per SECURITY_REMEDIATION.md",
    status: "P0 — URGENT",
    priorityColor: "#00d4ff",
    statusColor: "#ff3b5c",
    statusBg: "rgba(255,59,92,0.15)",
  },
  {
    priority: "P5",
    text: "IB Gateway paper port 4002 — verify TWS running",
    status: "PENDING",
    priorityColor: "#00d4ff",
    statusColor: "#fbbf24",
    statusBg: "rgba(251,191,36,0.12)",
  },
  {
    priority: "P6",
    text: "MGC redesign — extend history to 2022",
    status: "DEFERRED",
    priorityColor: "#475569",
    statusColor: "#475569",
    statusBg: "rgba(71,85,105,0.12)",
  },
  {
    priority: "P7",
    text: "CI/CD pipeline setup",
    status: "BACKLOG",
    priorityColor: "#334155",
    statusColor: "#334155",
    statusBg: "rgba(51,65,85,0.12)",
  },
];

const GO_LIVE_ITEMS = [
  {
    id: 1,
    text: "MCL WFE ≥ 0.70",
    result: "0.82",
    status: "PASS" as const,
  },
  {
    id: 2,
    text: "MNQ WFE ≥ 0.50",
    result: "0.57",
    status: "PASS" as const,
  },
  {
    id: 3,
    text: "Minimum 60 trades",
    result: "0/60",
    status: "PENDING" as const,
  },
  {
    id: 4,
    text: "Profit Factor ≥ 1.5",
    result: "—",
    status: "PENDING" as const,
  },
  {
    id: 5,
    text: "Sharpe Ratio ≥ 1.0",
    result: "—",
    status: "PENDING" as const,
  },
  {
    id: 6,
    text: "Win Rate ≥ 45%",
    result: "—",
    status: "PENDING" as const,
  },
  {
    id: 7,
    text: "Max Drawdown < 8%",
    result: "Monitoring",
    status: "ACTIVE" as const,
  },
  {
    id: 8,
    text: "No EP-3 events in 2 weeks",
    result: "Monitoring",
    status: "ACTIVE" as const,
  },
  {
    id: 9,
    text: "IB Gateway paper port verified",
    result: "—",
    status: "PENDING" as const,
  },
  {
    id: 10,
    text: "Kill switch test passed",
    result: "Monitoring",
    status: "ACTIVE" as const,
  },
];

// ── Sub-components ─────────────────────────────────────────────────────────

function PanelHead({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="text-xs font-mono tracking-widest uppercase pb-3 mb-4 border-b"
      style={{ color: "#00d4ff", borderColor: "rgba(0,212,255,0.15)", letterSpacing: "0.22em" }}
    >
      {children}
    </div>
  );
}

function StatusBadge({ status }: { status: "APPROVED" | "HALTED" | string }) {
  const approved = status === "APPROVED";
  return (
    <span
      className="text-xs font-mono tracking-wider px-2 py-0.5 rounded"
      style={
        approved
          ? { background: "rgba(0,255,136,0.1)", color: "#00ff88", border: "1px solid rgba(0,255,136,0.25)" }
          : { background: "rgba(255,59,92,0.1)", color: "#ff3b5c", border: "1px solid rgba(255,59,92,0.25)" }
      }
    >
      {status}
    </span>
  );
}

function WfeColor(wfe: number): string {
  if (wfe >= 0.7) return "#00ff88";
  if (wfe >= 0.5) return "#00d4ff";
  if (wfe >= 0.3) return "#fbbf24";
  return "#ff3b5c";
}

// ── WFE Monitor ────────────────────────────────────────────────────────────

function WfeMonitor() {
  const [animated, setAnimated] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => setAnimated(true), 400);
    return () => clearTimeout(t);
  }, []);

  return (
    <div
      className="rounded p-4 flex flex-col h-full"
      style={{
        background: "rgba(10,22,40,0.85)",
        border: "1px solid rgba(0,212,255,0.12)",
        boxShadow: "inset 0 0 30px rgba(0,212,255,0.03)",
      }}
    >
      <PanelHead>Walk-Forward Efficiency</PanelHead>

      <div className="flex flex-col gap-4 flex-1">
        {WFE_INSTRUMENTS.map((inst) => {
          const barWidth = animated ? inst.wfe * 100 : 0;
          const scoreColor = WfeColor(inst.wfe);
          const thresholdPct = 30; // 0.30 threshold at 30%
          const status = symbolTradeStatus(inst.symbol);

          return (
            <div key={inst.symbol} className="space-y-1">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span
                    className="text-sm font-mono font-bold tracking-wider"
                    style={{ color: inst.color }}
                  >
                    {inst.symbol}
                  </span>
                  <span className="text-xs text-slate-500 font-mono">{inst.tf}</span>
                  <StatusBadge status={status} />
                </div>
                <span
                  className="text-xl font-mono font-bold"
                  style={{ color: scoreColor, fontFamily: "'JetBrains Mono', monospace" }}
                >
                  {inst.wfe.toFixed(2)}
                </span>
              </div>

              <div className="text-xs text-slate-600 font-mono">{inst.detail}</div>

              {/* Progress bar with threshold marker */}
              <div className="relative" style={{ height: "6px" }}>
                <div
                  className="absolute inset-0 rounded"
                  style={{ background: "#0a1628" }}
                />
                {/* Threshold line at 0.30 */}
                <div
                  className="absolute top-0 bottom-0 w-px z-10"
                  style={{
                    left: `${thresholdPct}%`,
                    background: "rgba(251,191,36,0.6)",
                  }}
                />
                {/* Fill */}
                <div
                  className="absolute top-0 left-0 bottom-0 rounded"
                  style={{
                    width: `${barWidth}%`,
                    background: `linear-gradient(90deg, ${inst.gradFrom}, ${inst.gradTo})`,
                    transition: "width 1.8s cubic-bezier(0.16, 1, 0.3, 1)",
                  }}
                />
                {/* Sheen tip */}
                {animated && (
                  <div
                    className="absolute top-0 bottom-0 w-1 rounded-r"
                    style={{
                      left: `calc(${barWidth}% - 4px)`,
                      background: "rgba(255,255,255,0.5)",
                    }}
                  />
                )}
              </div>

              <div className="flex justify-between text-xs font-mono text-slate-600">
                <span>0.00</span>
                <span style={{ color: "rgba(251,191,36,0.7)" }}>0.30 threshold</span>
                <span>1.00</span>
              </div>
            </div>
          );
        })}
      </div>

      <div
        className="mt-4 pt-3 text-xs font-mono text-slate-600"
        style={{ borderTop: "1px solid rgba(30,41,59,0.6)", letterSpacing: "0.05em" }}
      >
        Next recalc: Sunday 06:00 CT &nbsp;·&nbsp; Window: 180d IS / 60d OOS
      </div>
    </div>
  );
}

// ── Phase Progress Chart ───────────────────────────────────────────────────

const PHASE_PIE_DATA = PHASES.map((p) => ({ name: p.name, value: p.value, color: p.color }));

function PhaseProgressChart() {
  return (
    <div
      className="rounded p-4 flex flex-col h-full"
      style={{
        background: "rgba(10,22,40,0.85)",
        border: "1px solid rgba(0,212,255,0.12)",
        boxShadow: "inset 0 0 30px rgba(0,212,255,0.03)",
      }}
    >
      <PanelHead>Session Progress — Phase Overview</PanelHead>

      <div className="flex flex-col items-center">
        <div style={{ width: "100%", height: 220 }}>
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={PHASE_PIE_DATA}
                cx="50%"
                cy="50%"
                innerRadius={65}
                outerRadius={90}
                paddingAngle={3}
                dataKey="value"
                startAngle={90}
                endAngle={-270}
              >
                {PHASE_PIE_DATA.map((entry, index) => (
                  <Cell key={`phase-${index}`} fill={entry.color} opacity={0.9} />
                ))}
              </Pie>
              <Tooltip
                contentStyle={{
                  background: "#0a1628",
                  border: "1px solid rgba(0,212,255,0.2)",
                  borderRadius: "4px",
                  fontFamily: "'JetBrains Mono', monospace",
                  fontSize: "12px",
                  color: "#94a3b8",
                }}
                formatter={(value: number) => [`${value}%`, ""]}
              />
            </PieChart>
          </ResponsiveContainer>
        </div>

        {/* Center overlay text — positioned absolutely over chart */}
        <div
          className="relative -mt-[134px] mb-[18px] text-center pointer-events-none"
        >
          <div
            className="text-3xl font-bold"
            style={{ fontFamily: "'JetBrains Mono', monospace", color: "#e2e8f0" }}
          >
            {OVERALL_PCT}%
          </div>
          <div className="text-xs font-mono text-slate-500 tracking-widest">COMPLETE</div>
          <div className="text-xs font-mono tracking-widest" style={{ color: "#334155" }}>v2.7</div>
        </div>

        {/* Phase legend */}
        <div className="w-full mt-2 grid grid-cols-2 gap-x-4 gap-y-1">
          {PHASES.map((p) => (
            <div key={p.name} className="flex items-center justify-between">
              <div className="flex items-center gap-1.5">
                <div
                  className="w-2 h-2 rounded-full flex-shrink-0"
                  style={{ background: p.color }}
                />
                <span className="text-xs text-slate-400 font-mono">{p.name}</span>
              </div>
              <span
                className="text-xs font-mono font-bold"
                style={{ color: p.color }}
              >
                {p.value}%
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── VIX Regime Visualizer ──────────────────────────────────────────────────

function getVixTier(vix: number | null | undefined): number {
  if (!vix) return -1;
  for (let i = 0; i < VIX_TIERS.length; i++) {
    if (vix >= VIX_TIERS[i].min && vix < VIX_TIERS[i].max) return i;
  }
  return -1;
}

function VixRegimeVisualizer({ macro }: { macro?: MacroData }) {
  const vix = macro?.vix ?? null;
  const activeTier = getVixTier(vix);

  return (
    <div
      className="rounded p-4 flex flex-col h-full"
      style={{
        background: "rgba(10,22,40,0.85)",
        border: "1px solid rgba(0,212,255,0.12)",
        boxShadow: "inset 0 0 30px rgba(0,212,255,0.03)",
      }}
    >
      <PanelHead>VIX Regime — Canonical 6-Tier</PanelHead>

      {/* Current VIX display */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <div
            className="text-4xl font-bold"
            style={{
              fontFamily: "'JetBrains Mono', monospace",
              color: activeTier >= 0 ? VIX_TIERS[activeTier].color : "#94a3b8",
            }}
          >
            {vix != null ? vix.toFixed(2) : "—"}
          </div>
          <div className="text-xs font-mono text-slate-500 tracking-widest mt-1">
            CURRENT VIX
          </div>
        </div>
        {activeTier >= 0 && (
          <div
            className="px-3 py-1.5 rounded font-mono text-sm font-bold tracking-widest"
            style={{
              background: `${VIX_TIERS[activeTier].color}18`,
              color: VIX_TIERS[activeTier].color,
              border: `1px solid ${VIX_TIERS[activeTier].color}40`,
            }}
          >
            {VIX_TIERS[activeTier].label}
          </div>
        )}
        {vix == null && (
          <div
            className="px-3 py-1.5 rounded font-mono text-xs tracking-widest"
            style={{
              background: "rgba(71,85,105,0.2)",
              color: "#475569",
              border: "1px solid rgba(71,85,105,0.3)",
            }}
          >
            NO DATA
          </div>
        )}
      </div>

      {/* Tier rows */}
      <div className="flex flex-col gap-1.5 flex-1">
        {VIX_TIERS.map((tier, i) => {
          const isActive = i === activeTier;
          const barWidth = Math.min(((tier.max === Infinity ? 40 : tier.max) / 40) * 100, 100);

          return (
            <div
              key={tier.label}
              className="flex items-center gap-3 px-2 py-1.5 rounded transition-all duration-300"
              style={{
                background: isActive ? `${tier.color}18` : "transparent",
                border: isActive ? `1px solid ${tier.color}35` : "1px solid transparent",
              }}
            >
              <span
                className="text-xs font-mono font-bold w-20 tracking-wider"
                style={{ color: isActive ? tier.color : "#475569" }}
              >
                {tier.label}
              </span>
              <div className="flex-1 relative h-1.5 rounded overflow-hidden" style={{ background: "#0a1628" }}>
                <div
                  className="absolute top-0 left-0 h-full rounded"
                  style={{
                    width: `${barWidth}%`,
                    background: isActive ? tier.color : `${tier.color}40`,
                  }}
                />
              </div>
              <span
                className="text-xs font-mono w-12 text-right"
                style={{ color: isActive ? tier.color : "#334155" }}
              >
                {tier.range}
              </span>
            </div>
          );
        })}
      </div>

      <div
        className="mt-3 pt-3 text-xs font-mono text-center"
        style={{
          borderTop: "1px solid rgba(30,41,59,0.6)",
          color: "#1e293b",
          letterSpacing: "0.1em",
        }}
      >
        IRON CONDORS: NORMAL + ELEVATED ONLY · NEVER HIGH/EXTREME
      </div>
    </div>
  );
}

// ── 30-Day Progress Tracker ────────────────────────────────────────────────

function ThirtyDayTracker() {
  // "today" and "startDate" are intentionally client-only state (GT-34,
  // sibling fix to GT-27 PR #496 / GT-30 PR #503 / GT-33 PR #506). See
  // lib/thirtyDayTracker.ts for the two hydration defects this closes:
  //   1. The old useState lazy initializer branched on `typeof window`
  //      directly, which is guaranteed to diverge between the server
  //      render and the client's first hydration render on every render
  //      -- not just across a clock boundary.
  //   2. `const today = new Date()` read directly during render is the
  //      unguarded-new-Date() class already fixed elsewhere in GT-27/30/33.
  // Both start at `null` and are only ever set from a mount-only effect, so
  // the server render and the client's pre-mount render always take the
  // same placeholder branch and can never disagree.
  const [today, setToday] = useState<Date | null>(null);
  const [startDate, setStartDate] = useState<Date | null>(null);

  useEffect(() => {
    const now = new Date();
    const stored = localStorage.getItem(START_DATE_STORAGE_KEY);
    setToday(now);
    setStartDate(resolveStartDate(now, stored));
  }, []);

  function handleDateChange(e: React.ChangeEvent<HTMLInputElement>) {
    const d = new Date(e.target.value + "T00:00:00");
    if (!isNaN(d.getTime())) {
      setStartDate(d);
      localStorage.setItem(START_DATE_STORAGE_KEY, e.target.value);
    }
  }

  function formatDateStr(d: Date) {
    return d.toISOString().split("T")[0];
  }

  function formatDisplayDate(d: Date) {
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  }

  const stats = startDate ? trackerStatsFor(startDate, today) : null;
  const calCells = startDate && stats ? buildCalendarCells(startDate, stats.endDate, today) : [];
  const daysElapsed = stats?.daysElapsed ?? 0;
  const daysRemaining = stats?.daysRemaining ?? WINDOW_DAYS;
  const progress = stats?.progress ?? 0;

  const cellColor: Record<string, string> = {
    before: "rgba(30,41,59,0.3)",
    "active-past": "rgba(0,212,255,0.35)",
    today: "#00d4ff",
    future: "rgba(30,41,59,0.15)",
    outside: "rgba(15,20,35,0.2)",
  };

  return (
    <div
      className="rounded p-4 flex flex-col h-full"
      style={{
        background: "rgba(10,22,40,0.85)",
        border: "1px solid rgba(0,212,255,0.12)",
      }}
    >
      <PanelHead>30-Day Paper Trading Window</PanelHead>

      {/* Header stats */}
      <div className="grid grid-cols-3 gap-3 mb-4">
        <div className="text-center">
          <div
            className="text-3xl font-bold"
            style={{ fontFamily: "'JetBrains Mono', monospace", color: "#00d4ff" }}
          >
            {daysElapsed}
          </div>
          <div className="text-xs font-mono text-slate-600 tracking-wider">ELAPSED</div>
        </div>
        <div className="text-center">
          <div
            className="text-3xl font-bold"
            style={{ fontFamily: "'JetBrains Mono', monospace", color: "#94a3b8" }}
          >
            {WINDOW_DAYS}
          </div>
          <div className="text-xs font-mono text-slate-600 tracking-wider">TARGET</div>
        </div>
        <div className="text-center">
          <div
            className="text-3xl font-bold"
            style={{ fontFamily: "'JetBrains Mono', monospace", color: daysRemaining === 0 ? "#00ff88" : "#fbbf24" }}
          >
            {daysRemaining}
          </div>
          <div className="text-xs font-mono text-slate-600 tracking-wider">REMAINING</div>
        </div>
      </div>

      {/* Progress bar */}
      <div className="mb-3">
        <div className="flex justify-between text-xs font-mono text-slate-500 mb-1">
          <span>Day {daysElapsed} of {WINDOW_DAYS}</span>
          <span>{progress.toFixed(0)}%</span>
        </div>
        <div className="relative h-2 rounded overflow-hidden" style={{ background: "#0a1628" }}>
          <div
            className="h-full rounded"
            style={{
              width: `${progress}%`,
              background: "linear-gradient(90deg, #0891b2, #00d4ff)",
              transition: "width 1s ease",
            }}
          />
        </div>
      </div>

      {/* Date info + input */}
      <div className="flex items-center justify-between mb-3 text-xs font-mono">
        <div>
          <span className="text-slate-500">Start: </span>
          <span className="text-slate-300">{startDate ? formatDisplayDate(startDate) : "—"}</span>
        </div>
        <div>
          <span className="text-slate-500">End: </span>
          <span className="text-slate-300">{stats ? formatDisplayDate(stats.endDate) : "—"}</span>
        </div>
      </div>

      {/* Start date picker */}
      <div className="flex items-center gap-2 mb-4">
        <label className="text-xs font-mono text-slate-500 tracking-wider whitespace-nowrap">
          Paper Start:
        </label>
        <input
          type="date"
          value={startDate ? formatDateStr(startDate) : ""}
          onChange={handleDateChange}
          disabled={!startDate}
          className="flex-1 rounded px-2 py-1 text-xs font-mono disabled:opacity-50"
          style={{
            background: "rgba(6,13,26,0.8)",
            border: "1px solid rgba(0,212,255,0.2)",
            color: "#94a3b8",
            outline: "none",
          }}
        />
      </div>

      {/* Calendar grid */}
      <div>
        <div className="grid grid-cols-7 gap-1 mb-1">
          {["S", "M", "T", "W", "T", "F", "S"].map((d, i) => (
            <div key={i} className="text-center text-xs font-mono" style={{ color: "#334155" }}>
              {d}
            </div>
          ))}
        </div>
        <div className="grid grid-cols-7 gap-1">
          {calCells.length > 0
            ? calCells.map((cell, i) => {
                const isToday = cell.status === "today";
                return (
                  <div
                    key={i}
                    className="aspect-square rounded flex items-center justify-center text-xs font-mono relative"
                    style={{
                      background: cellColor[cell.status],
                      color: isToday ? "#000" : cell.status === "active-past" ? "#00d4ff" : "#334155",
                      fontWeight: isToday ? "700" : "400",
                    }}
                  >
                    {isToday && (
                      <div
                        className="absolute inset-0 rounded animate-ping"
                        style={{ background: "rgba(0,212,255,0.4)" }}
                      />
                    )}
                    <span className="relative z-10">{cell.date.getDate()}</span>
                  </div>
                );
              })
            : // Pre-mount placeholder: same 35-cell grid, stable across
              // server and client-pre-mount renders (see lib/thirtyDayTracker.ts).
              Array.from({ length: 35 }).map((_, i) => (
                <div key={i} className="aspect-square rounded" style={{ background: cellColor.outside }} />
              ))}
        </div>
      </div>
    </div>
  );
}

// ── Priority Queue ─────────────────────────────────────────────────────────

function PriorityQueue() {
  return (
    <div
      className="rounded p-4 flex flex-col h-full"
      style={{
        background: "rgba(10,22,40,0.85)",
        border: "1px solid rgba(0,212,255,0.12)",
      }}
    >
      <PanelHead>Next Actions — Priority Queue</PanelHead>

      <div className="flex flex-col gap-0 flex-1">
        {PRIORITY_ITEMS.map((item, i) => (
          <div
            key={i}
            className="flex items-start gap-3 py-2.5"
            style={{
              borderBottom: i < PRIORITY_ITEMS.length - 1 ? "1px solid rgba(30,41,59,0.5)" : "none",
            }}
          >
            <span
              className="text-xs font-mono font-bold shrink-0 w-8"
              style={{ color: item.priorityColor }}
            >
              [{item.priority}]
            </span>
            <span className="text-xs text-slate-400 font-mono flex-1 leading-relaxed">
              {item.text}
            </span>
            <span
              className="text-xs font-mono px-2 py-0.5 rounded shrink-0"
              style={{
                background: item.statusBg,
                color: item.statusColor,
                border: `1px solid ${item.statusColor}35`,
              }}
            >
              {item.status}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Go-Live Validation Checklist ───────────────────────────────────────────

const STATUS_CONFIG = {
  PASS: {
    icon: "✓",
    color: "#00ff88",
    bg: "rgba(0,255,136,0.07)",
    border: "rgba(0,255,136,0.2)",
    badge: { color: "#00ff88", bg: "rgba(0,255,136,0.1)", border: "rgba(0,255,136,0.25)" },
  },
  PENDING: {
    icon: "○",
    color: "#475569",
    bg: "transparent",
    border: "transparent",
    badge: { color: "#64748b", bg: "rgba(100,116,139,0.1)", border: "rgba(100,116,139,0.25)" },
  },
  ACTIVE: {
    icon: "◉",
    color: "#00d4ff",
    bg: "rgba(0,212,255,0.05)",
    border: "rgba(0,212,255,0.15)",
    badge: { color: "#00d4ff", bg: "rgba(0,212,255,0.1)", border: "rgba(0,212,255,0.25)" },
  },
} as const;

type GoLiveStatus = "PASS" | "PENDING" | "ACTIVE";

function GoLiveChecklist() {
  const passCount = GO_LIVE_ITEMS.filter((i) => i.status === "PASS").length;
  const totalCount = GO_LIVE_ITEMS.length;

  return (
    <div
      className="rounded p-4"
      style={{
        background: "rgba(10,22,40,0.85)",
        border: "1px solid rgba(0,212,255,0.12)",
      }}
    >
      <div className="flex items-center justify-between mb-4">
        <PanelHead>Go-Live Validation Checklist</PanelHead>
        <span
          className="text-xs font-mono px-3 py-1 rounded ml-4"
          style={{
            background: "rgba(0,212,255,0.1)",
            color: "#00d4ff",
            border: "1px solid rgba(0,212,255,0.25)",
            flexShrink: 0,
          }}
        >
          {passCount}/{totalCount} COMPLETE — IN PROGRESS
        </span>
      </div>

      <div className="grid grid-cols-2 gap-2">
        {GO_LIVE_ITEMS.map((item) => {
          const cfg = STATUS_CONFIG[item.status as GoLiveStatus];
          return (
            <div
              key={item.id}
              className="flex items-center gap-3 p-3 rounded"
              style={{
                background: cfg.bg,
                border: `1px solid ${cfg.border}`,
              }}
            >
              <span
                className="text-base flex-shrink-0 font-mono w-5 text-center"
                style={{ color: cfg.color }}
              >
                {cfg.icon}
              </span>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-1.5">
                  <span className="text-xs font-mono text-slate-500 w-4 shrink-0">
                    {item.id}.
                  </span>
                  <span className="text-xs text-slate-300 font-mono leading-tight truncate">
                    {item.text}
                  </span>
                </div>
              </div>
              <span
                className="text-xs font-mono px-1.5 py-0.5 rounded shrink-0"
                style={{
                  color: cfg.badge.color,
                  background: cfg.badge.bg,
                  border: `1px solid ${cfg.badge.border}`,
                }}
              >
                {item.result}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Main Tab Component ─────────────────────────────────────────────────────

export default function AnalyticsTab({ data }: AnalyticsTabProps) {
  const macro = data?.macro?.data;

  return (
    <div className="space-y-4">
      {/* ── Section 1: Top Row (3 columns) ── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <WfeMonitor />
        <PhaseProgressChart />
        <VixRegimeVisualizer macro={macro} />
      </div>

      {/* ── Section 2: Middle Row (2 columns) ── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <ThirtyDayTracker />
        <PriorityQueue />
      </div>

      {/* ── Section 3: Bottom (full width) ── */}
      <GoLiveChecklist />
    </div>
  );
}
