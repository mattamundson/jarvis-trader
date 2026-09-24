import assert from "node:assert/strict";
import { test } from "node:test";

import { buildDecisionLevels } from "@/lib/spxIntraday/metrics";
import { buildSpxVerdict } from "@/lib/spxIntraday/verdict";
import type { SpxIntradayMetrics } from "@/lib/spxIntraday/types";

function liveDecisionZoneMetrics(): SpxIntradayMetrics {
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

test("current SPX manual-analysis state maps to breakout failure test", () => {
  const verdict = buildSpxVerdict(liveDecisionZoneMetrics(), "fresh");
  assert.equal(verdict.label, "BREAKOUT_FAILURE_TEST");
  assert.ok(verdict.summary.includes("7749.78"));
  assert.ok(verdict.bearEvidence.some((item) => item.includes("7752.01")));
});

test("degraded data returns DATA_DEGRADED, not a confident trade-like verdict", () => {
  const metrics = liveDecisionZoneMetrics();
  metrics.currentPrice = null;
  const verdict = buildSpxVerdict(metrics, "degraded");
  assert.equal(verdict.label, "DATA_DEGRADED");
  assert.equal(verdict.confidence, 0);
});
