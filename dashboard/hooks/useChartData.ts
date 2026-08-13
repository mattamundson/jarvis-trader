"use client";

import { POLL_INTERVAL } from "@/lib/polling-config";
import useSWR from "swr";
import { fetchBars, fetchEngine } from "@/lib/api";
import type {
  OHLCVBar,
  TechnicalAnalysisResult,
  RegimeStatusResult,
  WatchlistScanResponse,
  PipelineHistoryEntry,
} from "@/lib/api";

export type ChartSymbol = "MES" | "MCL" | "MNQ" | "MGC";
export type ChartTimeframe = "5m" | "15m" | "1h" | "4h" | "1d";

// Aliases used by stub components
export type OHLCBar = OHLCVBar;
export type TechnicalSnapshot = TechnicalAnalysisResult;
export interface RegimePoint {
  time: number;
  regime: "TRENDING" | "RANGING" | "VOLATILE" | string;
}

const TIMEFRAME_DAYS: Record<ChartTimeframe, number> = {
  "5m": 3,
  "15m": 7,
  "1h": 30,
  "4h": 60,
  "1d": 365,
};

export function useChartData(symbol: ChartSymbol, timeframe: ChartTimeframe) {
  const days = TIMEFRAME_DAYS[timeframe];

  // OHLCV bars — normalized via the shared fetchBars(), which reads the engine's
  // `timestamp` field. A duplicate inline parse here previously read `time`
  // (the engine sends `timestamp`), so every bar got time=undefined and the
  // chart silently emptied. Reuse fetchBars so there is one source of truth.
  const { data: bars = [], error: barsError, isLoading: barsLoading } = useSWR<OHLCVBar[]>(
    [`/analyze/bars/${symbol}`, timeframe, days],
    () => fetchBars(symbol, { timeframe, days }),
    { refreshInterval: POLL_INTERVAL.MINUTE, revalidateOnFocus: false }
  );

  // Technical analysis (POST endpoint — use SWR with POST)
  const {
    data: technical,
    error: technicalError,
    isLoading: technicalLoading,
  } = useSWR<TechnicalAnalysisResult | null>(
    [`/analyze/technical`, symbol, timeframe],
    (): Promise<TechnicalAnalysisResult | null> =>
      fetchEngine<TechnicalAnalysisResult>("/analyze/technical", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbol, timeframe, is_futures: true }),
      }).catch(() => null),
    { refreshInterval: POLL_INTERVAL.TWO_MINUTES, revalidateOnFocus: false }
  );

  // Regime status
  const { data: regime, error: regimeError } = useSWR<RegimeStatusResult | null>(
    `/backtest/regime-status?symbol=${symbol}&timeframe=${timeframe}`,
    (): Promise<RegimeStatusResult | null> =>
      fetchEngine<RegimeStatusResult>(
        `/backtest/regime-status?symbol=${symbol}&timeframe=${timeframe}`
      ).catch(() => null),
    { refreshInterval: POLL_INTERVAL.TWO_MINUTES, revalidateOnFocus: false }
  );

  // Watchlist scan for signals
  const { data: scanData, error: scanError } = useSWR<WatchlistScanResponse | null>(
    "/watchlist/scan",
    (): Promise<WatchlistScanResponse | null> =>
      fetchEngine<WatchlistScanResponse>("/watchlist/scan").catch(() => null),
    { refreshInterval: POLL_INTERVAL.MINUTE, revalidateOnFocus: false }
  );

  // Pipeline history
  const { data: pipelineHistory, error: pipelineError } = useSWR<PipelineHistoryEntry[] | null>(
    "/pipeline/history",
    (): Promise<PipelineHistoryEntry[] | null> =>
      fetchEngine<PipelineHistoryEntry[]>("/pipeline/history").catch(() => null),
    { refreshInterval: POLL_INTERVAL.SLOW, revalidateOnFocus: false }
  );

  // Find current symbol signal from scan
  const currentSignal = scanData?.symbols?.find((s) => s.symbol === symbol) ?? null;

  return {
    bars,
    barsLoading,
    barsError,
    technical,
    technicalLoading,
    technicalError,
    regime,
    regimeError,
    scanData,
    scanError,
    currentSignal,
    pipelineHistory: pipelineHistory ?? [],
    pipelineError,
    isLoading: barsLoading || technicalLoading,
  };
}
