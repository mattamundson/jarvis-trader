"use client";

import React, { useState, useMemo } from "react";
import {
  PieChart,
  Pie,
  Cell,
  ResponsiveContainer,
  Tooltip,
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  Radar,
  Legend,
} from "recharts";
import { cn } from "@/lib/utils";

// ── Audit Data ─────────────────────────────────────────────────────────────

type AuditStatus = "PASS" | "WARN" | "FAIL" | "PENDING";
type AuditCategory =
  | "Validation"
  | "Options"
  | "API"
  | "Paper"
  | "Dashboard"
  | "Docs"
  | "Infra";

interface AuditItem {
  id: number;
  cat: AuditCategory;
  title: string;
  status: AuditStatus;
  detail: string;
}

const AUDIT_ITEMS: AuditItem[] = [
  // Validation (6)
  {
    id: 1,
    cat: "Validation",
    title: "MCL WFE Validation",
    status: "PASS",
    detail: "WFE=0.82 EXCELLENT — static params, regime_filter=ON",
  },
  {
    id: 2,
    cat: "Validation",
    title: "MNQ WFE Validation",
    status: "PASS",
    detail: "WFE=0.57 GOOD — adaptive_regime=ON, no MTF, no volume filter",
  },
  {
    id: 3,
    cat: "Validation",
    title: "MGC Status",
    status: "WARN",
    detail: "WFE=0.14 OVERFIT — HALTED. Small-sample bias confirmed.",
  },
  {
    id: 4,
    cat: "Validation",
    title: "Filter Rejection Validation",
    status: "PASS",
    detail: "MTF hurts (WFE→0.17), Volume hurts (WFE→-0.23) for MNQ",
  },
  {
    id: 5,
    cat: "Validation",
    title: "Optimizer Kwarg Bug Fix",
    status: "PASS",
    detail: "Extra kwargs silently caused WF calls to return None. Fixed.",
  },
  {
    id: 6,
    cat: "Validation",
    title: "MES/SPY Overfit Documentation",
    status: "PASS",
    detail: "MES WFE=0.09 DO NOT TRADE. SPY WFE pending corrected WF.",
  },
  // Options Engine (5)
  {
    id: 7,
    cat: "Options",
    title: "greeks_monitor.py",
    status: "PASS",
    detail: "450 lines, Newton-Raphson IV solver, Black-Scholes Greeks",
  },
  {
    id: 8,
    cat: "Options",
    title: "strategy_executor.py",
    status: "PASS",
    detail: "632 lines, 7 strategies, VIX regime validation",
  },
  {
    id: 9,
    cat: "Options",
    title: "chain_fetcher.py",
    status: "PASS",
    detail: "439 lines, live yfinance chain fetching",
  },
  {
    id: 10,
    cat: "Options",
    title: "premium_calculator.py",
    status: "PASS",
    detail: "293 lines, probability of profit calculations",
  },
  {
    id: 11,
    cat: "Options",
    title: "position_manager.py",
    status: "PASS",
    detail: "487 lines, SQLite persistence, expiration alerts",
  },
  // API & Engine (3)
  {
    id: 12,
    cat: "API",
    title: "Options Endpoints Wired",
    status: "PASS",
    detail: "5 endpoints: /options/chain, /positions, /trade, /greeks, /scan",
  },
  {
    id: 13,
    cat: "API",
    title: "23 API Field Corrections",
    status: "PASS",
    detail: "engine/main.py updated with validated response shapes",
  },
  {
    id: 14,
    cat: "API",
    title: "FRED API Key",
    status: "FAIL",
    detail: "FRED_API_KEY not configured — macro data limited to VIX only",
  },
  // Paper Trading (4)
  {
    id: 15,
    cat: "Paper",
    title: "MCL Paper Config",
    status: "PASS",
    detail: "STC_OS=15, STC_OB=83, Stop=0.90 ATR, T1=1.50 ATR",
  },
  {
    id: 16,
    cat: "Paper",
    title: "MNQ Paper Config",
    status: "PASS",
    detail: "STC_OS=15, STC_OB=92, Stop=0.70 ATR, T1=1.00 ATR",
  },
  {
    id: 17,
    cat: "Paper",
    title: "MGC Paper Config Halted",
    status: "PASS",
    detail: "MGC disabled in paper_config.py — HALTED status enforced",
  },
  {
    id: 18,
    cat: "Paper",
    title: "Kill Thresholds Per Instrument",
    status: "PASS",
    detail: "Daily loss limits and drawdown thresholds set per symbol",
  },
  // Dashboard (4)
  {
    id: 19,
    cat: "Dashboard",
    title: "Command Center HUD",
    status: "PASS",
    detail: "Unified HUD with 5 tabs, Three.js background, live data",
  },
  {
    id: 20,
    cat: "Dashboard",
    title: "16/16 Build Clean",
    status: "PASS",
    detail: "Next.js 15 build passes 0 TypeScript errors",
  },
  {
    id: 21,
    cat: "Dashboard",
    title: "Performance Page v2.7 Data",
    status: "PASS",
    detail: "WFE scores, instrument status updated to v2.7",
  },
  {
    id: 22,
    cat: "Dashboard",
    title: "Scorecard Canonical Thresholds",
    status: "PASS",
    detail: "PF≥1.5, Sharpe≥1.0, MaxDD<10%, WR≥45% — canonical",
  },
  // Documentation (5)
  {
    id: 23,
    cat: "Docs",
    title: "JARVIS_TRADER_MASTER.md",
    status: "PASS",
    detail: "3,323 lines — single source of truth, 20 sections",
  },
  {
    id: 24,
    cat: "Docs",
    title: "MEMORY.md Updated",
    status: "PASS",
    detail: "89 lines, resolved conflicts, next phase 7-item list",
  },
  {
    id: 25,
    cat: "Docs",
    title: "PAPER_TRADING_APPROVAL.md",
    status: "PASS",
    detail: "MCL + MNQ approved. MGC halted. Criteria documented.",
  },
  {
    id: 26,
    cat: "Docs",
    title: "EXECUTIVE_BRIEFING.md",
    status: "PASS",
    detail: "Phase 2B summary with all WFE results and next steps",
  },
  {
    id: 27,
    cat: "Docs",
    title: "CANON_SOURCE_MAP.json",
    status: "PASS",
    detail: "All canonical values mapped to authoritative sources",
  },
  // Infrastructure (3)
  {
    id: 28,
    cat: "Infra",
    title: "Safety Layer Architecture",
    status: "PASS",
    detail: "Hardcoded Python safety, no LLM in risk enforcement",
  },
  {
    id: 29,
    cat: "Infra",
    title: "IB Gateway Paper Port 4002",
    status: "PENDING",
    detail: "Requires TWS running with paper port 4002 configuration",
  },
  {
    id: 30,
    cat: "Infra",
    title: "Rolling WFE Recalculation Job",
    status: "PENDING",
    detail: "Scheduler job for Sunday 06:00 CT recalculation not yet built",
  },
];

// ── Conflict Resolution Data ───────────────────────────────────────────────

const CONFLICTS = [
  {
    conflict: "VIX Regime Tiers",
    prior: "4-tier / 5-tier / 6-tier",
    canonical: "6-tier canonical",
    section: "§1.7",
  },
  {
    conflict: "Win Rate Threshold",
    prior: "28% / 50% / 55%",
    canonical: "Paper ≥45%, Live ≥50%",
    section: "§1.17",
  },
  {
    conflict: "Max Drawdown",
    prior: "8% / 10% / 15%",
    canonical: "Paper <10%, Live gate <8%",
    section: "§1.6",
  },
  {
    conflict: "Min Trades",
    prior: "40 / 60",
    canonical: "60 trades over 60 days",
    section: "§1.17",
  },
  {
    conflict: "MCL Status",
    prior: "DO NOT TRADE / APPROVED",
    canonical: "APPROVED (WFE=0.82)",
    section: "§1.5",
  },
  {
    conflict: "MGC Status",
    prior: "ACTIVE / HALTED",
    canonical: "HALTED (WFE=0.14)",
    section: "§1.5",
  },
  {
    conflict: "Next.js Version",
    prior: "14 / 15",
    canonical: "Next.js 15 (confirmed)",
    section: "§1.13",
  },
];

// ── Status Config ──────────────────────────────────────────────────────────

const STATUS_STYLE: Record<
  AuditStatus,
  {
    color: string;
    bg: string;
    border: string;
    leftBorder: string;
    badge: { color: string; bg: string; border: string };
  }
> = {
  PASS: {
    color: "#00ff88",
    bg: "rgba(0,255,136,0.03)",
    border: "rgba(0,255,136,0.12)",
    leftBorder: "#00ff88",
    badge: {
      color: "#00ff88",
      bg: "rgba(0,255,136,0.1)",
      border: "rgba(0,255,136,0.25)",
    },
  },
  WARN: {
    color: "#fbbf24",
    bg: "rgba(251,191,36,0.03)",
    border: "rgba(251,191,36,0.15)",
    leftBorder: "#fbbf24",
    badge: {
      color: "#fbbf24",
      bg: "rgba(251,191,36,0.1)",
      border: "rgba(251,191,36,0.25)",
    },
  },
  FAIL: {
    color: "#ff3b5c",
    bg: "rgba(255,59,92,0.04)",
    border: "rgba(255,59,92,0.2)",
    leftBorder: "#ff3b5c",
    badge: {
      color: "#ff3b5c",
      bg: "rgba(255,59,92,0.1)",
      border: "rgba(255,59,92,0.25)",
    },
  },
  PENDING: {
    color: "#64748b",
    bg: "transparent",
    border: "rgba(30,41,59,0.5)",
    leftBorder: "#334155",
    badge: {
      color: "#64748b",
      bg: "rgba(100,116,139,0.1)",
      border: "rgba(100,116,139,0.25)",
    },
  },
};

const CAT_COLORS: Record<AuditCategory, string> = {
  Validation: "#00ff88",
  Options: "#00d4ff",
  API: "#a78bfa",
  Paper: "#fbbf24",
  Dashboard: "#3b82f6",
  Docs: "#34d399",
  Infra: "#f97316",
};

// ── Score Ring Data ────────────────────────────────────────────────────────
// STATIC, manually-maintained audit snapshot — NOT live system health. The pass
// rate / pie below is frozen to whenever AUDIT_ITEMS was last hand-updated; it
// must render behind a "manual snapshot" badge so it never reads as current.
const SCORE_DATA = [
  { name: "PASS", value: 25, color: "#00ff88" },
  { name: "WARN", value: 1, color: "#fbbf24" },
  { name: "FAIL", value: 1, color: "#ff3b5c" },
  { name: "PENDING", value: 3, color: "#334155" },
];

// ── Helpers ────────────────────────────────────────────────────────────────

function PanelHead({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="text-xs font-mono tracking-widest uppercase pb-3 mb-4 border-b"
      style={{
        color: "#00d4ff",
        borderColor: "rgba(0,212,255,0.15)",
        letterSpacing: "0.22em",
      }}
    >
      {children}
    </div>
  );
}

// ── Category Breakdown ─────────────────────────────────────────────────────

const CATEGORIES: AuditCategory[] = [
  "Validation",
  "Options",
  "API",
  "Paper",
  "Dashboard",
  "Docs",
  "Infra",
];

function getCategoryStats(cat: AuditCategory) {
  const items = AUDIT_ITEMS.filter((i) => i.cat === cat);
  const pass = items.filter((i) => i.status === "PASS").length;
  return { total: items.length, pass };
}

// ── Radar Data ─────────────────────────────────────────────────────────────

function getRadarData() {
  return CATEGORIES.map((cat) => {
    const { total, pass } = getCategoryStats(cat);
    return {
      subject: cat,
      score: total > 0 ? Math.round((pass / total) * 100) : 0,
      fullMark: 100,
    };
  });
}

// ── Component: Summary Tiles ───────────────────────────────────────────────

function SummaryTiles() {
  const counts = useMemo(() => {
    const pass = AUDIT_ITEMS.filter((i) => i.status === "PASS").length;
    const warn = AUDIT_ITEMS.filter((i) => i.status === "WARN").length;
    const fail = AUDIT_ITEMS.filter((i) => i.status === "FAIL").length;
    const pending = AUDIT_ITEMS.filter((i) => i.status === "PENDING").length;
    return { pass, warn, fail, pending };
  }, []);

  const tiles = [
    { label: "TOTAL", value: AUDIT_ITEMS.length, color: "#94a3b8", border: "rgba(148,163,184,0.2)", bg: "rgba(148,163,184,0.05)" },
    { label: "PASS", value: counts.pass, color: "#00ff88", border: "rgba(0,255,136,0.25)", bg: "rgba(0,255,136,0.06)" },
    { label: "WARN / FAIL", value: counts.warn + counts.fail, color: "#ff3b5c", border: "rgba(255,59,92,0.25)", bg: "rgba(255,59,92,0.05)" },
    { label: "PENDING", value: counts.pending, color: "#fbbf24", border: "rgba(251,191,36,0.25)", bg: "rgba(251,191,36,0.05)" },
  ];

  return (
    <div className="grid grid-cols-4 gap-3">
      {tiles.map((t) => (
        <div
          key={t.label}
          className="rounded p-4 text-center"
          style={{ background: t.bg, border: `1px solid ${t.border}` }}
        >
          <div
            className="text-4xl font-bold"
            style={{ fontFamily: "'JetBrains Mono', monospace", color: t.color }}
          >
            {t.value}
          </div>
          <div
            className="text-xs font-mono tracking-widest mt-1"
            style={{ color: "#475569" }}
          >
            {t.label}
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Component: Score Ring ──────────────────────────────────────────────────

function ScoreRing() {
  return (
    <div
      className="rounded p-4 flex flex-col"
      style={{
        background: "rgba(10,22,40,0.85)",
        border: "1px solid rgba(0,212,255,0.12)",
      }}
    >
      <PanelHead>
        <span className="inline-flex items-center gap-2">
          Audit Score Ring
          <span
            className="rounded px-1.5 py-0.5 text-[8px] font-bold"
            style={{ background: "rgba(148,163,184,0.12)", border: "1px solid rgba(148,163,184,0.25)", color: "#94a3b8" }}
          >
            MANUAL SNAPSHOT
          </span>
        </span>
      </PanelHead>

      <div className="flex items-center gap-6">
        <div style={{ width: 200, height: 200, flexShrink: 0 }}>
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={SCORE_DATA}
                cx="50%"
                cy="50%"
                innerRadius={60}
                outerRadius={85}
                paddingAngle={2}
                dataKey="value"
                startAngle={90}
                endAngle={-270}
              >
                {SCORE_DATA.map((entry, index) => (
                  <Cell key={`score-${index}`} fill={entry.color} opacity={0.9} />
                ))}
              </Pie>
              <Tooltip
                contentStyle={{
                  background: "#0a1628",
                  border: "1px solid rgba(0,212,255,0.2)",
                  borderRadius: "4px",
                  fontFamily: "'JetBrains Mono', monospace",
                  fontSize: "11px",
                  color: "#94a3b8",
                }}
              />
            </PieChart>
          </ResponsiveContainer>
        </div>

        {/* Center text overlay */}
        <div className="relative" style={{ marginLeft: "-200px", width: "200px", textAlign: "center", pointerEvents: "none" }}>
          <div
            className="text-3xl font-bold"
            style={{ fontFamily: "'JetBrains Mono', monospace", color: "#00ff88" }}
          >
            83%
          </div>
          <div className="text-xs font-mono text-slate-500 tracking-widest">PASS RATE</div>
          <div className="text-xs font-mono" style={{ color: "#334155" }}>25 / 30</div>
        </div>

        {/* Legend */}
        <div className="flex flex-col gap-2 ml-4">
          {SCORE_DATA.map((s) => (
            <div key={s.name} className="flex items-center gap-2">
              <div
                className="w-3 h-3 rounded-full"
                style={{ background: s.color }}
              />
              <span className="text-xs font-mono text-slate-400">{s.name}</span>
              <span className="text-xs font-mono font-bold" style={{ color: s.color }}>
                {s.value}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Component: Radar Chart ─────────────────────────────────────────────────

function AuditRadar() {
  const radarData = useMemo(() => getRadarData(), []);

  return (
    <div
      className="rounded p-4 flex flex-col"
      style={{
        background: "rgba(10,22,40,0.85)",
        border: "1px solid rgba(0,212,255,0.12)",
      }}
    >
      <PanelHead>Category Pass Rate — Radar</PanelHead>

      <div style={{ width: "100%", height: 240 }}>
        <ResponsiveContainer width="100%" height="100%">
          <RadarChart data={radarData} margin={{ top: 10, right: 30, bottom: 10, left: 30 }}>
            <PolarGrid
              stroke="rgba(0,212,255,0.12)"
              gridType="polygon"
            />
            <PolarAngleAxis
              dataKey="subject"
              tick={{
                fill: "#475569",
                fontSize: 10,
                fontFamily: "'JetBrains Mono', monospace",
              }}
            />
            <Radar
              name="Pass Rate %"
              dataKey="score"
              stroke="#00d4ff"
              fill="#00d4ff"
              fillOpacity={0.15}
              strokeWidth={1.5}
              dot={{ fill: "#00d4ff", r: 3 }}
            />
            <Tooltip
              contentStyle={{
                background: "#0a1628",
                border: "1px solid rgba(0,212,255,0.2)",
                borderRadius: "4px",
                fontFamily: "'JetBrains Mono', monospace",
                fontSize: "11px",
                color: "#94a3b8",
              }}
              formatter={(value: number) => [`${value}%`, "Pass Rate"]}
            />
          </RadarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

// ── Component: Filter Bar ──────────────────────────────────────────────────

type FilterOption = "ALL" | AuditStatus;

function FilterBar({
  active,
  onChange,
  counts,
}: {
  active: FilterOption;
  onChange: (f: FilterOption) => void;
  counts: Record<FilterOption, number>;
}) {
  const options: FilterOption[] = ["ALL", "PASS", "WARN", "FAIL", "PENDING"];

  const optStyle: Record<FilterOption, { activeColor: string; activeBg: string; activeBorder: string }> = {
    ALL: { activeColor: "#00d4ff", activeBg: "rgba(0,212,255,0.15)", activeBorder: "rgba(0,212,255,0.4)" },
    PASS: { activeColor: "#00ff88", activeBg: "rgba(0,255,136,0.12)", activeBorder: "rgba(0,255,136,0.4)" },
    WARN: { activeColor: "#fbbf24", activeBg: "rgba(251,191,36,0.12)", activeBorder: "rgba(251,191,36,0.4)" },
    FAIL: { activeColor: "#ff3b5c", activeBg: "rgba(255,59,92,0.12)", activeBorder: "rgba(255,59,92,0.4)" },
    PENDING: { activeColor: "#64748b", activeBg: "rgba(100,116,139,0.12)", activeBorder: "rgba(100,116,139,0.4)" },
  };

  return (
    <div className="flex items-center gap-2 flex-wrap">
      <span className="text-xs font-mono text-slate-600 tracking-wider">FILTER:</span>
      {options.map((opt) => {
        const isActive = active === opt;
        const s = optStyle[opt];
        return (
          <button
            key={opt}
            onClick={() => onChange(opt)}
            className="px-3 py-1 rounded text-xs font-mono tracking-wider transition-all duration-150"
            style={
              isActive
                ? {
                    color: s.activeColor,
                    background: s.activeBg,
                    border: `1px solid ${s.activeBorder}`,
                  }
                : {
                    color: "#475569",
                    background: "rgba(30,41,59,0.3)",
                    border: "1px solid rgba(30,41,59,0.5)",
                  }
            }
          >
            {opt} ({counts[opt]})
          </button>
        );
      })}
    </div>
  );
}

// ── Component: Audit Cards ─────────────────────────────────────────────────

const CAT_BADGE_COLORS: Record<AuditCategory, { color: string; bg: string; border: string }> = {
  Validation: { color: "#00ff88", bg: "rgba(0,255,136,0.1)", border: "rgba(0,255,136,0.2)" },
  Options: { color: "#00d4ff", bg: "rgba(0,212,255,0.1)", border: "rgba(0,212,255,0.2)" },
  API: { color: "#a78bfa", bg: "rgba(167,139,250,0.1)", border: "rgba(167,139,250,0.2)" },
  Paper: { color: "#fbbf24", bg: "rgba(251,191,36,0.1)", border: "rgba(251,191,36,0.2)" },
  Dashboard: { color: "#3b82f6", bg: "rgba(59,130,246,0.1)", border: "rgba(59,130,246,0.2)" },
  Docs: { color: "#34d399", bg: "rgba(52,211,153,0.1)", border: "rgba(52,211,153,0.2)" },
  Infra: { color: "#f97316", bg: "rgba(249,115,22,0.1)", border: "rgba(249,115,22,0.2)" },
};

function AuditCard({ item }: { item: AuditItem }) {
  const s = STATUS_STYLE[item.status];
  const catStyle = CAT_BADGE_COLORS[item.cat];

  return (
    <div
      className="rounded overflow-hidden"
      style={{
        background: s.bg,
        border: `1px solid ${s.border}`,
        borderLeft: `3px solid ${s.leftBorder}`,
      }}
    >
      <div className="p-3">
        {/* Top row: ID, category, status */}
        <div className="flex items-center gap-2 mb-2">
          <span className="text-xs font-mono" style={{ color: "#334155" }}>
            #{item.id}
          </span>
          <span
            className="text-xs font-mono px-1.5 py-0.5 rounded"
            style={{
              color: catStyle.color,
              background: catStyle.bg,
              border: `1px solid ${catStyle.border}`,
            }}
          >
            {item.cat}
          </span>
          <div className="flex-1" />
          <span
            className="text-xs font-mono px-2 py-0.5 rounded font-bold tracking-wider"
            style={{
              color: s.badge.color,
              background: s.badge.bg,
              border: `1px solid ${s.badge.border}`,
            }}
          >
            {item.status}
          </span>
        </div>

        {/* Title */}
        <div
          className="text-sm font-bold mb-1"
          style={{ color: "#c9daf8", fontFamily: "'JetBrains Mono', monospace" }}
        >
          {item.title}
        </div>

        {/* Detail */}
        <div className="text-xs leading-relaxed" style={{ color: "#475569" }}>
          {item.detail}
        </div>
      </div>
    </div>
  );
}

// ── Component: Category Breakdown ─────────────────────────────────────────

function CategoryBreakdown() {
  return (
    <div
      className="rounded p-4"
      style={{
        background: "rgba(10,22,40,0.85)",
        border: "1px solid rgba(0,212,255,0.12)",
      }}
    >
      <PanelHead>Category Breakdown</PanelHead>

      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-3">
        {CATEGORIES.map((cat) => {
          const { total, pass } = getCategoryStats(cat);
          const pct = total > 0 ? Math.round((pass / total) * 100) : 0;
          const color = CAT_COLORS[cat];

          return (
            <div
              key={cat}
              className="rounded p-3 text-center"
              style={{
                background: `${color}08`,
                border: `1px solid ${color}25`,
              }}
            >
              <div
                className="text-xs font-mono font-bold mb-2 tracking-wider"
                style={{ color }}
              >
                {cat}
              </div>
              <div
                className="text-xl font-bold"
                style={{ fontFamily: "'JetBrains Mono', monospace", color }}
              >
                {pass}/{total}
              </div>
              <div className="text-xs font-mono mt-1" style={{ color: "#475569" }}>
                {pct}%
              </div>
              {/* Mini bar */}
              <div
                className="mt-2 h-1 rounded overflow-hidden"
                style={{ background: "#0a1628" }}
              >
                <div
                  className="h-full rounded"
                  style={{
                    width: `${pct}%`,
                    background: color,
                    transition: "width 1s ease",
                  }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Component: Conflict Resolution Table ──────────────────────────────────

function ConflictTable() {
  return (
    <div
      className="rounded p-4"
      style={{
        background: "rgba(10,22,40,0.85)",
        border: "1px solid rgba(0,212,255,0.12)",
      }}
    >
      <PanelHead>Conflict Resolution Log — v3.0 Master</PanelHead>

      <div className="overflow-x-auto">
        <table className="w-full" style={{ borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ borderBottom: "1px solid rgba(0,212,255,0.15)" }}>
              {["Conflict", "Prior Values", "v2.7 Canonical", "Section"].map((h) => (
                <th
                  key={h}
                  className="text-left pb-2 pr-4"
                  style={{
                    fontFamily: "'JetBrains Mono', monospace",
                    fontSize: "0.65rem",
                    color: "#334155",
                    letterSpacing: "0.15em",
                    textTransform: "uppercase",
                    fontWeight: 600,
                  }}
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {CONFLICTS.map((row, i) => (
              <tr
                key={i}
                style={{
                  borderBottom:
                    i < CONFLICTS.length - 1
                      ? "1px solid rgba(30,41,59,0.4)"
                      : "none",
                }}
              >
                <td
                  className="py-2.5 pr-4"
                  style={{
                    fontFamily: "'JetBrains Mono', monospace",
                    fontSize: "0.75rem",
                    color: "#94a3b8",
                    fontWeight: 600,
                  }}
                >
                  {row.conflict}
                </td>
                <td
                  className="py-2.5 pr-4"
                  style={{
                    fontFamily: "'JetBrains Mono', monospace",
                    fontSize: "0.7rem",
                    color: "#475569",
                  }}
                >
                  {row.prior}
                </td>
                <td
                  className="py-2.5 pr-4"
                  style={{
                    fontFamily: "'JetBrains Mono', monospace",
                    fontSize: "0.7rem",
                    color: "#00d4ff",
                    fontWeight: 600,
                  }}
                >
                  {row.canonical}
                </td>
                <td
                  className="py-2.5"
                  style={{
                    fontFamily: "'JetBrains Mono', monospace",
                    fontSize: "0.7rem",
                    color: "#334155",
                  }}
                >
                  {row.section}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div
        className="mt-3 pt-3 text-xs font-mono text-center"
        style={{
          borderTop: "1px solid rgba(30,41,59,0.4)",
          color: "#1e293b",
          letterSpacing: "0.08em",
        }}
      >
        JARVIS_TRADER_MASTER.md v3.0 · 3,323 lines · SINGLE SOURCE OF TRUTH
      </div>
    </div>
  );
}

// ── Main Tab Component ─────────────────────────────────────────────────────

export default function AuditTab() {
  const [filter, setFilter] = useState<FilterOption>("ALL");

  const filteredItems = useMemo(() => {
    if (filter === "ALL") return AUDIT_ITEMS;
    return AUDIT_ITEMS.filter((i) => i.status === filter);
  }, [filter]);

  const counts = useMemo<Record<FilterOption, number>>(() => {
    const pass = AUDIT_ITEMS.filter((i) => i.status === "PASS").length;
    const warn = AUDIT_ITEMS.filter((i) => i.status === "WARN").length;
    const fail = AUDIT_ITEMS.filter((i) => i.status === "FAIL").length;
    const pending = AUDIT_ITEMS.filter((i) => i.status === "PENDING").length;
    return {
      ALL: AUDIT_ITEMS.length,
      PASS: pass,
      WARN: warn,
      FAIL: fail,
      PENDING: pending,
    };
  }, []);

  return (
    <div className="space-y-4">
      {/* ── Top Row: Count Tiles ── */}
      <SummaryTiles />

      {/* ── Middle Row: Score Ring + Radar ── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <ScoreRing />
        <AuditRadar />
      </div>

      {/* ── Filter Bar ── */}
      <div
        className="rounded p-3 flex items-center gap-3"
        style={{
          background: "rgba(10,22,40,0.85)",
          border: "1px solid rgba(0,212,255,0.12)",
        }}
      >
        <FilterBar active={filter} onChange={setFilter} counts={counts} />
        <div className="ml-auto text-xs font-mono text-slate-600">
          Showing {filteredItems.length} of {AUDIT_ITEMS.length} items
        </div>
      </div>

      {/* ── Audit Cards Grid ── */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
        {filteredItems.map((item) => (
          <AuditCard key={item.id} item={item} />
        ))}
      </div>

      {/* ── Category Breakdown ── */}
      <CategoryBreakdown />

      {/* ── Conflict Resolution Table ── */}
      <ConflictTable />
    </div>
  );
}
