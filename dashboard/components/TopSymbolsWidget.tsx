"use client";

import { useEffect, useState } from "react";
import { RefreshCw, BarChart2 } from "lucide-react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchEngine } from "@/lib/api";


// ── Trade record shape returned by GET /portfolio/history/trades ─────────────
interface TradeRecord {
  id: number;
  trade_id: string;
  symbol: string;
  side: string;
  quantity: number;
  entry_price: number;
  exit_price: number | null;
  entry_time: string;
  exit_time: string | null;
  pnl: number;
  status: string;
  strategy_params: unknown;
  notes: string;
}

interface TradeHistoryResponse {
  trades: TradeRecord[];
  count: number;
  note?: string;
  error?: string;
}

// ── Per-symbol aggregated stats ───────────────────────────────────────────────
interface SymbolStats {
  symbol: string;
  totalTrades: number;
  winCount: number;
  winRate: number;
  totalPnl: number;
  avgPnl: number;
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

function winRateBadge(wr: number): "bull" | "warn" | "bear" {
  if (wr >= 55) return "bull";
  if (wr >= 40) return "warn";
  return "bear";
}

function pnlColor(value: number): string {
  if (value > 0) return "#00ff88";
  if (value < 0) return "#ff4444";
  return "#888888";
}

// ── Component ─────────────────────────────────────────────────────────────────

export function TopSymbolsWidget() {
  const [stats, setStats] = useState<SymbolStats[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  async function fetchData() {
    setLoading(true);
    setError(null);
    try {
      const raw: unknown = await fetchEngine<unknown>(
        `/portfolio/history/trades?status=CLOSED&limit=200`
      );
      const trades: TradeRecord[] = Array.isArray(raw)
        ? raw
        : ((raw as TradeHistoryResponse).trades ?? []);

      // Group by symbol
      const symbolMap = new Map<string, { wins: number; losses: number; totalPnl: number; count: number }>();

      for (const trade of trades) {
        const sym = trade.symbol?.toUpperCase() ?? "UNKNOWN";
        const pnl = typeof trade.pnl === "number" ? trade.pnl : 0;
        const existing = symbolMap.get(sym) ?? { wins: 0, losses: 0, totalPnl: 0, count: 0 };
        existing.count += 1;
        existing.totalPnl += pnl;
        if (pnl > 0) existing.wins += 1;
        symbolMap.set(sym, existing);
      }

      const aggregated: SymbolStats[] = Array.from(symbolMap.entries()).map(
        ([symbol, v]) => ({
          symbol,
          totalTrades: v.count,
          winCount: v.wins,
          winRate: v.count > 0 ? (v.wins / v.count) * 100 : 0,
          totalPnl: v.totalPnl,
          avgPnl: v.count > 0 ? v.totalPnl / v.count : 0,
        })
      );

      // Sort by total P&L descending
      aggregated.sort((a, b) => b.totalPnl - a.totalPnl);

      setStats(aggregated);
      setLastUpdated(new Date());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-3">
        <div className="flex items-center gap-2">
          <BarChart2 className="h-4 w-4" style={{ color: "#00ff88" }} />
          <CardTitle className="text-sm font-mono tracking-wider uppercase">
            Top Symbols
          </CardTitle>
        </div>
        <div className="flex items-center gap-3">
          {lastUpdated && !loading && (
            <span className="font-mono text-[10px]" style={{ color: "#555" }}>
              {lastUpdated.toLocaleTimeString()}
            </span>
          )}
          <button
            onClick={fetchData}
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
        {loading && (
          <div className="flex items-center justify-center py-10">
            <RefreshCw className="h-5 w-5 animate-spin" style={{ color: "#00ff88" }} />
            <span className="ml-2 font-mono text-sm" style={{ color: "#555" }}>
              Loading trade history…
            </span>
          </div>
        )}

        {!loading && error && (
          <div
            className="rounded-lg p-4 font-mono text-sm"
            style={{ backgroundColor: "#ff444412", border: "1px solid #ff444430", color: "#ff4444" }}
          >
            Error: {error}
          </div>
        )}

        {!loading && !error && stats.length === 0 && (
          <div className="py-10 text-center">
            <p className="font-mono text-sm" style={{ color: "#555" }}>
              No closed trades yet
            </p>
          </div>
        )}

        {!loading && !error && stats.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full font-mono text-xs">
              <thead>
                <tr style={{ borderBottom: "1px solid #1a1a2e" }}>
                  {["Symbol", "Trades", "Win%", "Total P&L", "Avg P&L"].map((h) => (
                    <th
                      key={h}
                      className={`pb-2 px-3 font-semibold uppercase tracking-wider ${
                        h === "Symbol" ? "text-left" : "text-right"
                      }`}
                      style={{ color: "#555", fontSize: "10px" }}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {stats.map((row) => (
                  <tr
                    key={row.symbol}
                    className="hover:bg-white/[0.02] transition-colors"
                    style={{ borderBottom: "1px solid #111" }}
                  >
                    {/* Symbol */}
                    <td className="py-2.5 px-3 text-left">
                      <span className="font-bold" style={{ color: "#e0e0e0" }}>
                        {row.symbol}
                      </span>
                    </td>

                    {/* Trades */}
                    <td className="py-2.5 px-3 text-right tabular-nums" style={{ color: "#888" }}>
                      {row.totalTrades}
                    </td>

                    {/* Win% badge */}
                    <td className="py-2.5 px-3 text-right">
                      <div className="flex justify-end">
                        <Badge variant={winRateBadge(row.winRate)}>
                          {row.winRate.toFixed(1)}%
                        </Badge>
                      </div>
                    </td>

                    {/* Total P&L */}
                    <td className="py-2.5 px-3 text-right tabular-nums font-bold">
                      <span style={{ color: pnlColor(row.totalPnl) }}>
                        {fmt$(row.totalPnl)}
                      </span>
                    </td>

                    {/* Avg P&L */}
                    <td className="py-2.5 px-3 text-right tabular-nums">
                      <span style={{ color: pnlColor(row.avgPnl) }}>
                        {fmt$(row.avgPnl)}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            {/* Footer summary */}
            <div
              className="mt-3 pt-3 flex items-center justify-between"
              style={{ borderTop: "1px solid #1a1a2e" }}
            >
              <span className="font-mono text-[10px]" style={{ color: "#555" }}>
                {stats.length} symbol{stats.length !== 1 ? "s" : ""} •{" "}
                {stats.reduce((s, r) => s + r.totalTrades, 0)} total closed trades
              </span>
              <span
                className="font-mono text-[10px] font-bold tabular-nums"
                style={{
                  color: pnlColor(stats.reduce((s, r) => s + r.totalPnl, 0)),
                }}
              >
                Net P&L:{" "}
                {fmt$(stats.reduce((s, r) => s + r.totalPnl, 0))}
              </span>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
