import { TrendingUp, TrendingDown, Minus } from "lucide-react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { formatCurrency, formatPercent } from "@/lib/utils";
import type { Position } from "@/lib/api";

interface PositionsPanelProps {
  positions: Position[];
  totalEquity: number;
  dailyPnl: number;
  unrealizedPnl: number;
}

export function PositionsPanel({
  positions,
  totalEquity,
  dailyPnl,
  unrealizedPnl,
}: PositionsPanelProps) {
  const dailyPct = totalEquity > 0 ? (dailyPnl / totalEquity) * 100 : 0;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>Positions</CardTitle>
          <div className="text-right">
            <p className="text-xl font-bold tabular-nums text-foreground">
              {formatCurrency(totalEquity)}
            </p>
            <p
              className={`text-xs tabular-nums ${
                dailyPnl >= 0 ? "text-bull" : "text-bear"
              }`}
            >
              {formatCurrency(dailyPnl)} ({formatPercent(dailyPct)}) today
            </p>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {positions.length === 0 ? (
          <p className="text-center text-sm text-muted-foreground py-6">
            No open positions
          </p>
        ) : (
          <ul className="space-y-2" role="list">
            {positions.map((pos) => (
              <li key={pos.symbol}>
                <PositionRow position={pos} />
              </li>
            ))}
          </ul>
        )}
        {unrealizedPnl !== 0 && (
          <div className="mt-3 flex justify-between border-t border-border pt-3 text-xs">
            <span className="text-muted-foreground">Unrealized P&L</span>
            <span className={`tabular-nums font-medium ${unrealizedPnl >= 0 ? "text-bull" : "text-bear"}`}>
              {formatCurrency(unrealizedPnl)}
            </span>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function PositionRow({ position: pos }: { position: Position }) {
  const Icon =
    pos.unrealized_pnl > 0
      ? TrendingUp
      : pos.unrealized_pnl < 0
      ? TrendingDown
      : Minus;

  const pnlStatus = pos.unrealized_pnl > 0 ? "profit" : pos.unrealized_pnl < 0 ? "loss" : "neutral";
  const positionType = pos.quantity > 0 ? "LONG" : "SHORT";

  return (
    <div
      className="flex items-center justify-between rounded-lg bg-muted/40 px-3 py-2"
      role="listitem"
      aria-label={`${pos.symbol} ${positionType} position with ${pnlStatus} P&L of ${formatCurrency(pos.unrealized_pnl)}`}
    >
      <div className="flex items-center gap-2">
        <Icon
          className={`h-4 w-4 ${
            pos.unrealized_pnl > 0
              ? "text-bull"
              : pos.unrealized_pnl < 0
              ? "text-bear"
              : "text-muted-foreground"
          }`}
          aria-label={pnlStatus}
        />
        <div>
          <div className="flex items-center gap-1.5">
            <span className="font-mono text-sm font-semibold">{pos.symbol}</span>
            {pos.is_futures && (
              <Badge variant="info">FUTURES</Badge>
            )}
          </div>
          <p className="text-xs text-muted-foreground">
            {pos.quantity > 0 ? "LONG" : "SHORT"} {Math.abs(pos.quantity)} ×{" "}
            {formatCurrency(pos.avg_cost)}
          </p>
        </div>
      </div>
      <div className="text-right">
        <p
          className={`tabular-nums text-sm font-medium ${
            pos.unrealized_pnl >= 0 ? "text-bull" : "text-bear"
          }`}
        >
          {formatCurrency(pos.unrealized_pnl)}
        </p>
        <p
          className={`tabular-nums text-xs ${
            pos.unrealized_pnl_pct >= 0 ? "text-bull" : "text-bear"
          }`}
        >
          {formatPercent(pos.unrealized_pnl_pct)}
        </p>
      </div>
    </div>
  );
}
