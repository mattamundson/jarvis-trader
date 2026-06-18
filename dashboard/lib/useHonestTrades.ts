"use client";

import useSWR from "swr";
import { fetchHonestTrades, type HonestTradeSet } from "@/lib/honestTrades";

/**
 * Shared SWR subscription to the honest deduped trade record.
 *
 * Every widget that needs the honest record MUST use this hook instead of its
 * own `useEffect` + `fetchHonestTrades()` + `setInterval`. SWR dedupes by the
 * shared `"honest-trades"` key, so the whole app issues ONE
 * `/master/trading/realized` request per refresh cycle regardless of how many
 * widgets are mounted, and every widget reads the same cached record (no
 * cross-widget divergence between refresh ticks).
 *
 * `fetchHonestTrades()` throws when the engine sim record is unavailable;
 * `shouldRetryOnError: false` keeps that from hammering the endpoint and leaves
 * `honest` null so callers can render their "unavailable" state.
 */
export function useHonestTrades(refreshMs = 60_000) {
  const { data, error, isLoading, mutate } = useSWR<HonestTradeSet>(
    "honest-trades",
    fetchHonestTrades,
    {
      refreshInterval: refreshMs,
      shouldRetryOnError: false,
      errorRetryCount: 0,
    },
  );
  return { honest: data ?? null, error, isLoading, mutate };
}
