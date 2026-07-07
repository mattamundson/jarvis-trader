"use client";

import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { RawRecordBadge } from "@/components/RawRecordBadge";
import { StalenessIndicator } from "@/components/ui/staleness-indicator";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { fetchEngine } from "@/lib/api";


// ── Types ────────────────────────────────────────────────────────────────────

interface SessionTodayResponse {
  date: string;
  session: string;
  closed_trades: number;
  open_trades: number;
  gross_pnl: number;
  wins: number;
  losses: number;
  win_rate: number | null;
  best_trade: number | null;
  worst_trade: number | null;
  avg_pnl: number | null;
  symbols_traded: string[];
  last_updated: string;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function sessionBadgeVariant(
  session: string
): "bull" | "bear" | "warn" | "info" | "neutral" {
  const s = session.toUpperCase();
  if (s === "RTH") return "bull";
  if (s === "EXTENDED") return "info";
  return "neutral";
}

function formatPnl(value: number): string {
  const sign = value >= 0 ? "+" : "";
  return `${sign}$${value.toFixed(2)}`;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function TodaySummaryWidget() {
  const [data, setData] = useState<SessionTodayResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const fetchData = async () => {
    try {
      const json = await fetchEngine(`/portfolio/stats/session-today`);
      setData(json);
      setError(null);
      setLastUpdated(new Date());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to fetch session data");
    }
  };

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 120_000);
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const hasTrades = data !== null && data.closed_trades > 0;
  const winRate =
    data?.win_rate != null && data.closed_trades >= 2
      ? `${(data.win_rate * 100).toFixed(1)}%`
      : "N/A";

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3">
        <CardTitle className="text-sm font-semibold">Today&apos;s Session</CardTitle>
        <div className="flex items-center gap-2">
          <RawRecordBadge />
          {data ? (
            <Badge variant={sessionBadgeVariant(data.session)}>
              {data.session}
            </Badge>
          ) : (
            <Badge variant="neutral">—</Badge>
          )}
        </div>
      </CardHeader>

      <CardContent>
        {error && (
          <p className="text-xs text-destructive mb-3">{error}</p>
        )}

        {!data && !error && (
          <p className="text-sm text-muted-foreground text-center py-6">
            Loading session data...
          </p>
        )}

        {data && !hasTrades && (
          <div className="flex flex-col items-center gap-2 py-6">
            <Badge variant="neutral">No trades yet today</Badge>
            <p className="text-xs text-muted-foreground">{data.date}</p>
          </div>
        )}

        {data && hasTrades && (
          <div className="grid grid-cols-3 gap-3">
            {/* Trades */}
            <div className="rounded-lg border border-border bg-muted/30 p-3 text-center">
              <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">
                Trades
              </p>
              <p className="font-mono text-lg font-bold tabular-nums">
                {data.closed_trades}
              </p>
            </div>

            {/* P&L */}
            <div className="rounded-lg border border-border bg-muted/30 p-3 text-center">
              <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">
                P&amp;L
              </p>
              <p
                className="font-mono text-lg font-bold tabular-nums"
                style={{
                  color:
                    data.gross_pnl > 0
                      ? "#00ff88"
                      : data.gross_pnl < 0
                      ? "#ff4444"
                      : undefined,
                }}
              >
                {formatPnl(data.gross_pnl)}
              </p>
            </div>

            {/* Win Rate */}
            <div className="rounded-lg border border-border bg-muted/30 p-3 text-center">
              <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">
                Win Rate
              </p>
              <p className="font-mono text-lg font-bold tabular-nums">
                {winRate}
              </p>
            </div>
          </div>
        )}

        {data && hasTrades && (
          <p className="text-[10px] text-muted-foreground/70 mt-2">
            P&amp;L, trades &amp; win-rate from the raw session record — may include
            re-logged duplicates. See the deduped stats widgets for the honest figure.
          </p>
        )}

        <div className="flex items-center gap-2 mt-3">
          {lastUpdated && <StalenessIndicator lastUpdated={lastUpdated} />}
          <p className="text-xs text-muted-foreground">Refreshes every 2 min</p>
        </div>
      </CardContent>
    </Card>
  );
}
