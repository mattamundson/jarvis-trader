"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { durationMinutes, type HonestTrade } from "@/lib/honestTrades";
import { useHonestTrades } from "@/lib/useHonestTrades";


interface DurationData {
  avgDuration: number;
  medianDuration: number;
  scalps: number;
  medium: number;
  long: number;
  total: number;
}

function formatDuration(minutes: number): string {
  if (minutes < 60) {
    return `${Math.round(minutes)}m`;
  }
  const hrs = Math.floor(minutes / 60);
  const mins = Math.round(minutes % 60);
  return mins > 0 ? `${hrs}hr ${mins}m` : `${hrs}hr`;
}

function computeDurationData(trades: HonestTrade[]): DurationData | null {
  const durations: number[] = [];

  for (const trade of trades) {
    // Use the honestTrades helper — guards both null timestamps and NaN
    const mins = durationMinutes(trade);
    if (mins === null || mins <= 0) continue;
    durations.push(mins);
  }

  if (durations.length < 3) return null;

  const total = durations.length;
  const avgDuration = durations.reduce((a, b) => a + b, 0) / total;

  const sorted = [...durations].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  const medianDuration =
    sorted.length % 2 === 0
      ? (sorted[mid - 1] + sorted[mid]) / 2
      : sorted[mid];

  const scalps = durations.filter((d) => d < 30).length;
  const medium = durations.filter((d) => d >= 30 && d < 120).length;
  const long = durations.filter((d) => d >= 120).length;

  return { avgDuration, medianDuration, scalps, medium, long, total };
}

export function TradeDurationWidget() {
  const { honest: set, isLoading: loading, error: loadError } = useHonestTrades(300_000);
  const error = !!loadError;
  const data = set ? computeDurationData(set.trades) : null;

  if (loading) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Trade Duration Analysis</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            <div className="animate-pulse h-10 bg-muted rounded" />
            <div className="animate-pulse h-6 bg-muted rounded" />
            <div className="animate-pulse h-6 bg-muted rounded" />
          </div>
        </CardContent>
      </Card>
    );
  }

  if (error) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Trade Duration Analysis</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">Unable to load trade data</p>
        </CardContent>
      </Card>
    );
  }

  if (!data) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Trade Duration Analysis</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            Not enough closed trades to analyze (need at least 3)
          </p>
        </CardContent>
      </Card>
    );
  }

  const { avgDuration, medianDuration, scalps, medium, long, total } = data;

  const badgeVariant: "info" | "neutral" | "warn" =
    avgDuration < 30 ? "info" : avgDuration < 90 ? "neutral" : "warn";

  const badgeLabel =
    avgDuration < 30 ? "Scalper" : avgDuration < 90 ? "Swing" : "Holding Long";

  // Proportional widths for bars (min 4% so even 0-count has a visible sliver)
  const maxCount = Math.max(scalps, medium, long, 1);
  const scalpsWidth = Math.max((scalps / maxCount) * 100, scalps > 0 ? 4 : 0);
  const mediumWidth = Math.max((medium / maxCount) * 100, medium > 0 ? 4 : 0);
  const longWidth = Math.max((long / maxCount) * 100, long > 0 ? 4 : 0);

  return (
    <Card>
      <CardHeader className="pb-2 flex flex-row items-center justify-between">
        <CardTitle className="text-sm">Trade Duration Analysis</CardTitle>
        <Badge variant={badgeVariant}>{badgeLabel}</Badge>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Big metric */}
        <div>
          <p className="text-3xl font-mono font-bold tabular-nums">
            {formatDuration(avgDuration)}
          </p>
          <p className="text-xs text-muted-foreground mt-0.5">Avg Hold Time</p>
        </div>

        {/* Mini bar chart */}
        <div className="space-y-1.5">
          <p className="text-xs text-muted-foreground mb-2">Duration Distribution</p>

          {/* Scalps bar */}
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground w-14 shrink-0">Scalps</span>
            <div className="flex-1 h-5 bg-muted/30 rounded overflow-hidden">
              <div
                className="h-full rounded bg-blue-500/20 border border-blue-500/40"
                style={{ width: `${scalpsWidth}%` }}
              />
            </div>
            <span className="text-xs font-mono tabular-nums w-8 text-right">{scalps}</span>
          </div>

          {/* Medium bar */}
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground w-14 shrink-0">Medium</span>
            <div className="flex-1 h-5 bg-muted/30 rounded overflow-hidden">
              <div
                className="h-full rounded bg-green-500/20 border border-green-500/40"
                style={{ width: `${mediumWidth}%` }}
              />
            </div>
            <span className="text-xs font-mono tabular-nums w-8 text-right">{medium}</span>
          </div>

          {/* Long bar */}
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground w-14 shrink-0">Long</span>
            <div className="flex-1 h-5 bg-muted/30 rounded overflow-hidden">
              <div
                className="h-full rounded bg-yellow-500/20 border border-yellow-500/40"
                style={{ width: `${longWidth}%` }}
              />
            </div>
            <span className="text-xs font-mono tabular-nums w-8 text-right">{long}</span>
          </div>
        </div>

        {/* Stats row */}
        <div className="grid grid-cols-4 gap-2 border-t border-border pt-3">
          <div className="text-center">
            <p className="text-xs text-muted-foreground">Scalps</p>
            <p className="text-sm font-mono font-bold text-blue-400 tabular-nums">{scalps}</p>
            <p className="text-[10px] text-muted-foreground">&lt;30m</p>
          </div>
          <div className="text-center">
            <p className="text-xs text-muted-foreground">Medium</p>
            <p className="text-sm font-mono font-bold text-green-400 tabular-nums">{medium}</p>
            <p className="text-[10px] text-muted-foreground">30–120m</p>
          </div>
          <div className="text-center">
            <p className="text-xs text-muted-foreground">Long</p>
            <p className="text-sm font-mono font-bold text-yellow-400 tabular-nums">{long}</p>
            <p className="text-[10px] text-muted-foreground">2hr+</p>
          </div>
          <div className="text-center">
            <p className="text-xs text-muted-foreground">Median</p>
            <p className="text-sm font-mono font-bold tabular-nums">{formatDuration(medianDuration)}</p>
            <p className="text-[10px] text-muted-foreground">of {total}</p>
          </div>
        </div>

        <p className="text-xs text-muted-foreground">Deduped trade record &bull; Refreshes every 5m</p>
      </CardContent>
    </Card>
  );
}
