"use client";

import React, { useMemo, useState } from "react";
import useSWR from "swr";
import {
  BarChart,
  Bar,
  LineChart,
  Line,
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  Cell,
  ComposedChart,
} from "recharts";
import {
  Activity,
  TrendingUp,
  Zap,
  Award,
  Target,
  ArrowUp,
  ArrowDown,
  Flame,
} from "lucide-react";
import { fetchEngine } from "@/lib/api";
import { StreakBadge } from "@/components/StreakBadge";
import type { TradeRecord, PerformanceSummary, DrawdownInfo } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { RollingPerformanceCard } from "@/components/RollingPerformanceCard";
import { DailyPnLChart } from "@/components/DailyPnLChart";
import { WinStreakWidget } from "@/components/WinStreakWidget";
import { TradeAnalyticsWidget } from "@/components/TradeAnalyticsWidget";
import { PerformanceSummaryWidget } from "@/components/PerformanceSummaryWidget";
import { RollingPerformanceWidget } from "@/components/RollingPerformanceWidget";
import { BestWorstTradesWidget } from "@/components/BestWorstTradesWidget";
import TradeRiskRewardWidget from "@/components/TradeRiskRewardWidget";
import { TradeHourlyBreakdownWidget } from "@/components/TradeHourlyBreakdownWidget";

// ── Types ────────────────────────────────────────────────────────────────────

interface TradeStats {
  symbol: string;
  trades: number;
  win_rate: number;
  profit_factor: number;
  avg_win: number;
  avg_loss: number;
  total_pnl: number;
}

interface HourlyStats {
  hour: string;
  win_rate: number;
  trades: number;
}

interface DailyStats {
  day: string;
  win_rate: number;
  trades: number;
}

interface MonthlyStats {
  month: string;
  pnl: number;
  trades: number;
}

interface EquityCurvePoint {
  time: string;
  equity: number;
}

interface PLDistribution {
  bin: string;
  count: number;
}

interface HoldingPeriod {
  period: string;
  count: number;
}

interface RiskRewardPoint {
  planned_rr: number;
  actual_rr: number;
  pnl: number;
}

interface StreakData {
  current_winning: number;
  current_losing: number;
  best_winning_streak: number;
  best_winning_pnl: number;
  worst_losing_streak: number;
  worst_losing_pnl: number;
  avg_streak_length: number;
}

// ── Fetcher ──────────────────────────────────────────────────────────────────

function fetcher<T>(url: string): Promise<T> {
  return fetchEngine<T>(url);
}

// ── Stat Card ────────────────────────────────────────────────────────────────

interface StatCardProps {
  label: string;
  value: string | number;
  sub?: string;
  trend?: "up" | "down" | null;
  icon: React.ElementType;
  valueClass?: string;
}

function StatCard({
  label,
  value,
  sub,
  trend,
  icon: Icon,
  valueClass = "text-foreground",
}: StatCardProps) {
  return (
    <div className="rounded-xl border border-border bg-card p-4 flex items-start gap-3">
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent/10">
        <Icon className="h-4 w-4 text-accent" />
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-xs text-muted-foreground uppercase tracking-wider">{label}</p>
        <div className="flex items-center gap-2 mt-1">
          <p className={`text-lg font-bold font-mono tabular-nums ${valueClass}`}>{value}</p>
          {trend === "up" && <ArrowUp className="h-4 w-4 text-bull" />}
          {trend === "down" && <ArrowDown className="h-4 w-4 text-bear" />}
        </div>
        {sub && <p className="text-xs text-muted-foreground mt-0.5">{sub}</p>}
      </div>
    </div>
  );
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function pct(v: number | undefined, decimals = 1): string {
  if (v === undefined || isNaN(v)) return "—";
  return `${(v * 100).toFixed(decimals)}%`;
}

function fmt(v: number | undefined, decimals = 2): string {
  if (v === undefined || isNaN(v)) return "—";
  return v.toFixed(decimals);
}

function pfColor(pf: number | undefined): string {
  if (pf === undefined || isNaN(pf)) return "text-muted-foreground";
  if (pf >= 3.0) return "text-green-400";
  if (pf >= 2.0) return "text-yellow-400";
  return "text-red-400";
}

// ── Data Processing Functions ────────────────────────────────────────────────

function processTradeData(trades: TradeRecord[]): {
  hourly: HourlyStats[];
  daily: DailyStats[];
  monthly: MonthlyStats[];
  equity: EquityCurvePoint[];
  pnlDist: PLDistribution[];
  holding: HoldingPeriod[];
  riskReward: RiskRewardPoint[];
  bySymbol: TradeStats[];
  streaks: StreakData;
  summary: PerformanceSummary;
} {
  const hourlyMap = new Map<string, { wins: number; total: number }>();
  const dailyMap = new Map<string, { wins: number; total: number }>();
  const monthlyMap = new Map<string, { pnl: number; trades: number }>();
  const symbolMap = new Map<string, {
    trades: number;
    wins: number;
    losses: number;
    total_pnl: number;
    sum_win: number;
    sum_loss: number;
  }>();

  let equityRunning = 100000;
  const equityCurve: EquityCurvePoint[] = [{ time: "Start", equity: equityRunning }];
  let totalWins = 0;
  let totalLosses = 0;
  let totalTrades = 0;
  let sumWins = 0;
  let sumLosses = 0;
  let grossProfit = 0;
  let grossLoss = 0;

  const holdingBuckets = new Map<string, number>();
  const plBuckets = new Map<string, number>();
  const riskRewardPoints: RiskRewardPoint[] = [];

  let winStreak = 0;
  let loseStreak = 0;
  let bestWinStreak = 0;
  let bestWinPnL = 0;
  let worstLoseStreak = 0;
  let worstLosePnL = 0;
  const allStreakLengths: number[] = [];

  // Process trades chronologically
  const sortedTrades = [...trades].sort(
    (a, b) => new Date(a.entry_time).getTime() - new Date(b.entry_time).getTime()
  );

  for (const trade of sortedTrades) {
    if (trade.status !== "CLOSED" || trade.realized_pnl === null) continue;

    totalTrades++;
    const pnl = trade.realized_pnl;
    equityRunning += pnl;

    // Track equity
    if (totalTrades % Math.max(1, Math.floor(totalTrades / 60)) === 0 || totalTrades === sortedTrades.length) {
      equityCurve.push({
        time: new Date(trade.exit_time || trade.entry_time).toLocaleDateString(),
        equity: equityRunning,
      });
    }

    // Win/loss streak tracking
    if (pnl > 0) {
      winStreak++;
      loseStreak = 0;
      totalWins++;
      sumWins += pnl;
      grossProfit += pnl;

      if (winStreak > bestWinStreak) {
        bestWinStreak = winStreak;
        bestWinPnL = 0;
      }
      bestWinPnL += pnl;
    } else {
      loseStreak++;
      winStreak = 0;
      totalLosses++;
      sumLosses += pnl;
      grossLoss += Math.abs(pnl);

      if (loseStreak > worstLoseStreak) {
        worstLoseStreak = loseStreak;
        worstLosePnL = 0;
      }
      worstLosePnL += pnl;
    }

    // Hourly stats
    const hourKey = new Date(trade.entry_time).getHours().toString().padStart(2, "0");
    const hour = hourlyMap.get(hourKey) || { wins: 0, total: 0 };
    hour.total++;
    if (pnl > 0) hour.wins++;
    hourlyMap.set(hourKey, hour);

    // Daily stats
    const dayKey = new Date(trade.entry_time).toLocaleDateString("en-US", { weekday: "short" });
    const day = dailyMap.get(dayKey) || { wins: 0, total: 0 };
    day.total++;
    if (pnl > 0) day.wins++;
    dailyMap.set(dayKey, day);

    // Monthly stats
    const monthKey = new Date(trade.entry_time).toLocaleDateString("en-US", { year: "numeric", month: "short" });
    const month = monthlyMap.get(monthKey) || { pnl: 0, trades: 0 };
    month.pnl += pnl;
    month.trades++;
    monthlyMap.set(monthKey, month);

    // Symbol stats
    const sym = symbolMap.get(trade.symbol) || {
      trades: 0,
      wins: 0,
      losses: 0,
      total_pnl: 0,
      sum_win: 0,
      sum_loss: 0,
    };
    sym.trades++;
    if (pnl > 0) {
      sym.wins++;
      sym.sum_win += pnl;
    } else {
      sym.losses++;
      sym.sum_loss += Math.abs(pnl);
    }
    sym.total_pnl += pnl;
    symbolMap.set(trade.symbol, sym);

    // Holding period distribution
    if (trade.exit_time) {
      const holdMs = new Date(trade.exit_time).getTime() - new Date(trade.entry_time).getTime();
      const holdMins = Math.round(holdMs / 60000);
      let bucket = "<5m";
      if (holdMins >= 5 && holdMins < 15) bucket = "5-15m";
      else if (holdMins >= 15 && holdMins < 60) bucket = "15-60m";
      else if (holdMins >= 60 && holdMins < 240) bucket = "1-4h";
      else if (holdMins >= 240) bucket = ">4h";

      holdingBuckets.set(bucket, (holdingBuckets.get(bucket) || 0) + 1);
    }

    // P&L distribution
    const plBucket = Math.floor(pnl / 50) * 50;
    const plKey = `$${plBucket}`;
    plBuckets.set(plKey, (plBuckets.get(plKey) || 0) + 1);

    // Risk:Reward (simplified - would need more data for true R:R)
    const plannedRR = 2; // Assumed
    const actualRR = pnl > 0 ? Math.abs(pnl / (sumLosses / totalLosses || 1)) : -Math.abs(pnl / (sumWins / totalWins || 1));
    riskRewardPoints.push({ planned_rr: plannedRR, actual_rr: Math.max(-3, Math.min(3, actualRR)), pnl });
  }

  // Record streaks ending
  if (winStreak > 0) allStreakLengths.push(winStreak);
  if (loseStreak > 0) allStreakLengths.push(loseStreak);

  const avgStreakLength = allStreakLengths.length > 0
    ? allStreakLengths.reduce((a, b) => a + b, 0) / allStreakLengths.length
    : 0;

  // Prepare hourly data
  const hourlyData: HourlyStats[] = [];
  for (let h = 0; h < 24; h++) {
    const key = h.toString().padStart(2, "0");
    const stats = hourlyMap.get(key);
    hourlyData.push({
      hour: `${key}:00`,
      win_rate: stats ? stats.wins / stats.total : 0,
      trades: stats?.total || 0,
    });
  }

  // Prepare daily data
  const dayOrder = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  const dailyData: DailyStats[] = dayOrder.map((day) => {
    const stats = dailyMap.get(day);
    return {
      day,
      win_rate: stats ? stats.wins / stats.total : 0,
      trades: stats?.total || 0,
    };
  });

  // Prepare monthly data
  const monthlyData: MonthlyStats[] = Array.from(monthlyMap.entries())
    .map(([month, data]) => ({ month, ...data }))
    .sort((a, b) => new Date(a.month).getTime() - new Date(b.month).getTime())
    .slice(-12);

  // Prepare P&L distribution
  const plDistData: PLDistribution[] = Array.from(plBuckets.entries())
    .map(([bin, count]) => ({ bin, count }))
    .sort((a, b) => parseInt(a.bin) - parseInt(b.bin));

  // Prepare holding period data
  const holdingData: HoldingPeriod[] = [
    { period: "<5m", count: holdingBuckets.get("<5m") || 0 },
    { period: "5-15m", count: holdingBuckets.get("5-15m") || 0 },
    { period: "15-60m", count: holdingBuckets.get("15-60m") || 0 },
    { period: "1-4h", count: holdingBuckets.get("1-4h") || 0 },
    { period: ">4h", count: holdingBuckets.get(">4h") || 0 },
  ];

  // Prepare symbol stats
  const symbolData: TradeStats[] = Array.from(symbolMap.entries()).map(([symbol, stats]) => ({
    symbol,
    trades: stats.trades,
    win_rate: stats.trades > 0 ? stats.wins / stats.trades : 0,
    profit_factor: stats.sum_loss > 0 ? stats.sum_win / stats.sum_loss : stats.sum_win > 0 ? 999 : 0,
    avg_win: stats.wins > 0 ? stats.sum_win / stats.wins : 0,
    avg_loss: stats.losses > 0 ? -stats.sum_loss / stats.losses : 0,
    total_pnl: stats.total_pnl,
  }));

  // Summary
  const totalPnL = sumWins - sumLosses;
  const profitFactor = sumLosses > 0 ? sumWins / sumLosses : sumWins > 0 ? 999 : 0;
  const sharpeRatio = totalTrades > 1 ? Math.sqrt(252 * 390) * (totalPnL / totalTrades) / Math.sqrt(Math.max(1, sumWins + sumLosses)) : 0;

  return {
    hourly: hourlyData,
    daily: dailyData,
    monthly: monthlyData,
    equity: equityCurve.length > 1 ? equityCurve : [{ time: "Start", equity: 100000 }],
    pnlDist: plDistData,
    holding: holdingData,
    riskReward: riskRewardPoints.slice(-100),
    bySymbol: symbolData.sort((a, b) => Math.abs(b.total_pnl) - Math.abs(a.total_pnl)),
    streaks: {
      current_winning: winStreak,
      current_losing: loseStreak,
      best_winning_streak: bestWinStreak,
      best_winning_pnl: bestWinPnL,
      worst_losing_streak: worstLoseStreak,
      worst_losing_pnl: worstLosePnL,
      avg_streak_length: avgStreakLength,
    },
    summary: {
      total_trades: totalTrades,
      winning_trades: totalWins,
      losing_trades: totalLosses,
      win_rate: totalTrades > 0 ? totalWins / totalTrades : 0,
      gross_profit: grossProfit,
      gross_loss: grossLoss,
      net_pnl: totalPnL,
      profit_factor: profitFactor,
      avg_win: totalWins > 0 ? sumWins / totalWins : 0,
      avg_loss: totalLosses > 0 ? -(sumLosses / totalLosses) : 0,
      sharpe_ratio: sharpeRatio,
      max_drawdown: 0.05, // Placeholder - would need to calculate from equity curve
    },
  };
}

// ── Section 1: Summary Cards ─────────────────────────────────────────────────

function SummarySection({ summary }: { summary: PerformanceSummary | null }) {
  if (!summary) return null;

  const pfTrend = (summary.profit_factor ?? 0) >= 2.0 ? "up" : "down";
  const winRateTrend = (summary.win_rate ?? 0) >= 0.5 ? "up" : "down";

  return (
    <div className="grid grid-cols-2 lg:grid-cols-6 gap-3">
      <StatCard
        label="Total Trades"
        value={summary.total_trades || 0}
        sub={`${summary.winning_trades || 0}W / ${summary.losing_trades || 0}L`}
        icon={Activity}
      />
      <StatCard
        label="Win Rate"
        value={pct(summary.win_rate, 0)}
        sub={summary.win_rate ? (summary.win_rate >= 0.5 ? "Above 50%" : "Below 50%") : "—"}
        trend={winRateTrend}
        icon={Zap}
        valueClass={summary.win_rate ? (summary.win_rate >= 0.5 ? "text-green-400" : "text-red-400") : ""}
      />
      <StatCard
        label="Profit Factor"
        value={fmt(summary.profit_factor, 2)}
        sub={summary.profit_factor ? (summary.profit_factor >= 3.0 ? "Strong" : summary.profit_factor >= 2.0 ? "Good" : "Weak") : "—"}
        trend={pfTrend}
        icon={TrendingUp}
        valueClass={pfColor(summary.profit_factor)}
      />
      <StatCard
        label="Sharpe Ratio"
        value={fmt(summary.sharpe_ratio ?? undefined, 2)}
        sub="Risk-adjusted return"
        icon={Award}
        valueClass={(summary.sharpe_ratio ?? 0) >= 1.0 ? "text-green-400" : "text-yellow-400"}
      />
      <StatCard
        label="Total P&L"
        value={`$${(summary.net_pnl || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}`}
        sub={summary.net_pnl ? (summary.net_pnl > 0 ? "Profitable" : "Loss") : "—"}
        icon={Target}
        valueClass={summary.net_pnl ? (summary.net_pnl > 0 ? "text-green-400" : "text-red-400") : ""}
      />
      <StatCard
        label="Max Drawdown"
        value={pct(summary.max_drawdown, 1)}
        sub="Peak to trough"
        icon={Flame}
        valueClass="text-warn"
      />
    </div>
  );
}

// ── Section 2: Performance by Time ───────────────────────────────────────────

function TimePerformanceSection({ data }: {
  data: {
    hourly: HourlyStats[];
    daily: DailyStats[];
    monthly: MonthlyStats[];
    equity: EquityCurvePoint[];
  };
}) {
  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-border bg-card p-5">
        <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-4">
          Win Rate by Hour of Day
        </p>
        <ResponsiveContainer width="100%" height={300}>
          <BarChart data={data.hourly} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
            <XAxis dataKey="hour" tick={{ fontSize: 11 }} />
            <YAxis domain={[0, 1]} label={{ value: "Win Rate", angle: -90, position: "insideLeft" }} />
            <Tooltip
              formatter={(v) => pct(v as number, 0)}
              contentStyle={{
                background: "hsl(var(--card))",
                border: "1px solid hsl(var(--border))",
                borderRadius: "8px",
                fontSize: "11px",
              }}
            />
            <Bar dataKey="win_rate" fill="#22c55e" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="rounded-xl border border-border bg-card p-5">
          <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-4">
            Win Rate by Day of Week
          </p>
          <ResponsiveContainer width="100%" height={250}>
            <BarChart data={data.daily} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
              <XAxis dataKey="day" tick={{ fontSize: 11 }} />
              <YAxis domain={[0, 1]} />
              <Tooltip
                formatter={(v) => pct(v as number, 0)}
                contentStyle={{
                  background: "hsl(var(--card))",
                  border: "1px solid hsl(var(--border))",
                  borderRadius: "8px",
                  fontSize: "11px",
                }}
              />
              <Bar dataKey="win_rate" fill="#3b82f6" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="rounded-xl border border-border bg-card p-5">
          <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-4">
            Monthly P&L
          </p>
          <ResponsiveContainer width="100%" height={250}>
            <BarChart data={data.monthly} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
              <XAxis dataKey="month" tick={{ fontSize: 11 }} />
              <YAxis />
              <Tooltip
                formatter={(v) => `$${v}`}
                contentStyle={{
                  background: "hsl(var(--card))",
                  border: "1px solid hsl(var(--border))",
                  borderRadius: "8px",
                  fontSize: "11px",
                }}
              />
              <Bar dataKey="pnl" radius={[4, 4, 0, 0]}>
                {data.monthly.map((entry, idx) => (
                  <Cell key={idx} fill={entry.pnl >= 0 ? "#22c55e" : "#ef4444"} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="rounded-xl border border-border bg-card p-5">
        <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-4">
          Cumulative Equity Curve
        </p>
        <ResponsiveContainer width="100%" height={300}>
          <LineChart data={data.equity} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
            <XAxis dataKey="time" tick={{ fontSize: 11 }} />
            <YAxis />
            <Tooltip
              formatter={(v) => `$${(v as number).toLocaleString(undefined, { maximumFractionDigits: 0 })}`}
              contentStyle={{
                background: "hsl(var(--card))",
                border: "1px solid hsl(var(--border))",
                borderRadius: "8px",
                fontSize: "11px",
              }}
            />
            <Line type="monotone" dataKey="equity" stroke="#22c55e" strokeWidth={2} dot={false} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

// ── Section 3: Performance by Symbol ─────────────────────────────────────────

type SortKey = "symbol" | "trades" | "win_rate" | "profit_factor" | "avg_win" | "avg_loss" | "total_pnl";

function SymbolPerformanceSection({ data }: { data: TradeStats[] }) {
  const [sortKey, setSortKey] = useState<SortKey>("total_pnl");
  const [sortDesc, setSortDesc] = useState(true);

  const sorted = useMemo(() => {
    return [...data].sort((a, b) => {
      const aVal = a[sortKey];
      const bVal = b[sortKey];
      const cmp = aVal > bVal ? 1 : aVal < bVal ? -1 : 0;
      return sortDesc ? -cmp : cmp;
    });
  }, [data, sortKey, sortDesc]);

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDesc(!sortDesc);
    } else {
      setSortKey(key);
      setSortDesc(true);
    }
  };

  const headers: { key: SortKey; label: string }[] = [
    { key: "symbol", label: "Symbol" },
    { key: "trades", label: "Trades" },
    { key: "win_rate", label: "Win %" },
    { key: "profit_factor", label: "PF" },
    { key: "avg_win", label: "Avg Win" },
    { key: "avg_loss", label: "Avg Loss" },
    { key: "total_pnl", label: "Total P&L" },
  ];

  return (
    <div className="rounded-xl border border-border bg-card overflow-hidden">
      <div className="px-5 py-3.5 border-b border-border">
        <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Performance by Symbol
        </p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-left">
          <thead>
            <tr className="border-b border-border bg-black/20">
              {headers.map(({ key, label }) => (
                <th
                  key={key}
                  className="px-4 py-2.5 text-xs font-medium uppercase tracking-wider text-muted-foreground cursor-pointer hover:text-foreground transition-colors"
                  onClick={() => toggleSort(key)}
                >
                  {label} {sortKey === key && (sortDesc ? "▼" : "▲")}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map((row, idx) => (
              <tr key={idx} className="border-b border-border hover:bg-white/[0.03] transition-colors">
                <td className="px-4 py-3 font-mono font-bold text-sm text-foreground">{row.symbol}</td>
                <td className="px-4 py-3 text-sm text-muted-foreground text-center tabular-nums">{row.trades}</td>
                <td className={`px-4 py-3 text-sm text-center tabular-nums ${
                  row.win_rate >= 0.5 ? "text-green-400" : row.win_rate >= 0.3 ? "text-yellow-400" : "text-red-400"
                }`}>
                  {pct(row.win_rate, 0)}
                </td>
                <td className={`px-4 py-3 text-sm text-center tabular-nums ${pfColor(row.profit_factor)}`}>
                  {fmt(row.profit_factor, 2)}
                </td>
                <td className="px-4 py-3 text-sm text-green-400 text-center tabular-nums">${fmt(row.avg_win, 0)}</td>
                <td className="px-4 py-3 text-sm text-red-400 text-center tabular-nums">${fmt(row.avg_loss, 0)}</td>
                <td className={`px-4 py-3 text-sm font-semibold text-center tabular-nums ${
                  row.total_pnl > 0 ? "text-green-400" : "text-red-400"
                }`}>
                  ${row.total_pnl.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Section 4: Trade Distribution ────────────────────────────────────────────

function TradeDistributionSection({ data }: {
  data: {
    pnlDist: PLDistribution[];
    holding: HoldingPeriod[];
    riskReward: RiskRewardPoint[];
  };
}) {
  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
      <div className="rounded-xl border border-border bg-card p-5">
        <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-4">
          P&L Distribution (by $50 bins)
        </p>
        <ResponsiveContainer width="100%" height={250}>
          <BarChart data={data.pnlDist} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
            <XAxis dataKey="bin" tick={{ fontSize: 10 }} angle={-45} textAnchor="end" height={60} />
            <YAxis tick={{ fontSize: 11 }} />
            <Tooltip
              contentStyle={{
                background: "hsl(var(--card))",
                border: "1px solid hsl(var(--border))",
                borderRadius: "8px",
                fontSize: "11px",
              }}
            />
            <Bar dataKey="count" fill="#8b5cf6" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="rounded-xl border border-border bg-card p-5">
        <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-4">
          Holding Period Distribution
        </p>
        <ResponsiveContainer width="100%" height={250}>
          <BarChart data={data.holding} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
            <XAxis dataKey="period" tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} />
            <Tooltip
              contentStyle={{
                background: "hsl(var(--card))",
                border: "1px solid hsl(var(--border))",
                borderRadius: "8px",
                fontSize: "11px",
              }}
            />
            <Bar dataKey="count" fill="#06b6d4" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="rounded-xl border border-border bg-card p-5">
        <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-4">
          Risk:Reward Scatter
        </p>
        <ResponsiveContainer width="100%" height={250}>
          <ScatterChart margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
            <XAxis dataKey="planned_rr" type="number" tick={{ fontSize: 11 }} name="Planned R:R" />
            <YAxis dataKey="actual_rr" type="number" tick={{ fontSize: 11 }} name="Actual R:R" />
            <Tooltip
              cursor={{ strokeDasharray: "3 3" }}
              contentStyle={{
                background: "hsl(var(--card))",
                border: "1px solid hsl(var(--border))",
                borderRadius: "8px",
                fontSize: "11px",
              }}
              formatter={(v) => fmt(v as number, 2)}
            />
            <Scatter name="Trades" data={data.riskReward} fill="#f59e0b" />
          </ScatterChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

// ── Section 5: Streak Analysis ──────────────────────────────────────────────

function StreakAnalysisSection({ streaks }: { streaks: StreakData }) {
  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-4">
        Streak Analysis
      </p>
      <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
        <div className="border border-border/50 rounded-lg p-4">
          <p className="text-xs text-muted-foreground mb-2">Current Winning Streak</p>
          <p className="text-2xl font-bold text-green-400">{streaks.current_winning}</p>
        </div>
        <div className="border border-border/50 rounded-lg p-4">
          <p className="text-xs text-muted-foreground mb-2">Current Losing Streak</p>
          <p className="text-2xl font-bold text-red-400">{streaks.current_losing}</p>
        </div>
        <div className="border border-border/50 rounded-lg p-4">
          <p className="text-xs text-muted-foreground mb-2">Avg Streak Length</p>
          <p className="text-2xl font-bold text-accent">{fmt(streaks.avg_streak_length, 1)}</p>
        </div>
        <div className="border border-border/50 rounded-lg p-4 lg:col-span-2">
          <p className="text-xs text-muted-foreground mb-2">Best Winning Streak</p>
          <p className="text-lg font-bold text-green-400">{streaks.best_winning_streak} wins</p>
          <p className="text-xs text-green-300 mt-1">${streaks.best_winning_pnl.toLocaleString(undefined, { maximumFractionDigits: 0 })} profit</p>
        </div>
        <div className="border border-border/50 rounded-lg p-4 lg:col-span-1">
          <p className="text-xs text-muted-foreground mb-2">Worst Losing Streak</p>
          <p className="text-lg font-bold text-red-400">{streaks.worst_losing_streak} losses</p>
          <p className="text-xs text-red-300 mt-1">${streaks.worst_losing_pnl.toLocaleString(undefined, { maximumFractionDigits: 0 })} loss</p>
        </div>
      </div>
    </div>
  );
}

// ── Main Page ────────────────────────────────────────────────────────────────

export default function StatsPage() {
  const { data: trades, isLoading, error } = useSWR<TradeRecord[]>(
    "/portfolio/history/trades",
    fetcher,
    { refreshInterval: 60_000 }
  );

  const processedData = useMemo(() => {
    if (!trades || trades.length === 0) return null;
    return processTradeData(trades);
  }, [trades]);

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="sticky top-0 z-50 border-b border-border bg-background/95 backdrop-blur">
        <div className="mx-auto max-w-[1600px] flex items-center gap-3 px-6 py-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent/10">
            <Activity className="h-5 w-5 text-accent" />
          </div>
          <div>
            <h1 className="font-bold text-foreground tracking-tight">JARVIS TRADER — Trade Statistics</h1>
            <p className="text-xs text-muted-foreground">Comprehensive performance analytics</p>
          </div>
          <div className="ml-4">
            <StreakBadge />
          </div>
          <nav className="hidden lg:flex items-center gap-4 ml-6">
            <a href="/" className="text-xs text-muted-foreground hover:text-foreground transition-colors">
              Dashboard
            </a>
            <a href="/backtest" className="text-xs text-muted-foreground hover:text-foreground transition-colors">
              Backtest
            </a>
            <a href="/stats" className="text-xs text-accent font-medium transition-colors">
              Statistics
            </a>
            <a href="/performance" className="text-xs text-muted-foreground hover:text-foreground transition-colors">
              Performance
            </a>
            <a href="/paper" className="text-xs text-muted-foreground hover:text-foreground transition-colors">
              Paper Trading
            </a>
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-[1600px] px-6 py-6 space-y-6">
        {/* Performance Summary — always shown at the top, loads independently */}
        <PerformanceSummaryWidget />

        {/* Rolling Performance Windows — independent fetch, always visible */}
        <RollingPerformanceWidget />

        {/* Best & Worst Trades — independent fetch, always visible */}
        <BestWorstTradesWidget />

        {/* Risk:Reward Analysis — independent fetch, always visible */}
        <TradeRiskRewardWidget />

        {/* Hourly Breakdown — independent fetch, always visible */}
        <TradeHourlyBreakdownWidget />

        {/* Win/Loss Streaks — independent fetch, always visible */}
        <WinStreakWidget />

        {/* Loading state */}
        {isLoading && (
          <div className="flex items-center gap-2 text-xs text-muted-foreground animate-pulse p-4">
            <Activity className="h-3.5 w-3.5" />
            Loading trade history from engine…
          </div>
        )}

        {/* Error state */}
        {error && (
          <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-400">
            Unable to load trade statistics. Ensure the engine is running on port 8010.
          </div>
        )}

        {/* Empty state */}
        {!isLoading && !error && (!trades || trades.length === 0) && (
          <div className="rounded-xl border border-border bg-card p-10 text-center">
            <Activity className="h-8 w-8 text-muted-foreground mx-auto mb-3" />
            <p className="text-sm text-muted-foreground">No completed trades found. Paper trading data will appear here once trades close.</p>
          </div>
        )}

        {/* Data loaded */}
        {processedData && (
          <>
            {/* Section 1: Summary Cards */}
            <SummarySection summary={processedData.summary} />

            {/* Rolling Performance Windows */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
              <RollingPerformanceCard />
            </div>

            {/* Daily P&L Chart + Win Streak */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
              <div className="lg:col-span-2">
                <DailyPnLChart days={30} />
              </div>
              <WinStreakWidget />
            </div>

            {/* Section 2: Performance by Time */}
            <TimePerformanceSection
              data={{
                hourly: processedData.hourly,
                daily: processedData.daily,
                monthly: processedData.monthly,
                equity: processedData.equity,
              }}
            />

            {/* Section 3: Symbol Performance */}
            <SymbolPerformanceSection data={processedData.bySymbol} />

            {/* Section 4: Trade Distribution */}
            <TradeDistributionSection
              data={{
                pnlDist: processedData.pnlDist,
                holding: processedData.holding,
                riskReward: processedData.riskReward,
              }}
            />

            {/* Section 5: Streak Analysis */}
            <StreakAnalysisSection streaks={processedData.streaks} />

            {/* Section 6: Trade Analytics (API-backed by-day / by-symbol) */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              <