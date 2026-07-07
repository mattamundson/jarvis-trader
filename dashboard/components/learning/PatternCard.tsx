"use client";

import useSWR from "swr";
import { fetchEngine } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

const REFRESH_MS = 60_000;

function fetcher<T = unknown>(url: string): Promise<T> {
  return fetchEngine<T>(url);
}

// ── Types ─────────────────────────────────────────────────────────────────────

interface HourPattern {
  hour: number;
  win_rate: number;
  trade_count: number;
  avg_pnl: number;
}

interface DayPattern {
  day: string;
  win_rate: number;
  trade_count: number;
  avg_pnl: number;
}

interface RegimePattern {
  regime: string;
  win_rate: number;
  trade_count: number;
  avg_pnl: number;
  profit_factor: number | null;
}

interface PatternsResponse {
  symbol: string;
  lookback_days: number;
  hourly_patterns: HourPattern[];
  daily_patterns: DayPattern[];
  regime_patterns: RegimePattern[];
  best_hours: number[];
  best_days: string[];
  error?: string;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtHour(h: number): string {
  const ampm = h >= 12 ? "PM" : "AM";
  const h12 = h % 12 === 0 ? 12 : h % 12;
  return `${h12}:00 ${ampm}`;
}

function winRateBadgeVariant(wr: number): "bull" | "bear" | "warn" | "neutral" {
  if (wr >= 0.6) return "bull";
  if (wr >= 0.45) return "warn";
  if (wr > 0) return "bear";
  return "neutral";
}

function pnlColor(pnl: number): string {
  if (pnl > 0) return "#00ff88";
  if (pnl < 0) return "#ff4444";
  return "#888";
}

// ── Component ─────────────────────────────────────────────────────────────────

interface PatternCardProps {
  symbol: string;
  lookbackDays?: number;
}

export function PatternCard({ symbol, lookbackDays = 30 }: PatternCardProps) {
  const key = `/learning/patterns?symbol=${symbol}&lookback_days=${lookbackDays}`;
  const { data, isLoading, error } = useSWR<PatternsResponse>(key, fetcher, {
    refreshInterval: REFRESH_MS,
  });

  if (isLoading) {
    return (
      <div className="rounded-xl border border-border bg-card p-4">
        <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground mb-3">
          Trade Patterns — {symbol}
        </p>
        <p className="font-mono text-xs text-muted-foreground/50 animate-pulse">
          Analyzing patterns…
        </p>
      </div>
    );
  }

  if (error || data?.error) {
    return (
      <div className="rounded-xl border border-border bg-card p-4">
        <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground mb-3">
          Trade Patterns — {symbol}
        </p>
        <p className="font-mono text-xs text-red-400/70 italic">
          {data?.error ?? "No pattern data available — need more trade history"}
        </p>
      </div>
    );
  }

  const hourly = data?.hourly_patterns ?? [];
  const daily = data?.daily_patterns ?? [];
  const regimes = data?.regime_patterns ?? [];
  const bestHours = data?.best_hours ?? [];
  const bestDays = data?.best_days ?? [];

  return (
    <div className="space-y-4">
      {/* Best times summary */}
      <div className="rounded-xl border border-border bg-card p-4 space-y-3">
        <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
          Optimal Trading Windows — {symbol}
        </p>
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-1.5">
            <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/60">
              Best Hours
            </p>
            {bestHours.length ? (
              <div className="flex flex-wrap gap-1.5">
                {bestHours.map((h) => (
                  <Badge key={h} variant="bull">
                    {fmtHour(h)}
                  </Badge>
                ))}
              </div>
            ) : (
              <p className="font-mono text-[10px] text-muted-foreground/40 italic">
                Insufficient data
              </p>
            )}
          </div>
          <div className="space-y-1.5">
            <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/60">
              Best Days
            </p>
            {bestDays.length ? (
              <div className="flex flex-wrap gap-1.5">
                {bestDays.map((d) => (
                  <Badge key={d} variant="bull">
                    {d}
                  </Badge>
                ))}
              </div>
            ) : (
              <p className="font-mono text-[10px] text-muted-foreground/40 italic">
                Insufficient data
              </p>
            )}
          </div>
        </div>
      </div>

      {/* Hourly breakdown */}
      {hourly.length > 0 && (
        <div className="rounded-xl border border-border bg-card overflow-hidden">
          <div className="px-4 py-3 border-b border-border">
            <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
              Hourly Win Rates
            </p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full font-mono text-xs">
              <thead>
                <tr className="border-b border-border text-[10px] uppercase tracking-wider text-muted-foreground">
                  <th className="text-left px-4 py-2">Hour (ET)</th>
                  <th className="text-center px-4 py-2">Win Rate</th>
                  <th className="text-right px-4 py-2">Trades</th>
                  <th className="text-right px-4 py-2">Avg P&L</th>
                </tr>
              </thead>
              <tbody>
                {hourly.map((row) => {
                  const isBest = bestHours.includes(row.hour);
                  return (
                    <tr
                      key={row.hour}
                      className={`border-b border-border/40 hover:bg-accent/5 transition-colors ${isBest ? "bg-bull/5" : ""}`}
                    >
                      <td className="px-4 py-2 flex items-center gap-2">
                        {isBest && (
                          <span className="inline-block w-1.5 h-1.5 rounded-full bg-bull/80" />
                        )}
                        <span className={isBest ? "text-bull font-semibold" : "text-foreground/80"}>
                          {fmtHour(row.hour)}
                        </span>
                      </td>
                      <td className="px-4 py-2 text-center">
                        <Badge variant={winRateBadgeVariant(row.win_rate)}>
                          {(row.win_rate * 100).toFixed(1)}%
                        </Badge>
                      </td>
                      <td className="px-4 py-2 text-right tabular-nums text-muted-foreground">
                        {row.trade_count}
                      </td>
                      <td
                        className="px-4 py-2 text-right tabular-nums font-semibold"
                        style={{ color: pnlColor(row.avg_pnl) }}
                      >
                        {row.avg_pnl >= 0 ? "+" : ""}${row.avg_pnl.toFixed(2)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Day-of-week breakdown */}
      {daily.length > 0 && (
        <div className="rounded-xl border border-border bg-card overflow-hidden">
          <div className="px-4 py-3 border-b border-border">
            <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
              Day-of-Week Breakdown
            </p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full font-mono text-xs">
              <thead>
                <tr className="border-b border-border text-[10px] uppercase tracking-wider text-muted-foreground">
                  <th className="text-left px-4 py-2">Day</th>
                  <th className="text-center px-4 py-2">Win Rate</th>
                  <th className="text-right px-4 py-2">Trades</th>
                  <th className="text-right px-4 py-2">Avg P&L</th>
                </tr>
              </thead>
              <tbody>
                {daily.map((row) => {
                  const isBest = bestDays.includes(row.day);
                  return (
                    <tr
                      key={row.day}
                      className={`border-b border-border/40 hover:bg-accent/5 transition-colors ${isBest ? "bg-bull/5" : ""}`}
                    >
                      <td className="px-4 py-2">
                        <span className={isBest ? "text-bull font-semibold" : "text-foreground/80"}>
                          {row.day}
                        </span>
                      </td>
                      <td className="px-4 py-2 text-center">
                        <Badge variant={winRateBadgeVariant(row.win_rate)}>
                          {(row.win_rate * 100).toFixed(1)}%
                        </Badge>
                      </td>
                      <td className="px-4 py-2 text-right tabular-nums text-muted-foreground">
                        {row.trade_count}
                      </td>
                      <td
                        className="px-4 py-2 text-right tabular-nums font-semibold"
                        style={{ color: pnlColor(row.avg_pnl) }}
                      >
                        {row.avg_pnl >= 0 ? "+" : ""}${row.avg_pnl.toFixed(2)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Regime breakdown */}
      {regimes.length > 0 && (
        <div className="rounded-xl border border-border bg-card overflow-hidden">
          <div className="px-4 py-3 border-b border-border">
            <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
              Performance by Regime
            </p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full font-mono text-xs">
              <thead>
                <tr className="border-b border-border text-[10px] uppercase tracking-wider text-muted-foreground">
                  <th className="text-left px-4 py-2">Regime</th>
                  <th className="text-center px-4 py-2">Win Rate</th>
                  <th className="text-right px-4 py-2">Trades</th>
                  <th className="text-right px-4 py-2">Avg P&L</th>
                  <th className="text-right px-4 py-2">Prof. Factor</th>
                </tr>
              </thead>
              <tbody>
                {regimes.map((row) => (
                  <tr
                    key={row.regime}
                    className="border-b border-border/40 hover:bg-accent/5 transition-colors"
                  >
                    <td className="px-4 py-2">
                      <Badge variant="info">{row.regime}</Badge>
                    </td>
                    <td className="px-4 py-2 text-center">
                      <Badge variant={winRateBadgeVariant(row.win_rate)}>
                        {(row.win_rate * 100).toFixed(1)}%
                      </Badge>
                    </td>
                    <td className="px-4 py-2 text-right tabular-nums text-muted-foreground">
                      {row.trade_count}
                    </td>
                    <td
                      className="px-4 py-2 text-right tabular-nums font-semibold"
                      style={{ color: pnlColor(row.avg_pnl) }}
                    >
                      {row.avg_pnl >= 0 ? "+" : ""}${row.avg_pnl.toFixed(2)}
                    </td>
                    <td className="px-4 py-2 text-right tabular-nums">
                      {row.profit_factor != null ? (
                        <span
                          style={{ color: row.profit_factor >= 1.5 ? "#00ff88" : row.profit_factor >= 1.0 ? "#ffcc00" : "#ff4444" }}
                          className="font-semibold"
                        >
                          {row.profit_factor.toFixed(2)}
                        </span>
                      ) : (
                        <span className="text-muted-foreground/40">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Empty state */}
      {!hourly.length && !daily.length && !regimes.length && (
        <div className="rounded-xl border border-border bg-card p-6 text-center">
          <p className="font-mono text-xs text-muted-foreground/50 italic">
            No pattern data for {symbol} in the last {lookbackDays} days.
            <br />
            Patterns emerge after 20+ completed trades.
          </p>
        </div>
      )}
    </div>
  );
}
