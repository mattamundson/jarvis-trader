import { describe, it, expect } from "vitest";

describe("flow fixture", () => {
  it("uses fixed old timestamp and fixture flag", async () => {
    const { GET } = await import("@/app/api/flow/route");
    
    const res = await GET();
    
    expect(res.status).toBe(200);
    const data = await res.json();
    
    expect(data.ts).toBe("2024-01-01T00:00:00.000Z");
    expect(data.fixture).toBe(true);
    expect(data.fixtureReason).toMatch(/No live data source configured/);
  });
  
  it("fixture timestamp is stale", async () => {
    const { GET } = await import("@/app/api/flow/route");
    const { isStale } = await import("@/lib/flowTypes");
    
    const res = await GET();
    const data = await res.json();
    
    expect(isStale(data.ts)).toBe(true);
  });
  
  it("bars have fixed timestamps", async () => {
    const { GET } = await import("@/app/api/flow/route");
    
    const res = await GET();
    const data = await res.json();
    
    expect(data.es.bars1m[0].ts).toBe("2024-01-01T00:00:00.000Z");
    expect(data.es.bars1m[data.es.bars1m.length - 1].ts).toBe("2024-01-01T00:09:00.000Z");
    
    for (const bar of data.es.bars1m) {
      expect(bar.ts).toMatch(/^2024-01-01T00:/);
    }
  });
});
