import { describe, it } from "node:test";
import assert from "node:assert/strict";
import type { OHLCVBar } from "@/lib/api";
import {
  calculateATRLevels,
  calculateInitialBalance,
  calculateTPOValueArea,
  calculateGapFill,
  calculateSessionVWAP,
  calculateOvernightHighLow,
} from "../lib/esChartLevels.ts";

function makeBar(time: number, open: number, high: number, low: number, close: number, volume = 100): OHLCVBar {
  return { time, open, high, low, close, volume };
}

function utcTime(year: number, month: number, day: number, hour: number, minute: number): number {
  return Math.floor(Date.UTC(year, month - 1, day, hour, minute) / 1000);
}

describe("calculateATRLevels", () => {
  it("returns null when bars are insufficient", () => {
    const bars = [makeBar(utcTime(2026, 11, 6, 14, 0), 5800, 5810, 5790, 5805)];
    const result = calculateATRLevels(bars, 5810, 5790);
    assert.equal(result, null);
  });

  it("calculates ATR levels from 14-period true range", () => {
    const bars: OHLCVBar[] = [];
    let prevClose = 5800;

    for (let i = 0; i < 20; i++) {
      const time = utcTime(2026, 11, 6 + i, 14, 0);
      const high = prevClose + 10;
      const low = prevClose - 10;
      const close = prevClose + 5;
      bars.push(makeBar(time, prevClose, high, low, close));
      prevClose = close;
    }

    const currentHigh = 5900;
    const currentLow = 5880;
    const result = calculateATRLevels(bars, currentHigh, currentLow);

    assert.ok(result !== null);
    assert.ok(result.atr14 > 0);
    assert.equal(result.upperLevel, result.priorClose + result.atr14);
    assert.equal(result.lowerLevel, result.priorClose - result.atr14);
    assert.ok(result.rangeUsedPct >= 0);
  });

  it("clamps range used % at 999", () => {
    const bars: OHLCVBar[] = [];
    for (let i = 0; i < 20; i++) {
      const time = utcTime(2026, 11, 6 + i, 14, 0);
      bars.push(makeBar(time, 5800, 5801, 5799, 5800));
    }

    const result = calculateATRLevels(bars, 10000, 1000);
    assert.ok(result !== null);
    assert.equal(result.rangeUsedPct, 999);
  });
});

describe("calculateInitialBalance", () => {
  it("returns null when no today bars exist", () => {
    const yesterday = new Date();
    yesterday.setUTCDate(yesterday.getUTCDate() - 1);
    const bars = [makeBar(Math.floor(yesterday.getTime() / 1000), 5800, 5810, 5790, 5805)];
    const result = calculateInitialBalance(bars);
    assert.equal(result, null);
  });

  it("calculates IB high/low from first RTH hour", () => {
    const now = new Date();
    const ibStart = utcTime(now.getUTCFullYear(), now.getUTCMonth() + 1, now.getUTCDate(), 13, 30);
    const bars = [
      makeBar(ibStart, 5800, 5820, 5795, 5810),
      makeBar(ibStart + 5 * 60, 5810, 5825, 5800, 5815),
      makeBar(ibStart + 10 * 60, 5815, 5830, 5805, 5820),
    ];

    const result = calculateInitialBalance(bars);
    assert.ok(result !== null);
    assert.equal(result.high, 5830);
    assert.equal(result.low, 5795);
  });
});

describe("calculateTPOValueArea", () => {
  it("returns null with insufficient bars", () => {
    const bars = [makeBar(utcTime(2026, 11, 6, 14, 0), 5800, 5810, 5790, 5805)];
    const result = calculateTPOValueArea(bars);
    assert.equal(result, null);
  });

  it("calculates VAH/VAL/POC from price distribution", () => {
    const bars: OHLCVBar[] = [];
    for (let i = 0; i < 30; i++) {
      const time = utcTime(2026, 11, 6, 14, i);
      bars.push(makeBar(time, 5800, 5820, 5780, 5810));
    }

    const result = calculateTPOValueArea(bars);
    assert.ok(result !== null);
    assert.ok(result.vah >= result.poc);
    assert.ok(result.val <= result.poc);
    assert.ok(result.vah >= result.val);
  });
});

describe("calculateGapFill", () => {
  it("returns prior RTH close", () => {
    const bars = [
      makeBar(utcTime(2026, 11, 6, 14, 0), 5800, 5810, 5790, 5805),
      makeBar(utcTime(2026, 11, 6, 15, 0), 5805, 5815, 5795, 5810),
    ];

    const result = calculateGapFill(bars);
    assert.equal(result, 5810);
  });

  it("returns null when no RTH bars", () => {
    const result = calculateGapFill([]);
    assert.equal(result, null);
  });
});

describe("calculateSessionVWAP", () => {
  it("returns null when no today bars", () => {
    const yesterday = new Date();
    yesterday.setUTCDate(yesterday.getUTCDate() - 1);
    const bars = [makeBar(Math.floor(yesterday.getTime() / 1000), 5800, 5810, 5790, 5805)];
    const result = calculateSessionVWAP(bars);
    assert.equal(result, null);
  });

  it("calculates VWAP from today typical price * volume", () => {
    const now = new Date();
    const t1 = utcTime(now.getUTCFullYear(), now.getUTCMonth() + 1, now.getUTCDate(), 14, 0);
    const bars = [
      makeBar(t1, 5800, 5810, 5790, 5800, 100),
      makeBar(t1 + 60, 5800, 5820, 5795, 5810, 200),
    ];

    const result = calculateSessionVWAP(bars);
    assert.ok(result !== null);
    assert.ok(result > 5790 && result < 5820);
  });
});

describe("calculateOvernightHighLow", () => {
  it("returns null when no overnight bars", () => {
    const bars = [makeBar(utcTime(2026, 11, 6, 14, 0), 5800, 5810, 5790, 5805)];
    const result = calculateOvernightHighLow(bars);
    assert.equal(result, null);
  });

  it("calculates high/low from non-RTH bars", () => {
    const bars = [
      makeBar(utcTime(2026, 11, 6, 3, 0), 5800, 5810, 5790, 5805),
      makeBar(utcTime(2026, 11, 6, 4, 0), 5805, 5825, 5795, 5815),
      makeBar(utcTime(2026, 11, 6, 14, 0), 5815, 5850, 5800, 5840),
    ];

    const result = calculateOvernightHighLow(bars);
    assert.ok(result !== null);
    assert.equal(result.high, 5825);
    assert.equal(result.low, 5790);
  });
});
