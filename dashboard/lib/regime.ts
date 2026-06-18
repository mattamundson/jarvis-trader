// Intraday Market Regime — typed data model, live engine wiring, and a
// deterministic sample snapshot used as a fallback.
//
// `fetchIntradayRegime()` calls GET /regime/intraday (engine analytics, no LLM).
// When the engine is unavailable the page falls back to `buildSampleRegime()` and
// renders a `sample` provenance badge so the data is never mistaken for live
// (Trust Pane convention).

import { fetchEngine } from "./api";

export type RegimeDirection = "BULLISH" | "BEARISH" | "NEUTRAL";
export type TimeframeBias = "BULL" | "BEAR" | "NEUTRAL";
export type Conviction = "HIGH" | "MEDIUM" | "LOW";
export type IndicatorTone = "bull" | "bear" | "neutral";

/** Score band edges for the -100..+100 regime scale. */
export const REGIME_SCALE_MAX = 100;

export interface TimeframeScore {
  label: string; // "5-MINUTE"
  score: number; // -100..+100
  bias: TimeframeBias;
}

export interface IndicatorReading {
  label: string; // "VWAP"
  value: string; // "Below"
  detail: string; // "$752.78"
  tone: IndicatorTone;
  /** Optional leading glyph: "up" | "down" — rendered as an arrow in the UI. */
  arrow?: "up" | "down";
  /** 0..1 fill for the thin progress bar under each card. */
  fill: number;
}

export interface RegimeHistoryPoint {
  /** Local clock label, e.g. "06:30 AM" — the x axis. */
  time: string;
  score: number; // composite regime score line
  shortEma: number;
  longEma: number;
  extraEma: number;
}

export interface OptionsFlow {
  flowSignal: RegimeDirection;
  netGex: number; // dollars, signed
  gexFlipLevel: number; // price
}

export interface IntradayRegime {
  symbol: string;
  price: number;
  direction: RegimeDirection;
  /** Composite regime score, -100..+100. */
  score: number;
  /** Share of indicators leaning the headline direction, 0..100. */
  directionPct: number;
  guidance: string; // "Look for SHORT entries"
  conviction: Conviction;
  liveTimeDilation: boolean;
  timeframeScores: TimeframeScore[];
  indicatorTimeframe: string; // "1-HOUR"
  indicators: IndicatorReading[];
  history: RegimeHistoryPoint[];
  snapshotCount: number;
  /** Null when the engine has no options/GEX source wired. */
  optionsFlow: OptionsFlow | null;
  /** "live" = computed by the engine; "sample" = deterministic local fallback. */
  source: "live" | "sample";
  updatedAt: string;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

export function directionFromScore(score: number): RegimeDirection {
  if (score >= 25) return "BULLISH";
  if (score <= -25) return "BEARISH";
  return "NEUTRAL";
}

export function biasFromScore(score: number): TimeframeBias {
  if (score >= 25) return "BULL";
  if (score <= -25) return "BEAR";
  return "NEUTRAL";
}

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));
const round2 = (v: number) => Math.round(v * 100) / 100;

/** Deterministic pseudo-noise in [-1, 1] so server and client render identically. */
function seededNoise(i: number): number {
  const x = Math.sin(i * 12.9898) * 43758.5453;
  return (x - Math.floor(x)) * 2 - 1;
}

function formatClock(minutesFromMidnight: number): string {
  const hh = Math.floor(minutesFromMidnight / 60);
  const mm = minutesFromMidnight % 60;
  const ampm = hh >= 12 ? "PM" : "AM";
  const h12 = hh % 12 === 0 ? 12 : hh % 12;
  return `${String(h12).padStart(2, "0")}:${String(mm).padStart(2, "0")} ${ampm}`;
}

/** Build the intraday score history: a descending, choppy bearish session. */
function buildHistory(points = 330): RegimeHistoryPoint[] {
  const start = 6 * 60 + 30; // 06:30 local
  const out: RegimeHistoryPoint[] = [];
  let shortEma = 8;
  let longEma = 10;
  let extraEma = 12;
  for (let i = 0; i < points; i++) {
    const trend = 12 - (i / points) * 66; // drifts +12 -> -54
    const swing = Math.sin(i / 18) * 14 + Math.sin(i / 5) * 6;
    const noise = seededNoise(i) * 8;
    const score = clamp(trend + swing + noise, -75, 55);
    shortEma += (score - shortEma) * 0.12;
    longEma += (score - longEma) * 0.05;
    extraEma += (score - extraEma) * 0.025;
    out.push({
      time: formatClock(start + i),
      score: round2(score),
      shortEma: round2(shortEma),
      longEma: round2(longEma),
      extraEma: round2(extraEma),
    });
  }
  return out;
}

/** Deterministic sample snapshot mirroring the design reference (SPY, bearish). */
export function buildSampleRegime(symbol = "SPY"): IntradayRegime {
  const history = buildHistory();
  return {
    symbol,
    price: 750.75,
    direction: "BEARISH",
    score: -54.3,
    directionPct: 45.5,
    guidance: "Look for SHORT entries",
    conviction: "HIGH",
    liveTimeDilation: true,
    timeframeScores: [
      { label: "5-MINUTE", score: -85.9, bias: "BEAR" },
      { label: "15-MINUTE", score: -90.6, bias: "BEAR" },
      { label: "1-HOUR", score: -18.3, bias: "BEAR" },
    ],
    indicatorTimeframe: "1-HOUR",
    indicators: [
      { label: "VWAP", value: "Below", detail: "$752.78", tone: "bear", arrow: "down", fill: 0.32 },
      { label: "DONCHIAN", value: "68% of range", detail: "20-bar channel", tone: "bull", fill: 0.68 },
      { label: "EMA STACK", value: "2/3 above", detail: "9-21-50", tone: "bear", fill: 0.66 },
      { label: "STRUCTURE", value: "Ranging", detail: "20-bar trend", tone: "neutral", fill: 0.5 },
      { label: "OBV", value: "Falling", detail: "5-bar trend", tone: "bear", arrow: "down", fill: 0.4 },
      { label: "RSI", value: "RSI 58", detail: "Neutral zone", tone: "bull", fill: 0.58 },
      { label: "MACD HIST", value: "-0.6509", detail: "12-26-9", tone: "bear", fill: 0.36 },
      { label: "RATE OF CHG", value: "-0.45%", detail: "14-bar ROC", tone: "bear", fill: 0.42 },
      { label: "ATR REGIME", value: "Contracting", detail: "Ratio 0.57", tone: "neutral", fill: 0.57 },
      { label: "BB POSITION", value: "51% in band", detail: "20-2.0 band", tone: "bull", fill: 0.51 },
    ],
    history,
    snapshotCount: 350,
    optionsFlow: {
      flowSignal: "BEARISH",
      netGex: 42_400_000,
      gexFlipLevel: 752,
    },
    source: "sample",
    updatedAt: new Date().toISOString(),
  };
}

// ── Live engine wiring ─────────────────────────────────────────────────────────

/** Snake_case payload from GET /regime/intraday (mirror of build_regime_snapshot). */
interface RawRegimeResponse {
  symbol: string;
  price: number;
  score: number;
  direction: RegimeDirection;
  direction_pct: number;
  guidance: string;
  conviction: Conviction;
  indicator_timeframe: string;
  timeframe_scores: Array<{ label: string; score: number; bias: TimeframeBias }>;
  indicators: Array<{
    label: string;
    value: string;
    detail: string;
    tone: IndicatorTone;
    arrow?: "up" | "down";
    fill: number;
  }>;
  history: Array<{
    time: string;
    score: number;
    short_ema: number;
    long_ema: number;
    extra_ema: number;
  }>;
  snapshot_count: number;
  options_flow: { flow_signal: RegimeDirection; net_gex: number; gex_flip_level: number } | null;
  updated_at: string;
}

function mapRawRegime(raw: RawRegimeResponse): IntradayRegime {
  return {
    symbol: raw.symbol,
    price: raw.price,
    direction: raw.direction,
    score: raw.score,
    directionPct: raw.direction_pct,
    guidance: raw.guidance,
    conviction: raw.conviction,
    // Real-time refresh flag is a UI concern; the live endpoint is request/response.
    liveTimeDilation: false,
    timeframeScores: raw.timeframe_scores,
    indicatorTimeframe: raw.indicator_timeframe,
    indicators: raw.indicators,
    history: raw.history.map((p) => ({
      time: p.time,
      score: p.score,
      shortEma: p.short_ema,
      longEma: p.long_ema,
      extraEma: p.extra_ema,
    })),
    snapshotCount: raw.snapshot_count,
    optionsFlow: raw.options_flow
      ? {
          flowSignal: raw.options_flow.flow_signal,
          netGex: raw.options_flow.net_gex,
          gexFlipLevel: raw.options_flow.gex_flip_level,
        }
      : null,
    source: "live",
    updatedAt: raw.updated_at,
  };
}

/** Fetch the live intraday regime from the engine; mapper normalizes to IntradayRegime. */
export async function fetchIntradayRegime(
  symbol: string,
  futures = false
): Promise<IntradayRegime> {
  const raw = await fetchEngine<RawRegimeResponse>(
    `/regime/intraday?symbol=${encodeURIComponent(symbol)}&futures=${futures}`
  );
  return mapRawRegime(raw);
}
