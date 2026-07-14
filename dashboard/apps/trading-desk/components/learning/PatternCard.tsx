"use client";

import useSWR from "swr";
import { fetchEngine } from "@/lib/api";
import { Badge } from "@/components/ui/badge";

const REFRESH_MS = 60_000;

function fetcher<T = unknown>(url: string): Promise<T> {
  return fetchEngine<T>(url);
}

// ── Types ─────────────────────────────────────────────────────────────────────
// Mirrors the ACTUAL engine response — GET /learning/patterns in
// engine/routers/learning_router.py wraps everything as {status, data}, and
// `data` is built from PatternExtractor.extract() (engine/learning/_experimental/
// pattern_extractor.py), which returns three buckets of generic Pattern objects
// (name/frequency/win_rate/avg_return/conditions/last_seen) — not the
// hourly_patterns/daily_patterns/best_hours/best_days shape this component
// used to assume.

interface LearningPattern {
  name: string;
  frequency: number;
  win_rate: number;
  /** Average trade return as a PERCENT, e.g. 1.25 means +1.25% (see
   *  engine/routers/learning_router.py `_fetch_closed_trades` return_pct calc). */
  avg_return: number;
  conditions: Record<string, unknown>;
  last_seen: string | null;
}

interface PatternsData {
  symbol: string | null;
  lookback_days: number;
  trades_analyzed: number;
  patterns_found: number;
  time_of_day: LearningPattern[];
  regime_patterns: LearningPattern[];
  streak_patterns: LearningPattern[];
}

interface PatternsEnvelope {
  status: string;
  data: PatternsData;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function winRateBadgeVariant(wr: number): "bull" | "bear" | "warn" | "neutral" {
  if (wr >= 0.6) return "bull";
  if (wr >= 0.45) return "warn";
  if (wr > 0) return "bear";
  return "neutral";
}

function returnColor(pct: number): string {
  if (pct > 0) return "#00ff88";
  if (pct < 0) return "#ff4444";
  return "#888";
}

function fmtLastSeen(ts: string | null): string {
  if (!ts) return "—";
  try {
    return new Date(ts).toLocaleDateString("en-US", { month: "short", day: "numeric" });
  } catch {
    return ts;
  }
}

// ── Reusable pattern table ───────────────────────────────────────────────────

function PatternTable({ title, patterns }: { title: string; patterns: LearningPattern[] }) {
  if (!patterns.length) return null;

  return (
    <div className="rounded-xl border border-border bg-card overflow-hidden">
      <div className="px-4 py-3 border-b border-border">
        <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
          {title}
        </p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full font-mono text-xs">
          <thead>
            <tr className="border-b border-border text-[10px] uppercase tracking-wider text-muted-foreground">
              <th className="text-left px-4 py-2">Pattern</th>
              <th className="text-center px-4 py-2">Win Rate</th>
              <th className="text-right px-4 py-2">Trades</th>
              <th className="text-right px-4 py-2">Avg Return</th>
              <th className="text-right px-4 py-2">Last Seen</th>
            </tr>
          </thead>
          <tbody>
            {patterns.map((p) => (
              <tr
                key={p.name}
                className="border-b border-border/40 hover:bg-accent/5 transition-colors"
              >
                <td className="px-4 py-2 text-foreground/80">{p.name}</td>
                <td className="px-4 py-2 text-center">
                  <Badge variant={winRateBadgeVariant(p.win_rate)}>
                    {(p.win_rate * 100).toFixed(1)}%
                  </Badge>
                </td>
                <td className="px-4 py-2 text-right tabular-nums text-muted-foreground">
                  {p.frequency}
                </td>
                <td
                  className="px-4 py-2 text-right tabular-nums font-semibold"
                  style={{ color: returnColor(p.avg_return) }}
                >
                  {p.avg_return >= 0 ? "+" : ""}
                  {p.avg_return.toFixed(2)}%
                </td>
                <td className="px-4 py-2 text-right text-muted-foreground/60">
                  {fmtLastSeen(p.last_seen)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Component ─────────────────────────────────────────────────────────────────

interface PatternCardProps {
  symbol: string;
  lookbackDays?: number;
}

export function PatternCard({ symbol, lookbackDays = 30 }: PatternCardProps) {
  const key = `/learning/patterns?symbol=${symbol}&lookback_days=${lookbackDays}`;
  const { data: envelope, isLoading, error } = useSWR<PatternsEnvelope>(key, fetcher, {
    refreshInterval: REFRESH_MS,
  });

  const data = envelope?.data;

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

  if (error) {
    return (
      <div className="rounded-xl border border-border bg-card p-4">
        <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground mb-3">
          Trade Patterns — {symbol}
        </p>
        <p className="font-mono text-xs text-red-400/70 italic">
          {error instanceof Error ? error.message : "No pattern data available — need more trade history"}
        </p>
      </div>
    );
  }

  const timeOfDay = data?.time_of_day ?? [];
  const regimes = data?.regime_patterns ?? [];
  const streaks = data?.streak_patterns ?? [];

  return (
    <div className="space-y-4">
      {/* Summary */}
      <div className="rounded-xl border border-border bg-card p-4 space-y-1">
        <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
          Trade Patterns — {symbol}
        </p>
        <p className="font-mono text-[11px] text-muted-foreground/60">
          {data?.trades_analyzed ?? 0} trades analyzed over the last {data?.lookback_days ?? lookbackDays} days
          {" · "}
          {data?.patterns_found ?? 0} pattern{(data?.patterns_found ?? 0) !== 1 ? "s" : ""} found
        </p>
      </div>

      <PatternTable title="Time-of-Day Patterns" patterns={timeOfDay} />
      <PatternTable title="Regime Patterns" patterns={regimes} />
      <PatternTable title="Streak Patterns" patterns={streaks} />

      {/* Empty state */}
      {!timeOfDay.length && !regimes.length && !streaks.length && (
        <div className="rounded-xl border border-border bg-card p-6 text-center">
          <p className="font-mono text-xs text-muted-foreground/50 italic">
            No pattern data for {symbol} in the last {lookbackDays} days.
            <br />
            Patterns emerge once 3+ trades share the same condition
            (PatternExtractor.MIN_PATTERN_FREQUENCY).
          </p>
        </div>
      )}
    </div>
  );
}
