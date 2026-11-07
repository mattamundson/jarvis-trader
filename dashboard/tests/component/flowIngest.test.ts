import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { POST } from "@/app/api/flow/ingest/route";
import { NextRequest } from "next/server";

vi.mock("@vercel/blob", () => ({
  put: vi.fn(),
}));

describe("flow ingest endpoint", () => {
  const originalEnv = process.env;
  
  beforeEach(() => {
    process.env = { ...originalEnv };
    process.env.FLOW_INGEST_TOKEN = "test-token-12345";
    process.env.BLOB_READ_WRITE_TOKEN = "blob-token-67890";
    vi.clearAllMocks();
    // The inherited master sanitizer enforces a source-clock freshness gate in sanitizeFlowData; freeze
    // Date.now just after the fixture ts so valid fixtures still reach the
    // storage branch while the freshness contract stays tested (stale negative
    // in the data-validation describe below).
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2024-01-01T12:02:00Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
    process.env = originalEnv;
  });
  
  const createRequest = (body: unknown, token?: string): NextRequest => {
    const headers = new Headers();
    if (token !== undefined) {
      headers.set("authorization", `Bearer ${token}`);
    }
    headers.set("content-type", "application/json");
    
    return new NextRequest("http://localhost:3010/api/flow/ingest", {
      method: "POST",
      headers,
      body: JSON.stringify(body),
    });
  };
  
  const validFlowData = {
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
  
  describe("authentication", () => {
    it("is reachable without Basic auth (middleware exempt)", async () => {
      const { isFlowIngestPath } = await import("@/lib/publicRoutes");
      expect(isFlowIngestPath("/api/flow/ingest", "POST")).toBe(true);
      expect(isFlowIngestPath("/api/flow/ingest", "GET")).toBe(false);
      expect(isFlowIngestPath("/api/flow", "POST")).toBe(false);
    });
    
    it("rejects request with missing authorization header", async () => {
      const req = createRequest(validFlowData);
      req.headers.delete("authorization");
      
      const res = await POST(req);
      
      expect(res.status).toBe(401);
      const body = await res.json();
      expect(body.error).toBe("Unauthorized");
    });
    
    it("rejects request with invalid bearer format", async () => {
      const req = createRequest(validFlowData, "");
      req.headers.set("authorization", "InvalidFormat");
      
      const res = await POST(req);
      
      expect(res.status).toBe(401);
      const body = await res.json();
      expect(body.error).toBe("Unauthorized");
    });
    
    it("rejects request with wrong token", async () => {
      const req = createRequest(validFlowData, "wrong-token");
      
      const res = await POST(req);
      
      expect(res.status).toBe(401);
      const body = await res.json();
      expect(body.error).toBe("Unauthorized");
    });
    
    it("accepts request with correct token", async () => {
      const { put } = await import("@vercel/blob");
      vi.mocked(put).mockResolvedValue({
        url: "https://blob.vercel-storage.com/flow/latest.json",
        downloadUrl: "https://blob.vercel-storage.com/flow/latest.json",
        pathname: "flow/latest.json",
        contentType: "application/json",
        contentDisposition: "inline",
      } as any);
      
      const req = createRequest(validFlowData, "test-token-12345");
      
      const res = await POST(req);
      
      expect(res.status).toBe(200);
      const body = await res.json();
      expect(body.success).toBe(true);
    });
    
    it("rejects when FLOW_INGEST_TOKEN not configured", async () => {
      delete process.env.FLOW_INGEST_TOKEN;
      
      const req = createRequest(validFlowData, "test-token-12345");
      
      const res = await POST(req);
      
      expect(res.status).toBe(500);
      const body = await res.json();
      expect(body.error).toBe("Server misconfigured");
    });
    
    it("uses constant time comparison for tokens", async () => {
      const req1 = createRequest(validFlowData, "test-token-12345");
      const req2 = createRequest(validFlowData, "test-token-00000");
      
      const start1 = Date.now();
      await POST(req1);
      const time1 = Date.now() - start1;
      
      const start2 = Date.now();
      await POST(req2);
      const time2 = Date.now() - start2;
      
      const timeDiff = Math.abs(time1 - time2);
      expect(timeDiff).toBeLessThan(50);
    });
  });
  
  describe("data validation", () => {
    it("rejects invalid JSON", async () => {
      const headers = new Headers();
      headers.set("authorization", "Bearer test-token-12345");
      headers.set("content-type", "application/json");
      
      const req = new NextRequest("http://localhost:3010/api/flow/ingest", {
        method: "POST",
        headers,
        body: "invalid json{",
      });
      
      const res = await POST(req);
      
      expect(res.status).toBe(400);
      const body = await res.json();
      expect(body.error).toBe("Invalid JSON");
    });
    
    it("rejects missing required es fields", async () => {
      const invalidData = {
        ...validFlowData,
        es: {
          ...validFlowData.es,
          last: undefined,
        },
      };
      
      const req = createRequest(invalidData, "test-token-12345");
      
      const res = await POST(req);
      
      expect(res.status).toBe(400);
      const body = await res.json();
      expect(body.error).toBe("Data failed validation");
    });
    
    it("rejects missing nq data", async () => {
      const invalidData = {
        ...validFlowData,
        nq: undefined,
      };
      
      const req = createRequest(invalidData, "test-token-12345");
      
      const res = await POST(req);
      
      expect(res.status).toBe(400);
      const body = await res.json();
      expect(body.error).toBe("Data failed validation");
    });
    
    it("rejects missing gex data", async () => {
      const invalidData = {
        ...validFlowData,
        gex: undefined,
      };
      
      const req = createRequest(invalidData, "test-token-12345");
      
      const res = await POST(req);
      
      expect(res.status).toBe(400);
      const body = await res.json();
      expect(body.error).toBe("Data failed validation");
    });
    
    it("rejects non-array gates", async () => {
      const invalidData = {
        ...validFlowData,
        gates: "not-an-array",
      };
      
      const req = createRequest(invalidData, "test-token-12345");
      
      const res = await POST(req);
      
      expect(res.status).toBe(400);
      const body = await res.json();
      expect(body.error).toBe("Data failed validation");
    });
    
    it("rejects stale timestamp beyond the freshness window", async () => {
      const stale = { ...validFlowData, ts: "2024-01-01T11:50:00Z" };
      const req = createRequest(stale, "test-token-12345");
      const res = await POST(req);
      expect(res.status).toBe(400);
      const body = await res.json();
      expect(body.error).toBe("Data failed validation");
    });

    it("sanitizes and strips extra fields", async () => {
      const { put } = await import("@vercel/blob");
      const putMock = vi.mocked(put);
      putMock.mockResolvedValue({
        url: "https://blob.vercel-storage.com/flow/latest.json",
        downloadUrl: "https://blob.vercel-storage.com/flow/latest.json",
        pathname: "flow/latest.json",
        contentType: "application/json",
        contentDisposition: "inline",
      } as any);
      
      const dataWithExtraFields = {
        ...validFlowData,
        accountId: "SECRET_ACCOUNT",
        position: 5,
        pnl: 1500,
        es: {
          ...validFlowData.es,
          secretField: "should-be-stripped",
        },
      };
      
      const req = createRequest(dataWithExtraFields, "test-token-12345");
      
      const res = await POST(req);
      
      expect(res.status).toBe(200);
      expect(putMock).toHaveBeenCalledOnce();
      
      const savedData = JSON.parse(putMock.mock.calls[0][1] as string);
      expect(savedData.accountId).toBeUndefined();
      expect(savedData.position).toBeUndefined();
      expect(savedData.pnl).toBeUndefined();
      expect(savedData.es.secretField).toBeUndefined();
    });
  });
  
  describe("storage", () => {
    it("stores valid data in Vercel Blob", async () => {
      const { put } = await import("@vercel/blob");
      const putMock = vi.mocked(put);
      putMock.mockResolvedValue({
        url: "https://blob.vercel-storage.com/flow/latest.json",
        downloadUrl: "https://blob.vercel-storage.com/flow/latest.json",
        pathname: "flow/latest.json",
        contentType: "application/json",
        contentDisposition: "inline",
      } as any);
      
      const req = createRequest(validFlowData, "test-token-12345");
      
      const res = await POST(req);
      
      expect(res.status).toBe(200);
      expect(putMock).toHaveBeenCalledWith(
        "flow/latest.json",
        expect.any(String),
        expect.objectContaining({
          access: "public",
          token: "blob-token-67890",
        })
      );
    });
    
    it("returns 500 when BLOB_READ_WRITE_TOKEN not configured", async () => {
      delete process.env.BLOB_READ_WRITE_TOKEN;
      
      const req = createRequest(validFlowData, "test-token-12345");
      
      const res = await POST(req);
      
      expect(res.status).toBe(500);
      const body = await res.json();
      expect(body.error).toBe("Storage not configured");
    });
    
    it("returns 500 when blob storage fails", async () => {
      const { put } = await import("@vercel/blob");
      vi.mocked(put).mockRejectedValue(new Error("Storage error"));
      
      const req = createRequest(validFlowData, "test-token-12345");
      
      const res = await POST(req);
      
      expect(res.status).toBe(500);
      const body = await res.json();
      expect(body.error).toBe("Storage failed");
    });
    
    it("returns timestamp in success response", async () => {
      const { put } = await import("@vercel/blob");
      vi.mocked(put).mockResolvedValue({
        url: "https://blob.vercel-storage.com/flow/latest.json",
        downloadUrl: "https://blob.vercel-storage.com/flow/latest.json",
        pathname: "flow/latest.json",
        contentType: "application/json",
        contentDisposition: "inline",
      } as any);
      
      const req = createRequest(validFlowData, "test-token-12345");
      
      const res = await POST(req);
      
      expect(res.status).toBe(200);
      const body = await res.json();
      expect(body.success).toBe(true);
      expect(body.ts).toBe("2024-01-01T12:00:00Z");
    });
  });
});
