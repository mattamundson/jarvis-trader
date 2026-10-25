export type MarketBriefSourceQuality = "fresh" | "stale" | "degraded";

export interface MarketBriefProbabilities {
  continuation: number;
  rotation: number;
  failure: number;
}

export interface MarketBriefProbabilitySource {
  primary?: string;
  conditional_status?: string;
  rationale?: string;
  walkforward?: {
    n?: number;
    mean_brier_model?: number;
    mean_brier_base?: number;
    paired_diff_base_minus_model?: number;
    paired_ci95?: [number, number] | number[];
    paired_t?: number;
    model_beats_base?: boolean;
    verdict?: string;
  };
}

export interface MarketBriefConditionalDiagnostic {
  state?: string;
  n?: number;
  status?: string;
  publish_as_edge?: boolean;
  probabilities?: MarketBriefProbabilities & { sum?: number };
}

export interface MarketBriefScores {
  status: "computed" | "low_confidence" | "degraded" | string;
  macro_event_count?: number;
  inputs?: {
    trend_score?: number;
    vol_score?: number;
    macro_score?: number;
  };
  probabilities: MarketBriefProbabilities;
  probability_source?: MarketBriefProbabilitySource;
  conditional_diagnostic?: MarketBriefConditionalDiagnostic;
  macro_events?: string[];
  notes?: string[];
}

export interface MarketBriefSymbolDaily {
  prev_close?: number | null;
  last_close?: number | null;
  day_open?: number | null;
  day_high?: number | null;
  day_low?: number | null;
  prev_day_high?: number | null;
  prev_day_low?: number | null;
}

export interface MarketBriefPivots {
  pivot?: number | null;
  r1?: number | null;
  s1?: number | null;
  support_2?: number | null;
  resistance_2?: number | null;
}

export interface MarketBriefSymbolSnapshot {
  provider?: string | null;
  confidence?: number | null;
  daily?: MarketBriefSymbolDaily;
  gap_pct?: number | null;
  pivots?: MarketBriefPivots;
}

export interface MarketBriefLevel {
  symbol: string;
  pivot: number | null;
  r1: number | null;
  s1: number | null;
}

export interface MarketBriefSnapshot {
  mode: "ANALYSIS_ONLY";
  orders_enabled: false;
  risk_config_touched: false;
  asOf: string | null;
  generatedAt: string | null;
  sourcePath: string | null;
  sourceQuality: MarketBriefSourceQuality;
  ageSeconds: number | null;
  scores: MarketBriefScores;
  symbols: Record<string, MarketBriefSymbolSnapshot>;
  levels: MarketBriefLevel[];
  warnings: string[];
  modelVersion: string;
}
