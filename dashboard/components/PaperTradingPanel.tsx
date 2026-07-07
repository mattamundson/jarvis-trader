"use client";

import useSWR from "swr";
import { TrendingUp, TrendingDown, FlaskConical } from "lucide-react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchEngine } from "@/lib/api";
import type { PaperPosition, PaperPerformance } from "@/lib/api";
import { formatCurrency } from "@/lib/utils";

const POLL_MS = 30_000;

function fetcher<T>(url: string): Promise<T> {
  return fetchEngine<T>(url);
}

export function PaperTradingPanel() {
  const { data: perfData } = useSWR<PaperPerformance | { performance: PaperPerformance }>(
    "/portfolio/paper/performance",
    fetcher,
    { refreshInterval: POLL_MS, shouldRetryOnError: false }
  );
  const performance: PaperPerformance | undefined = perfData
    ? "performance" in perfData
      ? (perfData as { performance: PaperPerformance }).performance
      : (perfData as PaperPerformance)
    : undefined;

  const { data: positionsData } = useSWR<{ positions: PaperPosition[]; count: number }>(
    "/portfolio/paper/positions",
    fetcher,
    { refreshInterval: POLL_MS, shouldRetryOnError: false }
  );
  const positions = Array.isArray(positionsData)
    ? positionsData
    : positionsData?.positions ?? [];

  const sessionNotStarted =
    !performance ||
    (performance.total_pnl === 0 && performance.num_trades === 0);

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <FlaskConical className="h-4 w-4 text-muted-foreground" />
            <CardTitle>Paper Trading</CardTitle>
          </div>
          <Badge variant="bull">ACTIVE</Badge>
        </div>
        {/*
          Labeling for the two-scoreboard discrepancy: this card reads the
          engine's own /portfolio/paper/performance (its local trade_history
          DB, raw rows -- can include re-logged winners). The "Realized
          record (deduped)" card reads master-api's read-time-deduped ledger,
          a different pipeline with a different trade count. Both are real;
          they are not computing the same universe, so they will not agree.
        */}
        <p className="mt-1 text-[11px] text-muted-foreground">
          Engine trade_history (raw, may include re-logged rows) — see{" "}
          <span className="font-medium">Realized record (deduped)</span> for
          the deduplicated scoreboard.
        </p>
      </CardHeader>

      <CardContent className="space-y-4">
        {sessionNotStarted ? (
          <p className="text-center text-sm text-muted-foreground py-4">
            Paper trading session not started
          </p>
        ) : (
          <>
            {/* Performance row */}
            {performance && (
              <div className="grid grid-cols-4 gap-2">
                <PerfStat
                  label="P&L"
                  value={formatCurrency(performance.total_pnl)}
                  colorClass={
                    performance.total_pnl >= 0 ? "text-bull" : "text-bear"
                  }
                />
                <PerfStat
                  label="Win Rate"
                  value={`${(performance.win_rate * 100).toFixed(1)}%`}
                  colorClass="text-foreground"
                />
                <PerfStat
                  label="Prof. Factor"
                  value={
                    performance.profit_factor != null && isFinite(performance.profit_factor)
                      ? performance.profit_factor.toFixed(2)
                      : "—"
                  }
                  colorClass={
                    performance.profit_factor == null
                      ? "text-muted-foreground"
                      : performance.profit_factor >= 1.5
                      ? "text-bull"
                      : performance.profit_factor >= 1
                      ? "text-warn"
                      : "text-bear"
                  }
                />
                <PerfStat
                  label="Trades"
                  value={String(performance.num_trades)}
                  colorClass="text-foreground"
                />
              </div>
            )}

            {/* Divider */}
            <div className="border-t border-border" />

            {/* Positions table */}
            {!positions || positions.length === 0 ? (
              <p className="text-center text-sm text-muted-foreground py-3">
                No open positions — engine watching for signals
              </p>
            ) : (
              <div className="space-y-1">
                {/* Table header */}
                <div className="grid grid-cols-[1fr_80px_60px_90px_1fr_90px] gap-2 px-2 pb-1">
                  {["Symbol", "Direction", "Qty", "Entry $", "Entry Time", "Unr. P&L"].map(
                    (h) => (
                      <span
                        key={h}
                        className="font-mono text-[10px] font-semibold uppercase tracking-wider text-muted-foreground"
                      >
                        {h}
                      </span>
                    )
                  )}
                </div>

                {/* Rows */}
                {positions.map((pos) => (
                  <PositionRow key={pos.trade_id} pos={pos} />
                ))}
              </div>
            )}

            {/* Avg win/loss footer */}
            {performance &&
              (performance.avg_win !== 0 || performance.avg_loss !== 0) && (
                <div className="flex items-center justify-end gap-4 border-t border-border pt-3 text-xs">
                  <span className="text-muted-foreground">
                    Avg win:{" "}
                    <span className="tabular-nums text-bull">
                      {formatCurrency(performance.avg_win)}
                    </span>
                  </span>
                  <span className="text-muted-foreground">
                    Avg loss:{" "}
                    <span className="tabular-nums text-bear">
                      {formatCurrency(performance.avg_loss)}
                    </span>
                  </span>
                  {performance.max_dd !== 0 && (
                    <span className="text-muted-foreground">
                      Max DD:{" "}
                      <span className="tabular-nums text-bear">
                        {/*
                          performance.max_dd is a raw dollar figure from the
                          engine's /portfolio/paper/performance (equity-peak
                          minus trough in $, e.g. -1981.70) -- not a fraction.
                          formatPercent(x * 100) previously treated it as a
                          0..1 ratio and rendered "-198170.35%". Render as
                          currency instead.
                        */}
                        {formatCurrency(performance.max_dd)}
                      </span>
                    </span>
                  )}
                </div>
              )}
          </>
        )}
      </CardContent>
    </Card>
  );
}

// ── Sub-components ────────────────────────────────────────────────────────────

function PerfStat({
  label,
  value,
  colorClass,
}: {
  label: string;
  value: string;
  colorClass: string;
}) {
  return (
    <div className="rounded-lg bg-muted/40 px-3 py-2 text-center">
      <p className="font-mono text-[10px] text-muted-foreground uppercase tracking-wider mb-0.5">
        {label}
      </p>
      <p className={`font-mono text-sm font-bold tabular-nums ${colorClass}`}>
        {value}
      </p>
    </div>
  );
}

function PositionRow({ pos }: { pos: PaperPosition }) {
  const isLong =
    (pos.action ?? "").toLowerCase() === "buy" ||
    (pos.action ?? "").toLowerCase() === "long";

  const entryTime = (() => {
    try {
      return new Date(pos.entry_time).toLocaleString("en-US", {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch {
      return pos.entry_time;
    }
  })();

  return (
    <div className="grid grid-cols-[1fr_80px_60px_90px_1fr_90px] gap-2 items-center rounded-lg bg-muted/30 px-2 py-2 hover:bg-muted/50 transition-colors">
      {/* Symbol */}
      <span className="font-mono text-sm font-semibold text-foreground">
        {pos.symbol}
      </span>

      {/* Direction */}
      <div className="flex items-center gap-1">
        {isLong ? (
          <TrendingUp className="h-3.5 w-3.5 text-bull shrink-0" />
        ) : (
          <TrendingDown className="h-3.5 w-3.5 text-bear shrink-0" />
        )}
        <span
          className={`font-mono text-xs font-semibold uppercase ${
            isLong ? "text-bull" : "text-bear"
          }`}
        >
          {isLong ? "LONG" : "SHORT"}
        </span>
      </div>

      {/* Qty */}
      <span className="font-mono text-xs tabular-nums text-foreground">
        {pos.quantity}
      </span>

      {/* Entry price */}
      <span className="font-mono text-xs tabular-nums text-foreground">
        {formatCurrency(pos.entry_price)}
      </span>

      {/* Entry time */}
      <span className="font-mono text-xs text-muted-foreground">
        {entryTime}
      </span>

      {/* Unrealized P&L — no live price available, show dash */}
      <span className="font-mono text-xs tabular-nums text-muted-foreground text-right">
        —
      </span>
    </div>
  );
}
