"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Clock, TrendingUp, Zap, Timer, Info } from "lucide-react";
import {
  durationMinutes,
  dedupCaveat,
  type HonestTrade,
  type HonestTradeSet,
} from "@/lib/honestTrades";
import { useHonestTrades } from "@/lib/useHonestTrades";


// ── Types ─────────────────────────────────────────────────────────────────────

interface BucketStats {
  label: string;
  range: string;
  count: number;
  wins: number;
  totalPnl: number;
}

interface AvgTradeTimeData {
  avgMinutes: number;
  fastestMinutes: number;
  slowestMinutes: number;
  fastestSymbol: string;
  slowestSymbol: string;
  totalClosed: number;
  buckets: Record<BucketName, BucketStats>;
  caveat: string;
}

type BucketName = "scalp" | "short" | "swing" | "extended";

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatDuration(minutes: number): string {
  if (minutes < 60) return `${Math.round(minutes)}m`;
  const hrs = Math.floor(minutes / 60);
  const mins = Math.round(minutes % 60);
  return mins > 0 ? `${hrs}h ${mins}m` : `${hrs}h`;
}

function formatPnl(value: number): string {
  const sign = value >= 0 ? "+" : "";
  return `${sign}$${value.toFixed(2)}`;
}

function getBucketName(minutes: number): BucketName {
  if (minutes < 5) return "scalp";
  if (minutes < 30) return "short";
  if (minutes < 120) return "swing";
  return "extended";
}

function computeData(trades: HonestTrade[], set: HonestTradeSet): AvgTradeTimeData | null {
  const durations: { minutes: number; trade: HonestTrade }[] = [];

  for (const t of trades) {
    const m = durationMinutes(t);
    // guard null and non-positive durations
    if (m === null || m <= 0) continue;
    durations.push({ minutes: m, trade: t });
  }

  if (durations.length === 0) return null;

  const mins = durations.map((d) => d.minutes);
  const avgMinutes = mins.reduce((a, b) => a + b, 0) / mins.length;

  const minEntry = durations.reduce((a, b) => (a.minutes < b.minutes ? a : b));
  const maxEntry = durations.reduce((a, b) => (a.minutes > b.minutes ? a : b));

  const buckets: Record<BucketName, BucketStats> = {
    scalp:    { label: "Scalp",    range: "< 5 min",    count: 0, wins: 0, totalPnl: 0 },
    short:    { label: "Short",    range: "5–30 min",   count: 0, wins: 0, totalPnl: 0 },
    swing:    { label: "Swing",    range: "30–120 min", count: 0, wins: 0, totalPnl: 0 },
    extended: { label: "Extended", range: "> 2 hr",     count: 0, wins: 0, totalPnl: 0 },
  };

  for (const { minutes: m, trade } of durations) {
    const key = getBucketName(m);
    const bucket = buckets[key];
    bucket.count += 1;
    bucket.totalPnl += trade.pnl;
    if (trade.pnl > 0) bucket.wins += 1;
  }

  return {
    avgMinutes,
    fastestMinutes: minEntry.minutes,
    slowestMinutes: maxEntry.minutes,
    fastestSymbol: minEntry.trade.symbol,
    slowestSymbol: maxEntry.trade.symbol,
    totalClosed: durations.length,
    buckets,
    caveat: dedupCaveat(set),
  };
}

function avgVariant(minutes: number): "bull" | "bear" | "warn" | "info" | "neutral" {
  if (minutes < 5) return "info";
  if (minutes < 30) return "bull";
  if (minutes < 120) return "neutral";
  return "warn";
}

function avgLabel(minutes: number): string {
  if (minutes < 5) return "Scalper";
  if (minutes < 30) return "Short-Term";
  if (minutes < 120) return "Swing";
  return "Extended";
}

// ── Sub-components ────────────────────────────────────────────────────────────

function BucketRow({
  bucket,
  maxCount,
}: {
  bucket: BucketStats;
  maxCount: number;
}) {
  const winRate = bucket.count > 0 ? (bucket.wins / bucket.count) * 100 : 0;
  const barWidth =
    maxCount > 0
      ? Math.max((bucket.count / maxCount) * 100, bucket.count > 0 ? 4 : 0)
      : 0;

  const pnlColor =
    bucket.totalPnl > 0
      ? "text-green-400"
      : bucket.totalPnl < 0
      ? "text-red-400"
      : "text-muted-foreground";

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-xs">
        <div className="flex items-center gap-2 min-w-0">
          <span className="font-medium text-foreground w-16 shrink-0">{bucket.label}</span>
          <span className="text-muted-foreground text-[10px] shrink-0">{bucket.range}</span>
        </div>
        <div className="flex items-center gap-3 shrink-0 ml-2">
          <span className="font-mono tabular-nums text-muted-foreground text-[10px]">
            WR: {bucket.count > 0 ? `${winRate.toFixed(0)}%` : "–"}
          </span>
          <span className={`font-mono tabular-nums text-[10px] ${pnlColor}`}>
            {bucket.count > 0 ? formatPnl(bucket.totalPnl) : "–"}
          </span>
          <span className="font-mono tabular-nums font-bold w-6 text-right">{bucket.count}</span>
        </div>
      </div>
      <div className="h-4 bg-muted/30 rounded overflow-hidden">
        <div
          className="h-full rounded bg-blue-500/25 border border-blue-500/40 transition-all duration-500"
          style={{ width: `${barWidth}%` }}
        />
      </div>
    </div>
  );
}

// ── Main Widget ───────────────────────────────────────────────────────────────

export default function AvgTradeTimeWidget() {
  const { honest: honestSet, isLoading: loading, error: loadError } = useHonestTrades(60_000);
  const error = !!loadError;
  const data = honestSet ? computeData(honestSet.trades, honestSet) : null;

  // ── Loading state ──────────────────────────────────────────────────────────

  if (loading) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-2">
            <Clock className="h-4 w-4" />
            Avg Trade Hold Time
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            <div className="animate-pulse h-10 bg-muted rounded" />
            <div className="animate-pulse h-5 bg-muted rounded" />
            <div className="animate-pulse h-5 bg-muted rounded" />
            <div className="animate-pulse h-5 bg-muted rounded" />
            <div className="animate-pulse h-5 bg-muted rounded" />
          </div>
        </CardContent>
      </Card>
    );
  }

  // ── Error state ────────────────────────────────────────────────────────────

  if (error) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-2">
            <Clock className="h-4 w-4" />
            Avg Trade Hold Time
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">Unable to load trade data</p>
        </CardContent>
      </Card>
    );
  }

  // ── Empty state ────────────────────────────────────────────────────────────

  if (!data) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-2">
            <Clock className="h-4 w-4" />
            Avg Trade Hold Time
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            No closed trades with valid timestamps found
          </p>
        </CardContent>
      </Card>
    );
  }

  // ── Populated state ────────────────────────────────────────────────────────

  const {
    avgMinutes,
    fastestMinutes,
    slowestMinutes,
    fastestSymbol,
    slowestSymbol,
    totalClosed,
    buckets,
    caveat,
  } = data;

  const bucketOrder: BucketName[] = ["scalp", "short", "swing", "extended"];
  const maxCount = Math.max(...bucketOrder.map((k) => buckets[k].count), 1);

  return (
    <Card>
      <CardHeader className="pb-2 flex flex-row items-center justify-between">
        <CardTitle className="text-sm flex items-center gap-2">
          <Clock className="h-4 w-4" />
          Avg Trade Hold Time
        </CardTitle>
        <Badge variant={avgVariant(avgMinutes)}>{avgLabel(avgMinutes)}</Badge>
      </CardHeader>
      <CardContent className="space-y-5">
        {/* Primary metric */}
        <div>
          <p className="text-3xl font-mono font-bold tabular-nums">
            {formatDuration(avgMinutes)}
          </p>
          <p className="text-xs text-muted-foreground mt-0.5">
            Average hold time &bull; {totalClosed} closed trade{totalClosed !== 1 ? "s" : ""}
          </p>
        </div>

        {/* Fastest / Slowest */}
        <div className="grid grid-cols-2 gap-3">
          <div className="rounded-lg border border-border bg-muted/10 px-3 py-2.5 space-y-1">
            <div className="flex items-center gap-1.5 text-[10px] text-muted-foreground uppercase tracking-wider">
              <Zap className="h-3 w-3" />
              Fastest
            </div>
            <p className="font-mono font-bold tabular-nums text-green-400">
              {formatDuration(fastestMinutes)}
            </p>
            <p className="text-[10px] text-muted-foreground">{fastestSymbol}</p>
          </div>
          <div className="rounded-lg border border-border bg-muted/10 px-3 py-2.5 space-y-1">
            <div className="flex items-center gap-1.5 text-[10px] text-muted-foreground uppercase tracking-wider">
              <Timer className="h-3 w-3" />
              Slowest
            </div>
            <p className="font-mono font-bold tabular-nums text-yellow-400">
              {formatDuration(slowestMinutes)}
            </p>
            <p className="text-[10px] text-muted-foreground">{slowestSymbol}</p>
          </div>
        </div>

        {/* Distribution buckets */}
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <p className="text-xs text-muted-foreground">Hold Time Distribution</p>
            <div className="flex items-center gap-3 text-[10px] text-muted-foreground">
              <span>WR = Win Rate</span>
              <span>P&amp;L = Total</span>
            </div>
          </div>
          {bucketOrder.map((key) => (
            <BucketRow key={key} bucket={buckets[key]} maxCount={maxCount} />
          ))}
        </div>

        {/* Win rate by bucket summary */}
        <div className="grid grid-cols-4 gap-2 border-t border-border pt-3">
          {bucketOrder.map((key) => {
            const b = buckets[key];
            const wr = b.count > 0 ? (b.wins / b.count) * 100 : null;
            const wrColor =
              wr === null
                ? "text-muted-foreground"
                : wr >= 50
                ? "text-green-400"
                : "text-red-400";
            return (
              <div key={key} className="text-center space-y-0.5">
                <p className="text-[10px] text-muted-foreground">{b.label}</p>
                <p className={`text-sm font-mono font-bold tabular-nums ${wrColor}`}>
                  {wr !== null ? `${wr.toFixed(0)}%` : "—"}
                </p>
                <div className="flex items-center justify-center gap-0.5">
                  <TrendingUp className="h-2.5 w-2.5 text-muted-foreground" />
                  <p className="text-[10px] text-muted-foreground">{b.count} trades</p>
                </div>
              </div>
            );
          })}
        </div>

        {/* Footer */}
        <div className="space-y-1">
          <p className="text-xs text-muted-foreground">
            Auto-refreshes every 60s
          </p>
          {caveat && (
            <p className="text-[10px] text-muted-foreground flex items-center gap-1">
              <Info className="h-3 w-3 shrink-0" />
              {caveat}
            </p>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
