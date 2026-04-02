"use client";
import useSWR from "swr";
import { fetchEngine } from "@/lib/api";
import type { OptionsChainData, OptionsGreeksPortfolio } from "@/lib/api";
import type { ChartSymbol } from "./useChartData";

export function useOptionsChain(symbol: ChartSymbol) {
  const {
    data: chain,
    error: chainError,
    isLoading: chainLoading,
    mutate: mutateChain,
  } = useSWR<OptionsChainData | null>(
    [`/options/chain`, symbol],
    (): Promise<OptionsChainData | null> =>
      fetchEngine<OptionsChainData>(`/options/chain/${symbol}`).catch(() => null),
    { refreshInterval: 300_000, revalidateOnFocus: false, shouldRetryOnError: false }
  );

  const {
    data: greeks,
    error: greeksError,
    isLoading: greeksLoading,
  } = useSWR<OptionsGreeksPortfolio | null>(
    "/options/greeks",
    (): Promise<OptionsGreeksPortfolio | null> =>
      fetchEngine<OptionsGreeksPortfolio>("/options/greeks").catch(() => null),
    { refreshInterval: 60_000, revalidateOnFocus: false, shouldRetryOnError: false }
  );

  return {
    chain,
    chainLoading,
    chainError,
    mutateChain,
    greeks,
    greeksLoading,
    greeksError,
    isLoading: chainLoading || greeksLoading,
  };
}
