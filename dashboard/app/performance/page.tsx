"use client";

import Link from "next/link";
import React, { useState } from "react";
import { Activity, ArrowLeft, ChevronDown, ChevronUp } from "lucide-react";
import { WeeklyStatsWidget } from "@/components/WeeklyStatsWidget";
import { CommissionTrackerWidget } from "@/components/CommissionTrackerWidget";
import { TradeDurationWidget } from "@/components/TradeDurationWidget";
import { MonthlyBreakdownWidget } from "@/components/MonthlyBreakdownWidget";
import { DrawdownChart } from "@/components/DrawdownChart";
import { AccountROIWidget } from "@/components/AccountROIWidget";
import { WeeklyPnLCard } from "@/components/WeeklyPnLCard";
import { TopSymbolsWidget } from "@/components/TopSymbolsWidget";
import AvgTradeTimeWidget from "@/components/AvgTradeTimeWidget";
import { EquityCurveWidget } from "@/components/EquityCurveWidget";
import { EntryQualityWidget } from "@/components/EntryQualityWidget";
import { RecentTradesTableWidget } from "@/components/RecentTradesTableWidget";
import { WinRateBySymbolWidget } from "@/components/WinRateBySymbolWidget";
import { DailyPnLCalendarWidget } from "@/components/DailyPnLCalendarWidget";
import HoldTimeWidget from "@/components/HoldTimeWidget";
import { WinRateByHourWidget } from "@/components/WinRateByHourWidget";
import { StreakTrackerWidget } from "@/components/StreakTrackerWidget";
import { RegimeAttributionWidget } from "@/components/RegimeAttributionWidget";
import { QuantStatsPanel } from "@/components/QuantStatsPanel";
// P2.3 IA: folded in from the retired /stats page (the 10 analytics widgets not
// already rendered above). /stats now redirects here.
import { PerformanceSummaryWidget } from "@/components/PerformanceSummaryWidget";
import { ProfitFactorWidget } from "@/components/ProfitFactorWidget";
import { SharpeRatioWidget } from "@/components/SharpeRatioWidget";
import { TradeHourlyBreakdownWidget } from "@/components/TradeHourlyBreakdownWidget";
import { TradePnLHistogram } from "@/components/TradePnLHistogram";
import { BestWorstTradesWidget } from "@/components/BestWorstTradesWidget";
import { SymbolPerformanceWidget } from "@/components/SymbolPerformanceWidget";
import { RollingPerformanceWidget } from "@/components/RollingPerformanceWidget";
import { DrawdownChartWidget } from "@/components/DrawdownChartWidget";
import { PnLStreakWidget } from "@/components/PnLStreakWidget";
// P2.3 IA: honest deduped metric grid folded in from the retired /journal-review page
// (its behavioral LLM tools moved to /journal → Review). /journal-review redirects here.
import { JournalMetricsView } from "@/components/journal-review/JournalMetricsView";
import { WidgetErrorBoundary } from "@/components/WidgetErrorBoundary";
import { PriceChartPanel } from "@/components/charts/PriceChartPanel";
import type { ChartSymbol, ChartTimeframe } from "@/hooks/useChartData";

// ── Static Data (v2.7 FINAL WFE — 2026-03-30) ──────────────────────────────

interface BacktestRow {
  rank: number;
  symbol: string;
  tf: string;
  trades: number;
  wr: number;
  pf: number;
  sharpe: number;
  returnPct: number;
  maxDD: number | null;
  wfe: number;
  status: "ACTIVE" | "RESEARCH" | "DO NOT TRADE";
}

const BACKTEST_DATA: BacktestRow[] = [
  { rank: 1, symbol: "MGC", tf: "1d", trades: 47, wr: 51.1, pf: 2.60, sharpe: 2.04, returnPct: 34.4, maxDD: 3.0, wfe: 0.14, status: "DO NOT TRADE" },
  { rank: 2, symbol: "SPY", tf: "1h", trades: 23, wr: 65.2, pf: 3.00, sharpe: -1.55, returnPct: 0.7, maxDD: 5.0, wfe: -1.11, status: "DO NOT TRADE" },
  { rank: 3, symbol: "MNQ", tf: "1h", trades: 86, wr: 47.7, pf: 1.46, sharpe: 0.19, returnPct: 13.6, maxDD: 0.1, wfe: 0.57, status: "ACTIVE" },
  { rank: 4, symbol: "MCL", tf: "1h", trades: 65, wr: 60.0, pf: 1.83, sharpe: 0.15, returnPct: 0.2, maxDD: null, wfe: 0.82, status: "ACTIVE" },
  { rank: 5, symbol: "MES", tf: "1h", trades: 21, wr: 42.9, pf: 0.96, sharpe: -0.12, returnPct: -4.0, maxDD: 0.1, wfe: 0.09, status: "DO NOT TRADE" },
];

interface WFERow {
  symbol: string;
  tf: string;
  staticWFE: number;
  adaptiveWFE: number;
  change: string;
  oosSharpe: number;
  oosPF: number;
  verdict: string;
  verdictColor: string;
}

const WFE_DATA: WFERow[] = [
  { symbol: "MGC", tf: "1d", staticWFE: 0.14, adaptiveWFE: 0.88, change: "+526%", oosSharpe: 0.89, oosPF: 2.55, verdict: "OVERFIT", verdictColor: "#ff4444" },
  { symbol: "MNQ", tf: "1h", staticWFE: 0.48, adaptiveWFE: 0.57, change: "+19%", oosSharpe: -0.06, oosPF: 1.05, verdict: "APPROVED", verdictColor: "#00ff88" },
  { symbol: "MCL", tf: "1h", staticWFE: 0.82, adaptiveWFE: -0.31, change: "-138%", oosSharpe: -0.48, oosPF: 0.81, verdict: "APPROVED", verdictColor: "#00ff88" },
  { symbol: "SPY", tf: "1h", staticWFE: -1.11, adaptiveWFE: -0.71, change: "+36%", oosSharpe: -3.84, oosPF: 1.04, verdict: "FAIL", verdictColor: "#ff4444" },
];

interface ImprovementRow {
  improvement: string;
  status: string;
  statusColor: string;
  mnqImpact: string;
  mgcImpact: string;
  keep: string;
  keepColor: string;
}

const IMPROVEMENT_DATA: ImprovementRow[] = [
  { improvement: "Regime-Adaptive STC", status: "Implemented", statusColor: "#00ff88", mnqImpact: "WFE 0.24 → 0.48", mgcImpact: "WFE 0.14 → 0.88 (adaptive)", keep: "YES", keepColor: "#00ff88" },
  { improvement: "Volume Filter", status: "Implemented", statusColor: "#00ff88", mnqImpact: "WFE 0.34 → -0.23 (SKIP)", mgcImpact: "WFE 0.88 → 0.20 (SKIP)", keep: "NO for futures", keepColor: "#ff4444" },
  { improvement: "MTF Alignment", status: "Implemented", statusColor: "#00ff88", mnqImpact: "Testing...", mgcImpact: "N/A (daily)", keep: "TBD", keepColor: "#ffcc00" },
  { improvement: "News Blackout", status: "Implemented", statusColor: "#00ff88", mnqImpact: "1% blocked", mgcImpact: "N/A", keep: "Live only", keepColor: "#888888" },
  { improvement: "Trailing Stop", status: "Investigated", statusColor: "#ffcc00", mnqImpact: "No improvement", mgcImpact: "Hurts returns", keep: "NO", keepColor: "#ff4444" },
];

interface DNTRow {
  symbol: string;
  tf: string;
  pf: number;
  wfe: string;
  reason: string;
}

const DNT_DATA: DNTRow[] = [
  { symbol: "M2K", tf: "1h", pf: 0.64, wfe: "N/A", reason: "Consistently losing; Russell unsuitable for STC" },
  { symbol: "M2K", tf: "1d", pf: 0.60, wfe: "N/A", reason: "Negative both timeframes" },
  { symbol: "MCL", tf: "1d", pf: 0.21, wfe: "N/A", reason: "Catastrophic PF; zero targets hit on daily crude" },
  { symbol: "MES", tf: "1d", pf: 0.75, wfe: "N/A", reason: "36/51 trades exit at EOD — targets unreachable" },
  { symbol: "MNQ", tf: "1d", pf: 0.79, wfe: "N/A", reason: "43/57 EOD exits; daily NQ too volatile for intraday targets" },
  { symbol: "MGC", tf: "1h", pf: 0.77, wfe: "N/A", reason: "Gold works daily only; hourly loses money" },
  { symbol: "MES", tf: "1h", pf: 0.96, wfe: "0.09", reason: "Only 1/6 OOS windows profitable; WFE 0.09 OVERFIT" },
  { symbol: "SPY", tf: "1h", pf: 3.00, wfe: "-1.11", reason: "Adaptive improved but still deeply overfit; WFE -1.11" },
];

// ── Helpers ──────────────────────────────────────────────────────────────────

// Tailwind's JIT scanner only picks up literal class strings, so color helpers
// return complete class strings (not runtime hex piped through inline style).
const TEXT_COLOR_CLASSES: Record<string, string> = {
  "#00ff88": "text-[#00ff88]",
  "#ff4444": "text-[#ff4444]",
  "#ffcc00": "text-[#ffcc00]",
  "#00d4ff": "text-[#00d4ff]",
  "#555": "text-[#555]",
  "#888": "text-[#888]",
  "#888888": "text-[#888888]",
};

const PILL_COLOR_CLASSES: Record<string, string> = {
  "#00ff88": "text-[#00ff88] bg-[#00ff8818] border-[#00ff8840]",
  "#ff4444": "text-[#ff4444] bg-[#ff444418] border-[#ff444440]",
  "#ffcc00": "text-[#ffcc00] bg-[#ffcc0018] border-[#ffcc0040]",
  "#00d4ff": "text-[#00d4ff] bg-[#00d4ff10] border-[#00d4ff33]",
  "#888888": "text-[#888888] bg-[#88888818] border-[#88888840]",
};

function wfeColorClass(wfe: number): string {
  if (wfe >= 0.70) return TEXT_COLOR_CLASSES["#00ff88"];
  if (wfe >= 0.30) return TEXT_COLOR_CLASSES["#ffcc00"];
  return TEXT_COLOR_CLASSES["#ff4444"];
}

function statusBadge(status: "ACTIVE" | "RESEARCH" | "DO NOT TRADE") {
  const map: Record<typeof status, string> = {
    ACTIVE: PILL_COLOR_CLASSES["#00ff88"],
    RESEARCH: PILL_COLOR_CLASSES["#ffcc00"],
    "DO NOT TRADE": PILL_COLOR_CLASSES["#ff4444"],
  };
  return (
    <span className={`font-mono text-[10px] font-bold tracking-wider px-2 py-0.5 rounded border ${map[status]}`}>
      {status}
    </span>
  );
}

/** CSS bar that scales to max=1.0 for WFE, clamped to [-1.5, 1.0] visual range */
function WFEBar({ value, maxWidth }: { value: number; maxWidth?: number }) {
  const max = maxWidth ?? 1.0;
  // Normalize: 0 is center, positive goes right, negative goes left
  // For simplicity: bar from 0 to value, scaled to percentage of max
  const absPct = Math.min(Math.abs(value) / max * 100, 100);
  const barBgClass = value >= 0.70 ? "bg-[#00ff88]" : value >= 0 ? "bg-[#ffcc00]" : "bg-[#ff4444]";

  return (
    <div className="relative h-4 w-full rounded bg-[#111]">
      {value >= 0 ? (
        <div
          className={`absolute top-0 left-0 h-full rounded-r opacity-70 transition-[width] duration-500 ease-linear ${barBgClass}`}
          style={{ width: `${absPct}%` }}
        />
      ) : (
        <div
          className={`absolute top-0 right-0 h-full rounded-l opacity-70 transition-[width] duration-500 ease-linear ${barBgClass}`}
          style={{ width: `${absPct}%` }}
        />
      )}
      {/* Value label */}
      <span className="absolute inset-0 flex items-center justify-center font-mono text-[10px] font-bold text-white [text-shadow:0_0_4px_rgba(0,0,0,0.8)]">
        {value.toFixed(2)}
      </span>
    </div>
  );
}

// ── SummaryCard ───────────────────────────────────────────────────────────────

function SummaryCard({
  label,
  value,
  sub,
  color,
}: {
  label: string;
  value: string;
  sub?: string;
  color?: string;
}) {
  const valueClass = (color && TEXT_COLOR_CLASSES[color]) || "text-[#e0e0e0]";
  return (
    <div className="rounded-xl p-4 flex flex-col gap-1 bg-panel border border-panel-border">
      <span className="font-mono text-[10px] uppercase tracking-wider text-[#555]">
        {label}
      </span>
      <span className={`font-mono text-2xl font-bold tabular-nums ${valueClass}`}>
        {value}
      </span>
      {sub && (
        <span className="font-mono text-[10px] text-[#555]">
          {sub}
        </span>
      )}
    </div>
  );
}

// ── Section Components ───────────────────────────────────────────────────────

function SectionHeader({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="mb-4">
      <h3 className="font-mono text-sm font-bold tracking-[0.15em] uppercase text-[#00ff88]">
        {title}
      </h3>
      {subtitle && (
        <p className="font-mono text-[10px] mt-1 text-[#555]">
          {subtitle}
        </p>
      )}
    </div>
  );
}

function BacktestMatrix() {
  const [sortKey, setSortKey] = useState<keyof BacktestRow>("rank");
  const [sortAsc, setSortAsc] = useState(true);

  const sorted = [...BACKTEST_DATA].sort((a, b) => {
    const av = a[sortKey] ?? 0;
    const bv = b[sortKey] ?? 0;
    if (typeof av === "string" && typeof bv === "string") return sortAsc ? av.localeCompare(bv) : bv.localeCompare(av);
    return sortAsc ? (av as number) - (bv as number) : (bv as number) - (av as number);
  });

  function toggleSort(key: keyof BacktestRow) {
    if (sortKey === key) setSortAsc(!sortAsc);
    else { setSortKey(key); setSortAsc(true); }
  }

  function SortIcon({ col }: { col: keyof BacktestRow }) {
    if (sortKey !== col) return null;
    return sortAsc
      ? <ChevronUp className="inline h-3 w-3 ml-0.5" />
      : <ChevronDown className="inline h-3 w-3 ml-0.5" />;
  }

  const cols: { key: keyof BacktestRow; label: string; align: string }[] = [
    { key: "rank", label: "#", align: "text-center" },
    { key: "symbol", label: "Symbol", align: "text-left" },
    { key: "tf", label: "TF", align: "text-center" },
    { key: "trades", label: "Trades", align: "text-right" },
    { key: "wr", label: "WR%", align: "text-right" },
    { key: "pf", label: "PF", align: "text-right" },
    { key: "sharpe", label: "Sharpe", align: "text-right" },
    { key: "returnPct", label: "Return%", align: "text-right" },
    { key: "maxDD", label: "MaxDD%", align: "text-right" },
    { key: "wfe", label: "WFE", align: "text-right" },
  ];

  return (
    <section className="rounded-xl p-5 bg-panel border border-panel-border">
      <SectionHeader
        title="Corrected Performance -- In Sample (Jun 2024 - Mar 2026)"
        subtitle="STC + ATR Stops/Targets | All returns gross of commissions ($2.50/contract + 1 tick slippage)"
      />
      <div className="mb-4 flex items-center gap-2 rounded-md px-3 py-2 font-mono text-[11px] uppercase tracking-wider bg-[#2a1f0a] border border-[#6b5414] text-[#e0b94a]">
        <span className="font-bold">Historical backtest</span>
        <span className="text-[#9a8030]">
          frozen in-sample research benchmark as of 2026-03-30 — not live trading results
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full font-mono text-xs">
          <thead>
            <tr className="border-b border-panel-border">
              {cols.map((c) => (
                <th
                  key={c.key}
                  className={`pb-2 px-2 text-[10px] font-semibold uppercase tracking-wider cursor-pointer select-none text-[#555] ${c.align}`}
                  onClick={() => toggleSort(c.key)}
                >
                  {c.label}<SortIcon col={c.key} />
                </th>
              ))}
              <th className="pb-2 px-2 text-[10px] text-center font-semibold uppercase tracking-wider text-[#555]">
                Status
              </th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((row) => (
              <tr
                key={`${row.symbol}-${row.tf}`}
                className="hover:bg-white/[0.02] transition-colors border-b border-[#111]"
              >
                <td className="py-2 px-2 text-center text-[#555]">{row.rank}</td>
                <td className="py-2 px-2 font-bold text-[#e0e0e0]">{row.symbol}</td>
                <td className="py-2 px-2 text-center text-[#888]">{row.tf}</td>
                <td className="py-2 px-2 text-right tabular-nums text-[#e0e0e0]">{row.trades}</td>
                <td className={`py-2 px-2 text-right tabular-nums ${row.wr >= 50 ? "text-[#00ff88]" : "text-[#ffcc00]"}`}>
                  {row.wr.toFixed(1)}
                </td>
                <td className={`py-2 px-2 text-right tabular-nums ${row.pf >= 2.0 ? "text-[#00ff88]" : row.pf >= 1.0 ? "text-[#ffcc00]" : "text-[#ff4444]"}`}>
                  {row.pf.toFixed(2)}
                </td>
                <td className={`py-2 px-2 text-right tabular-nums ${row.sharpe >= 1.0 ? "text-[#00ff88]" : row.sharpe >= 0 ? "text-[#ffcc00]" : "text-[#ff4444]"}`}>
                  {row.sharpe.toFixed(2)}
                </td>
                <td className={`py-2 px-2 text-right tabular-nums ${row.returnPct >= 0 ? "text-[#00ff88]" : "text-[#ff4444]"}`}>
                  {row.returnPct >= 0 ? "+" : ""}{row.returnPct.toFixed(1)}%
                </td>
                <td className="py-2 px-2 text-right tabular-nums text-[#888]">
                  {row.maxDD != null ? `${row.maxDD.toFixed(1)}%` : "—"}
                </td>
                <td className={`py-2 px-2 text-right tabular-nums font-bold ${wfeColorClass(row.wfe)}`}>
                  {row.wfe.toFixed(2)}
                </td>
                <td className="py-2 px-2 text-center">{statusBadge(row.status)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* WFE legend */}
      <div className="flex items-center gap-4 mt-4 pt-3 border-t border-panel-border">
        <span className="font-mono text-[9px] tracking-wider text-[#555]">WFE THRESHOLDS:</span>
        <span className="font-mono text-[9px] text-[#00ff88]">{"≥"}0.70 EXCELLENT</span>
        <span className="font-mono text-[9px] text-[#ffcc00]">0.30-0.70 ACCEPTABLE</span>
        <span className="font-mono text-[9px] text-[#ff4444]">&lt;0.30 OVERFIT</span>
      </div>
    </section>
  );
}

function WalkForwardChart() {
  return (
    <section className="rounded-xl p-5 bg-panel border border-panel-border">
      <SectionHeader
        title="Walk-Forward Efficiency -- Static vs Adaptive"
        subtitle="Regime-adaptive mode: RegimeClassifier switches STC params per market regime | Bars scale to WFE 1.0 = 100%"
      />
      <div className="mb-4 flex items-center gap-2 rounded-md px-3 py-2 font-mono text-[11px] uppercase tracking-wider bg-[#2a1f0a] border border-[#6b5414] text-[#e0b94a]">
        <span className="font-bold">Historical backtest</span>
        <span className="text-[#9a8030]">
          frozen WFE study as of 2026-03-30 — not live trading results
        </span>
      </div>

      {/* Threshold reference lines */}
      <div className="relative mb-6">
        <div className="flex items-center gap-3 mb-2">
          <span className="font-mono text-[9px] text-[#555]">THRESHOLD GUIDE:</span>
          <div className="flex items-center gap-1">
            <div className="h-px w-4 bg-[#ff4444]" />
            <span className="font-mono text-[9px] text-[#ff4444]">0.30 ACCEPTABLE</span>
          </div>
          <div className="flex items-center gap-1">
            <div className="h-px w-4 bg-[#ffcc00]" />
            <span className="font-mono text-[9px] text-[#ffcc00]">0.50 GOOD</span>
          </div>
          <div className="flex items-center gap-1">
            <div className="h-px w-4 bg-[#00ff88]" />
            <span className="font-mono text-[9px] text-[#00ff88]">0.70 EXCELLENT</span>
          </div>
        </div>
      </div>

      {/* Table header */}
      <div className="grid grid-cols-12 gap-3 mb-2 px-1">
        <div className="col-span-1 font-mono text-[10px] uppercase tracking-wider text-[#555]">Symbol</div>
        <div className="col-span-4 font-mono text-[10px] uppercase tracking-wider text-[#555]">Static WFE</div>
        <div className="col-span-4 font-mono text-[10px] uppercase tracking-wider text-[#555]">Adaptive WFE</div>
        <div className="col-span-1 font-mono text-[10px] uppercase tracking-wider text-center text-[#555]">Change</div>
        <div className="col-span-2 font-mono text-[10px] uppercase tracking-wider text-center text-[#555]">Verdict</div>
      </div>

      {/* Data rows */}
      {WFE_DATA.map((row) => (
        <div
          key={`${row.symbol}-${row.tf}`}
          className="grid grid-cols-12 gap-3 items-center py-2 px-1 border-b border-[#111]"
        >
          <div className="col-span-1">
            <span className="font-mono text-xs font-bold text-[#e0e0e0]">
              {row.symbol}
            </span>
            <span className="font-mono text-[10px] ml-1 text-[#555]">{row.tf}</span>
          </div>
          <div className="col-span-4">
            <WFEBar value={row.staticWFE} />
          </div>
          <div className="col-span-4">
            <WFEBar value={row.adaptiveWFE} />
          </div>
          <div className="col-span-1 text-center">
            <span className={`font-mono text-[10px] font-bold ${row.change.startsWith("+") ? "text-[#00ff88]" : "text-[#ff4444]"}`}>
              {row.change}
            </span>
          </div>
          <div className="col-span-2 text-center">
            <span className={`font-mono text-[10px] font-bold tracking-wider px-2 py-0.5 rounded border ${PILL_COLOR_CLASSES[row.verdictColor]}`}>
              {row.verdict}
            </span>
          </div>
        </div>
      ))}

      {/* OOS detail sub-table */}
      <div className="mt-4 pt-3 border-t border-panel-border">
        <span className="font-mono text-[9px] tracking-wider mb-2 block text-[#555]">
          OUT-OF-SAMPLE METRICS (ADAPTIVE MODE)
        </span>
        <div className="grid grid-cols-4 gap-2">
          {WFE_DATA.map((row) => (
            <div
              key={`${row.symbol}-oos`}
              className="rounded-lg p-3 bg-[#111] border border-panel-border"
            >
              <span className="font-mono text-[10px] font-bold block mb-2 text-[#e0e0e0]">
                {row.symbol} {row.tf}
              </span>
              <div className="flex justify-between">
                <span className="font-mono text-[9px] text-[#555]">OOS Sharpe</span>
                <span className={`font-mono text-[10px] font-bold tabular-nums ${row.oosSharpe >= 0 ? "text-[#00ff88]" : "text-[#ff4444]"}`}>
                  {row.oosSharpe.toFixed(2)}
                </span>
              </div>
              <div className="flex justify-between mt-1">
                <span className="font-mono text-[9px] text-[#555]">OOS PF</span>
                <span className={`font-mono text-[10px] font-bold tabular-nums ${row.oosPF >= 1.5 ? "text-[#00ff88]" : row.oosPF >= 1.0 ? "text-[#ffcc00]" : "text-[#ff4444]"}`}>
                  {row.oosPF.toFixed(2)}
                </span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function ImprovementTracker() {
  return (
    <section className="rounded-xl p-5 bg-panel border border-panel-border">
      <SectionHeader
        title="Signal Improvement Tracker"
        subtitle="Each improvement tested via walk-forward validation before acceptance"
      />
      <div className="mb-4 flex items-center gap-2 rounded-md px-3 py-2 font-mono text-[11px] uppercase tracking-wider bg-[#2a1f0a] border border-[#6b5414] text-[#e0b94a]">
        <span className="font-bold">Historical snapshot</span>
        <span className="text-[#9a8030]">
          frozen improvement audit as of 2026-03-30 — not live results
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full font-mono text-xs">
          <thead>
            <tr className="border-b border-panel-border">
              {["Improvement", "Status", "MNQ Impact", "MGC Impact", "Keep?"].map((h) => (
                <th
                  key={h}
                  className="pb-2 px-2 text-left text-[10px] font-semibold uppercase tracking-wider text-[#555]"
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {IMPROVEMENT_DATA.map((row) => (
              <tr
                key={row.improvement}
                className="hover:bg-white/[0.02] transition-colors border-b border-[#111]"
              >
                <td className="py-2.5 px-2 font-semibold text-[#e0e0e0]">
                  {row.improvement}
                </td>
                <td className="py-2.5 px-2">
                  <span className={`font-mono text-[10px] font-bold tracking-wider px-2 py-0.5 rounded border ${PILL_COLOR_CLASSES[row.statusColor]}`}>
                    {row.status}
                  </span>
                </td>
                <td className="py-2.5 px-2 tabular-nums text-[#ccc]">
                  {row.mnqImpact}
                </td>
                <td className="py-2.5 px-2 tabular-nums text-[#ccc]">
                  {row.mgcImpact}
                </td>
                <td className="py-2.5 px-2">
                  <span className={`font-bold ${TEXT_COLOR_CLASSES[row.keepColor]}`}>
                    {row.keep}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function DoNotTradeList() {
  return (
    <section className="rounded-xl p-5 bg-panel border border-panel-border">
      <SectionHeader
        title="Do Not Trade -- Permanently Removed"
        subtitle="Instruments that failed walk-forward validation or show structural unsuitability for STC strategy"
      />
      <div className="mb-4 flex items-center gap-2 rounded-md px-3 py-2 font-mono text-[11px] uppercase tracking-wider bg-[#2a1f0a] border border-[#6b5414] text-[#e0b94a]">
        <span className="font-bold">Historical snapshot</span>
        <span className="text-[#9a8030]">
          frozen DNT list as of 2026-03-30 — see gate-v2 verdicts in Strategy Ledger for current status
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full font-mono text-xs">
          <thead>
            <tr className="border-b border-panel-border">
              {["Symbol", "TF", "PF", "WFE", "Reason"].map((h) => (
                <th
                  key={h}
                  className={`pb-2 px-2 text-[10px] font-semibold uppercase tracking-wider text-[#555] ${h === "Reason" ? "text-left" : "text-center"}`}
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {DNT_DATA.map((row, i) => (
              <tr
                key={`${row.symbol}-${row.tf}-${i}`}
                className="hover:bg-white/[0.02] transition-colors border-b border-[#111]"
              >
                <td className="py-2 px-2 text-center font-bold text-[#ff4444]">
                  {row.symbol}
                </td>
                <td className="py-2 px-2 text-center text-[#888]">
                  {row.tf}
                </td>
                <td className={`py-2 px-2 text-center tabular-nums ${row.pf >= 1.0 ? "text-[#ffcc00]" : "text-[#ff4444]"}`}>
                  {row.pf.toFixed(2)}
                </td>
                <td className="py-2 px-2 text-center tabular-nums text-[#ff4444]">
                  {row.wfe}
                </td>
                <td className="py-2 px-2 text-left text-[#888]">
                  {row.reason}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Count */}
      <div className="mt-3 pt-2 border-t border-panel-border">
        <span className="font-mono text-[9px] text-[#555]">
          {DNT_DATA.length} instrument/timeframe combinations permanently excluded
        </span>
      </div>
    </section>
  );
}

// ── Live Price (per-symbol, our real-time bars) ───────────────────────────────

function LivePriceSection() {
  const [open, setOpen] = useState(true);
  const [sym, setSym] = useState<ChartSymbol>("MES");
  const [tf, setTf] = useState<ChartTimeframe>("1h");

  return (
    <section className="rounded-xl p-5 bg-panel border border-panel-border">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between text-left"
      >
        <SectionHeader
          title="Live Price -- Per Symbol"
          subtitle="Real-time JARVIS bars (our data, not TradingView's delayed futures embed) with closed-trade markers"
        />
        {open ? (
          <ChevronUp className="h-4 w-4 text-[#555]" />
        ) : (
          <ChevronDown className="h-4 w-4 text-[#555]" />
        )}
      </button>
      {open && (
        <div className="mt-2">
          <PriceChartPanel
            symbol={sym}
            timeframe={tf}
            onSymbolChange={setSym}
            onTimeframeChange={setTf}
            height={380}
          />
        </div>
      )}
    </section>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────────

export default function PerformancePage() {
  return (
    <div className="min-h-screen bg-[#050505]">
      {/* Header */}
      <header className="sticky top-0 z-50 backdrop-blur bg-[rgba(5,5,5,0.95)] border-b border-panel-border">
        <div className="mx-auto max-w-[1920px] 2xl:max-w-[2400px] flex items-center justify-between px-6 py-3">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#00ff8815]">
              <Activity className="h-5 w-5 text-[#00ff88]" />
            </div>
            <div>
              <h1 className="font-bold tracking-tight text-[#e0e0e0]">
                JARVIS TRADER
              </h1>
              <p className="text-xs text-[#555]">
                IBKR Futures + Schwab Options
              </p>
            </div>
            <nav className="hidden lg:flex items-center gap-4 ml-6">
              <Link href="/" className="text-xs transition-colors text-[#888]">
                Dashboard
              </Link>
              <Link href="/analysis" className="text-xs transition-colors text-[#888]">
                Analysis
              </Link>
              <Link href="/backtest" className="text-xs transition-colors text-[#888]">
                Backtest
              </Link>
              <Link
                href="/performance"
                className="text-xs font-semibold pb-0.5 text-[#e0e0e0] border-b border-[#00ff88]"
              >
                Performance
              </Link>
              <Link href="/validation" className="text-xs transition-colors text-[#888]">
                Validation
              </Link>
              <Link href="/journal" className="text-xs transition-colors text-[#888]">
                Journal
              </Link>
              <Link href="/paper" className="text-xs font-semibold transition-colors text-[#00ff88]">
                Paper Trading
              </Link>
              <Link href="/watchlist" className="text-xs transition-colors text-[#888]">
                Watchlist
              </Link>
              <Link href="/scorecard" className="text-xs transition-colors text-[#888]">
                Scorecard
              </Link>
              <Link href="/settings" className="text-xs transition-colors text-[#888]">
                Settings
              </Link>
              <Link href="/health" className="text-xs transition-colors text-[#888]">
                Health
              </Link>
            </nav>
          </div>
          <div className="flex items-center gap-3">
            <Link
              href="/"
              className="flex items-center gap-1.5 text-xs transition-colors text-[#888]"
            >
              <ArrowLeft className="h-3.5 w-3.5" />
              Back to Dashboard
            </Link>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1920px] 2xl:max-w-[2400px] px-6 py-6 space-y-6">
        {/* Portfolio Tearsheet — QuantStats institutional metrics */}
        <WidgetErrorBoundary name="Tearsheet">
          <QuantStatsPanel />
        </WidgetErrorBoundary>

        {/* Account ROI */}
        <WidgetErrorBoundary name="Account ROI">
          <AccountROIWidget />
        </WidgetErrorBoundary>

        {/* Weekly P&L */}
        <WidgetErrorBoundary name="Weekly P&L">
          <WeeklyPnLCard />
        </WidgetErrorBoundary>

        {/* Daily P&L Calendar */}
        <WidgetErrorBoundary name="Daily P&L Calendar">
          <DailyPnLCalendarWidget />
        </WidgetErrorBoundary>

        {/* Win Rate by Hour of Day */}
        <WidgetErrorBoundary name="Win Rate by Hour">
          <WinRateByHourWidget />
        </WidgetErrorBoundary>

        {/* Streak Tracker */}
        <WidgetErrorBoundary name="Streak Tracker">
          <StreakTrackerWidget />
        </WidgetErrorBoundary>

        {/* Regime Attribution */}
        <WidgetErrorBoundary name="Regime Attribution">
          <RegimeAttributionWidget />
        </WidgetErrorBoundary>

        {/* Page title */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <div>
            <h2 className="text-2xl font-bold tracking-tight font-mono text-[#e0e0e0]">
              Backtest Performance Analytics
            </h2>
            <p className="text-sm mt-1 font-mono text-[#555]">
              JARVIS TRADER v2.7 | STC (Schaff Trend Cycle) + ATR Stops/Targets + Regime Filter
            </p>
          </div>
          <div className="flex items-center gap-3">
            <Link
              href="/strategy-ledger"
              className={`font-mono text-[10px] font-bold tracking-wider px-3 py-1.5 rounded border hover:opacity-80 transition-opacity ${PILL_COLOR_CLASSES["#ffcc00"]}`}
            >
              2026-03-30 SNAPSHOT (historical) — see live gate-v2 verdicts in Strategy Ledger →
            </Link>
            <span className="font-mono text-[10px] tracking-wider px-2 py-1 rounded bg-[#00d4ff10] border border-[#00d4ff33] text-[#00d4ff]">
              Updated 2026-03-30
            </span>
          </div>
        </div>

        {/* Summary cards */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <SummaryCard label="Active Instruments" value="2" sub="MCL 1h (0.82) + MNQ 1h (0.57) APPROVED" color="#00ff88" />
          <SummaryCard label="Research" value="0" sub="All cleared or halted" color="#555" />
          <SummaryCard label="Do Not Trade" value="8" sub="Failed walk-forward" color="#ff4444" />
          <SummaryCard label="Best WFE" value="0.82" sub="MCL 1h APPROVED (static)" color="#00ff88" />
        </div>

        {/* Live per-symbol price chart — our own real-time futures bars */}
        <LivePriceSection />

        {/* Hold time analytics */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <WidgetErrorBoundary name="Hold Time">
            <HoldTimeWidget />
          </WidgetErrorBoundary>
        </div>

        {/* Weekly live performance summary */}
        <WidgetErrorBoundary name="Weekly Stats">
          <WeeklyStatsWidget />
        </WidgetErrorBoundary>

        {/* Commission cost tracker */}
        <WidgetErrorBoundary name="Commission Tracker">
          <CommissionTrackerWidget />
        </WidgetErrorBoundary>

        {/* Trade duration analysis */}
        <WidgetErrorBoundary name="Trade Duration">
          <TradeDurationWidget />
        </WidgetErrorBoundary>

        {/* Section 1: Backtest Performance Matrix */}
        <BacktestMatrix />

        {/* Section 2: Walk-Forward Efficiency Chart */}
        <WalkForwardChart />

        {/* Section 3: Signal Improvement Tracker */}
        <ImprovementTracker />

        {/* Section 4: Do Not Trade List */}
        <DoNotTradeList />

        {/* Section 5: Monthly Breakdown */}
        <WidgetErrorBoundary name="Monthly Breakdown">
          <MonthlyBreakdownWidget />
        </WidgetErrorBoundary>

        {/* Section 6: Drawdown Chart */}
        <WidgetErrorBoundary name="Drawdown Chart">
          <DrawdownChart />
        </WidgetErrorBoundary>

        {/* Section 7: Top Symbols by P&L */}
        <WidgetErrorBoundary name="Top Symbols">
          <TopSymbolsWidget />
        </WidgetErrorBoundary>

        {/* Section 8: Avg Trade Hold Time */}
        <WidgetErrorBoundary name="Avg Trade Time">
          <AvgTradeTimeWidget />
        </WidgetErrorBoundary>

        {/* Section 9: Equity Curve */}
        <WidgetErrorBoundary name="Equity Curve">
          <EquityCurveWidget />
        </WidgetErrorBoundary>

        {/* Section 10: Entry Quality */}
        <WidgetErrorBoundary name="Entry Quality">
          <EntryQualityWidget />
        </WidgetErrorBoundary>

        {/* Section 11: Recent Closed Trades */}
        <WidgetErrorBoundary name="Recent Closed Trades">
          <RecentTradesTableWidget />
        </WidgetErrorBoundary>

        {/* Section 12: Win Rate by Symbol */}
        <WidgetErrorBoundary name="Win Rate by Symbol">
          <WinRateBySymbolWidget />
        </WidgetErrorBoundary>

        {/* Section 12b: Journal Review honest metric grid (folded in from the retired
            /journal-review page, P2.3 IA — behavioral tools live on /journal → Review) */}
        <WidgetErrorBoundary name="Journal Review Metrics">
          <JournalMetricsView />
        </WidgetErrorBoundary>

        {/* Section 13: Extended Analytics (folded in from the retired /stats page, P2.3 IA) */}
        <WidgetErrorBoundary name="Performance Summary">
          <PerformanceSummaryWidget />
        </WidgetErrorBoundary>
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          <WidgetErrorBoundary name="Profit Factor">
            <ProfitFactorWidget />
          </WidgetErrorBoundary>
          <WidgetErrorBoundary name="Sharpe Ratio">
            <SharpeRatioWidget />
          </WidgetErrorBoundary>
          <WidgetErrorBoundary name="P&L Streak">
            <PnLStreakWidget />
          </WidgetErrorBoundary>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <WidgetErrorBoundary name="Trade Hourly Breakdown">
            <TradeHourlyBreakdownWidget />
          </WidgetErrorBoundary>
          <WidgetErrorBoundary name="Trade P&L Histogram">
            <TradePnLHistogram />
          </WidgetErrorBoundary>
          <WidgetErrorBoundary name="Best/Worst Trades">
            <BestWorstTradesWidget />
          </WidgetErrorBoundary>
          <WidgetErrorBoundary name="Symbol Performance">
            <SymbolPerformanceWidget />
          </WidgetErrorBoundary>
          <WidgetErrorBoundary name="Rolling Performance">
            <RollingPerformanceWidget />
          </WidgetErrorBoundary>
          <WidgetErrorBoundary name="Drawdown Chart">
            <DrawdownChartWidget />
          </WidgetErrorBoundary>
        </div>

        {/* Footer */}
        <div className="pt-4 pb-8 border-t border-panel-border">
          <p className="font-mono text-[10px] text-[#333]">
            Source: 55+ result files in engine/backtest/results/ | Includes optimizer JSONs, corrected backtests,
            sensitivity analysis (3 instruments), Monte Carlo (4 instruments, 10k sims each), and walk-forward
            validation (5 instruments, 6-7 windows each).
          </p>
        </div>
      </main>
    </div>
  );
}
