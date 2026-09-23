import type { IntradayBar, SpxIntradayMetrics, SpxProbabilityBands, SpxScenarioProbability } from "./types";

function round(n: number, dp = 2): number {
  const factor = 10 ** dp;
  return Math.round(n * factor) / factor;
}

function normalCdf(x: number): number {
  // Abramowitz-Stegun approximation; enough precision for dashboard probabilities.
  const sign = x < 0 ? -1 : 1;
  const absX = Math.abs(x) / Math.sqrt(2);
  const t = 1 / (1 + 0.3275911 * absX);
  const a1 = 0.254829592;
  const a2 = -0.284496736;
  const a3 = 1.421413741;
  const a4 = -1.453152027;
  const a5 = 1.061405429;
  const erf = 1 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * Math.exp(-absX * absX);
  return 0.5 * (1 + sign * erf);
}

function percentile(mean: number, sigma: number, z: number): number {
  return round(mean + z * sigma);
}

function minuteReturnStdev(bars: IntradayBar[]): number | null {
  const closes = bars.map((b) => b.close).filter(Number.isFinite);
  if (closes.length < 20) return null;
  const rets: number[] = [];
  for (let i = 1; i < closes.length; i += 1) {
    if (closes[i - 1] > 0) rets.push(Math.log(closes[i] / closes[i - 1]));
  }
  if (rets.length < 10) return null;
  const mean = rets.reduce((sum, v) => sum + v, 0) / rets.length;
  const variance = rets.reduce((sum, v) => sum + (v - mean) ** 2, 0) / Math.max(1, rets.length - 1);
  return Math.sqrt(variance);
}

export function minutesToCashClose(now = new Date()): number {
  const close = new Date(now);
  close.setHours(16, 0, 0, 0);
  // Use local dashboard host time. JARVIS runs Central/Eastern aware operationally,
  // but this read-only model only needs a bounded remaining-session clock.
  return Math.max(1, Math.min(390, Math.round((close.getTime() - now.getTime()) / 60_000)));
}

function probabilityCloseAbove(price: number, target: number, sigma: number): number {
  if (sigma <= 0) return price > target ? 1 : 0;
  return Math.max(0, Math.min(1, 1 - normalCdf((target - price) / sigma)));
}

function probabilityTouch(price: number, target: number, sigma: number): number {
  if (sigma <= 0) return price === target ? 1 : 0;
  const distance = Math.abs(target - price);
  return Math.max(0, Math.min(1, 2 * (1 - normalCdf(distance / sigma))));
}

export function buildProbabilityBands(
  metrics: SpxIntradayMetrics,
  bars: IntradayBar[],
  now = new Date(),
): SpxProbabilityBands | null {
  const price = metrics.currentPrice;
  if (price == null) return null;
  const remainingMinutes = minutesToCashClose(now);
  const minuteStdev = minuteReturnStdev(bars) ?? 0.00035;
  const realizedSigma = price * minuteStdev * Math.sqrt(remainingMinutes);
  const vix = metrics.vix ?? 16;
  const vixSigma = price * (vix / 100) * Math.sqrt(remainingMinutes / (252 * 390));
  const fatTailSigma = Math.max(realizedSigma, vixSigma) * 1.35;
  const sigma = Math.max(0.75, 0.45 * realizedSigma + 0.35 * vixSigma + 0.20 * fatTailSigma);
  const closeAbove: Record<string, number> = {};
  const closeBelow: Record<string, number> = {};
  const touchAbove: Record<string, number> = {};
  const touchBelow: Record<string, number> = {};

  for (const level of metrics.levels) {
    const key = level.value.toFixed(2);
    const closeAboveProb = probabilityCloseAbove(price, level.value, sigma);
    const closeBelowProb = 1 - closeAboveProb;
    const touchProb = probabilityTouch(price, level.value, sigma);
    closeAbove[key] = round(closeAboveProb * 100, 1);
    closeBelow[key] = round(closeBelowProb * 100, 1);
    if (level.value >= price) {
      touchAbove[key] = round(Math.max(touchProb, closeAboveProb) * 100, 1);
    } else {
      touchBelow[key] = round(Math.max(touchProb, closeBelowProb) * 100, 1);
    }
  }

  return {
    p10: percentile(price, sigma, -1.2816),
    p25: percentile(price, sigma, -0.6745),
    p50: round(price),
    p75: percentile(price, sigma, 0.6745),
    p90: percentile(price, sigma, 1.2816),
    closeAbove,
    closeBelow,
    touchAbove,
    touchBelow,
    remainingMinutes,
    blendedSigmaPoints: round(sigma),
  };
}

export function buildScenarios(
  metrics: SpxIntradayMetrics,
  bands: SpxProbabilityBands | null,
): SpxScenarioProbability[] {
  const price = metrics.currentPrice ?? bands?.p50 ?? 0;
  const level = (value: number) => metrics.levels.find((l) => Math.abs(l.value - value) < 0.01);
  const pivot = level(7749.78)?.value ?? price;
  const immediate = level(7752.01)?.value ?? price + 2;
  const buyerControl = level(7743.84)?.value ?? price - 6;
  const dayHigh = metrics.dayHigh ?? level(7756.76)?.value ?? price + 7;
  const abovePivot = bands?.closeAbove[pivot.toFixed(2)] ?? 50;
  const aboveImmediate = bands?.closeAbove[immediate.toFixed(2)] ?? 40;
  const belowBuyer = bands?.closeBelow[buyerControl.toFixed(2)] ?? 15;
  const aboveHigh = metrics.dayHigh == null ? 8 : Math.max(3, Math.min(30, 100 - (bands?.closeBelow[dayHigh.toFixed(2)] ?? 90)));
  const failure = Math.max(8, Math.min(35, belowBuyer));
  const save = Math.max(10, Math.min(35, aboveImmediate));
  const squeeze = Math.max(3, Math.min(15, aboveHigh));
  const pin = Math.max(20, 100 - failure - save - squeeze);
  const total = pin + failure + save + squeeze;
  const norm = (v: number) => round((v / total) * 100, 1);

  return [
    {
      id: "pin_chop",
      label: "Pin / chop around pivot",
      probability: norm(pin),
      expectedCloseBand: [round(Math.min(pivot, price) - 2), round(Math.max(immediate, price) + 1)],
      trigger: `Holds near ${pivot.toFixed(2)} without reclaiming day high`,
      invalidation: `Clean break above ${(metrics.dayHigh ?? immediate).toFixed(2)} or below ${buyerControl.toFixed(2)}`,
    },
    {
      id: "breakout_failure",
      label: "Breakout failure / buyer-control test",
      probability: norm(failure),
      expectedCloseBand: [round(buyerControl - 3), round(pivot)],
      trigger: `Sustained trade below ${pivot.toFixed(2)}`,
      invalidation: `Reclaim above ${immediate.toFixed(2)}`,
    },
    {
      id: "bullish_save",
      label: "Late reclaim / bullish save",
      probability: norm(save),
      expectedCloseBand: [round(immediate), round((metrics.dayHigh ?? immediate + 5))],
      trigger: `Reclaim ${immediate.toFixed(2)}`,
      invalidation: `Lose ${pivot.toFixed(2)} again`,
    },
    {
      id: "late_squeeze",
      label: "Late squeeze through day high",
      probability: norm(squeeze),
      expectedCloseBand: [round(dayHigh), round(dayHigh + 8)],
      trigger: `Break and hold above ${dayHigh.toFixed(2)}`,
      invalidation: `Reject below ${immediate.toFixed(2)}`,
    },
  ];
}
