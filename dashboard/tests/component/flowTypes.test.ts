import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { isStale, biasLabel } from "@/lib/flowTypes";

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
});
