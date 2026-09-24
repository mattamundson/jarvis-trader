import type {
  MarketBriefConditionalDiagnostic,
  MarketBriefLevel,
  MarketBriefProbabilitySource,
  MarketBriefScores,
  MarketBriefSnapshot,
  MarketBriefSymbolSnapshot,
} from "./types";

const MODEL_VERSION = "market-brief-machine-score-v1";
const STALE_AFTER_SECONDS = 18 * 60 * 60;

function finiteNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function stringOrNull(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function probability(value: unknown): number {
  const n = finiteNumber(value);
  if (n == null) return 0;
  return Math.max(0, Math.min(100, Number(n.toFixed(1))));
}

function normalizeProbabilitySource(raw: unknown): MarketBriefProbabilitySource | undefined {
  const obj = raw && typeof raw === "object" ? (raw as Record<string, unknown>) : null;
  if (!obj) return undefined;
  const wf = obj.walkforward && typeof obj.walkforward === "object" ? obj.walkforward as Record<string, unknown> : null;
  return {
    primary: stringOrNull(obj.primary) ?? undefined,
    conditional_status: stringOrNull(obj.conditional_status) ?? undefined,
    rationale: stringOrNull(obj.rationale) ?? undefined,
    walkforward: wf ? {
      n: finiteNumber(wf.n) ?? undefined,
      mean_brier_model: finiteNumber(wf.mean_brier_model) ?? undefined,
      mean_brier_base: finiteNumber(wf.mean_brier_base) ?? undefined,
      paired_diff_base_minus_model: finiteNumber(wf.paired_diff_base_minus_model) ?? undefined,
      paired_ci95: Array.isArray(wf.paired_ci95) ? wf.paired_ci95.map(prob => finiteNumber(prob) ?? 0) : undefined,
      paired_t: finiteNumber(wf.paired_t) ?? undefined,
      model_beats_base: typeof wf.model_beats_base === "boolean" ? wf.model_beats_base : undefined,
      verdict: stringOrNull(wf.verdict) ?? undefined,
    } : undefined,
  };
}

function normalizeConditionalDiagnostic(raw: unknown): MarketBriefConditionalDiagnostic | undefined {
  const obj = raw && typeof raw === "object" ? (raw as Record<string, unknown>) : null;
  if (!obj) return undefined;
  const probsRaw = obj.probabilities && typeof obj.probabilities === "object" ? obj.probabilities as Record<string, unknown> : {};
  return {
    state: stringOrNull(obj.state) ?? undefined,
    n: finiteNumber(obj.n) ?? undefined,
    status: stringOrNull(obj.status) ?? undefined,
    publish_as_edge: typeof obj.publish_as_edge === "boolean" ? obj.publish_as_edge : undefined,
    probabilities: {
      continuation: probability(probsRaw.continuation),
      rotation: probability(probsRaw.rotation),
      failure: probability(probsRaw.failure),
      sum: probability(probsRaw.sum),
    },
  };
}

function normalizeScores(raw: unknown): MarketBriefScores {
  const obj = raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
  const probsRaw = obj.probabilities && typeof obj.probabilities === "object" ? obj.probabilities as Record<string, unknown> : {};
  const probabilities = {
    continuation: probability(probsRaw.continuation),
    rotation: probability(probsRaw.rotation),
    failure: probability(probsRaw.failure),
  };

  return {
    status: typeof obj.status === "string" ? obj.status : "degraded",
    macro_event_count: finiteNumber(obj.macro_event_count) ?? undefined,
    inputs: obj.inputs && typeof obj.inputs === "object" ? {
      trend_score: finiteNumber((obj.inputs as Record<string, unknown>).trend_score) ?? undefined,
      vol_score: finiteNumber((obj.inputs as Record<string, unknown>).vol_score) ?? undefined,
      macro_score: finiteNumber((obj.inputs as Record<string, unknown>).macro_score) ?? undefined,
    } : undefined,
    probabilities,
    probability_source: normalizeProbabilitySource(obj.probability_source),
    conditional_diagnostic: normalizeConditionalDiagnostic(obj.conditional_diagnostic),
    macro_events: Array.isArray(obj.macro_events) ? obj.macro_events.filter((v): v is string => typeof v === "string") : [],
    notes: Array.isArray(obj.notes) ? obj.notes.filter((v): v is string => typeof v === "string") : [],
  };
}

function normalizeSymbol(raw: unknown): MarketBriefSymbolSnapshot {
  const obj = raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
  const dailyRaw = obj.daily && typeof obj.daily === "object" ? obj.daily as Record<string, unknown> : {};
  const pivotsRaw = obj.pivots && typeof obj.pivots === "object" ? obj.pivots as Record<string, unknown> : {};
  return {
    provider: stringOrNull(obj.provider),
    confidence: finiteNumber(obj.confidence),
    gap_pct: finiteNumber(obj.gap_pct),
    daily: {
      prev_close: finiteNumber(dailyRaw.prev_close),
      last_close: finiteNumber(dailyRaw.last_close),
      day_open: finiteNumber(dailyRaw.day_open),
      day_high: finiteNumber(dailyRaw.day_high),
      day_low: finiteNumber(dailyRaw.day_low),
      prev_day_high: finiteNumber(dailyRaw.prev_day_high),
      prev_day_low: finiteNumber(dailyRaw.prev_day_low),
    },
    pivots: {
      pivot: finiteNumber(pivotsRaw.pivot),
      r1: finiteNumber(pivotsRaw.r1),
      s1: finiteNumber(pivotsRaw.s1),
      support_2: finiteNumber(pivotsRaw.support_2),
      resistance_2: finiteNumber(pivotsRaw.resistance_2),
    },
  };
}

function levelsFromSymbols(symbols: Record<string, MarketBriefSymbolSnapshot>): MarketBriefLevel[] {
  return ["ES=F", "NQ=F", "SPY", "QQQ"].map((symbol) => ({
    symbol,
    pivot: symbols[symbol]?.pivots?.pivot ?? null,
    r1: symbols[symbol]?.pivots?.r1 ?? null,
    s1: symbols[symbol]?.pivots?.s1 ?? null,
  }));
}

export function extractMachinePayload(markdown: string): Record<string, unknown> | null {
  const marker = "### Market machine payload (JSON)";
  const markerIndex = markdown.indexOf(marker);
  const searchFrom = markerIndex >= 0 ? markerIndex : 0;
  const fenceStart = markdown.indexOf("```json", searchFrom);
  if (fenceStart < 0) return null;
  const jsonStart = fenceStart + "```json".length;
  const fenceEnd = markdown.indexOf("```", jsonStart);
  if (fenceEnd < 0) return null;
  const raw = markdown.slice(jsonStart, fenceEnd).trim();
  try {
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed as Record<string, unknown> : null;
  } catch {
    return null;
  }
}

export function summarizeMachinePayload(
  payload: Record<string, unknown> | null,
  options: { sourcePath: string | null; sourceMtimeMs?: number; nowMs?: number; loadError?: string | null } = { sourcePath: null },
): MarketBriefSnapshot {
  const nowMs = options.nowMs ?? Date.now();
  const warnings: string[] = [];
  if (options.loadError) warnings.push(options.loadError);

  const generatedAt = stringOrNull(payload?.generated_at);
  const generatedMs = generatedAt ? Date.parse(generatedAt) : NaN;
  const sourceMs = Number.isFinite(generatedMs) ? generatedMs : options.sourceMtimeMs;
  const ageSeconds = sourceMs ? Math.max(0, Math.floor((nowMs - sourceMs) / 1000)) : null;
  const sourceQuality = !payload ? "degraded" : ageSeconds == null ? "degraded" : ageSeconds > STALE_AFTER_SECONDS ? "stale" : "fresh";
  if (!payload) warnings.push("Machine-scored market brief payload unavailable.");
  if (sourceQuality === "stale") warnings.push("Machine-scored market brief artifact is stale; refresh before using intraday.");

  const rawSymbols = payload?.symbols && typeof payload.symbols === "object" ? payload.symbols as Record<string, unknown> : {};
  const symbols = Object.fromEntries(Object.entries(rawSymbols).map(([symbol, raw]) => [symbol, normalizeSymbol(raw)]));

  return {
    mode: "ANALYSIS_ONLY",
    orders_enabled: false,
    risk_config_touched: false,
    asOf: generatedAt,
    generatedAt,
    sourcePath: options.sourcePath,
    sourceQuality,
    ageSeconds,
    scores: normalizeScores(payload?.scores),
    symbols,
    levels: levelsFromSymbols(symbols),
    warnings,
    modelVersion: MODEL_VERSION,
  };
}

export function degradedMarketBrief(message: string): MarketBriefSnapshot {
  return summarizeMachinePayload(null, { sourcePath: null, loadError: message });
}
