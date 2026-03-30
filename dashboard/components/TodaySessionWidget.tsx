"use client";

import React, { useState, useEffect } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

const ENGINE_URL = process.env.NEXT_PUBLIC_ENGINE_URL || "http://localhost:8010";

interface TradeRecord {
  id: number;
  symbol: string;
  side: "BUY" | "SELL";
  realized_pnl: number | null;
  status: "OPEN" | "CLOSED" | "CANCELLED";
  entry_time: string;
  exit_time: string | null;
  notes: string | null;
}

interface SessionStats {
  session_pnl: number;
  open_trades: number;
  closed_trades: number;
  wins: number;
  losses: number;
  win_rate: number;
  best_trade: number | null;
  worst_trade: number | null;
  today_trades: TradeRecord[];
}

function getTodayDate(): string {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function formatPnl(val: number): string {
  const abs = Math.abs(val).toFixed(2);
  return val >= 0 ? `+$${abs}` : `-$${abs}`;
}

function formatTime(isoStr: string): string {
  const d = new Date(isoStr);
  const h = String(d.getHours()).padStart(2, "0");
  const min = String(d.getMinutes()).padStart(2, "0");
  return `${h}:${min}`;
}

function computeStats(trades: TradeRecord[]): SessionStats {
  const today = getTodayDate();

  const todayTrades = trades.filter((t) => {
    if (!t.entry_time) return false;
    return t.entry_time.slice(0, 10) === today;
  });

  const closedTrades = todayTrades.filter((t) => t.status === "CLOSED");
  const openTrades = todayTrades.filter((t) => t.status === "OPEN");

  const session_pnl = closedTrades.reduce(
    (sum, t) => sum + (t.realized_pnl ?? 0),
    0
  );

  const wins = closedTrades.filter((t) => (t.realized_pnl ?? 0) > 0);
  const losses = closedTrades.filter((t) => (t.realized_pnl ?? 0) <= 0);

  const win_rate =
    closedTrades.length > 0
      ? (wins.length / closedTrades.length) * 100
      : 0;

  const pnlValues = closedTrades
    .map((t) => t.realized_pnl ?? 0)
    .filter((_, i) => closedTrades[i].realized_pnl !== null);

  const best_trade = pnlValues.length > 0 ? Math.max(...pnlValues) : null;
  const worst_trade = pnlValues.length > 0 ? Math.min(...pnlValues) : null;

  // Sort most recent first, take top 5
  const sorted = [...todayTrades].sort(
    (a, b) =>
      new Date(b.entry_time).getTime() - new Date(a.entry_time).getTime()
  );
  const today_trades = sorted.slice(0, 5);

  return {
    session_pnl,
    open_trades: openTrades.length,
    closed_trades: closedTrades.length,
    wins: wins.length,
    losses: losses.length,
    win_rate,
    best_trade,
    worst_trade,
    today_trades,
  };
}

function DayBadge({ stats }: { stats: SessionStats }) {
  if (stats.session_pnl > 0) {
    return <Badge variant="bull">WINNING DAY</Badge>;
  }
  if (stats.session_pnl < 0) {
    return <Badge variant="bear">LOSING DAY</Badge>;
  }
  if (stats.open_trades > 0 && stats.session_pnl === 0) {
    return <Badge variant="info">OPEN TRADES</Badge>;
  }
  return <Badge variant="neutral">NO TRADES</Badge>;
}

export function TodaySessionWidget() {
  const [trades, setTrades] = useState<TradeRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  async function fetchTrades() {
    try {
      const res = await fetch(
        `${ENGINE_URL}/portfolio/history/trades?limit=100`
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      const raw: TradeRecord[] = Array.isArray(json)
        ? json
        : Array.isArray(json.trades)
        ? json.trades
        : [];
      setTrades(raw);
      setError(false);
      setLastUpdated(new Date());
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchTrades();
    const interval = setInterval(fetchTrades, 30_000);
    return () => clearInterval(interval);
  }, []);

  if (loading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="font-mono text-xs tracking-widest uppercase text-muted-foreground">
            Today&apos;s Session
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-3 animate-pulse">
            <div className="h-10 w-40 rounded bg-muted" />
            <div className="h-4 w-32 rounded bg-muted" />
            <div className="h-4 w-full rounded bg-muted" />
            <div className="h-4 w-3/4 rounded bg-muted" />
          </div>
        </CardContent>
      </Card>
    );
  }

  if (error) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="font-mono text-xs tracking-widest uppercase text-muted-foreground">
            Today&apos;s Session
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-destructive font-mono">
            Session data unavailable
          </p>
        </CardContent>
      </Card>
    );
  }

  const stats = computeStats(trades);
  const hasTodayTrades =
    stats.open_trades > 0 || stats.closed_trades > 0;

  const pnlColor =
    stats.session_pnl > 0
      ? "text-bull"
      : stats.session_pnl < 0
      ? "text-bear"
      : "text-muted-foreground";

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="font-mono text-xs tracking-widest uppercase text-muted-foreground">
            Today&apos;s Session
          </CardTitle>
          <DayBadge stats={stats} />
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* Large P&L */}
        <div>
          <p
            className={`text-4xl font-bold tabular-nums tracking-tight font-mono ${pnlColor}`}
          >
            {stats.session_pnl >= 0
              ? `+$${stats.session_pnl.toFixed(2)}`
              : `-$${Math.abs(stats.session_pnl).toFixed(2)}`}
          </p>
          <p className="text-xs text-muted-foreground font-mono mt-1">
            Today&apos;s Session P&L
            {lastUpdated && (
              <span className="ml-2 text-muted-foreground/50">
                · updated {formatTime(lastUpdated.toISOString())}
              </span>
            )}
          </p>
        </div>

        {/* 4 mini stats */}
        <div className="grid grid-cols-4 gap-2">
          {[
            { label: "Trades", value: stats.open_trades + stats.closed_trades },
            { label: "Open", value: stats.open_trades },
            { label: "Wins", value: stats.wins },
            { label: "Losses", value: stats.losses },
          ].map(({ label, value }) => (
            <div
              key={label}
              className="rounded-lg border border-border bg-muted/30 px-3 py-2 text-center"
            >
              <p className="font-mono text-lg font-bold tabular-nums text-foreground">
                {value}
              </p>
              <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                {label}
              </p>
            </div>
          ))}
        </div>

        {/* Win rate bar */}
        <div>
          <div className="flex items-center justify-between mb-1.5">
            <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
              Win Rate
            </span>
            <span className="font-mono text-xs font-semibold text-foreground tabular-nums">
              {stats.win_rate.toFixed(1)}%
            </span>
          </div>
          <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
            <div
              className="h-full rounded-full bg-bull transition-all duration-500"
              style={{ width: `${Math.min(stats.win_rate, 100)}%` }}
            />
          </div>
        </div>

        {/* Best / Worst trade */}
        <div className="flex items-center gap-2 font-mono text-xs">
          <span className="text-muted-foreground">Best / Worst:</span>
          <span className="text-bull font-semibold tabular-nums">
            {stats.best_trade !== null ? formatPnl(stats.best_trade) : "—"}
          </span>
          <span className="text-muted-foreground">/</span>
          <span className="text-bear font-semibold tabular-nums">
            {stats.worst_trade !== null ? formatPnl(stats.worst_trade) : "—"}
          </span>
        </div>

        {/* Separator */}
        <div className="border-t border-border" />

        {/* Trade list or empty state */}
        {!hasTodayTrades ? (
          <div className="flex items-center gap-2 py-3 text-muted-foreground font-mono text-sm">
            <span>🕐</span>
            <span>No trades today — session not yet started</span>
          </div>
        ) : (
          <div className="space-y-1">
            <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground mb-2">
              Recent Trades (Today)
            </p>
            {stats.today_trades.map((t) => {
              const pnl = t.realized_pnl;
              const pnlStr =
                pnl !== null
                  ? pnl >= 0
                    ? `+$${pnl.toFixed(2)}`
                    : `-$${Math.abs(pnl).toFixed(2)}`
                  : "—";
              const pnlClass =
                pnl === null
                  ? "text-muted-foreground"
                  : pnl > 0
                  ? "text-bull"
                  : "text-bear";

              return (
                <div
                  key={t.id}
                  className="flex items-center justify-between rounded-lg bg-muted/20 px-3 py-2 font-mono text-xs"
                >
                  <div className="flex items-center gap-2 min-w-0">
                    <span className="font-semibold text-foreground shrink-0">
                      {t.symbol}
                    </span>
                    <Badge variant={t.side === "BUY" ? "bull" : "bear"}>
                      {t.side}
                    </Badge>
                    <span
                      className={`text-[10px] uppercase tracking-wide ${
                        t.status === "OPEN"
                          ? "text-info"
                          : t.status === "CLOSED"
                          ? "text-muted-foreground"
                          : "text-warn"
                      }`}
                    >
                      {t.status}
                    </span>
                  </div>
                  <div className="flex items-center gap-3 shrink-0">
                    <span className={`tabular-nums font-semibold ${pnlClass}`}>
                      {pnlStr}
                    </span>
                    <span className="tabular-nums text-muted-foreground/70">
                      {formatTime(t.entry_time)}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
