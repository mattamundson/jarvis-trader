"use client";

import { useState } from "react";
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
  target2: number | null;
  stop1: number | null;
  stop2: number | null;
  win_rate: number | null;
  raw_text?: string;
}

interface SignalsResponse {
  data: BotSignal[];
  total: number;
  limit: number;
  offset: number;
}

function buildUrl(symbol: string, direction: string, signalType: string, offset: number): string {
  const params = new URLSearchParams();
  if (symbol) params.set("symbol", symbol);
  if (direction) params.set("direction", direction);
  if (signalType) params.set("signal_type", signalType);
  params.set("limit", "50");
  params.set("offset", String(offset));
  return `/discord/signals?${params.toString()}`;
}

function fmt(ts: string): string {
  try {
    return new Date(ts).toLocaleString("en-US", {
      month: "short", day: "numeric",
      hour: "2-digit", minute: "2-digit",
    });
  } catch {
    return ts;
  }
}

export function SignalFeed() {
  const [symbol, setSymbol] = useState("");
  const [direction, setDirection] = useState("");
  const [signalType, setSignalType] = useState("");
  const [offset, setOffset] = useState(0);

  const url = buildUrl(symbol, direction, signalType, offset);
  const { data, isLoading } = useSWR<SignalsResponse>(url, fetcher, {
    refreshInterval: REFRESH_MS,
    keepPreviousData: true,
  });

  const rows = data?.data ?? [];
  const total = data?.total ?? 0;
  const pageSize = 50;

  function handleFilterChange(setter: (v: string) => void) {
    return (e: React.ChangeEvent<HTMLSelectElement | HTMLInputElement>) => {
      setter(e.target.value);
      setOffset(0);
    };
  }

  return (
    <div className="space-y-3">
      {/* Filters */}
      <div className="flex flex-wrap gap-2">
        <input
          className="rounded-lg border border-border bg-card px-3 py-1.5 font-mono text-xs text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-accent/50"
          placeholder="Symbol (ES, NQ…)"
          value={symbol}
          onChange={handleFilterChange(setSymbol)}
        />
        <select
          className="rounded-lg border border-border bg-card px-3 py-1.5 font-mono text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-accent/50"
          value={direction}
          onChange={handleFilterChange(setDirection)}
        >
          <option value="">All Directions</option>
          <option value="LONG">LONG</option>
          <option value="SHORT">SHORT</option>
        </select>
        <select
          className="rounded-lg border border-border bg-card px-3 py-1.5 font-mono text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-accent/50"
          value={signalType}
          onChange={handleFilterChange(setSignalType)}
        >
          <option value="">All Types</option>
          <option value="ENTRY">ENTRY</option>
          <option value="EXIT">EXIT</option>
        </select>
        <span className="font-mono text-[10px] text-muted-foreground self-center ml-auto">
          {isLoading ? "Loading…" : `${total.toLocaleString()} records`}
        </span>
      </div>

      {/* Table */}
      <div className="rounded-xl border border-border bg-card overflow-x-auto">
        <table className="w-full font-mono text-xs min-w-[700px]">
          <thead>
            <tr className="border-b border-border text-[10px] uppercase tracking-wider text-muted-foreground">
              <th className="text-left px-3 py-2">Time</th>
              <th className="text-left px-3 py-2">Symbol</th>
              <th className="text-left px-3 py-2">Dir</th>
              <th className="text-left px-3 py-2">Type</th>
              <th className="text-right px-3 py-2">Entry</th>
              <th className="text-right px-3 py-2">Target 1</th>
              <th className="text-right px-3 py-2">Stop 1</th>
              <th className="text-right px-3 py-2">WR%</th>
            </tr>
          </thead>
          <tbody>
            {!rows.length ? (
              <tr>
                <td colSpan={8} className="text-center py-10 text-muted-foreground/50 italic">
                  {isLoading ? "Loading signals…" : "No signals found"}
                </td>
              </tr>
            ) : (
              rows.map((row, i) => {
                const isLong = row.direction === "LONG";
                const dirColor = isLong ? "#00ff88" : "#ff4444";
                return (
                  <tr
                    key={row.id ?? i}
                    className="border-b border-border/40 hover:bg-accent/5 transition-colors"
                  >
                    <td className="px-3 py-2 text-[10px] text-muted-foreground whitespace-nowrap">
                      {fmt(row.timestamp)}
                    </td>
                    <td className="px-3 py-2 font-semibold" style={{ color: "#00d4ff" }}>
                      {row.symbol}
                    </td>
                    <td className="px-3 py-2 font-bold" style={{ color: dirColor }}>
                      {row.direction}
                    </td>
                    <td className="px-3 py-2 text-muted-foreground">{row.signal_type}</td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      {row.entry_price != null ? row.entry_price.toFixed(2) : "—"}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums" style={{ color: "#00ff88" }}>
                      {row.target1 != null ? row.target1.toFixed(2) : "—"}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums" style={{ color: "#ff4444" }}>
                      {row.stop1 != null ? row.stop1.toFixed(2) : "—"}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums text-muted-foreground">
                      {row.win_rate != null ? `${(row.win_rate * 100).toFixed(1)}%` : "—"}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {total > pageSize && (
        <div className="flex items-center gap-3 justify-end">
          <button
            onClick={() => setOffset(Math.max(0, offset - pageSize))}
            disabled={offset === 0}
            className="rounded-lg border border-border px-3 py-1 font-mono text-xs text-muted-foreground hover:text-foreground disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
          >
            Prev
          </button>
          <span className="font-mono text-[10px] text-muted-foreground">
            {offset + 1}–{Math.min(offset + pageSize, total)} of {total}
          </span>
          <button
            onClick={() => setOffset(offset + pageSize)}
            disabled={offset + pageSize >= total}
            className="rounded-lg border border-border px-3 py-1 font-mono text-xs text-muted-foreground hover:text-foreground disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}
