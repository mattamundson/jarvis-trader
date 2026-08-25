"use client";

import useSWR from "swr";
import { Database } from "lucide-react";
import { fetchCacheStats, type CacheStatsResponse } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { POLL_INTERVAL } from "@/lib/polling-config";

// ── Engine cache stats (GET /cache/stats) ────────────────────────────────────
// Read-only display of the engine's 30-minute signal-cache hit/miss counters
// (engine routers/cache_router.py -> cache.get_cache_stats()). The router also
// exposes POST /cache/invalidate[/{symbol}] -- intentionally not wired here;
// this panel is display-only, same as the rest of Plan Phase 8 row 6.

function StatBlock({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border bg-card/60 px-3 py-2">
      <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">{label}</p>
      <p className="mt-0.5 font-mono text-sm font-bold text-foreground tabular-nums">{value}</p>
    </div>
  );
}

/** Read-only engine cache-stats card. Mounted on /health alongside the other subsystem cards. */
export function CacheStatsCard() {
  const { data, error, isLoading } = useSWR<CacheStatsResponse>(
    "cache-stats",
    fetchCacheStats,
    { refreshInterval: POLL_INTERVAL.NORMAL, shouldRetryOnError: false }
  );

  return (
    <div className="rounded-xl border border-border bg-card p-4 space-y-3">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Database className="h-4 w-4 text-accent" />
          <span className="text-sm font-semibold text-foreground">Signal Cache</span>
        </div>
        {data && (
          <Badge variant={data.redis_connected ? "bull" : "warn"}>
            {data.redis_connected ? "Redis connected" : "Redis unavailable"}
          </Badge>
        )}
      </div>

      {isLoading && !data && (
        <p className="text-xs text-muted-foreground animate-pulse">Loading cache stats…</p>
      )}
      {error && (
        <p className="text-xs text-muted-foreground">
          /cache/stats unreachable — engine offline or endpoint not deployed.
        </p>
      )}

      {data && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          <StatBlock label="Hits" value={String(data.cache_hits)} />
          <StatBlock label="Misses" value={String(data.cache_misses)} />
          <StatBlock label="Total accesses" value={String(data.total_accesses)} />
          <StatBlock label="Hit rate" value={`${data.hit_rate_percent.toFixed(1)}%`} />
        </div>
      )}

      <p className="font-mono text-[10px] text-muted-foreground/70">
        Read-only. Counters reset on engine restart; cumulative since last boot.
      </p>
    </div>
  );
}
