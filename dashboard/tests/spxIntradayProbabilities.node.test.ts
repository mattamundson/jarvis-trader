import assert from "node:assert/strict";
import { test } from "node:test";

import { buildProbabilityBands, buildScenarios } from "@/lib/spxIntraday/probabilities";
import { buildDecisionLevels } from "@/lib/spxIntraday/metrics";
import type { IntradayBar, SpxIntradayMetrics } from "@/lib/spxIntraday/types";

function syntheticBars(): IntradayBar[] {
  return Array.from({ length: 120 }, (_, i) => {
    const close = 7748 + Math.sin(i / 5) * 2 + i * 0.015;
    return { time: 1_700_000_000 + i * 60, open: close - 0.5, high: close + 1, low: close - 1, close, volume: 1000 };
  });
}

function metrics(): SpxIntradayMetrics {
  return {
    currentPrice: 7749.78,
    dayHigh: 7756.76,
    dayLow: 7686.71,
    dayChangePct: 1.08,
    previousClose: 7666.6,
    vix: 14.41,
    vixChangePct: -5.2,
    rsi14: 43.9,
    ema9: 7750.26,
    ema21: 7750.46,
    sma50: 7751.44,
    vwap: 7730.59,
    returns: { fiveMinPct: -0.012, fifteenMinPct: -0.01, thirtyMinPct: -0.031, sixtyMinPct: -0.067 },
    breadth: {
      spyPct: 1.08,
      qqqPct: 1.17,
      rspPct: 0.65,
      iwmPct: 0.33,
      spyRspSpread: 0.43,
      qqqIwmSpread: 0.84,
      sectorsGreen: 8,
      sectorsTotal: 11,
    },
    levels: buildDecisionLevels(7749.78),
  };
}

test("probability bands are monotonic and distinguish touch from close", () => {
  const m = metrics();
  const bands = buildProbabilityBands(m, syntheticBars(), new Date("2026-09-03T15:35:00-05:00"));
  assert.ok(bands);
  assert.ok(bands.p10 <= bands.p25);
  assert.ok(bands.p25 <= bands.p50);
  assert.ok(bands.p50 <= bands.p75);
  assert.ok(bands.p75 <= bands.p90);
  const buyer = "7743.84";
  assert.ok((bands.touchBelow[buyer] ?? 0) >= (bands.closeBelow[buyer] ?? 0));
});

test("scenarios normalize to approximately 100 percent", () => {
  const m = metrics();
  const bands = buildProbabilityBands(m, syntheticBars(), new Date("2026-09-03T15:35:00-05:00"));
  const scenarios = buildScenarios(m, bands);
  const total = scenarios.reduce((sum, scenario) => sum + scenario.probability, 0);
  assert.ok(Math.abs(total - 100) <= 0.2);
  assert.equal(scenarios.length, 4);
});
