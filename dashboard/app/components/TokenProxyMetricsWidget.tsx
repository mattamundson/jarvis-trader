"use client";

import { useEffect, useState } from "react";
import { fetchEngine } from "@/lib/api";

type BadgeVariant = "bull" | "bear" | "warn" | "info" | "neutral";

interface TokenProxyMetrics {
  compressions?: number;
  cache_hits?: number;
  cache_misses?: number;
  chars_original?: number;
  chars_after_compression?: number;
  evictions?: number;
  context_trims?: number;
  market_data_trims?: number;
  available?: boolean;
  error?: string;
}

const POLL_INTERVAL_MS = 5000;

function variantClass(v: BadgeVariant): string {
  switch (v) {
    case "bull":
      return "bg-green-900/40 text-green-300 border-green-700";
    case "bear":
      return "bg-red-900/40 text-red-300 border-red-700";
    case "warn":
      return "bg-amber-900/40 text-amber-300 border-amber-700";
    case "info":
      return "bg-blue-900/40 text-blue-300 border-blue-700";
    case "neutral":
    default:
      return "bg-zinc-800/60 text-zinc-300 border-zinc-600";
  }
}

function Badge({
  variant,
  children,
}: {
  variant: BadgeVariant;
  children: React.ReactNode;
}) {
  return (
    <span
      className={`px-2 py-0.5 text-xs font-medium rounded border ${variantClass(variant)}`}
    >
      {children}
    </span>
  );
}

export default function TokenProxyMetricsWidget() {
  const [metrics, setMetrics] = useState<TokenProxyMetrics | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function fetchMetrics() {
      try {
        const data = await fetchEngine<TokenProxyMetrics>("/obs/token-proxy/metrics");
        if (!cancelled) {
          setMetrics(data);
          setError(null);
          setLastUpdated(new Date());
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : String(e));
        }
      }
    }

    fetchMetrics();
    const id = setInterval(fetchMetrics, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  if (error && !metrics) {
    return (
      <div className="p-4 rounded-lg border border-zinc-800 bg-zinc-950">
        <h3 className="text-sm font-semibold text-zinc-300 mb-2">
          Token Proxy Metrics
        </h3>
        <Badge variant="bear">Error: {error}</Badge>
      </div>
    );
  }

  if (!metrics) {
    return (
      <div className="p-4 rounded-lg border border-zinc-800 bg-zinc-950">
        <h3 className="text-sm font-semibold text-zinc-300 mb-2">
          Token Proxy Metrics
        </h3>
        <Badge variant="neutral">Loading...</Badge>
      </div>
    );
  }

  const original = metrics.chars_original ?? 0;
  const compressed = metrics.chars_after_compression ?? 0;
  const savings = original > 0 ? ((original - compressed) / original) * 100 : 0;
  const savingsVariant: BadgeVariant =
    savings > 20 ? "bull" : savings >= 10 ? "info" : "neutral";

  const hits = metrics.cache_hits ?? 0;
  const misses = metrics.cache_misses ?? 0;
  const total = hits + misses;
  const hitRate = total > 0 ? (hits / total) * 100 : 0;
  const hitRateVariant: BadgeVariant =
    hitRate > 50 ? "bull" : hitRate >= 20 ? "info" : "neutral";

  const evictions = metrics.evictions ?? 0;
  const evictionsVariant: BadgeVariant = evictions > 50 ? "warn" : "neutral";

  return (
    <div className="p-4 rounded-lg border border-zinc-800 bg-zinc-950 space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-zinc-300">
          Token Proxy Metrics
        </h3>
        {lastUpdated && (
          <span className="text-xs text-zinc-500">
            {lastUpdated.toLocaleTimeString()}
          </span>
        )}
      </div>

      <div className="grid grid-cols-2 gap-3 text-xs">
        <div className="space-y-1">
          <div className="text-zinc-500">Compression savings</div>
          <Badge variant={savingsVariant}>{savings.toFixed(1)}%</Badge>
        </div>

        <div className="space-y-1">
          <div className="text-zinc-500">Cache hit rate</div>
          <Badge variant={hitRateVariant}>{hitRate.toFixed(1)}%</Badge>
        </div>

        <div className="space-y-1">
          <div className="text-zinc-500">Compressions</div>
          <span className="text-zinc-200 font-mono">
            {metrics.compressions ?? 0}
          </span>
        </div>

        <div className="space-y-1">
          <div className="text-zinc-500">Evictions</div>
          <Badge variant={evictionsVariant}>{evictions}</Badge>
        </div>
      </div>

      {error && (
        <div className="text-xs text-amber-400">Last fetch error: {error}</div>
      )}
    </div>
  );
}
