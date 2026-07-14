"use client";

import { useState } from "react";
import useSWR from "swr";
import { fetchEngine } from "@/lib/api";

const REFRESH_MS = 15_000;

function fetcher<T = unknown>(url: string): Promise<T> {
  return fetchEngine<T>(url);
}

interface Commentary {
  id?: number;
  timestamp: string;
  channel: string;
  message: string;
  author?: string;
}

interface CommentaryResponse {
  data: Commentary[];
  total: number;
  limit: number;
  offset: number;
}

function buildUrl(channel: string, offset: number): string {
  const params = new URLSearchParams();
  if (channel) params.set("channel", channel);
  params.set("limit", "50");
  params.set("offset", String(offset));
  return `/discord/commentary?${params.toString()}`;
}

function fmtDate(ts: string): string {
  try {
    return new Date(ts).toLocaleString("en-US", {
      month: "short", day: "numeric", year: "numeric",
      hour: "2-digit", minute: "2-digit",
    });
  } catch {
    return ts;
  }
}

const CHANNEL_COLORS: Record<string, string> = {
  "general": "#00d4ff",
  "market-updates": "#ffcc00",
};

function channelColor(ch: string): string {
  return CHANNEL_COLORS[ch] ?? "#888";
}

export function CoreyFeed() {
  const [channel, setChannel] = useState("");
  const [offset, setOffset] = useState(0);

  const url = buildUrl(channel, offset);
  const { data, isLoading } = useSWR<CommentaryResponse>(url, fetcher, {
    refreshInterval: REFRESH_MS,
    keepPreviousData: true,
  });

  const rows = data?.data ?? [];
  const total = data?.total ?? 0;
  const pageSize = 50;

  return (
    <div className="space-y-3">
      {/* Filter bar */}
      <div className="flex flex-wrap gap-2 items-center">
        <select
          className="rounded-lg border border-border bg-card px-3 py-1.5 font-mono text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-accent/50"
          value={channel}
          onChange={(e) => { setChannel(e.target.value); setOffset(0); }}
        >
          <option value="">All Channels</option>
          <option value="general">general</option>
          <option value="market-updates">market-updates</option>
        </select>
        <span className="font-mono text-[10px] text-muted-foreground ml-auto">
          {isLoading ? "Loading…" : `${total.toLocaleString()} messages`}
        </span>
      </div>

      {/* Timeline */}
      {!rows.length ? (
        <div className="rounded-xl border border-border bg-card p-10 text-center font-mono text-[10px] text-muted-foreground/50 italic">
          {isLoading ? "Loading commentary…" : "No commentary found"}
        </div>
      ) : (
        <div className="space-y-2">
          {rows.map((item, i) => {
            const color = channelColor(item.channel);
            return (
              <div
                key={item.id ?? i}
                className="rounded-xl border border-border bg-card p-4 space-y-2 hover:border-accent/30 transition-colors"
              >
                <div className="flex items-center gap-2 flex-wrap">
                  <span
                    className="font-mono text-[10px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded border"
                    style={{ color, borderColor: `${color}44` }}
                  >
                    #{item.channel}
                  </span>
                  {item.author && (
                    <span className="font-mono text-[10px] text-muted-foreground">
                      {item.author}
                    </span>
                  )}
                  <span className="font-mono text-[10px] text-muted-foreground/60 ml-auto">
                    {fmtDate(item.timestamp)}
                  </span>
                </div>
                <p className="font-mono text-[12px] text-foreground/90 leading-relaxed whitespace-pre-wrap">
                  {item.message}
                </p>
              </div>
            );
          })}
        </div>
      )}

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
