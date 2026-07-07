"use client";

/**
 * RiskAttributionPanel — 30-day rolling P&L attribution by pipeline analyst.
 *
 * Renders:
 *  1. Stacked bar chart (inline SVG, no chart library) — per-analyst contribution per day.
 *  2. Summary table — mean, std, max draw, win-rate-when-top for each analyst.
 *
 * Data: GET /attribution/window?days=30 via fetchRiskAttribution().
 * Refresh: every 5 minutes.
 * Empty state: shown when window has no closed trades.
 */

import React, { useMemo } from "react";
import useSWR from "swr";
import { BarChart2 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  fetchRiskAttribution,
  type RiskAttributionResponse,
  type DailyAttributionEntry,
} from "@/lib/api";

// ── Constants ─────────────────────────────────────────────────────────────────

const REFRESH_MS = 5 * 60_000;

const ANALYST_COLORS: Record<string, string> = {
  technical:     "#34d399", // emerald
  news:          "#60a5fa", // blue
  social:        "#a78bfa", // violet
  fundamental:   "#f59e0b", // amber
  corey:         "#fb923c", // orange
  pattern_vision:"#38bdf8", // sky
  kronos:        "#e879f9", // fuchsia
  options:       "#4ade80", // green
  regime_adjust: "#94a3b8", // slate
  other:         "#6b7280", // zinc
};

const ANALYST_ORDER = Object.keys(ANALYST_COLORS);

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmt(v: number): string {
  const abs = Math.abs(v);
  const sign = v < 0 ? "-" : "+";
  if (abs >= 1000) return `${sign}$${(abs / 1000).toFixed(1)}k`;
  return `${sign}$${abs.toFixed(0)}`;
}

function fmtPct(v: number): string {
  return `${(v * 100).toFixed(1)}%`;
}

function truncLabel(s: string, maxLen = 9): string {
  return s.length > maxLen ? s.slice(0, maxLen - 1) + "…" : s;
}

/**
 * One concrete, honestly-derived recommendation from the window stats.
 * Never fabricates: returns null when no analyst has attributable P&L, and
 * every number in the text comes straight from `per_analyst` / `top_contributor_by_abs`.
 */
function buildRecommendation(
  data: RiskAttributionResponse
): { text: string; tone: "bull" | "bear" } | null {
  const attributed = Object.entries(data.per_analyst).filter(
    ([, s]) => Math.abs(s.total) > 0.01
  );
  if (attributed.length === 0) return null;

  const [worstSlot, worstStat] = attributed.reduce((a, b) =>
    b[1].total < a[1].total ? b : a
  );
  const top = data.top_contributor_by_abs;
  const topStat = top ? data.per_analyst[top] : undefined;

  if (worstStat.total < -0.01) {
    return {
      tone: "bear",
      text: `Recommend: review ${worstSlot} — largest 30-day drag at ${fmt(
        worstStat.total
      )}${top ? `; ${top} leads at ${fmt(topStat?.total ?? 0)}` : ""}. Consider down-weighting ${worstSlot} if the drag persists.`,
    };
  }
  return {
    tone: "bull",
    text: `Recommend: no analyst is a net 30-day drag${
      top ? `; ${top} leads at ${fmt(topStat?.total ?? 0)}` : ""
    }. Weights look healthy — hold current allocation.`,
  };
}

// ── Stacked Bar Chart ─────────────────────────────────────────────────────────

interface StackedBarChartProps {
  daily: DailyAttributionEntry[];
}

function StackedBarChart({ daily }: StackedBarChartProps) {
  const activeDays = daily.filter((d) => d.n_trades > 0);

  if (activeDays.length === 0) {
    return (
      <p className="text-xs text-zinc-500 italic py-4 text-center">
        No closed trades in window
      </p>
    );
  }

  const SVG_W = 560;
  const SVG_H = 120;
  const PAD_LEFT = 36;
  const PAD_RIGHT = 8;
  const PAD_TOP = 8;
  const PAD_BOTTOM = 20;
  const chartW = SVG_W - PAD_LEFT - PAD_RIGHT;
  const chartH = SVG_H - PAD_TOP - PAD_BOTTOM;

  // Find max absolute value across all days for y-scale
  const maxAbs = Math.max(
    ...activeDays.map((d) =>
      Math.max(
        Math.abs(
          ANALYST_ORDER.reduce(
            (acc, k) => acc + Math.max(0, d.attribution[k] ?? 0),
            0
          )
        ),
        Math.abs(
          ANALYST_ORDER.reduce(
            (acc, k) => acc + Math.min(0, d.attribution[k] ?? 0),
            0
          )
        )
      )
    ),
    1
  );

  const barW = Math.max(4, chartW / activeDays.length - 2);
  const scaleY = (v: number) => (v / maxAbs) * (chartH / 2);

  const midY = PAD_TOP + chartH / 2;

  const yTick = (label: string, y: number) => (
    <text
      x={PAD_LEFT - 4}
      y={y + 3}
      textAnchor="end"
      fontSize={8}
      fill="#71717a"
    >
      {label}
    </text>
  );

  return (
    <svg
      viewBox={`0 0 ${SVG_W} ${SVG_H}`}
      className="w-full"
      style={{ maxHeight: 120 }}
      aria-label="30-day analyst attribution stacked bar chart"
    >
      {/* Axis */}
      <line
        x1={PAD_LEFT}
        y1={midY}
        x2={SVG_W - PAD_RIGHT}
        y2={midY}
        stroke="#3f3f46"
        strokeWidth={0.5}
      />
      {yTick(fmt(maxAbs), PAD_TOP)}
      {yTick("0", midY)}
      {yTick(fmt(-maxAbs), PAD_TOP + chartH)}

      {activeDays.map((day, i) => {
        const x = PAD_LEFT + i * (chartW / activeDays.length) + 1;
        let posY = midY;
        let negY = midY;

        return (
          <g key={day.date}>
            {ANALYST_ORDER.map((slot) => {
              const val = day.attribution[slot] ?? 0;
              if (Math.abs(val) < 0.01) return null;
              const h = Math.abs(scaleY(val));
              if (val > 0) {
                const rect = (
                  <rect
                    key={slot}
                    x={x}
                    y={posY - h}
                    width={barW}
                    height={h}
                    fill={ANALYST_COLORS[slot] ?? ANALYST_COLORS.other}
                    opacity={0.85}
                  />
                );
                posY -= h;
                return rect;
              } else {
                const rect = (
                  <rect
                    key={slot}
                    x={x}
                    y={negY}
                    width={barW}
                    height={h}
                    fill={ANALYST_COLORS[slot] ?? ANALYST_COLORS.other}
                    opacity={0.6}
                  />
                );
                negY += h;
                return rect;
              }
            })}
            {/* Date label every 5 bars */}
            {i % 5 === 0 && (
              <text
                x={x + barW / 2}
                y={SVG_H - 4}
                textAnchor="middle"
                fontSize={7}
                fill="#52525b"
              >
                {day.date.slice(5)} {/* MM-DD */}
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}

// ── Legend ─────────────────────────────────────────────────────────────────────

function Legend() {
  return (
    <div className="flex flex-wrap gap-x-3 gap-y-1 mt-1">
      {ANALYST_ORDER.map((slot) => (
        <span key={slot} className="flex items-center gap-1">
          <span
            className="inline-block h-2 w-2 rounded-sm"
            style={{ backgroundColor: ANALYST_COLORS[slot] }}
          />
          <span className="text-[9px] text-zinc-500">{truncLabel(slot)}</span>
        </span>
      ))}
    </div>
  );
}

// ── Stats Table ───────────────────────────────────────────────────────────────

interface StatsTableProps {
  data: RiskAttributionResponse;
}

function StatsTable({ data }: StatsTableProps) {
  const rows = useMemo(() => {
    return ANALYST_ORDER.map((slot) => {
      const s = data.per_analyst[slot];
      return {
        slot,
        total: s?.total ?? 0,
        mean: s?.mean ?? 0,
        std: s?.std ?? 0,
        max_loss: s?.max_loss ?? 0,
        win_rate_top: s?.win_rate_top ?? 0,
      };
    })
      .filter((r) => Math.abs(r.total) > 0.01)
      .sort((a, b) => Math.abs(b.total) - Math.abs(a.total));
  }, [data]);

  if (rows.length === 0) {
    return (
      <p className="text-xs text-zinc-500 italic">No attributable trades in window.</p>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[10px] font-mono">
        <thead>
          <tr className="text-zinc-600 border-b border-zinc-800">
            <th className="text-left pb-1">Analyst</th>
            <th className="text-right pb-1">Total</th>
            <th className="text-right pb-1">Mean/day</th>
            <th className="text-right pb-1">Std</th>
            <th className="text-right pb-1">Max draw</th>
            <th className="text-right pb-1">Win% top</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.slot} className="border-b border-zinc-900/50">
              <td className="py-0.5 pr-2 text-zinc-300">
                <span
                  className="inline-block h-1.5 w-1.5 rounded-sm mr-1 align-middle"
                  style={{ backgroundColor: ANALYST_COLORS[r.slot] ?? "#6b7280" }}
                />
                {r.slot}
                {r.slot === data.top_contributor_by_abs && (
                  <Badge
                    variant="bull"
                    className="ml-1 text-[8px] px-1 py-0 leading-none"
                  >
                    top
                  </Badge>
                )}
              </td>
              <td
                className={[
                  "text-right",
                  r.total >= 0 ? "text-emerald-400" : "text-rose-400",
                ].join(" ")}
              >
                {fmt(r.total)}
              </td>
              <td className="text-right text-zinc-400">{fmt(r.mean)}</td>
              <td className="text-right text-zinc-500">{fmt(r.std)}</td>
              <td className="text-right text-rose-400/80">{fmt(r.max_loss)}</td>
              <td className="text-right text-zinc-400">{fmtPct(r.win_rate_top)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Panel ─────────────────────────────────────────────────────────────────────

export function RiskAttributionPanel() {
  const { data, error, isLoading } = useSWR<RiskAttributionResponse>(
    "/attribution/window?days=30",
    () => fetchRiskAttribution({ days: 30 }),
    { refreshInterval: REFRESH_MS, shouldRetryOnError: false }
  );

  const recommendation = useMemo(
    () => (data ? buildRecommendation(data) : null),
    [data]
  );

  return (
    <Card className="border-zinc-800 bg-zinc-950/60">
      <CardHeader className="py-3">
        <CardTitle className="text-sm font-medium text-zinc-300 flex items-center gap-2">
          <BarChart2 className="h-4 w-4" /> Risk Attribution
        </CardTitle>
        <p className="text-[11px] text-zinc-500">
          30-day P&amp;L by analyst · pro-rata signal weights
        </p>
      </CardHeader>

      <CardContent className="pb-4 space-y-3">
        {isLoading && (
          <div className="space-y-2">
            <div className="h-24 animate-pulse rounded bg-zinc-800/60" />
            <div className="h-20 animate-pulse rounded bg-zinc-800/40" />
          </div>
        )}

        {error && (
          <p className="text-xs text-rose-400">
            Attribution unavailable — engine offline?
          </p>
        )}

        {!isLoading && !error && data && (
          <>
            {/* Summary badges */}
            <div className="flex items-center gap-2 flex-wrap">
              <Badge variant="neutral" className="text-[10px] font-mono">
                {data.n_trades} trades
              </Badge>
              <Badge variant="neutral" className="text-[10px] font-mono">
                {data.days_with_trades}d active
              </Badge>
              <Badge
                variant={data.total_pnl >= 0 ? "bull" : "bear"}
                className="text-[10px] font-mono"
              >
                {fmt(data.total_pnl)} net
              </Badge>
              {data.top_contributor_by_abs && (
                <Badge variant="info" className="text-[10px] font-mono">
                  top: {data.top_contributor_by_abs}
                </Badge>
              )}
            </div>

            {/* Stacked bar chart */}
            <StackedBarChart daily={data.daily} />
            <Legend />

            {/* Stats table */}
            <StatsTable data={data} />

            {/* Concrete recommendation — derived from the same window stats */}
            {recommendation && (
              <p
                className={[
                  "text-[11px] leading-snug border-t border-zinc-800 pt-2",
                  recommendation.tone === "bear"
                    ? "text-rose-300"
                    : "text-emerald-300",
                ].join(" ")}
              >
                {recommendation.text}
              </p>
            )}
          </>
        )}

        {!isLoading && !error && data?.n_trades === 0 && (
          <p className="text-xs text-zinc-500 italic py-2 text-center">
            No closed trades in the last 30 days.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
