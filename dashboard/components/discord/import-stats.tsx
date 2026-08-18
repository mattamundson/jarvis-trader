"use client";

import useSWR from "swr";
import { fetchEngine } from "@/lib/api";
import { winRatePercent } from "@/lib/discordWinRate";

const REFRESH_MS = 30_000;

function fetcher<T = unknown>(url: string): Promise<T> {
  return fetchEngine<T>(url);
}

interface TableStats {
  count: number;
  earliest: string | null;
  latest: string | null;
}

interface SignalBySymbol {
  symbol: string;
  cnt: number;
  longs: number;
  shorts: number;
  avg_win_rate: number | null;
}

interface DiscordStats {
  discord_bot_signals: TableStats;
  discord_ib_reports: TableStats;
  discord_corey_alerts: TableStats;
  discord_corey_commentary: TableStats;
  signals_by_symbol: SignalBySymbol[];
}

function fmt(ts: string | null): string {
  if (!ts) return "—";
  try {
    return new Date(ts).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  } catch {
    return ts;
  }
}

export function ImportStats() {
  const { data, isLoading } = useSWR<DiscordStats>("/discord/stats", fetcher, {
    refreshInterval: REFRESH_MS,
  });

  const STAT_CARDS = [
    {
      key: "discord_bot_signals" as const,
      label: "Bot Signals",
      color: "#00ff88",
    },
    {
      key: "discord_ib_reports" as const,
      label: "IB Reports",
      color: "#00d4ff",
    },
    {
      key: "discord_corey_alerts" as const,
      label: "Corey Alerts",
      color: "#ffcc00",
    },
    {
      key: "discord_corey_commentary" as const,
      label: "Commentary",
      color: "#ff9500",
    },
  ];

  return (
    <div className="space-y-4">
      {/* Count overview */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {STAT_CARDS.map(({ key, label, color }) => {
          const stats = data?.[key];
          return (
            <div key={key} className="rounded-xl border border-border bg-card p-4 space-y-2">
              <p
                className="font-mono text-[10px] font-bold uppercase tracking-wider"
                style={{ color }}
              >
                {label}
              </p>
              <p
                className="font-mono text-2xl font-bold tabular-nums"
                style={{ color }}
              >
                {isLoading ? "…" : (stats?.count ?? 0).toLocaleString()}
              </p>
              <div className="font-mono text-[10px] text-muted-foreground space-y-0.5">
                <p>From: {fmt(stats?.earliest ?? null)}</p>
                <p>To: {fmt(stats?.latest ?? null)}</p>
              </div>
            </div>
          );
        })}
      </div>

      {/* Per-symbol breakdown */}
      {(data?.signals_by_symbol?.length ?? 0) > 0 && (
        <div className="rounded-xl border border-border bg-card p-4">
          <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground mb-3">
            Signals by Symbol
          </p>
          <div className="font-mono text-xs overflow-x-auto">
            <div className="grid grid-cols-5 gap-3 pb-2 mb-1 border-b border-border text-[10px] uppercase tracking-wider text-muted-foreground min-w-[400px]">
              <span>Symbol</span>
              <span className="text-right">Total</span>
              <span className="text-right">Longs</span>
              <span className="text-right">Shorts</span>
              <span className="text-right">Avg WR%</span>
            </div>
            {data!.signals_by_symbol.map((row) => (
              <div
                key={row.symbol}
                className="grid grid-cols-5 gap-3 py-1.5 border-b border-border/40 min-w-[400px]"
              >
                <span className="font-semibold" style={{ color: "#00ff88" }}>
                  {row.symbol}
                </span>
                <span className="text-right tabular-nums">{row.cnt}</span>
                <span className="text-right tabular-nums" style={{ color: "#00ff88" }}>
                  {row.longs}
                </span>
                <span className="text-right tabular-nums" style={{ color: "#ff4444" }}>
                  {row.shorts}
                </span>
                <span className="text-right tabular-nums text-muted-foreground">
                  {row.avg_win_rate != null ? `${winRatePercent(row.avg_win_rate).toFixed(1)}%` : "—"}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
