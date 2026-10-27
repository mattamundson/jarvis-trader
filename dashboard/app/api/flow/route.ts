import { NextResponse } from "next/server";
import type { FlowSnapshot } from "@/lib/flowTypes";

const FAKE_FIXTURE: FlowSnapshot = {
  ts: new Date().toISOString(),
  es: {
    last: 5845.25,
    vwap: 5843.5,
    onHigh: 5850.0,
    onLow: 5838.75,
    cvd: 1250,
    cvdLow: -340,
    bars1m: [
      { ts: new Date(Date.now() - 4 * 60000).toISOString(), open: 5840, high: 5842, low: 5839, close: 5841, volume: 120 },
      { ts: new Date(Date.now() - 3 * 60000).toISOString(), open: 5841, high: 5843, low: 5840, close: 5842, volume: 145 },
      { ts: new Date(Date.now() - 2 * 60000).toISOString(), open: 5842, high: 5845, low: 5841, close: 5844, volume: 180 },
      { ts: new Date(Date.now() - 1 * 60000).toISOString(), open: 5844, high: 5846, low: 5843, close: 5845, volume: 160 },
      { ts: new Date().toISOString(), open: 5845, high: 5846, low: 5844, close: 5845.25, volume: 95 },
    ],
    deltaAtPrice: [
      { price: 5846, bidLots: 5, askLots: 12 },
      { price: 5845.75, bidLots: 8, askLots: 18 },
      { price: 5845.5, bidLots: 14, askLots: 22 },
      { price: 5845.25, bidLots: 22, askLots: 15 },
      { price: 5845, bidLots: 28, askLots: 10 },
      { price: 5844.75, bidLots: 18, askLots: 8 },
      { price: 5844.5, bidLots: 12, askLots: 5 },
    ],
    bigPrints: [
      { ts: new Date(Date.now() - 2 * 60000).toISOString(), price: 5844.5, lots: 25, side: "bid" },
      { ts: new Date(Date.now() - 1 * 60000).toISOString(), price: 5845.0, lots: 32, side: "bid" },
      { ts: new Date(Date.now() - 30000).toISOString(), price: 5845.75, lots: 28, side: "ask" },
    ],
  },
  nq: {
    last: 20345.5,
    vwap: 20342.25,
  },
  gex: {
    callWall: 5860,
    putWall: 5825,
    flip: 5842,
    pin: 5850,
    asOf: new Date(Date.now() - 15 * 60000).toISOString(),
  },
  gates: [
    { level: 5850, status: "untested", closeCount: 0 },
    { level: 5847.5, status: "testing", closeCount: 1 },
    { level: 5842.5, status: "untested", closeCount: 0 },
    { level: 5835, status: "broken", closeCount: 3 },
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
