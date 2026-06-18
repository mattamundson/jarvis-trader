"use client";

import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { type HonestTrade } from "@/lib/honestTrades";
import { useHonestTrades } from "@/lib/useHonestTrades";


// RTH hours to display (8 AM through 3 PM CT)
const RTH_HOURS = [8, 9, 10, 11, 12, 13, 14, 15];

const HOUR_LABELS: Record<number, string> = {
  8: "8A",
  9: "9A",
  10: "10A",
  11: "11A",
  12: "12P",
  13: "1P",
  14: "2P",
  15: "3P",
};

interface HourBucket {
  count: number;
  wins: number;
  totalPnl: number;
}

type HourMap = Map<number, HourBucket>;

function buildHourMap(trades: HonestTrade[]): HourMap {
  const map: HourMap = new Map();

  for (const trade of trades) {
    // Guard null entry_time
    if (!trade.entry_time) continue;

    const hour = new Date(trade.entry_time).getHours();
    const existing = map.get(hour) ?? { count: 0, wins: 0, totalPnl: 0 };
    existing.count++;
    if (trade.pnl > 0) existing.wins++;
    existing.totalPnl += trade.pnl;
    map.set(hour, existing);
  }

  return map;
}

function barColor(winRate: number): string {
  if (winRate >= 0.6) return "#22c55e"; // green
  if (winRate >= 0.4) return "#eab308"; // yellow
  return "#ef4444";                      // red
}

function formatHourLabel(hour: number): string {
  if (hour === 0) return "12AM";
  if (hour < 12) return `${hour}AM`;
  if (hour === 12) return "12PM";
  return `${hour - 12}PM`;
}

// SVG bar chart — viewBox="0 0 420 100"
// 8 bars for hours 8–15, with x-axis labels
const CHART_W = 420;
const CHART_H = 100;
const BAR_AREA_H = 72; // height available for bars
const LABEL_Y = 94;    // y position for x-axis labels
const BAR_GAP = 4;
const BAR_COUNT = RTH_HOURS.length; // 8
const BAR_WIDTH = (CHART_W - BAR_GAP * (BAR_COUNT + 1)) / BAR_COUNT;

interface SvgBarChartProps {
  hourMap: HourMap;
  maxCount: number;
}

function SvgBarChart({ hourMap, maxCount }: SvgBarChartProps) {
  return (
    <svg
      viewBox={`0 0 ${CHART_W} ${CHART_H}`}
      className="w-full"
      aria-label="Trade distribution by hour"
    >
      {RTH_HOURS.map((hour, idx) => {
        const bucket = hourMap.get(hour);
        const count = bucket?.count ?? 0;
        const winRate = count > 0 ? (bucket?.wins ?? 0) / count : 0;
        const barH = maxCount > 0 ? Math.max(2, (count / maxCount) * BAR_AREA_H) : 2;
        const x = BAR_GAP + idx * (BAR_WIDTH + BAR_GAP);
        const y = BAR_AREA_H - barH;
        const fill = count > 0 ? barColor(winRate) : "rgba(255,255,255,0.08)";

        return (
          <g key={hour}>
            {/* Bar */}
            <rect
              x={x}
              y={y}
              width={BAR_WIDTH}
              height={barH}
              fill={fill}
              rx={2}
              opacity={count === 0 ? 0.35 : 1}
            />
            {/* Trade count label above bar */}
            {count > 0 && (
              <text
                x={x + BAR_WIDTH / 2}
                y={y - 3}
                textAnchor="middle"
                fontSize="8"
                fill="rgba(255,255,255,0.55)"
              >
                {count}
              </text>
            )}
            {/* X-axis label */}
            <text
              x={x + BAR_WIDTH / 2}
              y={LABEL_Y}
              textAnchor="middle"
              fontSize="9"
              fill="rgba(255,255,255,0.45)"
            >
              {HOUR_LABELS[hour]}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

interface StatCellProps {
  label: string;
  value: string;
  valueClass?: string;
}

function StatCell({ label, value, valueClass = "text-foreground" }: StatCellProps) {
  return (
    <div className="rounded-lg border border-border/50 bg-background/20 px-4 py-3 flex flex-col gap-1">
      <p className="text-xs text-muted-foreground uppercase tracking-wider">{label}</p>
      <p className={`text-sm font-semibold font-mono tabular-nums ${valueClass}`}>{value}</p>
    </div>
  );
}

export function TradeHourlyBreakdownWidget() {
  const { honest: set, isLoading: loading, error: loadError } = useHonestTrades(300_000);
  const error = loadError ? (loadError instanceof Error ? loadError.message : String(loadError)) : null;

  // Compute RTH aggregates from the trade set
  const hourMap: HourMap = set ? buildHourMap(set.trades) : new Map();

  let totalRthTrades = 0;
  let rthWins = 0;
  let maxCount = 1;
  let bestHour: number | null = null;
  let bestWinRate = -1;

  for (const hour of RTH_HOURS) {
    const bucket = hourMap.get(hour);
    if (!bucket) continue;
    totalRthTrades += bucket.count;
    rthWins += bucket.wins;
    if (bucket.count > maxCount) maxCount = bucket.count;

    const wr = bucket.count > 0 ? bucket.wins / bucket.count : 0;
    if (bucket.count >= 2 && wr > bestWinRate) {
      bestWinRate = wr;
      bestHour = hour;
    }
  }

  const insufficient = totalRthTrades < 5;

  const rthWinRate = totalRthTrades > 0 ? rthWins / totalRthTrades : 0;

  const winRateBadge = (): "bull" | "warn" | "bear" => {
    if (rthWinRate >= 0.6) return "bull";
    if (rthWinRate >= 0.4) return "warn";
    return "bear";
  };

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between flex-wrap gap-2">
          <CardTitle>Trade Distribution by Hour (CT)</CardTitle>
          <div className="flex items-center gap-2">
            <Badge variant="info">8:30AM–3:15PM CT</Badge>
            {!loading && !error && !insufficient && totalRthTrades > 0 && (
              <Badge variant={winRateBadge()}>
                {(rthWinRate * 100).toFixed(0)}% RTH Win
              </Badge>
            )}
          </div>
        </div>
      </CardHeader>

      <CardContent>
        {loading && (
          <p className="text-xs text-muted-foreground animate-pulse">
            Loading trade history…
          </p>
        )}

        {!loading && error && (
          <p className="text-xs text-red-400">Error: {error}</p>
        )}

        {!loading && !error && insufficient && (
          <p className="text-xs text-muted-foreground">
            Not enough RTH trade data yet (need at least 5 closed RTH trades).
          </p>
        )}

        {!loading && !error && !insufficient && (
          <div className="space-y-4">
            {/* SVG bar chart */}
            <div className="pt-1">
              <SvgBarChart hourMap={hourMap} maxCount={maxCount} />
            </div>

            {/* Color legend */}
            <div className="flex items-center gap-4 text-xs text-muted-foreground">
              <span className="flex items-center gap-1">
                <span className="inline-block w-2.5 h-2.5 rounded-sm bg-green-500" />
                {">= 60% win"}
              </span>
              <span className="flex items-center gap-1">
                <span className="inline-block w-2.5 h-2.5 rounded-sm bg-yellow-500" />
                {"40–59% win"}
              </span>
              <span className="flex items-center gap-1">
                <span className="inline-block w-2.5 h-2.5 rounded-sm bg-red-500" />
                {"< 40% win"}
              </span>
            </div>

            {/* Best hour callout */}
            {bestHour !== null && (
              <p className="text-xs text-muted-foreground">
                Best:{" "}
                <span className="text-foreground font-medium">
                  {formatHourLabel(bestHour)}
                </span>{" "}
                ({(bestWinRate * 100).toFixed(0)}% win rate,{" "}
                {hourMap.get(bestHour)?.count ?? 0} trades)
              </p>
            )}

            {/* Stats row */}
            <div className="grid grid-cols-3 gap-3">
              <StatCell
                label="RTH Trades"
                value={String(totalRthTrades)}
                valueClass="text-foreground"
              />
              <StatCell
                label="RTH Win Rate"
                value={`${(rthWinRate * 100).toFixed(1)}%`}
                valueClass={
                  rthWinRate >= 0.6
                    ? "text-green-400"
                    : rthWinRate >= 0.4
                    ? "text-yellow-400"
                    : "text-red-400"
                }
              />
              <StatCell
                label="Best Hour"
                value={bestHour !== null ? formatHourLabel(bestHour) : "—"}
                valueClass="text-accent"
              />
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default TradeHourlyBreakdownWidget;
