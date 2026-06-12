"use client";

import { useState, useRef } from "react";
import useSWR from "swr";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { BarChart2 } from "lucide-react";
import { fetchQuantStats, type QuantStatsMetrics, type RollingSharpPoint } from "@/lib/api";

// ── Constants ─────────────────────────────────────────────────────────────────

type DaysOption = 30 | 90 | 180 | 365;

const DAYS_OPTIONS: { label: string; value: DaysOption }[] = [
  { label: "30d", value: 30 },
  { label: "90d", value: 90 },
  { label: "180d", value: 180 },
  { label: "365d", value: 365 },
];

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtNum(v: number | null | undefined, digits: number = 2): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return v.toFixed(digits);
}

function fmtPct(v: number | null | undefined, digits: number = 1): string {
  if (v == null || !Number.isFinite(v)) return "—";
  const pct = v * 100;
  return `${pct >= 0 ? "+" : ""}${pct.toFixed(digits)}%`;
}

function fmtPctSigned(v: number | null | undefined, digits: number = 1): string {
  if (v == null || !Number.isFinite(v)) return "—";
  const pct = v * 100;
  const prefix = pct > 0 ? "+" : "";
  return `${prefix}${pct.toFixed(digits)}%`;
}

type BadgeVariant = "bull" | "bear" | "warn" | "info" | "neutral";

function sharpeBadge(sharpe: number | null): BadgeVariant {
  if (sharpe == null) return "neutral";
  if (sharpe >= 1.5) return "bull";
  if (sharpe < 0) return "bear";
  return "neutral";
}

function calmarBadge(calmar: number | null): BadgeVariant {
  if (calmar == null) return "neutral";
  if (calmar >= 1.5) return "bull";
  if (calmar < 0) return "bear";
  return "neutral";
}

/** Scale 0–1 opacity for heatmap cells */
function heatmapOpacity(value: number, maxAbs: number): number {
  if (maxAbs === 0) return 0;
  return Math.min(Math.abs(value) / maxAbs, 1);
}

// ── Sub-components ────────────────────────────────────────────────────────────

function LoadingSkeleton() {
  return (
    <Card className="border-zinc-800 bg-zinc-950/60">
      <CardHeader className="py-3">
        <CardTitle className="text-sm font-medium text-zinc-300 flex items-center gap-2">
          <BarChart2 className="h-4 w-4" /> Portfolio Tearsheet
        </CardTitle>
      </CardHeader>
      <CardContent className="pb-4 space-y-2">
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="h-12 animate-pulse rounded bg-zinc-800/80" />
        ))}
      </CardContent>
    </Card>
  );
}

function ErrorState({ message }: { message: string }) {
  return (
    <Card className="border-zinc-800 bg-zinc-950/60">
      <CardHeader className="py-3">
        <CardTitle className="text-sm font-medium text-zinc-300 flex items-center gap-2">
          <BarChart2 className="h-4 w-4" /> Portfolio Tearsheet
        </CardTitle>
      </CardHeader>
      <CardContent className="pb-3">
        <p className="text-xs text-rose-400">Tearsheet unavailable — check engine logs</p>
        <p className="text-[10px] text-zinc-600 mt-1 font-mono break-all">{message}</p>
      </CardContent>
    </Card>
  );
}

// ── Headline metrics grid ─────────────────────────────────────────────────────

interface MetricCellProps {
  label: string;
  value: string;
  badge?: BadgeVariant;
}

function MetricCell({ label, value, badge }: MetricCellProps) {
  return (
    <div className="rounded border border-zinc-800 bg-zinc-900/50 px-3 py-2 flex flex-col gap-1 min-w-0">
      <span className="text-[10px] text-zinc-500 uppercase tracking-wider truncate">{label}</span>
      <div className="flex items-center gap-1.5 min-w-0">
        <span className="font-mono text-sm font-semibold text-zinc-100 tabular-nums truncate">
          {value}
        </span>
        {badge && badge !== "neutral" && (
          <Badge variant={badge} className="text-[9px] shrink-0 border-zinc-700">
            {badge === "bull" ? "strong" : badge === "bear" ? "weak" : badge}
          </Badge>
        )}
      </div>
    </div>
  );
}

// ── Monthly returns heatmap ───────────────────────────────────────────────────

const MONTH_LABELS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function MonthlyReturnsTable({ monthly }: { monthly: Record<string, number> }) {
  if (!monthly || Object.keys(monthly).length === 0) {
    return (
      <p className="text-xs text-zinc-500 italic py-1">No monthly return data available.</p>
    );
  }

  // Group by year
  const byYear: Record<string, (number | null)[]> = {};
  for (const [key, val] of Object.entries(monthly)) {
    // key format: "YYYY-MM"
    const parts = key.split("-");
    if (parts.length < 2) continue;
    const year = parts[0];
    const month = parseInt(parts[1], 10) - 1; // 0-indexed
    if (!byYear[year]) byYear[year] = Array(12).fill(null);
    byYear[year][month] = val;
  }

  const years = Object.keys(byYear).sort();
  const allVals = Object.values(monthly).filter((v) => Number.isFinite(v));
  const maxAbs = allVals.length > 0 ? Math.max(...allVals.map(Math.abs)) : 0;

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[10px] font-mono border-collapse">
        <thead>
          <tr>
            <th className="text-left py-1 pr-2 text-zinc-500 font-normal w-10">Year</th>
            {MONTH_LABELS.map((m) => (
              <th key={m} className="text-center py-1 px-0.5 text-zinc-500 font-normal w-8">
                {m}
              </th>
            ))}
            <th className="text-right py-1 pl-2 text-zinc-500 font-normal w-14">YTD</th>
          </tr>
        </thead>
        <tbody>
          {years.map((year) => {
            const months = byYear[year];
            const ytd = months
              .filter((v): v is number => v !== null)
              .reduce((acc, v) => (1 + acc) * (1 + v) - 1, 0);

            return (
              <tr key={year}>
                <td className="py-0.5 pr-2 text-zinc-400 font-semibold">{year}</td>
                {months.map((val, mi) => {
                  if (val === null) {
                    return (
                      <td key={mi} className="py-0.5 px-0.5 text-center text-zinc-700">
                        —
                      </td>
                    );
                  }
                  const positive = val >= 0;
                  const opacity = heatmapOpacity(val, maxAbs);
                  const opacityClass = opacity > 0.8
                    ? "/80"
                    : opacity > 0.5
                    ? "/60"
                    : opacity > 0.3
                    ? "/40"
                    : "/20";
                  const bgClass = positive
                    ? `bg-emerald-500${opacityClass}`
                    : `bg-red-500${opacityClass}`;
                  const textClass = positive ? "text-emerald-200" : "text-red-200";
                  return (
                    <td
                      key={mi}
                      className={`py-0.5 px-0.5 text-center rounded ${bgClass} ${textClass} tabular-nums`}
                      title={`${year}-${String(mi + 1).padStart(2, "0")}: ${fmtPctSigned(val)}`}
                    >
                      {fmtPctSigned(val, 0).replace("+", "+")}
                    </td>
                  );
                })}
                <td
                  className={`py-0.5 pl-2 text-right tabular-nums font-semibold ${ytd >= 0 ? "text-emerald-400" : "text-red-400"}`}
                >
                  {fmtPctSigned(ytd)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ── Rolling Sharpe sparkline (inline SVG) ─────────────────────────────────────

function RollingSharpeSpark({ data }: { data: RollingSharpPoint[] }) {
  const svgRef = useRef<SVGSVGElement>(null);

  if (!data || data.length < 2) {
    return (
      <p className="text-xs text-zinc-500 italic py-1">
        Not enough data for rolling Sharpe chart.
      </p>
    );
  }

  const W = 600;
  const H = 80;
  const PAD = { top: 8, right: 8, bottom: 16, left: 8 };

  const values = data.map((d) => d.value);
  const minV = Math.min(...values);
  const maxV = Math.max(...values);
  const rangeV = maxV - minV || 1;

  function xPos(i: number): number {
    return PAD.left + (i / (data.length - 1)) * (W - PAD.left - PAD.right);
  }
  function yPos(v: number): number {
    return PAD.top + (1 - (v - minV) / rangeV) * (H - PAD.top - PAD.bottom);
  }

  // Zero line
  const zeroY = yPos(0);
  const showZero = minV < 0 && maxV > 0;

  // Polyline
  const safeY = (v: number): number => {
    const y = yPos(Number.isFinite(v) ? v : minV);
    return Number.isFinite(y) ? y : H - PAD.bottom;
  };
  const points = data.map((d, i) => `${xPos(i).toFixed(1)},${safeY(d.value).toFixed(1)}`).join(" ");

  // Fill path (closed polygon for gradient effect)
  const firstX = xPos(0).toFixed(1);
  const lastX = xPos(data.length - 1).toFixed(1);
  const baseY = (H - PAD.bottom).toFixed(1);
  const fillPath = `M${firstX},${baseY} ` +
    data.map((d, i) => `L${xPos(i).toFixed(1)},${safeY(d.value).toFixed(1)}`).join(" ") +
    ` L${lastX},${baseY} Z`;

  // Tooltip state — simplified: just show last value as a label
  const lastPoint = data[data.length - 1];
  const lastX2 = xPos(data.length - 1);
  const lastY2 = safeY(lastPoint.value);
  const lastColor = lastPoint.value >= 0 ? "#34d399" : "#f87171";

  return (
    <div className="relative w-full" style={{ height: H }}>
      <svg
        ref={svgRef}
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        className="w-full h-full"
        aria-label="Rolling 30d Sharpe sparkline"
      >
        <defs>
          <linearGradient id="sparkleFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#34d399" stopOpacity="0.3" />
            <stop offset="100%" stopColor="#34d399" stopOpacity="0.02" />
          </linearGradient>
        </defs>

        {/* Fill area */}
        <path d={fillPath} fill="url(#sparkleFill)" />

        {/* Zero reference line */}
        {showZero && (
          <line
            x1={PAD.left}
            y1={zeroY}
            x2={W - PAD.right}
            y2={zeroY}
            stroke="#52525b"
            strokeWidth="0.5"
            strokeDasharray="3,3"
          />
        )}

        {/* Main line */}
        <polyline
          points={points}
          fill="none"
          stroke="#34d399"
          strokeWidth="1.5"
          strokeLinejoin="round"
          strokeLinecap="round"
        />

        {/* Last value dot */}
        <circle cx={lastX2} cy={lastY2} r="3" fill={lastColor} />

        {/* Date labels — start and end */}
        <text
          x={PAD.left}
          y={H - 2}
          fontSize="7"
          fill="#52525b"
          fontFamily="monospace"
        >
          {(data[0]?.date ?? "").slice(5)}
        </text>
        <text
          x={W - PAD.right}
          y={H - 2}
          fontSize="7"
          fill="#52525b"
          fontFamily="monospace"
          textAnchor="end"
        >
          {(lastPoint?.date ?? "").slice(5)}
        </text>
      </svg>

      {/* Last value label overlay */}
      <span
        className="absolute top-1 right-2 font-mono text-[10px] tabular-nums"
        style={{ color: lastColor }}
      >
        {fmtNum(lastPoint.value)} Sharpe
      </span>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export function QuantStatsPanel() {
  const [days, setDays] = useState<DaysOption>(90);

  const swrKey = `/reports/quantstats?days=${days}`;

  const { data, error, isLoading } = useSWR<QuantStatsMetrics>(
    swrKey,
    () => fetchQuantStats({ days }),
    { revalidateOnFocus: false }
  );

  // ── Loading state ──────────────────────────────────────────────────────────
  if (isLoading) return <LoadingSkeleton />;

  // ── Error state ────────────────────────────────────────────────────────────
  if (error) {
    const msg = String((error as Error)?.message ?? error);
    return <ErrorState message={msg} />;
  }

  // ── Empty state ────────────────────────────────────────────────────────────
  if (!data || data.n_trades === 0) {
    return (
      <Card className="border-zinc-800 bg-zinc-950/60">
        <CardHeader className="py-3">
          <div className="flex items-center justify-between gap-2">
            <CardTitle className="text-sm font-medium text-zinc-300 flex items-center gap-2">
              <BarChart2 className="h-4 w-4" /> Portfolio Tearsheet
            </CardTitle>
            <DaysToggle days={days} setDays={setDays} />
          </div>
        </CardHeader>
        <CardContent className="pb-3">
          <p className="text-xs text-zinc-500 italic">
            No completed trades in the last {days}d.
          </p>
        </CardContent>
      </Card>
    );
  }

  const sharpeVariant = sharpeBadge(data.sharpe);
  const calmarVariant = calmarBadge(data.calmar);

  const metrics: MetricCellProps[] = [
    {
      label: "Sortino",
      value: fmtNum(data.sortino),
      badge: sharpeBadge(data.sortino),
    },
    {
      label: "Sharpe",
      value: fmtNum(data.sharpe),
      badge: sharpeVariant,
    },
    {
      label: "Calmar",
      value: fmtNum(data.calmar),
      badge: calmarVariant,
    },
    {
      label: "Max DD",
      value: fmtPct(data.max_dd),
    },
    {
      label: "DD Days",
      value: String(data.max_dd_duration_days ?? "—"),
    },
    {
      label: "Win Rate",
      value: data.win_rate != null ? `${(data.win_rate * 100).toFixed(1)}%` : "—",
    },
    {
      label: "Prof. Factor",
      value: fmtNum(data.profit_factor),
      badge:
        data.profit_factor != null
          ? data.profit_factor >= 1.5
            ? "bull"
            : data.profit_factor < 1.0
            ? "bear"
            : "neutral"
          : "neutral",
    },
  ];

  return (
    <Card className="border-zinc-800 bg-zinc-950/60">
      <CardHeader className="py-3 space-y-2">
        {/* Title row */}
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="text-sm font-medium text-zinc-300 flex items-center gap-2">
            <BarChart2 className="h-4 w-4" /> Portfolio Tearsheet
          </CardTitle>
          <div className="flex items-center gap-2">
            <Badge variant="neutral" className="border-zinc-700 text-zinc-500 text-[10px]">
              {data.n_trades} trade{data.n_trades !== 1 ? "s" : ""}
            </Badge>
            <Badge variant="neutral" className="border-zinc-700 text-zinc-500 text-[10px]">
              {data.source === "pnl_snapshots" ? "P&L snapshots" : "paper trades"}
            </Badge>
            <DaysToggle days={days} setDays={setDays} />
          </div>
        </div>

        {/* Date range */}
        <p className="text-[10px] text-zinc-600 font-mono">
          {data.start_date} → {data.end_date}
        </p>
      </CardHeader>

      <CardContent className="pb-4 space-y-4">
        {/* Headline metrics — 7-col grid wrapping on small */}
        <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-2">
          {metrics.map((m) => (
            <MetricCell key={m.label} {...m} />
          ))}
        </div>

        {/* Monthly returns heatmap */}
        <div className="space-y-1.5">
          <p className="text-[10px] text-zinc-500 uppercase tracking-wider font-semibold">
            Monthly Returns
          </p>
          <MonthlyReturnsTable monthly={data.monthly_returns} />
        </div>

        {/* Rolling 30d Sharpe sparkline */}
        <div className="space-y-1.5">
          <p className="text-[10px] text-zinc-500 uppercase tracking-wider font-semibold">
            Rolling 30d Sharpe
          </p>
          <div className="rounded border border-zinc-800 bg-zinc-900/40 p-2">
            <RollingSharpeSpark data={data.rolling_sharpe_30d} />
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

// ── DaysToggle sub-component ──────────────────────────────────────────────────

function DaysToggle({
  days,
  setDays,
}: {
  days: DaysOption;
  setDays: (d: DaysOption) => void;
}) {
  return (
    <div className="flex items-center rounded border border-zinc-700 overflow-hidden text-[10px]">
      {DAYS_OPTIONS.map((o) => (
        <button
          key={o.value}
          onClick={() => setDays(o.value)}
          className={`px-2 py-0.5 transition-colors ${
            days === o.value
              ? "bg-zinc-700 text-zinc-100"
              : "bg-zinc-900 text-zinc-500 hover:text-zinc-300"
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
