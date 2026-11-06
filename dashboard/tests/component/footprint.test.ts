import { describe, it, expect } from "vitest";
import {
  buildFootprintBar,
  buildCompositeProfile,
  aggregateBarsTo5m,
  type FootprintBar,
} from "@/lib/footprint";
import type { Bar1m } from "@/lib/flowTypes";

describe("buildFootprintBar", () => {
  it("should build footprint bar from bid/ask at price data", () => {
    const bar: Bar1m = {
      ts: "2024-01-01T12:00:00Z",
      open: 100,
      high: 102,
      low: 99,
      close: 101,
      volume: 50,
      bidAtPrice: { 100: 10, 101: 15 },
      askAtPrice: { 100: 5, 101: 20 },
    };

    const footprint = buildFootprintBar(bar);

    expect(footprint.ts).toBe(bar.ts);
    expect(footprint.open).toBe(100);
    expect(footprint.close).toBe(101);
    expect(footprint.levels).toHaveLength(2);
    expect(footprint.totalVolume).toBe(50);
    expect(footprint.netDelta).toBe(0);
  });

  it("should handle missing bid/ask data", () => {
    const bar: Bar1m = {
      ts: "2024-01-01T12:00:00Z",
      open: 100,
      high: 102,
      low: 99,
      close: 101,
      volume: 50,
    };

    const footprint = buildFootprintBar(bar);

    expect(footprint.levels).toHaveLength(0);
    expect(footprint.totalVolume).toBe(0);
    expect(footprint.netDelta).toBe(0);
  });

  it("should calculate delta correctly", () => {
    const bar: Bar1m = {
      ts: "2024-01-01T12:00:00Z",
      open: 100,
      high: 102,
      low: 99,
      close: 101,
      volume: 60,
      bidAtPrice: { 100: 30 },
      askAtPrice: { 100: 30 },
    };

    const footprint = buildFootprintBar(bar);

    expect(footprint.levels[0].delta).toBe(0);
    expect(footprint.netDelta).toBe(0);
  });

  it("should sort levels by price descending", () => {
    const bar: Bar1m = {
      ts: "2024-01-01T12:00:00Z",
      open: 100,
      high: 103,
      low: 99,
      close: 101,
      volume: 60,
      bidAtPrice: { 99: 10, 101: 10, 103: 10 },
      askAtPrice: { 99: 10, 101: 10, 103: 10 },
    };

    const footprint = buildFootprintBar(bar);

    expect(footprint.levels[0].price).toBe(103);
    expect(footprint.levels[1].price).toBe(101);
    expect(footprint.levels[2].price).toBe(99);
  });
});

describe("buildCompositeProfile", () => {
  it("should aggregate volume across bars", () => {
    const bars: Bar1m[] = [
      {
        ts: "2024-01-01T12:00:00Z",
        open: 100,
        high: 102,
        low: 99,
        close: 101,
        volume: 50,
        bidAtPrice: { 100: 10, 101: 10 },
        askAtPrice: { 100: 15, 101: 15 },
      },
      {
        ts: "2024-01-01T12:01:00Z",
        open: 101,
        high: 103,
        low: 100,
        close: 102,
        volume: 50,
        bidAtPrice: { 100: 10, 102: 10 },
        askAtPrice: { 100: 15, 102: 15 },
      },
    ];

    const profile = buildCompositeProfile(bars);

    expect(profile.totalVolume).toBe(100);
    expect(profile.levels.length).toBeGreaterThan(0);
  });

  it("should identify POC as highest volume level", () => {
    const bars: Bar1m[] = [
      {
        ts: "2024-01-01T12:00:00Z",
        open: 100,
        high: 102,
        low: 99,
        close: 101,
        volume: 100,
        bidAtPrice: { 100: 50 },
        askAtPrice: { 100: 50 },
      },
      {
        ts: "2024-01-01T12:01:00Z",
        open: 101,
        high: 103,
        low: 100,
        close: 102,
        volume: 20,
        bidAtPrice: { 101: 10 },
        askAtPrice: { 101: 10 },
      },
    ];

    const profile = buildCompositeProfile(bars);

    expect(profile.poc).toBe(100);
  });

  it("should handle empty bars array", () => {
    const profile = buildCompositeProfile([]);

    expect(profile.levels).toHaveLength(0);
    expect(profile.totalVolume).toBe(0);
    expect(profile.poc).toBe(0);
  });
});

describe("aggregateBarsTo5m", () => {
  it("should aggregate 1m bars into 5m bars", () => {
    const bars1m: Bar1m[] = Array.from({ length: 10 }, (_, i) => ({
      ts: `2024-01-01T12:0${i}:00Z`,
      open: 100 + i,
      high: 102 + i,
      low: 99 + i,
      close: 101 + i,
      volume: 10,
      bidAtPrice: { [100 + i]: 5 },
      askAtPrice: { [100 + i]: 5 },
    }));

    const bars5m = aggregateBarsTo5m(bars1m);

    expect(bars5m).toHaveLength(2);
    expect(bars5m[0].volume).toBe(50);
    expect(bars5m[1].volume).toBe(50);
  });

  it("should merge bid/ask at price data", () => {
    const bars1m: Bar1m[] = [
      {
        ts: "2024-01-01T12:00:00Z",
        open: 100,
        high: 102,
        low: 99,
        close: 101,
        volume: 10,
        bidAtPrice: { 100: 5 },
        askAtPrice: { 100: 5 },
      },
      {
        ts: "2024-01-01T12:01:00Z",
        open: 101,
        high: 103,
        low: 100,
        close: 102,
        volume: 10,
        bidAtPrice: { 100: 3 },
        askAtPrice: { 100: 7 },
      },
    ];

    const bars5m = aggregateBarsTo5m(bars1m);

    expect(bars5m).toHaveLength(1);
    expect(bars5m[0].bidAtPrice?.[100]).toBe(8);
    expect(bars5m[0].askAtPrice?.[100]).toBe(12);
  });

  it("should calculate OHLC correctly", () => {
    const bars1m: Bar1m[] = [
      {
        ts: "2024-01-01T12:00:00Z",
        open: 100,
        high: 105,
        low: 98,
        close: 102,
        volume: 10,
      },
      {
        ts: "2024-01-01T12:01:00Z",
        open: 102,
        high: 107,
        low: 101,
        close: 106,
        volume: 10,
      },
    ];

    const bars5m = aggregateBarsTo5m(bars1m);

    expect(bars5m[0].open).toBe(100);
    expect(bars5m[0].high).toBe(107);
    expect(bars5m[0].low).toBe(98);
    expect(bars5m[0].close).toBe(106);
  });

  it("should handle incomplete 5m periods", () => {
    const bars1m: Bar1m[] = Array.from({ length: 7 }, (_, i) => ({
      ts: `2024-01-01T12:0${i}:00Z`,
      open: 100,
      high: 102,
      low: 99,
      close: 101,
      volume: 10,
    }));

    const bars5m = aggregateBarsTo5m(bars1m);

    expect(bars5m).toHaveLength(2);
    expect(bars5m[0].volume).toBe(50);
    expect(bars5m[1].volume).toBe(20);
  });
});
