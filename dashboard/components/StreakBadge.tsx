"use client";

import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Flame, TrendingDown } from "lucide-react";

interface StreakData {
  current_streak: number;
  current_type: "win" | "loss" | "none";
  max_win_streak: number;
  max_loss_streak: number;
  total_trades: number;
  recent_results: string[];
}

export function StreakBadge() {
  const [data, setData] = useState<StreakData | null>(null);

  useEffect(() => {
    const load = async () => {
      try {
        const res = await fetch("http://localhost:8010/portfolio/stats/streaks");
        if (!res.ok) throw new Error("fetch failed");
        setData(await res.json());
      } catch {
        setData(null);
      }
    };
    load();
    const id = setInterval(load, 60_000);
    return () => clearInterval(id);
  }, []);

  if (!data || data.total_trades === 0) return null;

  const isWin = data.current_type === "win";
  const variant =
    data.current_streak >= 3
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
        {data.current_streak} {data.current_type} streak
      </Badge>
      <div className="flex gap-0.5">
        {data.recent_results.map((r, i) => (
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
