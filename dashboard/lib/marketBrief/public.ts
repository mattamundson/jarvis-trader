import type { MarketBriefSnapshot } from "./types";

export interface PublicMarketBriefSnapshot {
  mode: "ANALYSIS_ONLY";
  orders_enabled: false;
  risk_config_touched: false;
  generatedAt: string | null;
  asOf: string | null;
  sourceQuality: MarketBriefSnapshot["sourceQuality"];
  ageSeconds: number | null;
  scores: MarketBriefSnapshot["scores"];
  symbols: MarketBriefSnapshot["symbols"];
  levels: MarketBriefSnapshot["levels"];
  warnings: string[];
  modelVersion: string;
  publicContract: {
    surface: "public_market_brief";
    tradingControlsExposed: false;
    localPathExposed: false;
    probabilityContract: "trailing_unconditional_base_rate_primary";
  };
}

export function toPublicMarketBrief(snapshot: MarketBriefSnapshot): PublicMarketBriefSnapshot {
  return {
    mode: "ANALYSIS_ONLY",
    orders_enabled: false,
    risk_config_touched: false,
    generatedAt: snapshot.generatedAt,
    asOf: snapshot.asOf,
    sourceQuality: snapshot.sourceQuality,
    ageSeconds: snapshot.ageSeconds,
    scores: snapshot.scores,
    symbols: snapshot.symbols,
    levels: snapshot.levels,
    warnings: snapshot.warnings,
    modelVersion: snapshot.modelVersion,
    publicContract: {
      surface: "public_market_brief",
      tradingControlsExposed: false,
      localPathExposed: false,
      probabilityContract: "trailing_unconditional_base_rate_primary",
    },
  };
}
