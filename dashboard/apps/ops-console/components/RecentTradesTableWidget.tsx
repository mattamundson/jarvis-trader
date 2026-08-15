"use client";

import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
} from "@/components/ui/card";
import {
  dedupCaveat,
  durationMinutes,
} from "@/lib/honestTrades";
import { useHonestTrades } from "@/lib/useHonestTrades";

function formatDuration(mins: number | null): string {
  if (mins === null) return "—";
  const h = Math.floor(mins / 60);
  const m = Math.round(mins % 60);
  if (h === 0) return `${m}m`;
  return m === 0 ? `${h}hr` : `${h}hr ${m}m`;
}

function formatPnl(pnl: number | null | undefined): { text: string; className: string } {
  if (pnl == null) return { text: "—", className: "text-muted-foreground" };
  const abs = Math.abs(pnl).toFixed(2);
  if (pnl >= 0) return { text: `+$${abs}`, className: "text-green-400" };
  return { text: `-$${abs}`, className: "text-red-400" };
}

export function RecentTradesTableWidget() {
  const { honest: set, error: loadError } = useHonestTrades(120_000);
  const error = loadError
    ? (loadError instanceof Error ? loadError.message : String(loadError))
    : null;

  // Show the 10 most-recent trades (sorted by exit_time desc)
  const recent = set
    ? [...set.trades]
        .filter((t) => t.exit_time)
        .sort((a, b) => Date.parse(b.exit_time!) - Date.parse(a.exit_time!))
        .slice(0, 10)
    : [];

  const totalPnl = set ? formatPnl(set.net) : formatPnl(null);

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3">
        <CardTitle className="text-base font-semibold">Recent Trades</CardTitle>
        <Badge variant="neutral">Refreshes every 2m</Badge>
      </CardHeader>
      <CardContent>
        {error && (
          <p className="text-sm text-red-400 mb-2">Engine error: {error}</p>
        )}
        {!set && !error ? (
          <p className="text-sm text-muted-foreground text-center py-6">Loading…</p>
        ) : recent.length === 0 ? (
          <p className="text-sm text-muted-foreground text-center py-6">
            No closed trades yet
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-muted-foreground uppercase">
                  <th className="text-left pb-2 w-7">#</th>
                  <th className="text-left pb-2">Symbol</th>
                  <th className="text-left pb-2">Direction</th>
                  <th className="text-right pb-2">P&amp;L</th>
                  <th className="text-right pb-2">Duration</th>
                </tr>
              </thead>
              <tbody>
                {recent.map((trade, i) => {
                  const pnl = formatPnl(trade.pnl);
                  const dur = formatDuration(durationMinutes(trade));
                  return (
                    <tr
                      key={trade.id}
                      className="border-t border-border"
                    >
                      <td className="py-1.5 font-mono text-muted-foreground">
                        {i + 1}
                      </td>
                      <td className="py-1.5 font-mono font-medium">
                        {trade.symbol}
                      </td>
                      <td className="py-1.5">
                        <Badge variant={trade.direction === "LONG" ? "bull" : "bear"}>
                          {trade.direction}
                        </Badge>
                      </td>
                      <td
                        className={`py-1.5 text-right font-mono font-medium ${pnl.className}`}
                      >
                        {pnl.text}
                      </td>
                      <td className="py-1.5 text-right font-mono text-muted-foreground">
                        {dur}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
              <tfoot>
                <tr className="border-t-2 border-border">
                  <td
                    colSpan={3}
                    className="pt-2 text-xs text-muted-foreground font-mono uppercase tracking-wider"
                  >
                    {set ? dedupCaveat(set) : ""}
                  </td>
                  <td
                    className={`pt-2 text-right font-mono font-semibold ${totalPnl.className}`}
                  >
                    {totalPnl.text}
                  </td>
                  <td />
                </tr>
              </tfoot>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
