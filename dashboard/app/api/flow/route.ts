import { NextResponse } from "next/server";
import type { FlowSnapshot } from "@/lib/flowTypes";

const FAKE_FIXTURE: FlowSnapshot = {
  ts: new Date().toISOString(),
  es: {
    last: 7718.25,
    vwap: 7716.5,
    onHigh: 7728.0,
    onLow: 7710.75,
    cvd: 850,
    cvdLow: -420,
    bars1m: [
      { ts: new Date(Date.now() - 9 * 60000).toISOString(), open: 7712, high: 7714, low: 7711, close: 7713, volume: 135 },
      { ts: new Date(Date.now() - 8 * 60000).toISOString(), open: 7713, high: 7715, low: 7712, close: 7714, volume: 128 },
      { ts: new Date(Date.now() - 7 * 60000).toISOString(), open: 7714, high: 7716, low: 7713, close: 7715, volume: 142 },
      { ts: new Date(Date.now() - 6 * 60000).toISOString(), open: 7715, high: 7717, low: 7714, close: 7716, volume: 155 },
      { ts: new Date(Date.now() - 5 * 60000).toISOString(), open: 7716, high: 7718, low: 7715, close: 7717, volume: 138 },
      { ts: new Date(Date.now() - 4 * 60000).toISOString(), open: 7717, high: 7719, low: 7716, close: 7718, volume: 148 },
      { ts: new Date(Date.now() - 3 * 60000).toISOString(), open: 7718, high: 7720, low: 7717, close: 7719, volume: 162 },
      { ts: new Date(Date.now() - 2 * 60000).toISOString(), open: 7719, high: 7721, low: 7718, close: 7720, volume: 185 },
      { ts: new Date(Date.now() - 1 * 60000).toISOString(), open: 7720, high: 7721, low: 7718, close: 7719, volume: 172 },
      { ts: new Date().toISOString(), open: 7719, high: 7720, low: 7717, close: 7718.25, volume: 210 },
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
      { ts: new Date(Date.now() - 3 * 60000).toISOString(), price: 7719.5, lots: 28, side: "ask" },
      { ts: new Date(Date.now() - 2 * 60000).toISOString(), price: 7718.5, lots: 35, side: "bid" },
      { ts: new Date(Date.now() - 1 * 60000).toISOString(), price: 7719.0, lots: 42, side: "bid" },
      { ts: new Date(Date.now() - 30000).toISOString(), price: 7720.0, lots: 25, side: "ask" },
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
    asOf: new Date(Date.now() - 15 * 60000).toISOString(),
  },
  gates: [
    { level: 7730, status: "untested", closeCount: 0 },
    { level: 7725, status: "testing", closeCount: 1 },
    { level: 7715, status: "testing", closeCount: 1 },
    { level: 7710, status: "broken", closeCount: 2 },
  ],
};

export async function GET() {
  const feedUrl = process.env.FLOW_FEED_URL;
  
  if (!feedUrl) {
    return NextResponse.json(FAKE_FIXTURE);
  }

  try {
    const res = await fetch(feedUrl, { 
      cache: "no-store",
      signal: AbortSignal.timeout(5000),
    });
    
    if (!res.ok) {
      console.warn(`[flow] FLOW_FEED_URL returned ${res.status}, falling back to fixture`);
      return NextResponse.json(FAKE_FIXTURE);
    }
    
    const data = await res.json();
    return NextResponse.json(data);
  } catch (err) {
    console.error("[flow] Failed to fetch FLOW_FEED_URL, falling back to fixture:", err);
    return NextResponse.json(FAKE_FIXTURE);
  }
}
