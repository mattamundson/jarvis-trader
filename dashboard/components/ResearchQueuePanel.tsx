"use client";

import { useMemo, useState } from "react";
import useSWR from "swr";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { BookMarked, ExternalLink, AlertTriangle } from "lucide-react";

// ── Types (mirror second-brain JARVIS_RESEARCH_QUEUE_FEED shape) ─────────────

interface FeedItem {
  summary: string;
  url: string;
  classification: string;
}

interface ResearchFeed {
  report?: string;
  generated_at_utc?: string;
  queue?: {
    strategy_indicator?: FeedItem[];
    risk_position_sizing?: FeedItem[];
    backtest_validation_integrity?: FeedItem[];
  };
}

type QueueKey = keyof NonNullable<ResearchFeed["queue"]>;

const TABS: { key: QueueKey; label: string }[] = [
  { key: "risk_position_sizing", label: "Risk / Sizing" },
  { key: "strategy_indicator", label: "Strategy / Indicators" },
  { key: "backtest_validation_integrity", label: "Validation Integrity" },
];

const FEED_URL = "/jarvis-research-queue-feed.json";

// ── Component ────────────────────────────────────────────────────────────────

export function ResearchQueuePanel() {
  const { data, error, isLoading } = useSWR<ResearchFeed>(
    FEED_URL,
    (url: string) => fetch(url).then((r) => r.json())
  );
  const [tab, setTab] = useState<QueueKey>("risk_position_sizing");

  const items = useMemo(() => data?.queue?.[tab] ?? [], [data, tab]);
  const generatedAt = data?.generated_at_utc
    ? new Date(data.generated_at_utc).toLocaleString()
    : "unknown";

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm font-medium flex items-center gap-2">
          <BookMarked className="h-4 w-4 text-blue-400" />
          X-Bookmarks Research Queue
        </CardTitle>
        <Badge variant="neutral" className="text-[10px] text-zinc-400">
          digest {generatedAt}
        </Badge>
      </CardHeader>
      <CardContent>
        {error ? (
          <div className="flex items-center gap-2 text-xs text-red-400">
            <AlertTriangle className="h-4 w-4" /> Failed to load research feed
          </div>
        ) : isLoading ? (
          <div className="text-xs text-zinc-500">Loading…</div>
        ) : (
          <>
            <div className="mb-3 flex flex-wrap gap-1.5">
              {TABS.map((t) => (
                <button
                  key={t.key}
                  onClick={() => setTab(t.key)}
                  className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                    tab === t.key
                      ? "bg-blue-600/20 text-blue-300 ring-1 ring-blue-500/40"
                      : "text-zinc-400 hover:text-zinc-200"
                  }`}
                >
                  {t.label}
                  <span className="ml-1 text-[10px] text-zinc-500">
                    ({data?.queue?.[t.key]?.length ?? 0})
                  </span>
                </button>
              ))}
            </div>
            <ul className="space-y-2 max-h-72 overflow-y-auto pr-1">
              {items.length === 0 ? (
                <li className="text-xs text-zinc-500">No items in this queue.</li>
              ) : (
                items.map((it, i) => (
                  <li
                    key={`${it.url}-${i}`}
                    className="rounded-md border border-zinc-800 bg-zinc-900/40 p-2.5"
                  >
                    <p className="text-xs leading-snug text-zinc-200">
                      {it.summary || "(no summary)"}
                    </p>
                    <div className="mt-1.5 flex items-center gap-2 text-[10px]">
                      <span className="text-zinc-500">{it.classification}</span>
                      <a
                        href={it.url}
                        target="_blank"
                        rel="noreferrer"
                        className="ml-auto inline-flex items-center gap-1 text-blue-400 hover:text-blue-300"
                      >
                        source <ExternalLink className="h-3 w-3" />
                      </a>
                    </div>
                  </li>
                ))
              )}
            </ul>
            <p className="mt-2 text-[10px] text-zinc-600">
              Paper-only research candidates from the X-bookmarks attachment
              review digest. Not trade signals.
            </p>
          </>
        )}
      </CardContent>
    </Card>
  );
}

export default ResearchQueuePanel;
