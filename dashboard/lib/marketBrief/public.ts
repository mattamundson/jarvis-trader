import type { MarketBriefProbabilities, MarketBriefSnapshot, MarketBriefSymbolSnapshot } from "./types";

export interface PublicScenario {
  name: string;
  probability: number;
  conditions: string[];
  targets: string[];
  invalidation: string;
}

export interface PublicInstrumentStructure {
  symbol: string;
  label: string;
  resistance: string[];
  support: string[];
  confirmation: string;
  invalidation: string;
  bias: string;
}

export interface PublicMarketBriefAnalysis {
  marketOverview: string[];
  auctionCues: string[];
  volatilityRegime: string[];
  esStructure: PublicInstrumentStructure;
  nqStructure: PublicInstrumentStructure;
  scenarioMap: PublicScenario[];
  intradayPlan: string[];
  finalThoughts: string[];
}

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
  analysis: PublicMarketBriefAnalysis;
  warnings: string[];
  modelVersion: string;
  publicContract: {
    surface: "public_market_brief";
    tradingControlsExposed: false;
    localPathExposed: false;
    probabilityContract: "trailing_unconditional_base_rate_primary";
    analysisContract: "deterministic_machine_payload_summary";
  };
}

function fmt(n: number | null | undefined, dp = 2): string {
  if (n == null || Number.isNaN(n)) return "—";
  return n.toLocaleString("en-US", { minimumFractionDigits: dp, maximumFractionDigits: dp });
}

function pct(n: number | null | undefined, dp = 1): string {
  if (n == null || Number.isNaN(n)) return "—";
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(dp)}%`;
}

function pivot(symbol: MarketBriefSymbolSnapshot | undefined, key: "pivot" | "r1" | "s1" | "support_2" | "resistance_2"): number | null | undefined {
  return symbol?.pivots?.[key];
}

function close(symbol: MarketBriefSymbolSnapshot | undefined): number | null | undefined {
  return symbol?.daily?.last_close;
}

function range(symbol: MarketBriefSymbolSnapshot | undefined): string {
  return `${fmt(symbol?.daily?.day_low)} → ${fmt(symbol?.daily?.day_high)}`;
}

function dominantScenario(probabilities: MarketBriefProbabilities): "continuation" | "rotation" | "failure" {
  const entries = Object.entries(probabilities) as Array<["continuation" | "rotation" | "failure", number]>;
  return entries.sort((a, b) => b[1] - a[1])[0]?.[0] ?? "continuation";
}

function buildInstrumentStructure(
  label: string,
  symbolKey: "ES=F" | "NQ=F",
  symbol: MarketBriefSymbolSnapshot | undefined,
  probabilities: MarketBriefProbabilities,
): PublicInstrumentStructure {
  const p = pivot(symbol, "pivot");
  const r1 = pivot(symbol, "r1");
  const s1 = pivot(symbol, "s1");
  const r2 = pivot(symbol, "resistance_2");
  const s2 = pivot(symbol, "support_2");
  const last = close(symbol);
  const dom = dominantScenario(probabilities);
  return {
    symbol: symbolKey,
    label,
    resistance: [
      `R1 / first upside reaction: ${fmt(r1)}`,
      `R2 / extension reference: ${fmt(r2)}`,
      `Current session high: ${fmt(symbol?.daily?.day_high)}`,
    ],
    support: [
      `Pivot / control: ${fmt(p)}`,
      `S1 / first downside test: ${fmt(s1)}`,
      `S2 / deeper failed-auction reference: ${fmt(s2)}`,
    ],
    confirmation: last != null && r1 != null
      ? `Continuation confirms only if price accepts above ${fmt(r1)}; one touch is not enough.`
      : "Continuation requires acceptance above the first resistance reference; one touch is not enough.",
    invalidation: last != null && s1 != null
      ? `Continuation invalidates on sustained trade below ${fmt(s1)} / failure to reclaim pivot ${fmt(p)}.`
      : "Continuation invalidates on sustained trade below first support and failure to reclaim pivot.",
    bias: dom === "continuation"
      ? `${label} bias favors continuation while price holds above pivot/control.`
      : dom === "rotation"
        ? `${label} bias favors rotation/absorption until acceptance clears resistance.`
        : `${label} bias favors failure/rejection unless pivot is reclaimed quickly.`,
  };
}

function buildScenarioMap(probabilities: MarketBriefProbabilities, es: MarketBriefSymbolSnapshot | undefined, nq: MarketBriefSymbolSnapshot | undefined): PublicScenario[] {
  return [
    {
      name: "Continuation / higher-value acceptance",
      probability: probabilities.continuation,
      conditions: [
        `ES accepts above ${fmt(pivot(es, "r1"))} and holds pivot/control ${fmt(pivot(es, "pivot"))}.`,
        `NQ confirms above ${fmt(pivot(nq, "r1"))} instead of lagging at resistance.`,
      ],
      targets: [`ES extension reference ${fmt(pivot(es, "resistance_2"))}`, `NQ extension reference ${fmt(pivot(nq, "resistance_2"))}`],
      invalidation: `Sustained ES loss of ${fmt(pivot(es, "s1"))} shifts this from continuation to failure/rotation scoring.`,
    },
    {
      name: "Rotation / absorption near highs",
      probability: probabilities.rotation,
      conditions: [
        `ES holds between ${fmt(pivot(es, "s1"))} and ${fmt(pivot(es, "r1"))}.`,
        "Buyers defend pullbacks but cannot force clean acceptance through resistance.",
      ],
      targets: [`ES control/pivot ${fmt(pivot(es, "pivot"))}`, `NQ control/pivot ${fmt(pivot(nq, "pivot"))}`],
      invalidation: "Clean acceptance above resistance upgrades to continuation; failed support downgrades to failure.",
    },
    {
      name: "Failure / responsive sellers take control",
      probability: probabilities.failure,
      conditions: [
        `ES fails below ${fmt(pivot(es, "s1"))} and cannot reclaim ${fmt(pivot(es, "pivot"))}.`,
        `NQ loses ${fmt(pivot(nq, "s1"))} with VIX firming rather than mean-reverting.`,
      ],
      targets: [`ES downside reference ${fmt(pivot(es, "support_2"))}`, `NQ downside reference ${fmt(pivot(nq, "support_2"))}`],
      invalidation: "Fast reclaim of pivot/control invalidates the failure branch.",
    },
  ];
}

function buildAnalysis(snapshot: MarketBriefSnapshot): PublicMarketBriefAnalysis {
  const probabilities = snapshot.scores.probabilities;
  const es = snapshot.symbols["ES=F"];
  const nq = snapshot.symbols["NQ=F"];
  const spy = snapshot.symbols.SPY;
  const qqq = snapshot.symbols.QQQ;
  const vix = snapshot.symbols["^VIX"];
  const dom = dominantScenario(probabilities);
  const probabilityLine = `Machine distribution: continuation ${probabilities.continuation.toFixed(1)}%, rotation ${probabilities.rotation.toFixed(1)}%, failure ${probabilities.failure.toFixed(1)}%.`;

  return {
    marketOverview: [
      probabilityLine,
      `ES last ${fmt(close(es))}; session range ${range(es)}; gap ${pct(es?.gap_pct, 2)}. NQ last ${fmt(close(nq))}; session range ${range(nq)}; gap ${pct(nq?.gap_pct, 2)}.`,
      `SPY gap ${pct(spy?.gap_pct, 2)} and QQQ gap ${pct(qqq?.gap_pct, 2)} provide cash-index confirmation context; VIX is ${fmt(close(vix))} with ${pct(vix?.gap_pct, 2)} change.`,
      dom === "continuation"
        ? "Primary read: buyers retain higher-value control, but the claim must be confirmed by acceptance above resistance rather than a single touch."
        : dom === "rotation"
          ? "Primary read: market is more likely absorbing/rotating than trending cleanly until resistance is accepted."
          : "Primary read: failure/rejection risk is dominant until pivot/control is reclaimed.",
    ],
    auctionCues: [
      `ES pivot/control is ${fmt(pivot(es, "pivot"))}; acceptance above ${fmt(pivot(es, "r1"))} marks higher-value migration, while loss of ${fmt(pivot(es, "s1"))} marks failed auction risk.`,
      `NQ pivot/control is ${fmt(pivot(nq, "pivot"))}; NQ must confirm above ${fmt(pivot(nq, "r1"))} to validate risk-on continuation.`,
      "Responsive sellers matter only if they create sustained rejection; first resistance touch alone is information, not reversal proof.",
      "The public brief treats all structural claims as scoreable conditions, not narrative certainty.",
    ],
    volatilityRegime: [
      `VIX level ${fmt(close(vix))}; day-over-day/gap proxy ${pct(vix?.gap_pct, 2)}.`,
      vix?.gap_pct != null && vix.gap_pct > 0
        ? "Volatility is firming; continuation needs stronger price acceptance to offset risk-premium expansion."
        : "Volatility is flat/down; continuation has cleaner confirmation if ES/NQ also accept higher value.",
      "A directional read without the VIX regime is downgraded; volatility decides whether a rally is confirmed or fragile.",
    ],
    esStructure: buildInstrumentStructure("ES", "ES=F", es, probabilities),
    nqStructure: buildInstrumentStructure("NQ", "NQ=F", nq, probabilities),
    scenarioMap: buildScenarioMap(probabilities, es, nq),
    intradayPlan: [
      `Early session: test whether ES can accept above ${fmt(pivot(es, "r1"))} or rotate back toward pivot ${fmt(pivot(es, "pivot"))}.`,
      `Midday: continuation remains valid only if pullbacks defend pivot/control; chop between pivot and R1 is rotation, not breakout confirmation.`,
      `Late session: close location versus ES ${fmt(pivot(es, "pivot"))}/${fmt(pivot(es, "r1"))} and NQ ${fmt(pivot(nq, "pivot"))}/${fmt(pivot(nq, "r1"))} determines which branch gets scored.`,
    ],
    finalThoughts: [
      `The site publishes the base-rate probability block because walk-forward testing did not prove that the conditional state model beats the trailing base rate.`,
      "The narrative layer restores the missing market-structure read, but every branch remains tied to explicit probabilities and invalidation levels.",
      "This is decision support only: no orders, broker access, risk config changes, or kill-switch interaction.",
    ],
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
    analysis: buildAnalysis(snapshot),
    warnings: snapshot.warnings,
    modelVersion: snapshot.modelVersion,
    publicContract: {
      surface: "public_market_brief",
      tradingControlsExposed: false,
      localPathExposed: false,
      probabilityContract: "trailing_unconditional_base_rate_primary",
      analysisContract: "deterministic_machine_payload_summary",
    },
  };
}
