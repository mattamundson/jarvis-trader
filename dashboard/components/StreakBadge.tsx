"use client";

import { Badge } from "@/components/ui/badge";
import { Flame, TrendingDown } from "lucide-react";
import { type HonestTrade } from "@/lib/honestTrades";
import { useHonestTrades } from "@/lib/useHonestTrades";

interface DerivedStreakData {
  currentStreak: number;
  currentType: "win" | "loss" | "none";
  totalTrades: number;
  recentResults: string[]; // "W" | "L", last 10 in close order
}

function deriveStreakData(trades: HonestTrade[]): DerivedStreakData {
  // Sort ascending by exit_time so we walk trades in close order
  const sorted = [...trades]
    .filter((t) => t.exit_time)
    .sort((a, b) => Date.parse(a.exit_time!) - Date.parse(b.exit_time!));

  if (sorted.length === 0) {
    return { currentStreak: 0, currentType: "none", totalTrades: 0, recentResults: [] };
  }

  let runWin = 0;
  let runLoss = 0;
  for (const t of sorted) {
    if (t.pnl > 0) {
      runWin++;
      runLoss = 0;
    } else {
      runLoss++;
      runWin = 0;
    }
  }

  const currentStreak = runWin > 0 ? runWin : runLoss;
  const currentType: "win" | "loss" | "none" = runWin > 0 ? "win" : runLoss > 0 ? "loss" : "none";

  // Recent results: last 10 trades
  const recentResults = sorted.slice(-10).map((t) => (t.pnl > 0 ? "W" : "L"));

  return { currentStreak, currentType, totalTrades: sorted.length, recentResults };
}

export function StreakBadge() {
  const { honest } = useHonestTrades(60_000);
  const streakData = honest ? deriveStreakData(honest.trades) : null;

  if (!streakData || streakData.totalTrades === 0) return null;

  const isWin = streakData.currentType === "win";
  const variant =
    streakData.currentStreak >= 3
      ? isWin
        ? "bull"
        : "bear"
      : isWin
      ? "info"
      : "neutral";

  return (
    <div className="flex items-center gap-3">
      <Badge variant={variant} className="flex items-center gap-1">
        {isWin ? (
          <Flame className="h-3 w-3" />
        ) : (
          <TrendingDown className="h-3 w-3" />
        )}
        {streakData.currentStreak} {streakData.currentType} streak
      </Badge>
      <div className="flex gap-0.5">
        {streakData.recentResults.map((r, i) => (
          <div
            key={i}
            className={`h-4 w-2 rounded-sm ${r === "W" ? "bg-green-500" : "bg-red-400"}`}
            title={r === "W" ? "Win" : "Loss"}
          />
        ))}
      </div>
    </div>
  );
}
