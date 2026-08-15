"use client";

import { useState } from "react";
import useSWR from "swr";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchEngine } from "@/lib/api";
import { BookMarked, RefreshCw, ExternalLink } from "lucide-react";

// ── Types (mirrors engine ClusterResult.to_dict() + Theme) ───────────────────

export interface BookmarkTheme {
  name: string;
  description: string;
  count: number;
  urls: string[];
  confidence: number;
}

export interface BookmarkThemesResponse {
  themes: BookmarkTheme[];
  bookmark_count: number;
  lookback_days: number;
  model: string;
  latency_ms: number;
  cost_usd: number;
  cached: boolean;
  actionable: boolean;
  error: string | null;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function confidenceColor(c: number): string {
  if (c >= 0.8) return "text-emerald-400";
  if (c >= 0.6) return "text-yellow-400";
  return "text-zinc-400";
}

function confidenceBarColor(c: number): string {
  if (c >= 0.8) return "bg-emerald-500";
  if (c >= 0.6) return "bg-yellow-500";
  return "bg-zinc-500";
}

function shortenUrl(url: string): string {
  try {
    const u = new URL(url);
    return u.hostname.replace(/^www\./, "") + (u.pathname.length > 30 ? u.pathname.slice(0, 28) + "…" : u.pathname);
  } catch {
    return url.length > 50 ? url.slice(0, 48) + "…" : url;
  }
}

// ── Main component ────────────────────────────────────────────────────────────

const BASE_PATH = "/discord/bookmarks/weekly-themes";

export function BookmarkThemesPanel() {
  const [forceKey, setForceKey] = useState(0);
  const [isRefreshing, setIsRefreshing] = useState(false);

  // Normal SWR key; refreshes every 30 minutes (data has 6h cache on the engine side)
  const swrKey = forceKey === 0 ? BASE_PATH : `${BASE_PATH}?refresh=true&_k=${forceKey}`;

  const { data, error, isLoading, mutate } = useSWR<BookmarkThemesResponse>(
    swrKey,
    (path: string) => fetchEngine<BookmarkThemesResponse>(path),
    { refreshInterval: 30 * 60 * 1000, revalidateOnFocus: false }
  );

  const handleRefresh = async () => {
    setIsRefreshing(true);
    setForceKey((k) => k + 1);
    try {
      await mutate();
    } finally {
      setIsRefreshing(false);
    }
  };

  // ── Loading state ──────────────────────────────────────────────────────────
  if (isLoading) {
    return (
      <Card className="border-zinc-800 bg-zinc-950/60">
        <CardHeader className="py-3">
          <CardTitle className="text-sm font-medium text-zinc-300 flex items-center gap-2">
            <BookMarked className="h-4 w-4" /> Bookmark Themes
          </CardTitle>
        </CardHeader>
        <CardContent className="pb-4 space-y-2">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-16 animate-pulse rounded bg-zinc-800/80" />
          ))}
        </CardContent>
      </Card>
    );
  }

  // ── Error state ────────────────────────────────────────────────────────────
  if (error || data?.error) {
    const msg = error
      ? String((error as Error)?.message ?? error)
      : data?.error ?? "unknown error";
    return (
      <Card className="border-zinc-800 bg-zinc-950/60">
        <CardHeader className="py-3">
          <CardTitle className="text-sm font-medium text-zinc-300 flex items-center gap-2">
            <BookMarked className="h-4 w-4" /> Bookmark Themes
          </CardTitle>
        </CardHeader>
        <CardContent className="pb-3">
          <p className="text-xs text-rose-400">
            Clusterer offline — check engine logs
          </p>
          <p className="text-[10px] text-zinc-600 mt-1 font-mono break-all">{msg}</p>
        </CardContent>
      </Card>
    );
  }

  const themes = data?.themes ?? [];

  // ── Empty state ────────────────────────────────────────────────────────────
  if (themes.length === 0) {
    return (
      <Card className="border-zinc-800 bg-zinc-950/60">
        <CardHeader className="py-3">
          <div className="flex items-center justify-between gap-2">
            <CardTitle className="text-sm font-medium text-zinc-300 flex items-center gap-2">
              <BookMarked className="h-4 w-4" /> Bookmark Themes
            </CardTitle>
            <RefreshButton onClick={handleRefresh} loading={isRefreshing} />
          </div>
        </CardHeader>
        <CardContent className="pb-3">
          <p className="text-xs text-zinc-500 italic">
            No themes yet — clusterer needs ≥ 4 bookmarks in the lookback window.
          </p>
        </CardContent>
      </Card>
    );
  }

  // ── Normal render ──────────────────────────────────────────────────────────
  return (
    <Card className="border-zinc-800 bg-zinc-950/60">
      <CardHeader className="py-3">
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="text-sm font-medium text-zinc-300 flex items-center gap-2">
            <BookMarked className="h-4 w-4" /> Bookmark Themes
          </CardTitle>
          <div className="flex items-center gap-2">
            {data?.cached && (
              <Badge variant="neutral" className="border-zinc-700 text-zinc-500 text-[10px]">
                cached
              </Badge>
            )}
            <Badge variant="neutral" className="border-zinc-700 text-zinc-400 text-[10px]">
              {data?.bookmark_count ?? 0} bookmarks · {data?.lookback_days ?? 7}d
            </Badge>
            <RefreshButton onClick={handleRefresh} loading={isRefreshing} />
          </div>
        </div>
        <p className="text-[11px] text-zinc-500 mt-1">
          Claude-clustered Discord bookmark themes. Haiku-powered, 6h cache, ~$0.02/run.
        </p>
      </CardHeader>

      <CardContent className="pb-4 space-y-3">
        {themes.map((theme, idx) => (
          <ThemeCard key={`${theme.name}-${idx}`} theme={theme} />
        ))}

        {/* Footer meta */}
        <div className="flex items-center justify-between pt-1 text-[10px] text-zinc-600">
          <span>{themes.length} theme{themes.length !== 1 ? "s" : ""} identified</span>
          {data?.model && (
            <span className="font-mono">{data.model.split("-").slice(-2).join("-")}</span>
          )}
          {data?.latency_ms ? (
            <span>{data.latency_ms}ms · ${data.cost_usd?.toFixed(4) ?? "0.0000"}</span>
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}

// ── ThemeCard sub-component ───────────────────────────────────────────────────

function ThemeCard({ theme }: { theme: BookmarkTheme }) {
  const pct = Math.round(theme.confidence * 100);
  const topUrls = theme.urls.slice(0, 3);

  return (
    <div className="rounded border border-zinc-800 bg-zinc-900/50 p-3 space-y-2">
      {/* Title row */}
      <div className="flex items-start justify-between gap-2">
        <p className="text-xs font-semibold text-zinc-100 leading-snug">{theme.name}</p>
        <span
          className={`text-xs font-mono shrink-0 ${confidenceColor(theme.confidence)}`}
          title="Model confidence"
        >
          {pct}%
        </span>
      </div>

      {/* Confidence bar */}
      <div className="h-1 w-full rounded-full bg-zinc-800">
        <div
          className={`h-1 rounded-full transition-all ${confidenceBarColor(theme.confidence)}`}
          style={{ width: `${pct}%` }}
        />
      </div>

      {/* Description */}
      <p className="text-[11px] text-zinc-400 leading-relaxed">{theme.description}</p>

      {/* Bookmark count + URLs */}
      <div className="flex items-center justify-between gap-1">
        <Badge variant="neutral" className="border-zinc-700 text-zinc-500 text-[10px]">
          {theme.count} bookmark{theme.count !== 1 ? "s" : ""}
        </Badge>
      </div>

      {topUrls.length > 0 && (
        <ul className="space-y-1">
          {topUrls.map((url, i) => (
            <li key={i}>
              <a
                href={url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-[10px] text-zinc-500 hover:text-zinc-300 transition-colors font-mono"
                title={url}
              >
                <ExternalLink className="h-2.5 w-2.5 shrink-0" />
                <span className="truncate max-w-[240px]">{shortenUrl(url)}</span>
              </a>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ── RefreshButton sub-component ───────────────────────────────────────────────

function RefreshButton({ onClick, loading }: { onClick: () => void; loading: boolean }) {
  return (
    <button
      onClick={onClick}
      disabled={loading}
      title="Force-refresh themes (bypasses 6h cache, costs ~$0.02)"
      className="inline-flex items-center gap-1 rounded border border-zinc-700 bg-zinc-900 px-2 py-0.5 text-[10px] text-zinc-400 hover:text-zinc-200 hover:border-zinc-600 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
    >
      <RefreshCw className={`h-3 w-3 ${loading ? "animate-spin" : ""}`} />
      {loading ? "Refreshing…" : "Refresh"}
    </button>
  );
}
