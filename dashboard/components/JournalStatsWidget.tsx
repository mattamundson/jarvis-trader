"use client";

import { useState, useEffect } from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchEngine } from "@/lib/api";


interface TradeRecord {
  id: number;
  symbol: string;
  side: "BUY" | "SELL";
  realized_pnl: number | null;
  status: "OPEN" | "CLOSED" | "CANCELLED";
  entry_time: string;
  exit_time: string | null;
  notes: string | null;
}

interface JournalStats {
  total_trades: number;
  open_trades: number;
  closed_trades: number;
  cancelled_trades: number;
  winning_trades: number;
  losing_trades: number;
  win_streak: number;
  loss_streak: number;
  current_streak: number;
  avg_winner: number;
  avg_loser: number;
  largest_win: number;
  largest_loss: number;
  notes_count: number;
}

function computeStats(trades: TradeRecord[]): JournalStats {
  const closed = trades.filter((t) => t.status === "CLOSED");
  const winners = closed.filter((t) => t.realized_pnl !== null && t.realized_pnl > 0);
  const losers = closed.filter(
    (t) => t.realized_pnl !== null && t.realized_pnl <= 0
  );

  // Streaks — iterate over closed trades in chronological order
  const closedChronological = [...closed].sort(
    (a, b) => new Date(a.exit_time ?? a.entry_time).getTime() - new Date(b.exit_time ?? b.entry_time).getTime()
  );

  let winStreak = 0;
  let lossStreak = 0;
  let curWin = 0;
  let curLoss = 0;

  for (const t of closedChronological) {
    if (t.realized_pnl === null) continue;
    if (t.realized_pnl > 0) {
      curWin++;
      curLoss = 0;
      if (curWin > winStreak) winStreak = curWin;
    } else {
      curLoss++;
      curWin = 0;
      if (curLoss > lossStreak) lossStreak = curLoss;
    }
  }

  // Current streak: look at the tail of closedChronological
  let currentStreak = 0;
  for (let i = closedChronological.length - 1; i >= 0; i--) {
    const t = closedChronological[i];
    if (t.realized_pnl === null) break;
    if (i === closedChronological.length - 1) {
      // Seed direction from last trade
      currentStreak = t.realized_pnl > 0 ? 1 : -1;
    } else {
      const isWin = t.realized_pnl > 0;
      const streakIsWin = currentStreak > 0;
      if (isWin === streakIsWin) {
        currentStreak += isWin ? 1 : -1;
      } else {
        break;
      }
    }
  }

  const avgWinner =
    winners.length > 0
      ? winners.reduce((s, t) => s + (t.realized_pnl ?? 0), 0) / winners.length
      : 0;
  const avgLoser =
    losers.length > 0
      ? losers.reduce((s, t) => s + (t.realized_pnl ?? 0), 0) / losers.length
      : 0;

  const allPnls = closed
    .map((t) => t.realized_pnl)
    .filter((p): p is number => p !== null);

  const largestWin = allPnls.length > 0 ? Math.max(...allPnls) : 0;
  const largestLoss = allPnls.length > 0 ? Math.min(...allPnls) : 0;

  return {
    total_trades: trades.length,
    open_trades: trades.filter((t) => t.status === "OPEN").length,
    closed_trades: closed.length,
    cancelled_trades: trades.filter((t) => t.status === "CANCELLED").length,
    winning_trades: winners.length,
    losing_trades: losers.length,
    win_streak: winStreak,
    loss_streak: lossStreak,
    current_streak: currentStreak,
    avg_winner: avgWinner,
    avg_loser: avgLoser,
    largest_win: largestWin,
    largest_loss: largestLoss,
    notes_count: trades.filter((t) => t.notes !== null).length,
  };
}

function fmt(value: number, signed = false): string {
  const prefix = signed && value > 0 ? "+" : "";
  return `${prefix}$${Math.abs(value).toFixed(2)}`;
}

// ── Stat cell ────────────────────────────────────────────────────────────────

interface StatCellProps {
  label: string;
  value: string;
  color?: "green" | "red" | "neutral";
}

function StatCell({ label, value, color = "neutral" }: StatCellProps) {
  const valueClass =
    color === "green"
      ? "text-emerald-400"
      : color === "red"
      ? "text-red-400"
      : "text-foreground";

  return (
    <div className="rounded-lg border border-border bg-card/50 px-4 py-3 flex flex-col gap-1">
      <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
        {label}
      </span>
      <span className={`font-mono text-xl font-bold tabular-nums ${valueClass}`}>
        {value}
      </span>
    </div>
  );
}

// ── Loading skeleton ─────────────────────────────────────────────────────────

function LoadingSkeleton() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Journal Statistics</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-2 gap-3">
          {Array.from({ length: 10 }).map((_, i) => (
            <div
              key={i}
              className="rounded-lg border border-border bg-card/50 px-4 py-3 h-16 animate-pulse"
            />
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

// ── Main widget ──────────────────────────────────────────────────────────────

export function JournalStatsWidget() {
  const [stats, setStats] = useState<JournalStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  async function fetchStats() {
    try {
      const raw: unknown = await fetchEngine(`/portfolio/history/trades?limit=500`);

      // Handle both array and wrapped { trades: [...] } responses
      const trades: TradeRecord[] = Array.isArray(raw)
        ? raw
        : Array.isArray((raw as { trades?: TradeRecord[] }).trades)
          ? (raw as { trades: TradeRecord[] }).trades
          : [];

      setStats(computeStats(trades));
      setError(false);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchStats();
    const interval = setInterval(fetchStats, 60_000);
    return () => clearInterval(interval);
  }, []);

  if (loading) return <LoadingSkeleton />;

  if (error) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Journal Statistics</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="font-mono text-sm text-muted-foreground text-center py-6">
            Journal data unavailable
          </p>
        </CardContent>
      </Card>
    );
  }

  if (!stats || stats.total_trades === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Journal Statistics</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="font-mono text-sm text-muted-foreground text-center py-6">
            No trades recorded yet
          </p>
        </CardContent>
      </Card>
    );
  }

  // Current streak banner
  let bannerContent: React.ReactNode;
  if (stats.current_streak > 0) {
    bannerContent = (
      <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-4 py-2 text-center">
        <span className="font-mono text-xs font-semibold text-emerald-400">
          Current Win Streak: {stats.current_streak} trade{stats.current_streak !== 1 ? "s" : ""}
        </span>
      </div>
    );
  } else if (stats.current_streak < 0) {
    bannerContent = (
      <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-2 text-center">
        <span className="font-mono text-xs font-semibold text-red-400">
          Current Loss Streak: {Math.abs(stats.current_streak)} trade{Math.abs(stats.current_streak) !== 1 ? "s" : ""}
        </span>
      </div>
    );
  } else {
    bannerContent = (
      <div className="rounded-lg border border-border bg-muted/30 px-4 py-2 text-center">
        <span className="font-mono text-xs text-muted-foreground">
          No active streak
        </span>
      </div>
    );
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>Journal Statistics</CardTitle>
          {stats.notes_count > 0 && (
            <Badge variant="info">{stats.notes_count} annotated trade{stats.notes_count !== 1 ? "s" : ""}</Badge>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {/* Row 1 */}
        <div className="grid grid-cols-2 gap-3">
          <StatCell label="Total Trades" value={String(stats.total_trades)} />
          <StatCell label="Open Positions" value={String(stats.open_trades)} />
        </div>

        {/* Row 2 */}
        <div className="grid grid-cols-2 gap-3">
          <StatCell label="Winning Trades" value={String(stats.winning_trades)} color="green" />
          <StatCell label="Losing Trades" value={String(stats.losing_trades)} color="red" />
        </div>

        {/* Row 3 */}
        <div className="grid grid-cols-2 gap-3">
          <StatCell
            label="Avg Winner"
            value={stats.winning_trades > 0 ? fmt(stats.avg_winner, true) : "—"}
            color="green"
          />
          <StatCell
            label="Avg Loser"
            value={stats.losing_trades > 0 ? fmt(stats.avg_loser, true) : "—"}
            color="red"
          />
        </div>

        {/* Row 4 */}
        <div className="grid grid-cols-2 gap-3">
          <StatCell
            label="Largest Win"
            value={stats.closed_trades > 0 ? fmt(stats.largest_win, true) : "—"}
            color="green"
          />
          <StatCell
            label="Largest Loss"
            value={stats.closed_trades > 0 ? fmt(stats.largest_loss, true) : "—"}
            color="red"
          />
        </div>

        {/* Row 5 */}
        <div className="grid grid-cols-2 gap-3">
          <StatCell label="Win Streak" value={String(stats.win_streak)} />
          <StatCell label="Loss Streak" value={String(stats.loss_streak)} />
        </div>

        {/* Current streak banner */}
        {bannerContent}
      </CardContent>
    </Card>
  );
}
