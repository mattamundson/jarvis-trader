"use client";
import useSWR from "swr";
import { fetchEngine } from "@/lib/api";
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

  // OHLCV bars
  const { data: rawBars, error: barsError, isLoading: barsLoading } = useSWR<OHLCVBar[]>(
    [`/analyze/bars/${symbol}`, timeframe, days],
    (): Promise<OHLCVBar[]> =>
      fetchEngine<OHLCVBar[]>(
        `/analyze/bars/${symbol}?timeframe=${timeframe}&days=${days}&futures=true`
      ).catch(() => [] as OHLCVBar[]),
    { refreshInterval: 60_000, revalidateOnFocus: false }
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
    { refreshInterval: 120_000, revalidateOnFocus: false }
  );

  // Regime status
  const { data: regime, error: regimeError } = useSWR<RegimeStatusResult | null>(
    `/backtest/regime-status?symbol=${symbol}&timeframe=${timeframe}`,
    (): Promise<RegimeStatusResult | null> =>
      fetchEngine<RegimeStatusResult>(
        `/backtest/regime-status?symbol=${symbol}&timeframe=${timeframe}`
      ).catch(() => null),
    { refreshInterval: 120_000, revalidateOnFocus: false }
  );

  // Watchlist scan for signals
  const { data: scanData, error: scanError } = useSWR<WatchlistScanResponse | null>(
    "/watchlist/scan",
    (): Promise<WatchlistScanResponse | null> =>
      fetchEngine<WatchlistScanResponse>("/watchlist/scan").catch(() => null),
    { refreshInterval: 60_000, revalidateOnFocus: false }
  );

  // Pipeline history
  const { data: pipelineHistory, error: pipelineError } = useSWR<PipelineHistoryEntry[] | null>(
    "/pipeline/history",
    (): Promise<PipelineHistoryEntry[] | null> =>
      fetchEngine<PipelineHistoryEntry[]>("/pipeline/history").catch(() => null),
    { refreshInterval: 30_000, revalidateOnFocus: false }
  );

  // Parse bars into lightweight-charts format.
  // The engine returns BarsResponse {symbol, timeframe, bars: [...], count, vwap_current, vwap_trend}.
  // The SWR type says OHLCVBar[], but the runtime payload can be either a bare
  // array or that wrapper object, so parse defensively against a loose RawBar.
  type RawBar = {
    time: string | number;
    open: number | string;
    high: number | string;
    low: number | string;
    close: number | string;
    volume?: number | string | null;
    vwap?: number | string | null;
    stc?: number | string | null;
  };
  const rawValue = rawBars as unknown;
  const rawBarsArray: RawBar[] = Array.isArray(rawValue)
    ? (rawValue as RawBar[])
    : Array.isArray((rawValue as { bars?: RawBar[] })?.bars)
    ? ((rawValue as { bars?: RawBar[] }).bars as RawBar[])
    : [];

  const bars: OHLCVBar[] = rawBarsArray
    .map((b: RawBar) => ({
      time: typeof b.time === "string" ? Math.floor(new Date(b.time).getTime() / 1000) : b.time,
      open: Number(b.open),
      high: Number(b.high),
      low: Number(b.low),
      close: Number(b.close),
      volume: b.volume != null ? Number(b.volume) : undefined,
      vwap: b.vwap != null ? Number(b.vwap) : undefined,
      stc: b.stc != null ? Number(b.stc) : undefined,
    }))
    .sort((a, b) => a.time - b.time);

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
