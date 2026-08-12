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
// Mirrors engine/routers/learning_router.py get_patterns() + PatternExtractor
// (engine/learning/_experimental/pattern_extractor.py). The engine wraps every
// /learning/* response in {status, data: {...}} — verified live 2026-08-12.
// Patterns come back as three flat arrays (time_of_day / regime_patterns /
// streak_patterns), each sharing one shape; there is no hourly/daily split and
// no best_hours/best_days field anywhere in the engine.

interface PatternItem {
  name: string;
  frequency: number;
  win_rate: number;
  avg_return: number;
  conditions: Record<string, number | string>;
  last_seen: string | null;
}

interface PatternsData {
  symbol: string | null;
  lookback_days: number;
  trades_analyzed: number;
  patterns_found: number;
  time_of_day: PatternItem[];
  regime_patterns: PatternItem[];
  streak_patterns: PatternItem[];
}

interface PatternsResponse {
  status: string;
  data: PatternsData;
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

function returnColor(ret: number): string {
  if (ret > 0) return "#00ff88";
  if (ret < 0) return "#ff4444";
  return "#888";
}

// ── Component ─────────────────────────────────────────────────────────────────

interface PatternCardProps {
  symbol: string;
  lookbackDays?: number;
}

export function PatternCard({ symbol, lookbackDays = 30 }: PatternCardProps) {
  const key = `/learning/patterns?symbol=${symbol}&lookback_days=${lookbackDays}`;
  const { data: resp, isLoading, error } = useSWR<PatternsResponse>(key, fetcher, {
    refreshInterval: REFRESH_MS,
  });

  const data = resp?.data;

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

  if (error || resp?.error) {
    return (
      <div className="rounded-xl border border-border bg-card p-4">
        <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground mb-3">
          Trade Patterns — {symbol}
        </p>
        <p className="font-mono text-xs text-red-400/70 italic">
          {resp?.error ?? "No pattern data available — need more trade history"}
        </p>
      </div>
    );
  }

  const timeOfDay = data?.time_of_day ?? [];
  const regimes = data?.regime_patterns ?? [];
  const streaks = data?.streak_patterns ?? [];
  const bestHours = timeOfDay
    .filter((p) => p.win_rate >= 0.6)
    .slice()
    .sort((a, b) => b.win_rate - a.win_rate)
    .map((p) => Number(p.conditions.hour))
    .filter((h) => Number.isFinite(h));

  return (
    <div className="space-y-4">
      {/* Summary */}
      <div className="rounded-xl border border-border bg-card p-4 space-y-3">
        <div className="flex items-center justify-between">
          <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
            Trade Patterns — {symbol}
          </p>
          {data && (
            <p className="font-mono text-[10px] text-muted-foreground/40">
              {data.trades_analyzed} trades · {data.patterns_found} patterns · last {data.lookback_days}d
            </p>
          )}
        </div>
        <div className="space-y-1.5">
          <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/60">
            Best Hours (60%+ win rate)
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
      </div>

      {/* Time-of-day breakdown */}
      {timeOfDay.length > 0 && (
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
                  <th className="text-right px-4 py-2">Avg Return</th>
                </tr>
              </thead>
              <tbody>
                {timeOfDay.map((row) => {
                  const hour = Number(row.conditions.hour);
                  const isBest = bestHours.includes(hour);
                  return (
                    <tr
                      key={row.name}
                      className={`border-b border-border/40 hover:bg-accent/5 transition-colors ${isBest ? "bg-bull/5" : ""}`}
                    >
                      <td className="px-4 py-2 flex items-center gap-2">
                        {isBest && (
                          <span className="inline-block w-1.5 h-1.5 rounded-full bg-bull/80" />
                        )}
                        <span className={isBest ? "text-bull font-semibold" : "text-foreground/80"}>
                          {Number.isFinite(hour) ? fmtHour(hour) : row.name}
                        </span>
                      </td>
                      <td className="px-4 py-2 text-center">
                        <Badge variant={winRateBadgeVariant(row.win_rate)}>
                          {(row.win_rate * 100).toFixed(1)}%
                        </Badge>
                      </td>
                      <td className="px-4 py-2 text-right tabular-nums text-muted-foreground">
                        {row.frequency}
                      </td>
                      <td
                        className="px-4 py-2 text-right tabular-nums font-semibold"
                        style={{ color: returnColor(row.avg_return) }}
                      >
                        {row.avg_return >= 0 ? "+" : ""}{row.avg_return.toFixed(2)}%
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
                  <th className="text-right px-4 py-2">Avg Return</th>
                </tr>
              </thead>
              <tbody>
                {regimes.map((row) => (
                  <tr
                    key={row.name}
                    className="border-b border-border/40 hover:bg-accent/5 transition-colors"
                  >
                    <td className="px-4 py-2">
                      <Badge variant="info">{String(row.conditions.regime ?? row.name)}</Badge>
                    </td>
                    <td className="px-4 py-2 text-center">
                      <Badge variant={winRateBadgeVariant(row.win_rate)}>
                        {(row.win_rate * 100).toFixed(1)}%
                      </Badge>
                    </td>
                    <td className="px-4 py-2 text-right tabular-nums text-muted-foreground">
                      {row.frequency}
                    </td>
                    <td
                      className="px-4 py-2 text-right tabular-nums font-semibold"
                      style={{ color: returnColor(row.avg_return) }}
                    >
                      {row.avg_return >= 0 ? "+" : ""}{row.avg_return.toFixed(2)}%
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Streak patterns */}
      {streaks.length > 0 && (
        <div className="rounded-xl border border-border bg-card overflow-hidden">
          <div className="px-4 py-3 border-b border-border">
            <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
              Win / Loss Streaks
            </p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full font-mono text-xs">
              <thead>
                <tr className="border-b border-border text-[10px] uppercase tracking-wider text-muted-foreground">
                  <th className="text-left px-4 py-2">Streak</th>
                  <th className="text-center px-4 py-2">Win Rate</th>
                  <th className="text-right px-4 py-2">Occurrences</th>
                </tr>
              </thead>
              <tbody>
                {streaks.map((row) => (
                  <tr
                    key={row.name}
                    className="border-b border-border/40 hover:bg-accent/5 transition-colors"
                  >
                    <td className="px-4 py-2 text-foreground/80">{row.name}</td>
                    <td className="px-4 py-2 text-center">
                      <Badge variant={winRateBadgeVariant(row.win_rate)}>
                        {(row.win_rate * 100).toFixed(0)}%
                      </Badge>
                    </td>
                    <td className="px-4 py-2 text-right tabular-nums text-muted-foreground">
                      {row.frequency}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Empty state */}
      {!timeOfDay.length && !regimes.length && !streaks.length && (
        <div className="rounded-xl border border-border bg-card p-6 text-center">
          <p className="font-mono text-xs text-muted-foreground/50 italic">
            No pattern data for {symbol} in the last {lookbackDays} days.
            <br />
            Patterns emerge after 3+ occurrences of a condition.
          </p>
        </div>
      )}
    </div>
  );
}
