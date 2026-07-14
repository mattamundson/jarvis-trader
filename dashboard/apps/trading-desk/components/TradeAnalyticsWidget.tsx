"use client";

// TradeAnalyticsWidget — derived entirely from the honest deduped trade record.
// Raw endpoints /analytics/trades/by-day, /by-symbol, /by-hour are NOT used
// (they over-count re-logged winners). All aggregates are computed client-side
// from fetchHonestTrades().
//
// Fields NOT available in honest record and therefore absent:
//   - best_trade / worst_trade per symbol (dropped — no per-trade fill breakdown)
//   - hour data derived from entry_time (entry_time may be null for some trades;
//     those trades are excluded from the "by hour" view with a caveat shown)

import { useState, useMemo } from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  bySymbolStats,
  dedupCaveat,
  type HonestTrade,
  type HonestTradeSet,
} from "@/lib/honestTrades";
import { useHonestTrades } from "@/lib/useHonestTrades";

// ── Local derived types ───────────────────────────────────────────────────────

type DayRow = {
  day: string;
  count: number;
  wins: number;
  losses: number;
  win_rate: number;
  total_pnl: number;
  avg_pnl: number;
};

type HourRow = {
  hour: number;
  hour_label: string;
  count: number;
  wins: number;
  losses: number;
  win_rate: number;
  total_pnl: number;
  avg_pnl: number;
};

type Tab = "day" | "symbol" | "hour";

const DOW_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

function buildDayRows(trades: HonestTrade[]): DayRow[] {
  const map = new Map<number, HonestTrade[]>();
  for (const t of trades) {
    if (!t.exit_time) continue;
    const dow = new Date(t.exit_time).getDay();
    const arr = map.get(dow) ?? [];
    arr.push(t);
    map.set(dow, arr);
  }
  const rows: DayRow[] = [];
  for (const [dow, arr] of map) {
    const wins = arr.filter((t) => t.pnl > 0).length;
    const losses = arr.filter((t) => t.pnl < 0).length;
    const total_pnl = arr.reduce((s, t) => s + t.pnl, 0);
    rows.push({
      day: DOW_NAMES[dow],
      count: arr.length,
      wins,
      losses,
      win_rate: arr.length ? wins / arr.length : 0,
      total_pnl,
      avg_pnl: arr.length ? total_pnl / arr.length : 0,
    });
  }
  // Sort by DOW index (Mon–Fri trading order)
  return rows.sort((a, b) => DOW_NAMES.indexOf(a.day) - DOW_NAMES.indexOf(b.day));
}

function buildHourRows(trades: HonestTrade[]): { rows: HourRow[]; excluded: number } {
  const map = new Map<number, HonestTrade[]>();
  let excluded = 0;
  for (const t of trades) {
    if (!t.entry_time) { excluded++; continue; }
    const h = new Date(t.entry_time).getHours();
    const arr = map.get(h) ?? [];
    arr.push(t);
    map.set(h, arr);
  }
  const rows: HourRow[] = [];
  for (const [h, arr] of map) {
    const wins = arr.filter((t) => t.pnl > 0).length;
    const losses = arr.filter((t) => t.pnl < 0).length;
    const total_pnl = arr.reduce((s, t) => s + t.pnl, 0);
    const ampm = h === 0 ? "12am" : h < 12 ? `${h}am` : h === 12 ? "12pm" : `${h - 12}pm`;
    rows.push({
      hour: h,
      hour_label: ampm,
      count: arr.length,
      wins,
      losses,
      win_rate: arr.length ? wins / arr.length : 0,
      total_pnl,
      avg_pnl: arr.length ? total_pnl / arr.length : 0,
    });
  }
  return { rows: rows.sort((a, b) => a.hour - b.hour), excluded };
}

// ── Formatters ────────────────────────────────────────────────────────────────

const fmtPnl = (v: number) =>
  (v >= 0 ? "+" : "") + "$" + Math.abs(v).toFixed(0);

const pnlVariant = (v: number): "bull" | "bear" | "neutral" =>
  v > 0 ? "bull" : v < 0 ? "bear" : "neutral";

// ── Widget ────────────────────────────────────────────────────────────────────

export function TradeAnalyticsWidget() {
  const [tab, setTab] = useState<Tab>("symbol");
  const { honest: set, isLoading: loading } = useHonestTrades(60_000);

  const trades = set?.trades ?? [];

  const symbols = useMemo(() => bySymbolStats(trades), [trades]);
  const days = useMemo(() => buildDayRows(trades), [trades]);
  const { rows: hourData, excluded: hourExcluded } = useMemo(
    () => buildHourRows(trades),
    [trades]
  );

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>Trade Analytics</CardTitle>
          <div className="flex gap-1">
            {(["symbol", "day", "hour"] as Tab[]).map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={`text-xs px-2 py-0.5 rounded border transition-colors ${
                  tab === t
                    ? "bg-accent text-accent-foreground border-accent"
                    : "text-muted-foreground border-border hover:text-foreground"
                }`}
              >
                {t === "symbol" ? "By Symbol" : t === "day" ? "By Day" : "By Hour"}
              </button>
            ))}
          </div>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        {loading ? (
          <div className="px-4 pb-4 space-y-2">
            {[...Array(3)].map((_, i) => (
              <div key={i} className="h-10 rounded bg-muted animate-pulse" />
            ))}
          </div>
        ) : tab === "symbol" ? (
          symbols.length === 0 ? (
            <p className="px-4 pb-4 text-xs text-muted-foreground">No symbol data yet</p>
          ) : (
            <div className="divide-y divide-border">
              {symbols.map((s) => (
                <div key={s.symbol} className="px-4 py-2.5 flex items-center gap-3">
                  <span className="font-mono text-sm font-semibold w-12">{s.symbol}</span>
                  <div className="flex-1 space-y-0.5">
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-muted-foreground">
                        {s.wins}W / {s.losses}L
                      </span>
                      <span className="text-xs text-muted-foreground">
                        {(s.winRate * 100).toFixed(0)}% WR
                      </span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-muted-foreground">
                        {s.trades} trades
                      </span>
                    </div>
                  </div>
                  <Badge variant={pnlVariant(s.net)}>
                    {fmtPnl(s.net)}
                  </Badge>
                </div>
              ))}
            </div>
          )
        ) : tab === "day" ? (
          days.length === 0 ? (
            <p className="px-4 pb-4 text-xs text-muted-foreground">No day breakdown yet</p>
          ) : (
            <div className="divide-y divide-border">
              {days.map((d) => (
                <div key={d.day} className="px-4 py-2.5 flex items-center gap-3">
                  <span className="font-mono text-sm font-semibold w-8">{d.day}</span>
                  <div className="flex-1 space-y-0.5">
                    <span className="text-xs text-muted-foreground">
                      {d.wins}W / {d.losses}L — {(d.win_rate * 100).toFixed(0)}% WR
                    </span>
                    <div className="text-xs text-muted-foreground">
                      Avg {fmtPnl(d.avg_pnl)} · {d.count} trades
                    </div>
                  </div>
                  <Badge variant={pnlVariant(d.total_pnl)}>
                    {fmtPnl(d.total_pnl)}
                  </Badge>
                </div>
              ))}
            </div>
          )
        ) : hourData.length === 0 ? (
          <p className="px-4 pb-4 text-xs text-muted-foreground">No hour breakdown yet</p>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-border">
                    <th className="px-4 py-2 text-left font-medium text-muted-foreground">Hour</th>
                    <th className="px-4 py-2 text-right font-medium text-muted-foreground">Trades</th>
                    <th className="px-4 py-2 text-right font-medium text-muted-foreground">W/L</th>
                    <th className="px-4 py-2 text-right font-medium text-muted-foreground">Win Rate</th>
                    <th className="px-4 py-2 text-right font-medium text-muted-foreground">Avg PnL</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {hourData.map((h) => (
                    <tr key={h.hour}>
                      <td className="px-4 py-2 font-mono font-semibold">{h.hour_label}</td>
                      <td className="px-4 py-2 text-right text-muted-foreground">{h.count}</td>
                      <td className="px-4 py-2 text-right text-muted-foreground">
                        {h.wins}W / {h.losses}L
                      </td>
                      <td className="px-4 py-2 text-right text-muted-foreground">
                        {(h.win_rate * 100).toFixed(0)}%
                      </td>
                      <td className="px-4 py-2 text-right">
                        <Badge variant={pnlVariant(h.avg_pnl)}>
                          {fmtPnl(h.avg_pnl)}
                        </Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {hourExcluded > 0 && (
              <p className="px-4 py-1.5 text-[10px] font-mono text-muted-foreground/60">
                {hourExcluded} trade{hourExcluded !== 1 ? "s" : ""} excluded (no entry_time)
              </p>
            )}
          </>
        )}

        {/* Dedup caveat footer */}
        {!loading && set && (
          <p className="px-4 pt-1 pb-3 text-[10px] font-mono text-muted-foreground/50">
            {dedupCaveat(set)}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
