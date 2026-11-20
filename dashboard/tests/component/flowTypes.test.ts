import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { isStale, biasLabel, analyzeGateAction, volumePaceRatio, type Gate, type DeltaAtPrice, type Bar1m } from "@/lib/flowTypes";

describe("flowTypes", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  describe("isStale", () => {
    it("returns false for recent timestamp", () => {
      const now = new Date("2024-01-01T12:00:00Z");
      vi.setSystemTime(now);
      
      const ts = new Date("2024-01-01T11:59:30Z").toISOString();
      expect(isStale(ts)).toBe(false);
    });

    it("returns true for timestamp older than threshold", () => {
      const now = new Date("2024-01-01T12:00:00Z");
      vi.setSystemTime(now);
      
      const ts = new Date("2024-01-01T11:58:00Z").toISOString();
      expect(isStale(ts)).toBe(true);
    });

    it("returns false when exactly at threshold", () => {
      const now = new Date("2024-01-01T12:00:00Z");
      vi.setSystemTime(now);
      
      const ts = new Date("2024-01-01T11:59:00Z").toISOString();
      expect(isStale(ts)).toBe(false);
    });

    it("respects custom threshold", () => {
      const now = new Date("2024-01-01T12:00:00Z");
      vi.setSystemTime(now);
      
      const ts = new Date("2024-01-01T11:59:00Z").toISOString();
      expect(isStale(ts, 30_000)).toBe(true);
      expect(isStale(ts, 120_000)).toBe(false);
    });
  });

  describe("biasLabel", () => {
    it("returns BULL when last above VWAP by more than 1", () => {
      expect(biasLabel(5845, 5843)).toBe("BULL");
      expect(biasLabel(5850, 5840)).toBe("BULL");
    });

    it("returns BEAR when last below VWAP by more than 1", () => {
      expect(biasLabel(5843, 5845)).toBe("BEAR");
      expect(biasLabel(5840, 5850)).toBe("BEAR");
    });

    it("returns NEUTRAL when within 1 point of VWAP", () => {
      expect(biasLabel(5844, 5844)).toBe("NEUTRAL");
      expect(biasLabel(5844.5, 5844)).toBe("NEUTRAL");
      expect(biasLabel(5844, 5844.5)).toBe("NEUTRAL");
      expect(biasLabel(5845, 5844.5)).toBe("NEUTRAL");
      expect(biasLabel(5844, 5844.99)).toBe("NEUTRAL");
    });

    it("returns BULL exactly at +1 threshold", () => {
      expect(biasLabel(5845, 5844)).toBe("BULL");
    });

    it("returns BEAR exactly at -1 threshold", () => {
      expect(biasLabel(5844, 5845)).toBe("BEAR");
    });
  });

  describe("analyzeGateAction", () => {
    const deltaAtPrice: DeltaAtPrice[] = [
      { price: 7720, bidLots: 5, askLots: 8 },
      { price: 7715, bidLots: 35, askLots: 15 },
      { price: 7710, bidLots: 12, askLots: 10 },
    ];

    it("returns BREAK when price beyond gate and CVD near low", () => {
      const gate: Gate = { level: 7715, status: "testing", closeCount: 1 };
      const result = analyzeGateAction(gate, 7722, -200, -250, deltaAtPrice);
      
      expect(result.action).toBe("BREAK");
      expect(result.reason).toContain("Price beyond gate");
    });

    it("returns ABSORB when heavy aggressive volume at gate with price holding", () => {
      const gate: Gate = { level: 7715, status: "testing", closeCount: 1 };
      const result = analyzeGateAction(gate, 7715.25, 500, -250, deltaAtPrice);
      
      expect(result.action).toBe("ABSORB");
      expect(result.reason).toContain("Heavy aggressive volume");
    });

    it("returns NEUTRAL when no clear signal", () => {
      const gate: Gate = { level: 7720, status: "untested", closeCount: 0 };
      const result = analyzeGateAction(gate, 7718, 100, -250, deltaAtPrice);
      
      expect(result.action).toBe("NEUTRAL");
      expect(result.reason).toBe("No clear signal");
    });

    it("requires price to be holding for ABSORB", () => {
      const gate: Gate = { level: 7715, status: "testing", closeCount: 1 };
      const result = analyzeGateAction(gate, 7720, 500, -250, deltaAtPrice);
      
      expect(result.action).not.toBe("ABSORB");
    });

    it("requires CVD near low for BREAK", () => {
      const gate: Gate = { level: 7715, status: "testing", closeCount: 1 };
      const result = analyzeGateAction(gate, 7722, 500, -250, deltaAtPrice);
      
      expect(result.action).not.toBe("BREAK");
    });
  });

  describe("volumePaceRatio", () => {
    it("returns null for insufficient data (fewer than 2 bars) — callers handle the null", () => {
      const bars: Bar1m[] = [
        { ts: "2024-01-01T12:00:00Z", open: 7710, high: 7712, low: 7709, close: 7711, volume: 100 },
      ];

      // Contract from the parent missing-data correction:
      // volumePaceRatio signals "not enough data" by returning null rather
      // than a fabricated neutral 1.0.
      expect(volumePaceRatio(bars)).toBeNull();
    });

    it("returns null for a bar with invalid (non-finite or negative) volume", () => {
      const bars: Bar1m[] = [
        { ts: "2024-01-01T12:00:00Z", open: 7710, high: 7712, low: 7709, close: 7711, volume: 100 },
        { ts: "2024-01-01T12:01:00Z", open: 7711, high: 7713, low: 7710, close: 7712, volume: Number.NaN },
      ];

      expect(volumePaceRatio(bars)).toBeNull();
    });

    it("returns green for volume 1.5x+ above average", () => {
      const bars: Bar1m[] = [
        { ts: "2024-01-01T12:00:00Z", open: 7710, high: 7712, low: 7709, close: 7711, volume: 100 },
        { ts: "2024-01-01T12:01:00Z", open: 7711, high: 7713, low: 7710, close: 7712, volume: 100 },
        { ts: "2024-01-01T12:02:00Z", open: 7712, high: 7714, low: 7711, close: 7713, volume: 150 },
      ];
      
      const result = volumePaceRatio(bars);
      if (result === null) throw new Error("Expected measured volume pace for valid multi-bar input");
      expect(result.ratio).toBe(1.5);
      expect(result.color).toBe("text-green-400");
    });

    it("returns cyan for volume 1.2-1.5x above average", () => {
      const bars: Bar1m[] = [
        { ts: "2024-01-01T12:00:00Z", open: 7710, high: 7712, low: 7709, close: 7711, volume: 100 },
        { ts: "2024-01-01T12:01:00Z", open: 7711, high: 7713, low: 7710, close: 7712, volume: 100 },
        { ts: "2024-01-01T12:02:00Z", open: 7712, high: 7714, low: 7711, close: 7713, volume: 125 },
      ];
      
      const result = volumePaceRatio(bars);
      if (result === null) throw new Error("Expected measured volume pace for valid multi-bar input");
      expect(result.ratio).toBe(1.25);
      expect(result.color).toBe("text-cyan-400");
    });

    it("returns red for volume 0.7x or below average", () => {
      const bars: Bar1m[] = [
        { ts: "2024-01-01T12:00:00Z", open: 7710, high: 7712, low: 7709, close: 7711, volume: 100 },
        { ts: "2024-01-01T12:01:00Z", open: 7711, high: 7713, low: 7710, close: 7712, volume: 100 },
        { ts: "2024-01-01T12:02:00Z", open: 7712, high: 7714, low: 7711, close: 7713, volume: 70 },
      ];
      
      const result = volumePaceRatio(bars);
      if (result === null) throw new Error("Expected measured volume pace for valid multi-bar input");
      expect(result.ratio).toBe(0.7);
      expect(result.color).toBe("text-red-400");
    });

    it("returns yellow for volume 0.7-0.85x average", () => {
      const bars: Bar1m[] = [
        { ts: "2024-01-01T12:00:00Z", open: 7710, high: 7712, low: 7709, close: 7711, volume: 100 },
        { ts: "2024-01-01T12:01:00Z", open: 7711, high: 7713, low: 7710, close: 7712, volume: 100 },
        { ts: "2024-01-01T12:02:00Z", open: 7712, high: 7714, low: 7711, close: 7713, volume: 80 },
      ];
      
      const result = volumePaceRatio(bars);
      if (result === null) throw new Error("Expected measured volume pace for valid multi-bar input");
      expect(result.ratio).toBe(0.8);
      expect(result.color).toBe("text-yellow-400");
    });

    it("returns neutral for volume near average", () => {
      const bars: Bar1m[] = [
        { ts: "2024-01-01T12:00:00Z", open: 7710, high: 7712, low: 7709, close: 7711, volume: 100 },
        { ts: "2024-01-01T12:01:00Z", open: 7711, high: 7713, low: 7710, close: 7712, volume: 100 },
        { ts: "2024-01-01T12:02:00Z", open: 7712, high: 7714, low: 7711, close: 7713, volume: 100 },
      ];
      
      const result = volumePaceRatio(bars);
      if (result === null) throw new Error("Expected measured volume pace for valid multi-bar input");
      expect(result.ratio).toBe(1.0);
      expect(result.color).toBe("text-slate-400");
    });
  });
});
