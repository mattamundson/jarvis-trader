"use client";

import { useState } from "react";
import useSWR from "swr";
import { Activity, AlertTriangle, Sunrise, Sunset } from "lucide-react";
import { fetchEngine } from "@/lib/api";

const REFRESH_MS = 5 * 60_000;

type Session = "premarket" | "preclose";

const SESSION_TABS: { id: Session; label: string }[] = [
  { id: "premarket", label: "Pre-Market (AM)" },
  { id: "preclose", label: "Pre-Close (PM)" },
];

const SESSION_META: Record<Session, { icon: typeof Sunrise; title: string; subtitle: string }> = {
  premarket: {
    icon: Sunrise,
    title: "Morning Framing Brief",
    subtitle: "Corey-style AMT read for ES/NQ — auto-generated every weekday morning",
  },
  preclose: {
    icon: Sunset,
    title: "Pre-Close Framing Brief",
    subtitle: "Acceptance vs Rejection into the close — auto-generated ~1hr before RTH close",
  },
};

interface FramingBrief {
  date: string;
  session: Session;
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

// The engine returns a 200 with an honest failure brief (rather than a 4xx/5xx)
// when the LLM generator could not run — e.g. credit-balance exhaustion. Detect
// that marker and render a clear failed state instead of raw error markdown.
const FAILURE_RE = /generation failed|credit balance is too low|failed to generate/i;

function isFailedBrief(markdown: string): boolean {
  return FAILURE_RE.test(markdown);
}

function extractFailureReason(markdown: string): string {
  const match = markdown.match(/Reason:\s*([^\n]+)/i);
  return match?.[1]?.trim() ?? "";
}

export default function FramingBriefPage() {
  const [session, setSession] = useState<Session>("premarket");
  // Empty string = "latest"; a YYYY-MM-DD string views a specific past brief.
  const [selectedDate, setSelectedDate] = useState("");

  const base = selectedDate ? `/framing-brief/${selectedDate}` : "/framing-brief/latest";
  const url = `${base}?session=${session}`;
  const { data, error, isLoading } = useSWR<FramingBrief>(url, fetcher, {
    refreshInterval: selectedDate ? 0 : REFRESH_MS,
  });
  const meta = SESSION_META[session];
  const SessionIcon = meta.icon;

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
              <p className="text-xs text-muted-foreground">Market Briefings</p>
            </div>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1920px] 2xl:max-w-[2400px] px-6 py-6 space-y-6">
        {/* Session tabs */}
        <div className="flex gap-1 border-b border-border">
          {SESSION_TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setSession(tab.id)}
              className={`px-4 py-2 font-mono text-xs font-medium transition-colors border-b-2 -mb-px ${
                session === tab.id
                  ? "border-accent text-accent"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-accent/10">
              <SessionIcon className="h-5 w-5 text-accent" />
            </div>
            <div>
              <h2 className="font-mono text-lg font-bold text-foreground tracking-tight">
                {meta.title}
              </h2>
              <p className="font-mono text-[11px] text-muted-foreground mt-0.5">
                {meta.subtitle}
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
          {data &&
            (isFailedBrief(data.markdown) ? (
              <div className="rounded-xl border border-warn/30 bg-warn/5 p-6 text-center space-y-3">
                <AlertTriangle className="h-8 w-8 text-warn mx-auto" />
                <p className="font-mono text-sm font-semibold text-warn">
                  Framing brief generation failed
                </p>
                {extractFailureReason(data.markdown) && (
                  <p className="font-mono text-[11px] text-muted-foreground max-w-2xl mx-auto break-words">
                    {extractFailureReason(data.markdown)}
                  </p>
                )}
                <p className="text-xs text-muted-foreground max-w-2xl mx-auto">
                  No brief was posted for {data.date} — this is an honest gap, not a stale or
                  fabricated read. The generator will retry on the next scheduled session.
                </p>
              </div>
            ) : (
              <div className="space-y-4">
                <div className="flex items-center justify-between border-b border-border pb-3">
                  <span className="font-mono text-xs font-semibold text-accent">{data.date}</span>
                  <span className="font-mono text-[10px] text-muted-foreground">
                    Generated {fmtGeneratedAt(data.generated_at)}
                  </span>
                </div>
                {/* Plain whitespace-pre-wrap rendering (same pattern as
                    components/discord/corey-feed.tsx) rather than a markdown
                    renderer — no react-markdown dependency exists in this
                    dashboard today. Headers/bold render as literal '#'/'**'
                    rather than styled text; upgrading to react-markdown is a
                    small follow-up if richer formatting is wanted. */}
                <p className="font-mono text-[12px] text-foreground/90 leading-relaxed whitespace-pre-wrap">
                  {data.markdown}
                </p>
              </div>
            ))}
        </div>
      </main>
    </div>
  );
}
