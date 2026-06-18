"use client";

import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  dedupCaveat,
  type HonestTrade,
  type HonestTradeSet,
} from "@/lib/honestTrades";
import { useHonestTrades } from "@/lib/useHonestTrades";

// ── Pure stat computation (derived from deduped HonestTrade[]) ───────────────

interface JournalStats {
  wins: number;
  losses: number;
  win_streak: number;
  loss_streak: number;
  current_streak: number;
  avg_winner: number;
  avg_loser: number;
  largest_win: number;
  largest_loss: number;
}

function computeStats(trades: HonestTrade[]): JournalStats {
  // Sort by exit_time ascending; trades without exit_time go last
  const sorted = [...trades].sort((a, b) => {
    if (!a.exit_time && !b.exit_time) return 0;
    if (!a.exit_time) return 1;
    if (!b.exit_time) return -1;
    return Date.parse(a.exit_time) - Date.parse(b.exit_time);
  });

  const winners = sorted.filter((t) => t.pnl > 0);
  const losers = sorted.filter((t) => t.pnl < 0);

  // Best/worst win + loss streaks (all-time)
  let winStreak = 0;
  let lossStreak = 0;
  let curWin = 0;
  let curLoss = 0;
  for (const t of sorted) {
    if (t.pnl > 0) {
      curWin++;
      curLoss = 0;
      if (curWin > winStreak) winStreak = curWin;
    } else if (t.pnl < 0) {
      curLoss++;
      curWin = 0;
      if (curLoss > lossStreak) lossStreak = curLoss;
    }
    // pnl === 0 (scratch) breaks neither streak
  }

  // Current streak: walk tail of sorted backwards
  let currentStreak = 0;
  for (let i = sorted.length - 1; i >= 0; i--) {
    const t = sorted[i];
    if (t.pnl === 0) break; // scratch stops the count
    if (i === sorted.length - 1) {
      currentStreak = t.pnl > 0 ? 1 : -1;
    } else {
      const isWin = t.pnl > 0;
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
      ? winners.reduce((s, t) => s + t.pnl, 0) / winners.length
      : 0;
  const avgLoser =
    losers.length > 0
      ? losers.reduce((s, t) => s + t.pnl, 0) / losers.length
      : 0;

  const allPnls = sorted.map((t) => t.pnl);
  const largestWin = allPnls.length > 0 ? Math.max(...allPnls) : 0;
  const largestLoss = allPnls.length > 0 ? Math.min(...allPnls) : 0;

  return {
    wins: winners.length,
    losses: losers.length,
    win_streak: winStreak,
    loss_streak: lossStreak,
    current_streak: currentStreak,
    avg_winner: avgWinner,
    avg_loser: avgLoser,
    largest_win: largestWin,
    largest_loss: largestLoss,
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
  const { honest: set, isLoading: loading, error: loadError } = useHonestTrades(60_000);
  const error = loadError != null;
  const stats: JournalStats | null = set ? computeStats(set.trades) : null;

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

  if (!stats || !set || set.trades.length === 0) {
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

  const caveat = dedupCaveat(set);

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>Journal Statistics</CardTitle>
          <Badge variant="info">{caveat}</Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {/* Row 1 */}
        <div className="grid grid-cols-2 gap-3">
          <StatCell label="Winning Trades" value={String(stats.wins)} color="green" />
          <StatCell label="Losing Trades" value={String(stats.losses)} color="red" />
        </div>

        {/* Row 2 */}
        <div className="grid grid-cols-2 gap-3">
          <StatCell
            label="Avg Winner"
            value={stats.wins > 0 ? fmt(stats.avg_winner, true) : "—"}
            color="green"
          />
          <StatCell
            label="Avg Loser"
            value={stats.losses > 0 ? fmt(stats.avg_loser, true) : "—"}
            color="red"
          />
        </div>

        {/* Row 3 */}
        <div className="grid grid-cols-2 gap-3">
          <StatCell
            label="Largest Win"
            value={set.trades.length > 0 ? fmt(stats.largest_win, true) : "—"}
            color="green"
          />
          <StatCell
            label="Largest Loss"
            value={set.trades.length > 0 ? fmt(stats.largest_loss, true) : "—"}
            color="red"
          />
        </div>

        {/* Row 4 */}
        <div className="grid grid-cols-2 gap-3">
          <StatCell label="Win Streak" value={String(stats.win_streak)} />
          <StatCell label="Loss Streak" value={String(stats.loss_streak)} />
        </div>

        {/* Current streak banner */}
        {bannerContent}

        {/* Dedup caveat footer */}
        {set.caveats.length > 0 && (
          <p className="font-mono text-[9px] text-muted-foreground text-center">
            {set.caveats[0]}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
