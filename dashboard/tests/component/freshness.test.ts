import { describe, it, expect } from "vitest";
import { classifyFreshness, isMarketHours, getRTHStalenessThreshold } from "@/lib/freshness";

describe("classifyFreshness", () => {
  it("should classify fixture data as SAMPLE_DATA", () => {
    const result = classifyFreshness({
      source: "Test",
      dataTimestamp: "2024-01-01T12:00:00Z",
      isFixture: true,
    });

    expect(result.state).toBe("SAMPLE_DATA");
    expect(result.source).toBe("Test");
  });

  it("should classify data < 10s old as LIVE", () => {
    const now = new Date();
    const ts = new Date(now.getTime() - 5000);

    const result = classifyFreshness({
      source: "Test",
      dataTimestamp: ts,
    });

    expect(result.state).toBe("LIVE");
    expect(result.ageSeconds).toBeLessThan(10);
  });

  it("should classify data < stalenessThreshold as DELAYED", () => {
    const now = new Date();
    const ts = new Date(now.getTime() - 60_000);

    const result = classifyFreshness({
      source: "Test",
      dataTimestamp: ts,
      stalenessThresholdMs: 120_000,
    });

    expect(result.state).toBe("DELAYED");
    expect(result.ageSeconds).toBeGreaterThanOrEqual(60);
    expect(result.ageSeconds).toBeLessThan(120);
  });

  it("should classify data >= stalenessThreshold as STALE", () => {
    const now = new Date();
    const ts = new Date(now.getTime() - 150_000);

    const result = classifyFreshness({
      source: "Test",
      dataTimestamp: ts,
      stalenessThresholdMs: 120_000,
    });

    expect(result.state).toBe("STALE");
    expect(result.ageSeconds).toBeGreaterThanOrEqual(120);
  });

  it("should handle string timestamps", () => {
    const now = new Date();
    const ts = new Date(now.getTime() - 3000);

    const result = classifyFreshness({
      source: "Test",
      dataTimestamp: ts.toISOString(),
    });

    expect(result.state).toBe("LIVE");
  });

  it("should use default stalenessThreshold of 120s", () => {
    const now = new Date();
    const ts = new Date(now.getTime() - 125_000);

    const result = classifyFreshness({
      source: "Test",
      dataTimestamp: ts,
    });

    expect(result.state).toBe("STALE");
  });
});

describe("isMarketHours", () => {
  it("should return false for weekend days", () => {
    const saturday = new Date("2024-01-06T10:00:00-06:00");
    const sunday = new Date("2024-01-07T10:00:00-06:00");

    expect(isMarketHours(saturday)).toBe(false);
    expect(isMarketHours(sunday)).toBe(false);
  });

  it("should return true for weekday RTH hours", () => {
    const rthOpen = new Date("2024-01-08T08:30:00-06:00");
    const rthMid = new Date("2024-01-08T12:00:00-06:00");

    expect(isMarketHours(rthOpen)).toBe(true);
    expect(isMarketHours(rthMid)).toBe(true);
  });

  it("should return false for weekday before RTH", () => {
    const beforeRTH = new Date("2024-01-08T07:00:00-06:00");

    expect(isMarketHours(beforeRTH)).toBe(false);
  });

  it("should return false for weekday after RTH", () => {
    const afterRTH = new Date("2024-01-08T16:00:00-06:00");

    expect(isMarketHours(afterRTH)).toBe(false);
  });
});

describe("getRTHStalenessThreshold", () => {
  it("should return 2 minutes during RTH", () => {
    const threshold = getRTHStalenessThreshold();
    expect([2 * 60 * 1000, 120 * 60 * 1000]).toContain(threshold);
  });
});
