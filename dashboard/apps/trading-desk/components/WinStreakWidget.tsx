"use client";

import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  type HonestTrade,
  type HonestTradeSet,
  dedupCaveat,
} from "@/lib/honestTrades";
import { useHonestTrades } from "@/lib/useHonestTrades";


interface StreakResult {
  currentStreak: number;
  currentStreakType: "WIN" | "LOSS" | "NONE";
  maxWinStreak: number;
  maxLossStreak: number;
  validTradeCount: number;
}

function computeStreaksFromHonest(trades: HonestTrade[]): StreakResult {
  // Already deduped — sort ascending by exit_time (close order); null goes to end
  const sorted = [...trades].sort((a, b) => {
    if (!a.exit_time && !b.exit_time) return 0;
    if (!a.exit_time) return 1;
    if (!b.exit_time) return -1;
    return Date.parse(a.exit_time) - Date.parse(b.exit_time);
  });

  if (sorted.length === 0) {
    return {
      currentStreak: 0,
      currentStreakType: "NONE",
      maxWinStreak: 0,
      maxLossStreak: 0,
      validTradeCount: 0,
    };
  }

  let maxWinStreak = 0;
  let maxLossStreak = 0;
  let runWin = 0;
  let runLoss = 0;

  for (const trade of sorted) {
    const isWin = trade.pnl > 0;
    if (isWin) {
      runWin++;
      runLoss = 0;
      if (runWin > maxWinStreak) maxWinStreak = runWin;
    } else {
      runLoss++;
      runWin = 0;
      if (runLoss > maxLossStreak) maxLossStreak = runLoss;
    }
  }

  let currentStreak = 0;
  let currentStreakType: "WIN" | "LOSS" | "NONE" = "NONE";
  if (runWin > 0) {
    currentStreak = runWin;
    currentStreakType = "WIN";
  } else if (runLoss > 0) {
    currentStreak = runLoss;
    currentStreakType = "LOSS";
  }

  return {
    currentStreak,
    currentStreakType,
    maxWinStreak,
    maxLossStreak,
    validTradeCount: sorted.length,
  };
}

export function WinStreakWidget() {
  const { honest: honestSet, isLoading: loading, error: loadError } = useHonestTrades(300_000);
  const error = loadError ? (loadError instanceof Error ? loadError.message : String(loadError)) : null;
  const streaks = honestSet ? computeStreaksFromHonest(honestSet.trades) : null;

  const currentNum = streaks?.currentStreak ?? 0;
  const currentType = streaks?.currentStreakType ?? "NONE";
  const maxWin = streaks?.maxWinStreak ?? 0;
  const maxLoss = streaks?.maxLossStreak ?? 0;
  const total = streaks?.validTradeCount ?? 0;

  const currentDisplay =
    currentType === "NONE"
      ? "0"
      : currentType === "WIN"
      ? `+${currentNum}`
      : `-${currentNum}`;

  const currentColor =
    currentType === "WIN"
      ? "text-green-400"
      : currentType === "LOSS"
      ? "text-red-400"
      : "text-muted-foreground";

  const streakBadgeVariant: "bull" | "bear" | "neutral" =
    currentType === "WIN" ? "bull" : currentType === "LOSS" ? "bear" : "neutral";

  const streakBadgeLabel =
    currentType === "WIN" ? "bull" : currentType === "LOSS" ? "bear" : "neutral";

  const hotStreak = currentType === "WIN" && currentNum >= 3;
  const coldStreak = currentType === "LOSS" && currentNum >= 3;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between flex-wrap gap-2">
          <CardTitle>Win/Loss Streaks</CardTitle>
          <Badge variant={streakBadgeVariant}>{streakBadgeLabel}</Badge>
        </div>
      </CardHeader>

      <CardContent>
        {/* Loading state */}
        {loading && (
          <p className="text-xs text-muted-foreground animate-pulse">
            Loading streak data…
          </p>
        )}

        {/* Error state */}
        {!loading && error && (
          <p className="text-xs text-red-400">Error: {error}</p>
        )}

        {/* Empty state */}
        {!loading && !error && streaks && total === 0 && (
          <p className="text-xs text-muted-foreground">
            No closed trades with P&amp;L data found.
          </p>
        )}

        {/* Data loaded */}
        {!loading && !error && streaks && total > 0 && (
          <div className="space-y-4">
            {/* 3-column grid */}
            <div className="grid grid-cols-3 gap-3">
              {/* Left: Current Streak */}
              <div className="rounded-lg border border-border/50 bg-background/20 px-4 py-4 flex flex-col items-center gap-2">
                <p className="text-xs text-muted-foreground uppercase tracking-wider text-center">
                  Current Streak
                </p>
                <p
                  className={`text-3xl font-bold font-mono tabular-nums leading-none ${currentColor}`}
                >
                  {currentDisplay}
                </p>
                <Badge variant={streakBadgeVariant}>{streakBadgeLabel}</Badge>
              </div>

              {/* Middle: Best Win Streak */}
              <div className="rounded-lg border border-border/50 bg-background/20 px-4 py-4 flex flex-col items-center gap-2">
                <p className="text-xs text-muted-foreground uppercase tracking-wider text-center">
                  Best Win Streak
                </p>
                <p className="text-3xl font-bold font-mono tabular-nums leading-none text-green-400 flex items-center gap-1">
                  {maxWin}
                  <span className="text-2xl">🔥</span>
                </p>
                <p className="text-xs text-muted-foreground">consecutive wins</p>
              </div>

              {/* Right: Worst Loss Streak */}
              <div className="rounded-lg border border-border/50 bg-background/20 px-4 py-4 flex flex-col items-center gap-2">
                <p className="text-xs text-muted-foreground uppercase tracking-wider text-center">
                  Worst Loss Streak
                </p>
                <p className="text-3xl font-bold font-mono tabular-nums leading-none text-red-400">
                  {maxLoss}
                </p>
                <p className="text-xs text-muted-foreground">consecutive losses</p>
              </div>
            </div>

            {/* Hot / cool callout */}
            {hotStreak && (
              <p className="text-xs font-medium text-green-400">Hot streak!</p>
            )}
            {coldStreak && (
              <p className="text-xs font-medium text-amber-400">
                Cool down period
              </p>
            )}

            {/* Footer */}
            <p className="text-xs text-muted-foreground">
              {honestSet ? dedupCaveat(honestSet) : `${total} valid trades analyzed`}
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default WinStreakWidget;
