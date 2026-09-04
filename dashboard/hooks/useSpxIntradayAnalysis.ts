"use client";

import useSWR from "swr";
import { localFetch } from "@/lib/api";
import type { SpxIntradaySnapshot } from "@/lib/spxIntraday";

function refreshInterval(): number {
  const now = new Date();
  const minutes = now.getHours() * 60 + now.getMinutes();
  // Conservative local-time RTH window. Outside RTH, keep the panel warm but cheap.
  return minutes >= 8 * 60 + 30 && minutes <= 15 * 60 + 15 ? 15_000 : 60_000;
}

export function useSpxIntradayAnalysis() {
  return useSWR<SpxIntradaySnapshot>("/api/spx-intraday", localFetch, {
    refreshInterval,
    revalidateOnFocus: false,
    shouldRetryOnError: false,
  });
}
