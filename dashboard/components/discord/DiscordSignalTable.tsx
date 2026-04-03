"use client";

import useSWR from "swr";
import { fetchEngine } from "@/lib/api";

const REFRESH_MS = 10_000;

function fetcher<T = unknown>(url: string): Promise<T> {
  return fetchEngine<T>(url);
}

interface BotSignal {
  id?: number;
  timestamp: string;
  symbol: string;
  direction: string;
  signal_type: string;
  entry_price: number | null;
  target1: number | null;
  stop1: number | null;
  win_rate: number | null;
}

interface SignalsResponse {
  data: BotSignal[];
  total: number;
  limit: number;
  offset: number;
}

function fmt(ts: string): string {
  try {
    return new Date(ts).toLocaleString("en-US", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return ts;
  }
}

function winRateColor(rate: number | null): string {
  if (rate == null) return "#888";
  const pct = rate * 100;
  if (pct >= 60) return "#00ff88";
  if (pct >= 40) return "#ffcc00";
  return "#ff4444";
}

export function DiscordSignalTable() {
  const { data, isLoading, error } = useSWR<SignalsResponse>(
    "/discord/signals?limit=20",
    fetcher,
    { refreshInterval: REFRESH_MS }
  );

  const rows = data?.data ?? [];
  const total = data?.total ?? 0;

  return (
    <div className="rounded-xl border border-border bg-card overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 border-b border-border flex items-center justify-between">
        <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
          Recent Signals
        </p>
        <span className="font-mono text-[10px] text-muted-foreground">
          {isLoading ? "Loading…" : `${total.toLocaleString()} total`}
        </span>
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full font-mono text-xs min-w-[640px]">
          <thead>
            <tr className="border-b border-border text-[10px] uppercase tracking-wider text-muted-foreground">
              <th className="text-left px-4 py-2">Time</th>
              <th className="text-left px-4 py-2">Symbol</th>
              <th className="text-left px-4 py-2">Direction</th>
              <th className="text-right px-4 py-2">Entry</th>
              <th className="text-right px-4 py-2">Target 1</th>
              <th className="text-right px-4 py-2">Stop</th>
              <th className="text-right px-4 py-2">Win Rate</th>
            </tr>
          </thead>
          <tbody>
            {error ? (
              <tr>
                <td
                  colSpan={7}
                  className="text-center py-10 font-mono text-[11px] text-red-400/70 italic"
                >
                  Failed to load signals — engine may be offline
                </td>
              </tr>
            ) : !rows.length ? (
              <tr>
                <td
                  colSpan={7}
                  className="text-center py-10 text-muted-foreground/50 italic"
                >
                  {isLoading ? (
                    <span className="animate-pulse">Loading signals…</span>
                  ) : (
                    "No signals found"
                  )}
                </td>
              </tr>
            ) : (
              rows.map((row, i) => {
                const isLong = row.direction === "LONG";
                const dirColor = isLong ? "#00ff88" : "#ff4444";
                const wrColor = winRateColor(row.win_rate);

                return (
                  <tr
                    key={row.id ?? i}
                    className="border-b border-border/40 hover:bg-accent/5 transition-colors"
                  >
                    <td className="px-4 py-2 text-[10px] text-muted-foreground whitespace-nowrap">
                      {fmt(row.timestamp)}
                    </td>
                    <td
                      className="px-4 py-2 font-semibold"
                      style={{ color: "#00d4ff" }}
                    >
                      {row.symbol}
                    </td>
                    <td className="px-4 py-2">
                      <span
                        className="px-2 py-0.5 rounded text-[10px] font-bold border"
                        style={{
                          color: dirColor,
                          borderColor: `${dirColor}44`,
                          backgroundColor: `${dirColor}10`,
                        }}
                      >
                        {row.direction}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-right tabular-nums">
                      {row.entry_price != null
                        ? row.entry_price.toFixed(2)
                        : "—"}
                    </td>
                    <td
                      className="px-4 py-2 text-right tabular-nums"
                      style={{ color: "#00ff88" }}
                    >
                      {row.target1 != null ? row.target1.toFixed(2) : "—"}
                    </td>
                    <td
                      className="px-4 py-2 text-right tabular-nums"
                      style={{ color: "#ff4444" }}
                    >
                      {row.stop1 != null ? row.stop1.toFixed(2) : "—"}
                    </td>
                    <td
                      className="px-4 py-2 text-right tabular-nums font-semibold"
                      style={{ color: wrColor }}
                    >
                      {row.win_rate != null
                        ? `${(row.win_rate * 100).toFixed(1)}%`
                        : "—"}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
