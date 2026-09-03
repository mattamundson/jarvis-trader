export type SpxOperatorVerdict =
  | "CONTINUATION"
  | "PIN_CHOP"
  | "BREAKOUT_FAILURE_TEST"
  | "REVERSAL_CONFIRMED"
  | "DATA_DEGRADED";

export type SpxProxyUsed = "SPX_DIRECT" | "ES_ADJUSTED" | "SPY_PROXY";
export type SourceQuality = "fresh" | "stale" | "degraded";

export interface IntradayBar {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
  vwap?: number;
}

export interface MarketPriceEntry {
  symbol: string;
  last_price: number | null;
  prev_close: number | null;
  change_pct: number | null;
  source?: string;
  as_of?: number | null;
  is_live?: boolean;
  stale_after_s?: number;
  error?: string;
}

export type MarketPriceSnapshot = Record<string, MarketPriceEntry>;

export interface SpxIntradayInputs {
  asOf: string;
  prices: MarketPriceSnapshot;
  bars: IntradayBar[];
  proxyUsed: SpxProxyUsed;
  warnings: string[];
}

export interface SpxDecisionLevel {
  label: string;
  value: number;
  distance: number;
  status: "above" | "below" | "at" | "lost" | "reclaimed";
  role: "support" | "resistance" | "pivot" | "failure" | "target";
}

export interface SpxScenarioProbability {
  id: string;
  label: string;
  probability: number;
  expectedCloseBand: [number, number];
  trigger: string;
  invalidation: string;
}

export interface SpxProbabilityBands {
  p10: number;
  p25: number;
  p50: number;
  p75: number;
  p90: number;
  closeAbove: Record<string, number>;
  closeBelow: Record<string, number>;
  touchAbove: Record<string, number>;
  touchBelow: Record<string, number>;
  remainingMinutes: number;
  blendedSigmaPoints: number;
}

export interface SpxIntradayMetrics {
  currentPrice: number | null;
  dayHigh: number | null;
  dayLow: number | null;
  dayChangePct: number | null;
  previousClose: number | null;
  vix: number | null;
  vixChangePct: number | null;
  rsi14: number | null;
  ema9: number | null;
  ema21: number | null;
  sma50: number | null;
  vwap: number | null;
  returns: {
    fiveMinPct: number | null;
    fifteenMinPct: number | null;
    thirtyMinPct: number | null;
    sixtyMinPct: number | null;
  };
  breadth: {
    spyPct: number | null;
    qqqPct: number | null;
    rspPct: number | null;
    iwmPct: number | null;
    spyRspSpread: number | null;
    qqqIwmSpread: number | null;
    sectorsGreen: number | null;
    sectorsTotal: number | null;
  };
  levels: SpxDecisionLevel[];
}

export interface SpxVerdict {
  label: SpxOperatorVerdict;
  confidence: number;
  summary: string;
  bullEvidence: string[];
  bearEvidence: string[];
  invalidation: string[];
}

export interface SpxIntradaySnapshot extends SpxIntradayMetrics {
  mode: "ANALYSIS_ONLY";
  orders_enabled: false;
  risk_config_touched: false;
  asOf: string;
  symbol: "SPX";
  proxyUsed: SpxProxyUsed;
  sourceQuality: SourceQuality;
  probabilityBands: SpxProbabilityBands | null;
  scenarios: SpxScenarioProbability[];
  verdict: SpxVerdict;
  warnings: string[];
  modelVersion: string;
}
