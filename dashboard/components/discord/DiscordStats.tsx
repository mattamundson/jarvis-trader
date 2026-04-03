"use client";

import useSWR from "swr";
import { fetchEngine } from "@/lib/api";

const REFRESH_MS = 30_000;

function fetcher<T = unknown>(url: string): Promise<T> {
  return fetchEngine<T>(url);
}

interface TableStats {
  count: number;
  earliest: string | null;
  latest: string | null;
}

interface DiscordStatsResponse {
  discord_bot_signals: TableStats;
  discord_ib_reports: TableStats;
  discord_corey_alerts: TableStats;
  discord_corey_commentary: TableStats;
}

function fmtDate(ts: string | null): string {
  if (!ts) return "—";
  try {
    return new Date(ts).toLocaleDateString("en-US", {
      month: "short",
      year: "numeric",
    });
  } catch {
    return ts;
  }
}

export function DiscordStats() {
  const { data, isLoading } = useSWR<DiscordStatsResponse>(
    "/discord/stats",
    fetcher,
    { refreshInterval: REFRESH_MS }
  );

  const totalSignals = data?.discord_bot_signals?.count ?? 0;
  const totalIB = data?.discord_ib_reports?.count ?? 0;
  const totalAlerts = data?.discord_corey_alerts?.count ?? 0;
  const totalCommentary = data?.discord_corey_commentary?.count ?? 0;
  const totalAll = totalSignals + totalIB + totalAlerts + totalCommentary;

  // Date range derived from earliest/latest across all tables
  const allEarliests = [
    data?.discord_bot_signals?.earliest,
    data?.discord_ib_reports?.earliest,
    data?.discord_corey_alerts?.earliest,
    data?.discord_corey_commentary?.earliest,
  ].filter(Boolean) as string[];
  const allLatests = [
    data?.discord_bot_signals?.latest,
    data?.discord_ib_reports?.latest,
    data?.discord_corey_alerts?.latest,
    data?.discord_corey_commentary?.latest,
  ].filter(Boolean) as string[];

  const earliest = allEarliests.length
    ? allEarliests.sort()[0]
    : null;
  const latest = allLatests.length
    ? allLatests.sort().reverse()[0]
    : null;

  const STATS = [
    {
      label: "Total Records",
      value: isLoading ? "…" : totalAll.toLocaleString(),
      color: "#00d4ff",
      sub: "across all tables",
    },
    {
      label: "Bot Signals",
      value: isLoading ? "…" : totalSignals.toLocaleString(),
      color: "#00ff88",
      sub: "parsed trade signals",
    },
    {
      label: "IB Reports",
      value: isLoading ? "…" : totalIB.toLocaleString(),
      color: "#00d4ff",
      sub: "initial balance data",
    },
    {
      label: "Commentary",
      value: isLoading ? "…" : totalCommentary.toLocaleString(),
      color: "#ff9500",
      sub: "Corey analysis posts",
    },
    {
      label: "Corey Alerts",
      value: isLoading ? "…" : totalAlerts.toLocaleString(),
      color: "#ffcc00",
      sub: "live trade alerts",
    },
    {
      label: "Date Range",
      value: isLoading
        ? "…"
        : earliest && latest
        ? `${fmtDate(earliest)} — ${fmtDate(latest)}`
        : "—",
      color: "#888",
      sub: "historical coverage",
    },
  ];

  return (
    <div className="rounded-xl border border-border bg-card p-4 space-y-3">
      <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
        Discord Import Summary
      </p>
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4">
        {STATS.map(({ label, value, color, sub }) => (
          <div key={label} className="space-y-1">
            <p
              className="font-mono text-[10px] font-bold uppercase tracking-wider"
              style={{ color }}
            >
              {label}
            </p>
            <p
              className="font-mono text-xl font-bold tabular-nums leading-tight"
              style={{ color }}
            >
              {value}
            </p>
            <p className="font-mono text-[10px] text-muted-foreground/60">{sub}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
