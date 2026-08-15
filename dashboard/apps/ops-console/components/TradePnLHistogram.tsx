"use client";

import React from "react";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
} from "@/components/ui/card";
import { type HonestTrade } from "@/lib/honestTrades";
import { useHonestTrades } from "@/lib/useHonestTrades";


// ── Bucket config ─────────────────────────────────────────────────────────────

interface Bucket {
  label: string;
  shortLabel: string;
  min: number;
  max: number;
  fill: string;
}

const BUCKETS: Bucket[] = [
  { label: "< -$50",      shortLabel: "<-50",    min: -Infinity, max: -50,     fill: "#ef4444" },
  { label: "-$50–-$25",   shortLabel: "-50/-25", min: -50,       max: -25,     fill: "#ef4444" },
  { label: "-$25–$0",     shortLabel: "-25/0",   min: -25,       max: 0,       fill: "#f87171" },
  { label: "$0–$25",      shortLabel: "0/25",    min: 0,         max: 25,      fill: "#86efac" },
  { label: "$25–$50",     shortLabel: "25/50",   min: 25,        max: 50,      fill: "#22c55e" },
  { label: "$50–$100",    shortLabel: "50/100",  min: 50,        max: 100,     fill: "#22c55e" },
  { label: "> $100",      shortLabel: ">100",    min: 100,       max: Infinity, fill: "#22c55e" },
];

function getBucketIndex(pnl: number): number {
  for (let i = 0; i < BUCKETS.length; i++) {
    if (pnl >= BUCKETS[i].min && pnl < BUCKETS[i].max) return i;
  }
  // Edge: pnl === 100 should go to "> $100" but loop puts it in "$50–$100"
  // Handle the last bucket's max being Infinity — already covered.
  return BUCKETS.length - 1;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function TradePnLHistogram() {
  const { honest: set, isLoading: loading, error: loadError } = useHonestTrades(5 * 60 * 1000);
  const error = loadError ? (loadError instanceof Error ? loadError.message : String(loadError)) : null;

  // All honest trades have a valid pnl — no status/null filter needed
  const closedTrades = set?.trades ?? [];

  // Bucket counts
  const counts = new Array(BUCKETS.length).fill(0);
  for (const t of closedTrades) {
    const idx = getBucketIndex(t.pnl);
    counts[idx]++;
  }

  // Win/loss stats
  const winTrades = closedTrades.filter((t) => t.pnl >= 0);
  const lossTrades = closedTrades.filter((t) => t.pnl < 0);
  const winCount = winTrades.length;
  const lossCount = lossTrades.length;

  const avgWin =
    winCount > 0
      ? winTrades.reduce((s, t) => s + t.pnl, 0) / winCount
      : 0;
  const avgLoss =
    lossCount > 0
      ? lossTrades.reduce((s, t) => s + t.pnl, 0) / lossCount
      : 0;

  const ratio =
    avgLoss === 0 ? "∞" : (avgWin / Math.abs(avgLoss)).toFixed(1);

  // SVG dimensions
  const BAR_WIDTH = 50;
  const BAR_GAP = 10;
  const MAX_BAR_HEIGHT = 80;
  const CHART_HEIGHT = 100;
  const maxCount = Math.max(...counts, 1);

  const hasEnoughData = closedTrades.length >= 3;

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle className="text-base font-semibold">P&amp;L Distribution</CardTitle>
        <div className="flex gap-2">
          <Badge variant="bear">{lossCount} Losses</Badge>
          <Badge variant="bull">{winCount} Wins</Badge>
        </div>
      </CardHeader>
      <CardContent>
        {loading ? (
          <div className="flex items-center justify-center py-10">
            <div className="h-5 w-5 rounded-full border-2 border-accent border-t-transparent animate-spin mr-2" />
            <span className="text-sm text-muted-foreground">Loading trades…</span>
          </div>
        ) : error ? (
          <div className="rounded-lg border border-bear/20 bg-bear/5 p-4 text-sm text-bear">
            Error: {error}
          </div>
        ) : !hasEnoughData ? (
          <div className="flex items-center justify-center py-10">
            <p className="text-sm text-muted-foreground">
              Need more trades for distribution analysis
            </p>
          </div>
        ) : (
          <>
            {/* SVG Bar Chart */}
            <div className="w-full overflow-x-auto">
              <svg
                viewBox="0 0 420 100"
                preserveAspectRatio="xMidYMid meet"
                className="w-full"
                style={{ minWidth: 320 }}
              >
                {BUCKETS.map((bucket, i) => {
                  const x = i * (BAR_WIDTH + BAR_GAP);
                  const count = counts[i];
                  const barH = count === 0 ? 2 : Math.max(2, (count / maxCount) * MAX_BAR_HEIGHT);
                  const barY = MAX_BAR_HEIGHT - barH;
                  const labelY = MAX_BAR_HEIGHT - barH - 4;

                  return (
                    <g key={bucket.label}>
                      {/* Bar */}
                      <rect
                        x={x}
                        y={barY}
                        width={BAR_WIDTH}
                        height={barH}
                        fill={bucket.fill}
                        rx={2}
                        opacity={count === 0 ? 0.3 : 1}
                      />
                      {/* Count label above bar */}
                      {count > 0 && (
                        <text
                          x={x + BAR_WIDTH / 2}
                          y={Math.max(labelY, 8)}
                          textAnchor="middle"
                          fontSize="9"
                          fill="currentColor"
                          className="fill-muted-foreground"
                        >
                          {count}
                        </text>
                      )}
                      {/* Bucket label below chart, rotated */}
                      <text
                        x={x + BAR_WIDTH / 2}
                        y={CHART_HEIGHT - 2}
                        textAnchor="end"
                        fontSize="8"
                        fill="currentColor"
                        className="fill-muted-foreground"
                        transform={`rotate(-45, ${x + BAR_WIDTH / 2}, ${CHART_HEIGHT - 2})`}
                      >
                        {bucket.shortLabel}
                      </text>
                    </g>
                  );
                })}
              </svg>
            </div>

            {/* Stats row */}
            <div className="grid grid-cols-3 gap-2 mt-3 text-center">
              <div>
                <p className="text-xs text-muted-foreground">Avg Win</p>
                <p className="text-sm font-mono font-medium text-green-400">
                  +${avgWin.toFixed(2)}
                </p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Avg Loss</p>
                <p className="text-sm font-mono font-medium text-red-400">
                  -${Math.abs(avgLoss).toFixed(2)}
                </p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">W:L Ratio</p>
                <p className="text-sm font-mono font-medium">{ratio}:1</p>
              </div>
            </div>
          </>
        )}

        <p className="text-xs text-muted-foreground mt-2">
          Deduped trade record &bull; Refreshes every 5m
        </p>
      </CardContent>
    </Card>
  );
}
