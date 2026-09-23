import assert from "node:assert/strict";
import { test } from "node:test";

import {
  buildDecisionLevels,
  buildSpxIntradayMetrics,
  exponentialMovingAverage,
  rsi,
  simpleMovingAverage,
  vwap,
} from "@/lib/spxIntraday/metrics";
import type { IntradayBar, MarketPriceSnapshot } from "@/lib/spxIntraday/types";

function barsFromCloses(closes: number[]): IntradayBar[] {
  return closes.map((close, i) => ({
    time: 1_700_000_000 + i * 60,
    open: close - 0.5,
    high: close + 1,
    low: close - 1,
    close,
    volume: 100 + i,
  }));
}

test("moving averages and RSI produce deterministic values", () => {
  const values = Array.from({ length: 60 }, (_, i) => 100 + i);
  assert.equal(simpleMovingAverage(values, 50), 134.5);
  assert.ok((exponentialMovingAverage(values, 9) ?? 0) > 150);
  assert.equal(rsi(values, 14), 100);
});

test("VWAP uses typical price weighted by volume", () => {
  const result = vwap([
    { time: 1, open: 99, high: 101, low: 99, close: 100, volume: 10 },
    { time: 2, open: 109, high: 111, low: 109, close: 110, volume: 30 },
  ]);
  assert.equal(result, 107.5);
});

test("decision levels classify the 7749.78 pivot as at/decision zone", () => {
  const levels = buildDecisionLevels(7749.78);
  const pivot = levels.find((l) => l.value === 7749.78);
  const immediate = levels.find((l) => l.value === 7752.01);
  assert.equal(pivot?.status, "at");
  assert.equal(immediate?.status, "lost");
});

test("metrics build the SPX manual-analysis fields from bars and price snapshots", () => {
  const closes = Array.from({ length: 70 }, (_, i) => 7680 + i * 1.01);
  const bars = barsFromCloses(closes);
  const prices: MarketPriceSnapshot = {
    "^GSPC": { symbol: "^GSPC", last_price: 7749.78, prev_close: 7666.6, change_pct: 1.08, yf_ticker: "^GSPC" },
    "^VIX": { symbol: "^VIX", last_price: 14.41, prev_close: 15.2, change_pct: -5.2, yf_ticker: "^VIX" },
    SPY: { symbol: "SPY", last_price: 774.9, prev_close: 766.6, change_pct: 1.08, yf_ticker: "SPY" },
    QQQ: { symbol: "QQQ", last_price: 600, prev_close: 593, change_pct: 1.17, yf_ticker: "QQQ" },
    RSP: { symbol: "RSP", last_price: 200, prev_close: 198.7, change_pct: 0.65, yf_ticker: "RSP" },
    IWM: { symbol: "IWM", last_price: 230, prev_close: 229.2, change_pct: 0.33, yf_ticker: "IWM" },
  };
  const metrics = buildSpxIntradayMetrics(bars, prices);
  assert.equal(metrics.currentPrice, 7749.78);
  assert.equal(metrics.vix, 14.41);
  assert.equal(metrics.breadth.qqqIwmSpread, 0.84);
  assert.equal(metrics.levels.find((l) => l.value === 7749.78)?.status, "at");
});
