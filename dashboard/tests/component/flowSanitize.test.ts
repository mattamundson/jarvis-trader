import { describe, it, expect } from "vitest";
import { sanitizeFlowData } from "@/lib/flowSanitize";

describe("flowSanitize", () => {
  const now = new Date();
  const recentTs = new Date(now.getTime() - 30_000).toISOString();
  const barTs = new Date(now.getTime() - 60_000).toISOString();
  const printTs = new Date(now.getTime() - 30_000).toISOString();
  const gexTs = new Date(now.getTime() - 15 * 60_000).toISOString();

  const validData = {
    ts: recentTs,
    es: {
      last: 7718.25,
      vwap: 7716.5,
      onHigh: 7728.0,
      onLow: 7710.75,
      cvd: 850,
      cvdLow: -420,
      bars1m: [
        { ts: barTs, open: 7712, high: 7714, low: 7711, close: 7713, volume: 135 },
      ],
      deltaAtPrice: [
        { price: 7720, bidLots: 8, askLots: 15 },
      ],
      bigPrints: [
        { ts: printTs, price: 7719.5, lots: 28, side: "ask" },
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
      asOf: gexTs,
    },
    gates: [
      { level: 7730, status: "untested", closeCount: 0 },
    ],
  };
  
  it("accepts valid data", () => {
    const result = sanitizeFlowData(validData);
    
    expect(result).not.toBeNull();
    expect(result?.ts).toBe(recentTs);
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

  describe("bidAtPrice / askAtPrice validation", () => {
    it("passes through valid bidAtPrice and askAtPrice", () => {
      const dataWithFootprint = {
        ...validData,
        es: {
          ...validData.es,
          bars1m: [
            {
              ts: barTs,
              open: 7712,
              high: 7714,
              low: 7711,
              close: 7713,
              volume: 135,
              bidAtPrice: { "7712.25": 15, "7713.00": 20 },
              askAtPrice: { "7712.25": 10, "7713.00": 18 },
            },
          ],
        },
      };

      const result = sanitizeFlowData(dataWithFootprint);

      expect(result).not.toBeNull();
      expect(result?.es.bars1m[0].bidAtPrice).toEqual({ 7712.25: 15, 7713: 20 });
      expect(result?.es.bars1m[0].askAtPrice).toEqual({ 7712.25: 10, 7713: 18 });
    });

    it("strips bidAtPrice with negative lots", () => {
      const dataWithNegative = {
        ...validData,
        es: {
          ...validData.es,
          bars1m: [
            {
              ts: barTs,
              open: 7712,
              high: 7714,
              low: 7711,
              close: 7713,
              volume: 135,
              bidAtPrice: { "7712.25": -5, "7713.00": 20 },
            },
          ],
        },
      };

      const result = sanitizeFlowData(dataWithNegative);

      expect(result).not.toBeNull();
      expect(result?.es.bars1m[0].bidAtPrice).toBeUndefined();
    });

    it("strips askAtPrice with invalid price", () => {
      const dataWithInvalidPrice = {
        ...validData,
        es: {
          ...validData.es,
          bars1m: [
            {
              ts: barTs,
              open: 7712,
              high: 7714,
              low: 7711,
              close: 7713,
              volume: 135,
              askAtPrice: { "not-a-number": 10, "7713.00": 18 },
            },
          ],
        },
      };

      const result = sanitizeFlowData(dataWithInvalidPrice);

      expect(result).not.toBeNull();
      expect(result?.es.bars1m[0].askAtPrice).toBeUndefined();
    });

    it("strips bidAtPrice with > 400 keys", () => {
      const tooManyKeys: Record<string, number> = {};
      for (let i = 0; i < 401; i++) {
        tooManyKeys[`${7700 + i * 0.25}`] = 5;
      }

      const dataWithTooMany = {
        ...validData,
        es: {
          ...validData.es,
          bars1m: [
            {
              ts: barTs,
              open: 7712,
              high: 7714,
              low: 7711,
              close: 7713,
              volume: 135,
              bidAtPrice: tooManyKeys,
            },
          ],
        },
      };

      const result = sanitizeFlowData(dataWithTooMany);

      expect(result).not.toBeNull();
      expect(result?.es.bars1m[0].bidAtPrice).toBeUndefined();
    });

    it("allows exactly 400 keys", () => {
      const exactLimit: Record<string, number> = {};
      for (let i = 0; i < 400; i++) {
        exactLimit[`${7700 + i * 0.25}`] = 5;
      }

      const dataWithExactLimit = {
        ...validData,
        es: {
          ...validData.es,
          bars1m: [
            {
              ts: barTs,
              open: 7712,
              high: 7714,
              low: 7711,
              close: 7713,
              volume: 135,
              bidAtPrice: exactLimit,
            },
          ],
        },
      };

      const result = sanitizeFlowData(dataWithExactLimit);

      expect(result).not.toBeNull();
      expect(result?.es.bars1m[0].bidAtPrice).toBeDefined();
      expect(Object.keys(result?.es.bars1m[0].bidAtPrice || {}).length).toBe(400);
    });

    it("strips empty bidAtPrice/askAtPrice objects", () => {
      const dataWithEmpty = {
        ...validData,
        es: {
          ...validData.es,
          bars1m: [
            {
              ts: barTs,
              open: 7712,
              high: 7714,
              low: 7711,
              close: 7713,
              volume: 135,
              bidAtPrice: {},
              askAtPrice: {},
            },
          ],
        },
      };

      const result = sanitizeFlowData(dataWithEmpty);

      expect(result).not.toBeNull();
      expect(result?.es.bars1m[0].bidAtPrice).toBeUndefined();
      expect(result?.es.bars1m[0].askAtPrice).toBeUndefined();
    });

    it("handles bars with mixed footprint data presence", () => {
      const dataWithMixed = {
        ...validData,
        es: {
          ...validData.es,
          bars1m: [
            {
              ts: new Date(now.getTime() - 120_000).toISOString(),
              open: 7710,
              high: 7712,
              low: 7709,
              close: 7711,
              volume: 100,
            },
            {
              ts: barTs,
              open: 7712,
              high: 7714,
              low: 7711,
              close: 7713,
              volume: 135,
              bidAtPrice: { "7712.25": 15 },
              askAtPrice: { "7712.25": 10 },
            },
          ],
        },
      };

      const result = sanitizeFlowData(dataWithMixed);

      expect(result).not.toBeNull();
      expect(result?.es.bars1m[0].bidAtPrice).toBeUndefined();
      expect(result?.es.bars1m[0].askAtPrice).toBeUndefined();
      expect(result?.es.bars1m[1].bidAtPrice).toEqual({ 7712.25: 15 });
      expect(result?.es.bars1m[1].askAtPrice).toEqual({ 7712.25: 10 });
    });

    it("strips non-object bidAtPrice/askAtPrice", () => {
      const dataWithNonObject = {
        ...validData,
        es: {
          ...validData.es,
          bars1m: [
            {
              ts: barTs,
              open: 7712,
              high: 7714,
              low: 7711,
              close: 7713,
              volume: 135,
              bidAtPrice: "not-an-object",
              askAtPrice: [1, 2, 3],
            },
          ],
        },
      };

      const result = sanitizeFlowData(dataWithNonObject);

      expect(result).not.toBeNull();
      expect(result?.es.bars1m[0].bidAtPrice).toBeUndefined();
      expect(result?.es.bars1m[0].askAtPrice).toBeUndefined();
    });
  });
});
