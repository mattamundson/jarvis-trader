"use client";

import { useState } from "react";
import useSWR from "swr";
import { Activity, Sunrise } from "lucide-react";
import { fetchEngine } from "@/lib/api";

const REFRESH_MS = 5 * 60_000;

interface FramingBrief {
  date: string;
  markdown: string;
  generated_at: number;
}

function fetcher<T = unknown>(url: string): Promise<T> {
  return fetchEngine<T>(url);
}

function fmtGeneratedAt(epochSeconds: number): string {
  try {
    return new Date(epochSeconds * 1000).toLocaleString("en-US", {
      month: "short", day: "numeric", year: "numeric",
      hour: "2-digit", minute: "2-digit",
    });
  } catch {
    return "";
  }
}

export default function FramingBriefPage() {
  // Empty string = "latest"; a YYYY-MM-DD string views a specific past brief.
  const [selectedDate, setSelectedDate] = useState("");

  const url = selectedDate ? `/framing-brief/${selectedDate}` : "/framing-brief/latest";
  const { data, error, isLoading } = useSWR<FramingBrief>(url, fetcher, {
    refreshInterval: selectedDate ? 0 : REFRESH_MS,
  });

  return (
    <div className="min-h-screen bg-background">
      <header className="sticky top-0 z-50 border-b border-border bg-background/95 backdrop-blur">
        <div className="mx-auto max-w-[1920px] 2xl:max-w-[2400px] flex items-center justify-between px-6 py-3">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent/10">
              <Activity className="h-5 w-5 text-accent" />
            </div>
            <div>
              <h1 className="font-bold text-foreground tracking-tight">JARVIS TRADER</h1>
              <p className="text-xs text-muted-foreground">Morning Framing Brief</p>
            </div>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1920px] 2xl:max-w-[2400px] px-6 py-6 space-y-6">
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-accent/10">
              <Sunrise className="h-5 w-5 text-accent" />
            </div>
            <div>
              <h2 className="font-mono text-lg font-bold text-foreground tracking-tight">
                Morning Framing Brief
              </h2>
              <p className="font-mono text-[11px] text-muted-foreground mt-0.5">
                Corey-style AMT read for ES/NQ — auto-generated every weekday morning
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
              Date
            </span>
            <input
              type="date"
              value={selectedDate}
              onChange={(e) => setSelectedDate(e.target.value)}
              className="rounded-lg border border-border bg-card px-3 py-1.5 font-mono text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-accent/50"
            />
            {selectedDate && (
              <button
                onClick={() => setSelectedDate("")}
                className="font-mono text-[11px] text-muted-foreground hover:text-foreground underline"
              >
                Latest
              </button>
            )}
          </div>
        </div>

        <div className="rounded-xl border border-border bg-card p-6">
          {isLoading && (
            <p className="font-mono text-xs text-muted-foreground italic">Loading brief…</p>
          )}
          {error && (
            <p className="font-mono text-xs text-muted-foreground italic">
              No framing brief available{selectedDate ? ` for ${selectedDate}` : ""}. The
              scheduled generator may not have run yet, or the engine is unreachable.
            </p>
          )}
          {data && (
            <div className="space-y-4">
              <div className="flex items-center justify-between border-b border-border pb-3">
                <span className="font-mono text-xs font-semibold text-accent">{data.date}</span>
                <span className="font-mono text-[10px] text-muted-foreground">
                  Generated {fmtGeneratedAt(data.generated_at)}
                </span>
              </div>
              {/*
                Plain whitespace-pre-wrap rendering (same pattern as
                components/discord/corey-feed.tsx) rather than a markdown
                renderer — no react-markdown dependency exists in this
                dashboard today. Headers/bold render as literal '#'/'**'
                rather than styled text; upgrading to react-markdown is a
                small follow-up if richer formatting is wanted.
              */}
              <p className="font-mono text-[12px] text-foreground/90 leading-relaxed whitespace-pre-wrap">
                {data.markdown}
              </p>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
