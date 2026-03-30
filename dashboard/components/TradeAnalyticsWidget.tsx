"use client";
import { useEffect, useState } from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

type DayRow = {
  day: string;
  count: number;
  wins: number;
  losses: number;
  win_rate: number;
  total_pnl: number;
  avg_pnl: number;
};

type SymbolRow = {
  symbol: string;
  count: number;
  wins: number;
  losses: number;
  win_rate: number;
  total_pnl: number;
  avg_pnl: number;
  best_trade: number;
  worst_trade: number;
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

export function TradeAnalyticsWidget() {
  const [tab, setTab] = useState<Tab>("symbol");
  const [days, setDays] = useState<DayRow[]>([]);
  const [symbols, setSymbols] = useState<SymbolRow[]>([]);
  const [hourData, setHourData] = useState<HourRow[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      fetch("http://localhost:8010/analytics/trades/by-day").then((r) => r.json()),
      fetch("http://localhost:8010/analytics/trades/by-symbol").then((r) => r.json()),
      fetch("http://localhost:8010/analytics/trades/by-hour").then((r) => r.json()),
    ])
      .then(([d, s, h]) => {
        setDays(d.days ?? []);
        setSymbols(s.symbols ?? []);
        setHourData(h.hours ?? []);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  const fmtPnl = (v: number) =>
    (v >= 0 ? "+" : "") + "$" + Math.abs(v).toFixed(0);

  const pnlVariant = (v: number): "bull" | "bear" | "neutral" =>
    v > 0 ? "bull" : v < 0 ? "bear" : "neutral";

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
                        {(s.win_rate * 100).toFixed(0)}% WR
                      </span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-muted-foreground">
                        Avg {fmtPnl(s.avg_pnl)}
                      </span>
                      <span className="text-xs text-muted-foreground">
                        {s.count} trades
                      </span>
                    </div>
                  </div>
                  <Badge variant={pnlVariant(s.total_pnl)}>
                    {fmtPnl(s.total_pnl)}
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
                      {h.win_rate.toFixed(0)}%
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
        )}
      </CardContent>
    </Card>
  );
}
