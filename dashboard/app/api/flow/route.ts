import { NextResponse } from "next/server";
import { head } from "@vercel/blob";
import type { FlowSnapshot } from "@/lib/flowTypes";
import { sanitizeFlowData } from "@/lib/flowSanitize";
import { cacheFlowData, getLastKnownGood } from "@/lib/flowCache";

const FAKE_FIXTURE: FlowSnapshot = {
  ts: "2024-01-01T00:00:00.000Z",
  fixture: true,
  es: {
    last: 7718.25,
    vwap: 7716.5,
    onHigh: 7728.0,
    onLow: 7710.75,
    cvd: 850,
    cvdLow: -420,
    bars1m: [
      { ts: "2024-01-01T00:00:00.000Z", open: 7712, high: 7714, low: 7711, close: 7713, volume: 135 },
      { ts: "2024-01-01T00:01:00.000Z", open: 7713, high: 7715, low: 7712, close: 7714, volume: 128 },
      { ts: "2024-01-01T00:02:00.000Z", open: 7714, high: 7716, low: 7713, close: 7715, volume: 142 },
      { ts: "2024-01-01T00:03:00.000Z", open: 7715, high: 7717, low: 7714, close: 7716, volume: 155 },
      { ts: "2024-01-01T00:04:00.000Z", open: 7716, high: 7718, low: 7715, close: 7717, volume: 138 },
      { ts: "2024-01-01T00:05:00.000Z", open: 7717, high: 7719, low: 7716, close: 7718, volume: 148 },
      { ts: "2024-01-01T00:06:00.000Z", open: 7718, high: 7720, low: 7717, close: 7719, volume: 162 },
      { ts: "2024-01-01T00:07:00.000Z", open: 7719, high: 7721, low: 7718, close: 7720, volume: 185 },
      { ts: "2024-01-01T00:08:00.000Z", open: 7720, high: 7721, low: 7718, close: 7719, volume: 172 },
      { ts: "2024-01-01T00:09:00.000Z", open: 7719, high: 7720, low: 7717, close: 7718.25, volume: 210 },
    ],
    deltaAtPrice: [
      { price: 7720, bidLots: 8, askLots: 15 },
      { price: 7719.5, bidLots: 12, askLots: 22 },
      { price: 7719, bidLots: 18, askLots: 25 },
      { price: 7718.5, bidLots: 25, askLots: 18 },
      { price: 7718, bidLots: 32, askLots: 14 },
      { price: 7717.5, bidLots: 22, askLots: 10 },
      { price: 7717, bidLots: 15, askLots: 8 },
    ],
    bigPrints: [
      { ts: "2024-01-01T00:06:00.000Z", price: 7719.5, lots: 28, side: "ask" },
      { ts: "2024-01-01T00:07:00.000Z", price: 7718.5, lots: 35, side: "bid" },
      { ts: "2024-01-01T00:08:00.000Z", price: 7719.0, lots: 42, side: "bid" },
      { ts: "2024-01-01T00:08:30.000Z", price: 7720.0, lots: 25, side: "ask" },
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
    asOf: "2024-01-01T00:00:00.000Z",
  },
  gates: [
    { level: 7730, status: "untested", closeCount: 0 },
    { level: 7725, status: "testing", closeCount: 1 },
    { level: 7715, status: "testing", closeCount: 1 },
    { level: 7710, status: "broken", closeCount: 2 },
  ],
};

async function fetchFromBlob(): Promise<FlowSnapshot | null> {
  const blobToken = process.env.BLOB_READ_WRITE_TOKEN;
  
  if (!blobToken) {
    return null;
  }
  
  try {
    const blob = await head("flow/latest.json", { token: blobToken });
    const res = await fetch(blob.url, {
      cache: "no-store",
      signal: AbortSignal.timeout(5000),
    });
    
    if (!res.ok) {
      return null;
    }
    
    const data = await res.json();
    return data as FlowSnapshot;
  } catch (err) {
    console.error("[flow] Failed to fetch from Vercel Blob:", err);
    return null;
  }
}

async function fetchFromFeedUrl(): Promise<FlowSnapshot | null> {
  const feedUrl = process.env.FLOW_FEED_URL;
  
  if (!feedUrl) {
    return null;
  }
  
  try {
    const res = await fetch(feedUrl, { 
      cache: "no-store",
      signal: AbortSignal.timeout(5000),
    });
    
    if (!res.ok) {
      console.warn(`[flow] FLOW_FEED_URL returned ${res.status}`);
      return null;
    }
    
    const raw = await res.json();
    const sanitized = sanitizeFlowData(raw);
    
    if (!sanitized) {
      console.warn("[flow] FLOW_FEED_URL returned invalid schema");
      return null;
    }
    
    return sanitized;
  } catch (err) {
    console.error("[flow] Failed to fetch FLOW_FEED_URL:", err);
    return null;
  }
}

export async function GET() {
  let data = await fetchFromBlob();
  
  if (!data) {
    data = await fetchFromFeedUrl();
  }
  
  if (data) {
    // Cache successful fetch
    cacheFlowData(data);
    return NextResponse.json(data);
  }
  
  // All sources failed - try last-known-good cache
  const cached = getLastKnownGood();
  
  if (cached.data) {
    console.warn(`[flow] Serving cached data (${cached.age_seconds}s old) - blob + feed unreachable`);
    
    // Add metadata to indicate cached/stale data
    const response = {
      ...cached.data,
      _cache: {
        served_from_cache: true,
        age_seconds: cached.age_seconds,
        is_stale: cached.is_stale
      }
    };
    
    return NextResponse.json(response, {
      headers: {
        "X-Cache-Status": "STALE",
        "X-Cache-Age": String(cached.age_seconds)
      }
    });
  }
  
  // No cache available - fall back to fixture
  return NextResponse.json(FAKE_FIXTURE);
}
