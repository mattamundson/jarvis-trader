"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import useSWR from "swr";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Bookmark, Search } from "lucide-react";
import {
  fetchBookmarksRecent,
  fetchBookmarksSearch,
  type BookmarkRow,
  type BookmarkFeedResponse,
} from "@/lib/api";

// ── Constants ─────────────────────────────────────────────────────────────────

type FeedMode = "recent" | "search";

type SourceFilter = "all" | "x_post" | "github" | "video" | "other";

type RecentHours = 24 | 72 | 168 | 720;

const RECENT_HOURS_OPTIONS: { label: string; value: RecentHours }[] = [
  { label: "24h", value: 24 },
  { label: "3d", value: 72 },
  { label: "7d", value: 168 },
  { label: "30d", value: 720 },
];

const SOURCE_OPTIONS: { label: string; value: SourceFilter }[] = [
  { label: "All sources", value: "all" },
  { label: "X / Twitter", value: "x_post" },
  { label: "GitHub", value: "github" },
  { label: "Video", value: "video" },
  { label: "Other", value: "other" },
];

const SEARCH_DAYS_DEFAULT = 30;
const DEBOUNCE_MS = 400;
const MIN_QUERY_LEN = 2;

// ── Helpers ───────────────────────────────────────────────────────────────────

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

function sourceChipVariant(src: string | null): "info" | "neutral" {
  if (src === "x_post" || src === "github") return "info";
  return "neutral";
}

function sourceLabel(src: string | null): string {
  if (!src) return "link";
  if (src === "x_post") return "X post";
  if (src === "github") return "GitHub";
  if (src === "video") return "video";
  return src;
}

function titleForRow(row: BookmarkRow): string {
  if (row.embed_title) return row.embed_title;
  try {
    const u = new URL(row.url);
    const path = u.pathname.replace(/\/$/, "");
    return (u.hostname.replace(/^www\./, "") + (path || "/")).slice(0, 80);
  } catch {
    return row.url.slice(0, 80);
  }
}

// ── Sub-components ────────────────────────────────────────────────────────────

function LoadingSkeleton() {
  return (
    <Card className="border-zinc-800 bg-zinc-950/60">
      <CardHeader className="py-3">
        <CardTitle className="text-sm font-medium text-zinc-300 flex items-center gap-2">
          <Bookmark className="h-4 w-4" /> Bookmark Feed
        </CardTitle>
      </CardHeader>
      <CardContent className="pb-4 space-y-2">
        {[1, 2, 3, 4, 5].map((i) => (
          <div key={i} className="h-12 animate-pulse rounded bg-zinc-800/80" />
        ))}
      </CardContent>
    </Card>
  );
}

function ErrorState({ message }: { message: string }) {
  return (
    <Card className="border-zinc-800 bg-zinc-950/60">
      <CardHeader className="py-3">
        <CardTitle className="text-sm font-medium text-zinc-300 flex items-center gap-2">
          <Bookmark className="h-4 w-4" /> Bookmark Feed
        </CardTitle>
      </CardHeader>
      <CardContent className="pb-3">
        <p className="text-xs text-rose-400">Feed unavailable — check engine logs</p>
        <p className="text-[10px] text-zinc-600 mt-1 font-mono break-all">{message}</p>
      </CardContent>
    </Card>
  );
}

function EmptyState({ mode }: { mode: FeedMode }) {
  return (
    <p className="text-xs text-zinc-500 italic py-2">
      {mode === "search"
        ? "No bookmarks matched your query."
        : "No bookmarks in this time window."}
    </p>
  );
}

function BookmarkItem({ row }: { row: BookmarkRow }) {
  const title = titleForRow(row);
  const variant = sourceChipVariant(row.source_type);

  return (
    <div className="rounded border border-zinc-800 bg-zinc-900/50 p-2.5 space-y-1">
      {/* Title + timestamp row */}
      <div className="flex items-start justify-between gap-2">
        <a
          href={row.url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-xs font-medium text-zinc-100 hover:text-white leading-snug line-clamp-2 transition-colors"
          title={row.url}
        >
          {title}
        </a>
        <span className="text-[10px] text-zinc-500 shrink-0 font-mono">
          {relativeTime(row.posted_at)}
        </span>
      </div>

      {/* Badges row */}
      <div className="flex items-center gap-1.5 flex-wrap">
        <Badge variant={variant} className="text-[10px] border-zinc-700">
          {sourceLabel(row.source_type)}
        </Badge>
        {row.domain && (
          <Badge variant="neutral" className="text-[10px] border-zinc-700 text-zinc-500">
            {row.domain}
          </Badge>
        )}
      </div>

      {/* Description snippet */}
      {row.embed_description && (
        <p className="text-[11px] text-zinc-400 leading-relaxed line-clamp-2">
          {row.embed_description}
        </p>
      )}
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export function BookmarkFeedPanel() {
  const [mode, setMode] = useState<FeedMode>("recent");
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>("all");
  const [recentHours, setRecentHours] = useState<RecentHours>(168);
  const [searchInput, setSearchInput] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Debounce search input
  const handleSearchChange = useCallback((val: string) => {
    setSearchInput(val);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      setDebouncedQuery(val.trim());
    }, DEBOUNCE_MS);
  }, []);

  // Clean up debounce on unmount
  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, []);

  // SWR key — null key suppresses fetch
  const recentKey =
    mode === "recent" ? `/discord/bookmarks/recent?hours=${recentHours}` : null;

  const searchKey =
    mode === "search" && debouncedQuery.length >= MIN_QUERY_LEN
      ? `/discord/bookmarks/search?query=${encodeURIComponent(debouncedQuery)}&days=${SEARCH_DAYS_DEFAULT}`
      : null;

  const { data: recentData, error: recentError, isLoading: recentLoading } =
    useSWR<BookmarkFeedResponse>(
      recentKey,
      () => fetchBookmarksRecent({ hours: recentHours }),
      { revalidateOnFocus: false }
    );

  const { data: searchData, error: searchError, isLoading: searchLoading } =
    useSWR<BookmarkFeedResponse>(
      searchKey,
      () => fetchBookmarksSearch({ query: debouncedQuery, days: SEARCH_DAYS_DEFAULT }),
      { revalidateOnFocus: false }
    );

  const isLoading = mode === "recent" ? recentLoading : searchLoading;
  const error = mode === "recent" ? recentError : searchError;
  const rawRows = (mode === "recent" ? recentData?.data : searchData?.data) ?? [];

  // Apply source filter
  const rows =
    sourceFilter === "all"
      ? rawRows
      : rawRows.filter((r) => (r.source_type ?? "other") === sourceFilter);

  const totalCount = rawRows.length;

  // ── Render ─────────────────────────────────────────────────────────────────

  if (isLoading && rows.length === 0) {
    return <LoadingSkeleton />;
  }

  if (error) {
    const msg = String((error as Error)?.message ?? error);
    return <ErrorState message={msg} />;
  }

  return (
    <Card className="border-zinc-800 bg-zinc-950/60">
      <CardHeader className="py-3 space-y-2">
        {/* Title row */}
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="text-sm font-medium text-zinc-300 flex items-center gap-2">
            <Bookmark className="h-4 w-4" /> Bookmark Feed
          </CardTitle>
          {/* Mode toggle */}
          <div className="flex items-center rounded border border-zinc-700 overflow-hidden text-[10px]">
            {(["recent", "search"] as FeedMode[]).map((m) => (
              <button
                key={m}
                onClick={() => setMode(m)}
                className={`px-2.5 py-0.5 transition-colors ${
                  mode === m
                    ? "bg-zinc-700 text-zinc-100"
                    : "bg-zinc-900 text-zinc-500 hover:text-zinc-300"
                }`}
              >
                {m === "recent" ? "Recent" : "Search"}
              </button>
            ))}
          </div>
        </div>

        {/* Filter row */}
        <div className="flex items-center gap-2 flex-wrap">
          {/* Source filter */}
          <select
            value={sourceFilter}
            onChange={(e) => setSourceFilter(e.target.value as SourceFilter)}
            className="rounded border border-zinc-700 bg-zinc-900 px-2 py-0.5 text-[11px] text-zinc-300 focus:outline-none focus:ring-1 focus:ring-zinc-600"
          >
            {SOURCE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>

          {/* Time range (recent mode only) */}
          {mode === "recent" && (
            <div className="flex items-center rounded border border-zinc-700 overflow-hidden text-[10px]">
              {RECENT_HOURS_OPTIONS.map((o) => (
                <button
                  key={o.value}
                  onClick={() => setRecentHours(o.value)}
                  className={`px-2 py-0.5 transition-colors ${
                    recentHours === o.value
                      ? "bg-zinc-700 text-zinc-100"
                      : "bg-zinc-900 text-zinc-500 hover:text-zinc-300"
                  }`}
                >
                  {o.label}
                </button>
              ))}
            </div>
          )}

          {/* Count badge */}
          {totalCount > 0 && (
            <Badge variant="neutral" className="border-zinc-700 text-zinc-500 text-[10px] ml-auto">
              {rows.length === totalCount
                ? `${totalCount} bookmark${totalCount !== 1 ? "s" : ""}`
                : `${rows.length} / ${totalCount}`}
            </Badge>
          )}
        </div>

        {/* Search input (search mode only) */}
        {mode === "search" && (
          <div className="relative">
            <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3 w-3 text-zinc-500" />
            <input
              type="text"
              value={searchInput}
              onChange={(e) => handleSearchChange(e.target.value)}
              placeholder="Search bookmarks… (min 2 chars)"
              className="w-full rounded border border-zinc-700 bg-zinc-900 pl-6 pr-3 py-1 text-xs text-zinc-200 placeholder-zinc-600 focus:outline-none focus:ring-1 focus:ring-zinc-600"
            />
          </div>
        )}
      </CardHeader>

      <CardContent className="pb-4 space-y-2">
        {/* Search idle state */}
        {mode === "search" && debouncedQuery.length < MIN_QUERY_LEN && (
          <p className="text-xs text-zinc-500 italic py-2">
            Type at least 2 characters to search.
          </p>
        )}

        {/* Loading indicator for in-flight search/refresh */}
        {isLoading && rows.length > 0 && (
          <p className="text-[10px] text-zinc-600 animate-pulse">Refreshing…</p>
        )}

        {/* Empty state */}
        {!isLoading &&
          rows.length === 0 &&
          (mode === "recent" || debouncedQuery.length >= MIN_QUERY_LEN) && (
            <EmptyState mode={mode} />
          )}

        {/* Bookmark list */}
        {rows.map((row, idx) => (
          <BookmarkItem key={`${row.url}-${idx}`} row={row} />
        ))}
      </CardContent>
    </Card>
  );
}
