import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { sanitizeFlowData } from "@/lib/flowSanitize";

describe("flowSanitize", () => {
  // The inherited master sanitizer enforces a source-clock freshness gate (ts may be at most 5 min old
  // and at most 60 s in the future). Freeze Date.now just after the fixture
  // timestamp so the still-valid fixtures pass while the freshness contract
  // stays genuinely tested (stale/future negatives at the bottom).
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2024-01-01T12:02:00Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  const validData = {
    ts: "2024-01-01T12:00:00Z",
    es: {
      last: 7718.25,
      vwap: 7716.5,
      onHigh: 7728.0,
      onLow: 7710.75,
      cvd: 850,
      cvdLow: -420,
      bars1m: [
        { ts: "2024-01-01T11:59:00Z", open: 7712, high: 7714, low: 7711, close: 7713, volume: 135 },
      ],
      deltaAtPrice: [
        { price: 7720, bidLots: 8, askLots: 15 },
      ],
      bigPrints: [
        { ts: "2024-01-01T11:59:30Z", price: 7719.5, lots: 28, side: "ask" },
      ],
    },
    nq: {
      last: 21234.75,
      vwap: 21232.5,
    },
    gex: {
      callWall: 7735,
      putWall: 7695,
      flip: 7715,
      pin: 7725,
      asOf: "2024-01-01T11:45:00Z",
    },
    gates: [
      { level: 7730, status: "untested", closeCount: 0 },
    ],
  };
  
  it("accepts valid data", () => {
    const result = sanitizeFlowData(validData);
    
    expect(result).not.toBeNull();
    expect(result?.ts).toBe("2024-01-01T12:00:00Z");
    expect(result?.es.last).toBe(7718.25);
  });
  
  it("strips extra fields", () => {
    const dataWithExtra = {
      ...validData,
      accountId: "SECRET_ACCOUNT",
      position: 5,
      pnl: 1500,
      es: {
        ...validData.es,
        secretField: "should-be-stripped",
      },
    };
    
    const result = sanitizeFlowData(dataWithExtra);
    
    expect(result).not.toBeNull();
    expect((result as any).accountId).toBeUndefined();
    expect((result as any).position).toBeUndefined();
    expect((result as any).pnl).toBeUndefined();
    expect((result as any).es.secretField).toBeUndefined();
  });
  
  it("preserves fixture flag when true", () => {
    const fixtureData = { ...validData, fixture: true };
    const result = sanitizeFlowData(fixtureData);
    
    expect(result).not.toBeNull();
    expect(result?.fixture).toBe(true);
  });
  
  it("omits fixture flag when false or missing", () => {
    const dataWithFalseFix = { ...validData, fixture: false };
    const resultFalse = sanitizeFlowData(dataWithFalseFix);
    
    expect(resultFalse).not.toBeNull();
    expect(resultFalse?.fixture).toBeUndefined();
    
    const resultMissing = sanitizeFlowData(validData);
    expect(resultMissing).not.toBeNull();
    expect(resultMissing?.fixture).toBeUndefined();
  });
  
  it("rejects missing ts", () => {
    const invalid = { ...validData };
    delete (invalid as any).ts;
    
    expect(sanitizeFlowData(invalid)).toBeNull();
  });
  
  it("rejects missing es", () => {
    const invalid = { ...validData };
    delete (invalid as any).es;
    
    expect(sanitizeFlowData(invalid)).toBeNull();
  });
  
  it("rejects missing nq", () => {
    const invalid = { ...validData };
    delete (invalid as any).nq;
    
    expect(sanitizeFlowData(invalid)).toBeNull();
  });
  
  it("rejects missing gex", () => {
    const invalid = { ...validData };
    delete (invalid as any).gex;
    
    expect(sanitizeFlowData(invalid)).toBeNull();
  });
  
  it("rejects non-array gates", () => {
    const invalid = { ...validData, gates: "not-an-array" };
    
    expect(sanitizeFlowData(invalid)).toBeNull();
  });
  
  it("rejects null input", () => {
    expect(sanitizeFlowData(null)).toBeNull();
  });
  
  it("rejects non-object input", () => {
    expect(sanitizeFlowData("not an object")).toBeNull();
    expect(sanitizeFlowData(42)).toBeNull();
    expect(sanitizeFlowData([])).toBeNull();
  });

  it("rejects stale timestamp beyond the freshness window", () => {
    const stale = { ...validData, ts: "2024-01-01T11:50:00Z" };
    expect(sanitizeFlowData(stale)).toBeNull();
  });

  it("rejects timestamp too far in the future", () => {
    const future = { ...validData, ts: "2024-01-01T12:05:00Z" };
    expect(sanitizeFlowData(future)).toBeNull();
  });
});
