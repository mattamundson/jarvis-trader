"use client";

import useSWR from "swr";
import { localFetch } from "@/lib/api";
import type { MarketBriefSnapshot } from "@/lib/marketBrief/types";

export function useMarketBrief() {
  return useSWR<MarketBriefSnapshot>("/api/market-brief", localFetch, {
    refreshInterval: 60_000,
    revalidateOnFocus: false,
    shouldRetryOnError: false,
  });
}
