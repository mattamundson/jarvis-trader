"use client";

import { useEffect, useState } from "react";
import { RefreshCw, TrendingUp } from "lucide-react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchEngine } from "@/lib/api";


// ── Types ─────────────────────────────────────────────────────────────────────

interface TradeRecord {
  id: number;
  symbol: string;
  side: "BUY" | "SELL";
  realized_pnl: number | null;
  status: "OPEN" | "CLOSED" | "CANCELLED";
  entry_time: string;
  exit_time: string | null;
}

interface SymbolStats {
  symbol: string;
  total_trades: number;
  wins: number;
  losses: number;
  win_rate: number;
  total_pnl: number;
  avg_pnl: number;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmt$(value: number): string {
  const abs = Math.abs(value);
  const sign = value >= 0 ? "+" : "-";
  return `${sign}$${abs.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function pnlColor(value: number): string {
  if (value > 0) return "#00ff88";
  if (value < 0) return "#ff4444";
  return "#888888";
}

function barColor(winRate: number): string {
  if (winRate >= 55) return "#00ff88";
  if (winRate >= 40) return "#ffcc00";
  return "#ff4444";
}

function winRateBadgeVariant(winRate: number): "bull" | "warn" | "bear" {
  if (winRate >= 55) return "bull";
  if (winRate >= 40) return "warn";
  return "bear";
}

function aggregateBySymbol(trades: TradeRecord[]): SymbolStats[] {
  const map = new Map<
    string,
    { wins: number; losses: number; total_pnl: number; count: number }
  >();

  for (const t of trades) {
    const sym = (t.symbol ?? "UNKNOWN").toUpperCase();
    const pnl = typeof t.realized_pnl === "number" ? t.realized_pnl : 0;
    const existing = map.get(sym) ?? {
      wins: 0,
      losses: 0,
      total_pnl: 0,
      count: 0,
    };
    existing.count += 1;
    existing.total_pnl += pnl;
    if (pnl > 0) {
      existing.wins += 1;
    } else {
      existing.losses += 1;
    }
    map.set(sym, existing);
  }

  return Array.from(map.entries())
    .map(([symbol, v]) => ({
      symbol,
      total_trades: v.count,
      wins: v.wins,
      losses: v.losses,
      win_rate: v.count > 0 ? (v.wins / v.count) * 100 : 0,
      total_pnl: v.total_pnl,
      avg_pnl: v.count > 0 ? v.total_pnl / v.count : 0,
    }))
    .sort((a, b) => b.total_trades - a.total_trades);
}

// ── Loading skeleton ──────────────────────────────────────────────────────────

function SkeletonRow() {
  return (
    <div
      className="grid grid-cols-12 gap-3 items-center py-3 animate-pulse"
      style={{ borderBottom: "1px solid #111" }}
    >
      <div className="col-span-2 h-3 rounded" style={{ backgroundColor: "#1a1a2e" }} />
      <div className="col-span-4 h-2 rounded-full" style={{ backgroundColor: "#1a1a2e" }} />
      <div className="col-span-2 h-3 rounded" style={{ backgroundColor: "#1a1a2e" }} />
      <div className="col-span-2 h-3 rounded" style={{ backgroundColor: "#1a1a2e" }} />
      <div className="col-span-2 h-5 rounded-full" style={{ backgroundColor: "#1a1a2e" }} />
    </div>
  );
}

// ── Symbol row ────────────────────────────────────────────────────────────────

function SymbolRow({ row }: { row: SymbolStats }) {
  const color = barColor(row.win_rate);
  return (
    <div
      className="grid grid-cols-12 gap-3 items-center py-3 hover:bg-white/[0.02] transition-colors"
      style={{ borderBottom: "1px solid #111" }}
    >
      {/* Symbol name */}
      <div className="col-span-2">
        <span className="font-mono text-xs font-bold" style={{ color: "#e0e0e0" }}>
          {row.symbol}
        </span>
      </div>

      {/* Win rate bar + percentage */}
      <div className="col-span-4 flex items-center gap-2">
        <div className="h-2 bg-muted rounded-full flex-1 min-w-0">
          <div
            className="h-2 rounded-full transition-all duration-500"
            style={{
              width: `${Math.min(row.win_rate, 100)}%`,
              backgroundColor: color,
            }}
          />
        </div>
        <span
          className="font-mono text-[11px] tabular-nums whitespace-nowrap"
          style={{ color, minWidth: "38px", textAlign: "right" }}
        >
          {row.win_rate.toFixed(1)}%
        </span>
      </div>

      {/* W/L count */}
      <div className="col-span-2">
        <span className="font-mono text-[11px] tabular-nums" style={{ color: "#888" }}>
          W/L:{" "}
          <span style={{ color: "#00ff88" }}>{row.wins}</span>
          <span style={{ color: "#555" }}>/</span>
          <span style={{ color: "#ff4444" }}>{row.losses}</span>
        </span>
      </div>

      {/* Total P&L */}
      <div className="col-span-2 text-right">
        <span
          className="font-mono text-[11px] tabular-nums font-bold"
          style={{ color: pnlColor(row.total_pnl) }}
        >
          {fmt$(row.total_pnl)}
        </span>
      </div>

      {/* Badge */}
      <div className="col-span-2 flex justify-end">
        <Badge variant={winRateBadgeVariant(row.win_rate)}>
          {row.win_rate >= 55 ? "BULL" : row.win_rate >= 40 ? "WARN" : "BEAR"}
        </Badge>
      </div>
    </div>
  );
}

// ── Component ─────────────────────────────────────────────────────────────────

export function WinRateBySymbolWidget() {
  const [stats, setStats] = useState<SymbolStats[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  async function fetchData() {
    setError(null);
    try {
      const raw: unknown = await fetchEngine<unknown>(
        `/portfolio/history/trades?status=CLOSED&limit=500`
      );

      // Handle both array and { trades: [...] } shapes
      let trades: TradeRecord[];
      if (Array.isArray(raw)) {
        trades = raw as TradeRecord[];
      } else if (
        raw !== null &&
        typeof raw === "object" &&
        "trades" in (raw as object) &&
        Array.isArray((raw as { trades: unknown }).trades)
      ) {
        trades = (raw as { trades: TradeRecord[] }).trades;
      } else {
        trades = [];
      }

      setStats(aggregateBySymbol(trades));
      setLastUpdated(new Date());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 120_000);
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Overall summary stats ─────────────────────────────────────────────────
  const overallTrades = stats.reduce((s, r) => s + r.total_trades, 0);
  const overallWins = stats.reduce((s, r) => s + r.wins, 0);
  const overallLosses = stats.reduce((s, r) => s + r.losses, 0);
  const overallWinRate =
    overallTrades > 0 ? (overallWins / overallTrades) * 100 : 0;
  const overallPnl = stats.reduce((s, r) => s + r.total_pnl, 0);
  const overallAvgPnl = overallTrades > 0 ? overallPnl / overallTrades : 0;

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-3">
        <div className="flex items-center gap-2">
          <TrendingUp className="h-4 w-4" style={{ color: "#00ff88" }} />
          <CardTitle className="text-sm font-mono tracking-wider uppercase">
            Win Rate by Symbol
          </CardTitle>
        </div>
        <div className="flex items-center gap-3">
          {lastUpdated && !loading && (
            <span className="font-mono text-[10px]" style={{ color: "#555" }}>
              {lastUpdated.toLocaleTimeString()}
            </span>
          )}
          <button
            onClick={() => {
              setLoading(true);
              fetchData();
            }}
            disabled={loading}
            className="flex items-center gap-1.5 rounded px-2 py-1 text-[11px] font-mono transition-colors disabled:opacity-40"
            style={{
              backgroundColor: "#00ff8812",
              border: "1px solid #00ff8830",
              color: "#00ff88",
            }}
          >
            <RefreshCw className={`h-3 w-3 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </button>
        </div>
      </CardHeader>

      <CardContent>
        {/* Column headers — only shown when data is present */}
        {!loading && !error && stats.length > 0 && (
          <div className="grid grid-cols-12 gap-3 mb-1">
            <div
              className="col-span-2 font-mono text-[10px] uppercase tracking-wider"
              style={{ color: "#555" }}
            >
              Symbol
            </div>
            <div
              className="col-span-4 font-mono text-[10px] uppercase tracking-wider"
              style={{ color: "#555" }}
            >
              Win Rate
            </div>
            <div
              className="col-span-2 font-mono text-[10px] uppercase tracking-wider"
              style={{ color: "#555" }}
            >
              W / L
            </div>
            <div
              className="col-span-2 font-mono text-[10px] uppercase tracking-wider text-right"
              style={{ color: "#555" }}
            >
              Total P&amp;L
            </div>
            <div
              className="col-span-2 font-mono text-[10px] uppercase tracking-wider text-right"
              style={{ color: "#555" }}
            >
              Signal
            </div>
          </div>
        )}

        {/* Loading skeleton — first load only */}
        {loading && (
          <div>
            {[1, 2, 3, 4].map((i) => (
              <SkeletonRow key={i} />
            ))}
          </div>
        )}

        {/* Error state */}
        {!loading && error && (
          <div
            className="rounded-lg p-4 font-mono text-sm"
            style={{
              backgroundColor: "#ff444412",
              border: "1px solid #ff444430",
              color: "#ff4444",
            }}
          >
            Symbol data unavailable
          </div>
        )}

        {/* Empty state */}
        {!loading && !error && stats.length === 0 && (
          <div className="py-10 text-center">
            <p className="font-mono text-sm" style={{ color: "#555" }}>
              No closed trades yet
            </p>
          </div>
        )}

        {/* Symbol rows + summary */}
        {!loading && !error && stats.length > 0 && (
          <>
            {stats.map((row) => (
              <SymbolRow key={row.symbol} row={row} />
            ))}

            {/* Overall summary row — separator + bold combined stats */}
            <div
              className="grid grid-cols-12 gap-3 items-center py-3 mt-1"
              style={{ borderTop: "2px solid #1a1a2e" }}
            >
              <div className="col-span-2">
                <span
                  className="font-mono text-xs font-bold uppercase tracking-wider"
                  style={{ color: "#e0e0e0" }}
                >
                  TOTAL
                </span>
              </div>

              {/* Overall win rate bar */}
              <div className="col-span-4 flex items-center gap-2">
                <div className="h-2 bg-muted rounded-full flex-1 min-w-0">
                  <div
                    className="h-2 rounded-full transition-all duration-500"
                    style={{
                      width: `${Math.min(overallWinRate, 100)}%`,
                      backgroundColor: barColor(overallWinRate),
                    }}
                  />
                </div>
                <span
                  className="font-mono text-[11px] tabular-nums font-bold whitespace-nowrap"
                  style={{
                    color: barColor(overallWinRate),
                    minWidth: "38px",
                    textAlign: "right",
                  }}
                >
                  {overallWinRate.toFixed(1)}%
                </span>
              </div>

              {/* Overall W/L */}
              <div className="col-span-2">
                <span
                  className="font-mono text-[11px] tabular-nums font-bold"
                  style={{ color: "#888" }}
                >
                  W/L:{" "}
                  <span style={{ color: "#00ff88" }}>{overallWins}</span>
                  <span style={{ color: "#555" }}>/</span>
                  <span style={{ color: "#ff4444" }}>{overallLosses}</span>
                </span>
              </div>

              {/* Overall total P&L */}
              <div className="col-span-2 text-right">
                <span
                  className="font-mono text-[11px] tabular-nums font-bold"
                  style={{ color: pnlColor(overallPnl) }}
                >
                  {fmt$(overallPnl)}
                </span>
              </div>

              {/* Overall badge */}
              <div className="col-span-2 flex justify-end">
                <Badge variant={winRateBadgeVariant(overallWinRate)}>
                  {overallWinRate.toFixed(1)}%
                </Badge>
              </div>
            </div>

            {/* Footer */}
            <div
              className="pt-2 pb-1 flex items-center justify-between"
              style={{ borderTop: "1px solid #1a1a2e" }}
            >
              <span className="font-mono text-[10px]" style={{ color: "#555" }}>
                {stats.length} symbol{stats.length !== 1 ? "s" : ""} &bull;{" "}
                {overallTrades} closed trade{overallTrades !== 1 ? "s" : ""} &bull; refreshes every 2 min
              </span>
              <span className="font-mono text-[10px]" style={{ color: "#555" }}>
                avg/trade:{" "}
                <span
                  style={{ color: pnlColor(overallAvgPnl), fontWeight: 700 }}
                >
                  {fmt$(overallAvgPnl)}
                </span>
              </span>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
