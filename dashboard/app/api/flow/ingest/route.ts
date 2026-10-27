import { NextResponse, type NextRequest } from "next/server";
import { put } from "@vercel/blob";
import type { FlowSnapshot } from "@/lib/flowTypes";

function constantTimeCompare(a: string, b: string): boolean {
  if (a.length !== b.length) {
    return false;
  }
  let result = 0;
  for (let i = 0; i < a.length; i++) {
    result |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return result === 0;
}

function sanitizeFlowData(data: unknown): FlowSnapshot | null {
  if (typeof data !== "object" || data === null) {
    return null;
  }
  
  const raw = data as Record<string, unknown>;
  
  if (typeof raw.ts !== "string") {
    return null;
  }
  
  const es = raw.es as Record<string, unknown> | undefined;
  const nq = raw.nq as Record<string, unknown> | undefined;
  const gex = raw.gex as Record<string, unknown> | undefined;
  const gates = raw.gates as Array<unknown> | undefined;
  
  if (!es || !nq || !gex || !Array.isArray(gates)) {
    return null;
  }
  
  if (
    typeof es.last !== "number" ||
    typeof es.vwap !== "number" ||
    typeof es.onHigh !== "number" ||
    typeof es.onLow !== "number" ||
    typeof es.cvd !== "number" ||
    typeof es.cvdLow !== "number" ||
    !Array.isArray(es.bars1m) ||
    !Array.isArray(es.deltaAtPrice) ||
    !Array.isArray(es.bigPrints)
  ) {
    return null;
  }
  
  if (typeof nq.last !== "number" || typeof nq.vwap !== "number") {
    return null;
  }
  
  if (
    typeof gex.callWall !== "number" ||
    typeof gex.putWall !== "number" ||
    typeof gex.flip !== "number" ||
    typeof gex.pin !== "number" ||
    typeof gex.asOf !== "string"
  ) {
    return null;
  }
  
  const sanitizedBars = es.bars1m.map((bar: unknown) => {
    const b = bar as Record<string, unknown>;
    return {
      ts: String(b.ts),
      open: Number(b.open),
      high: Number(b.high),
      low: Number(b.low),
      close: Number(b.close),
      volume: Number(b.volume),
    };
  });
  
  const sanitizedDelta = es.deltaAtPrice.map((d: unknown) => {
    const delta = d as Record<string, unknown>;
    return {
      price: Number(delta.price),
      bidLots: Number(delta.bidLots),
      askLots: Number(delta.askLots),
    };
  });
  
  const sanitizedPrints = es.bigPrints.map((p: unknown) => {
    const print = p as Record<string, unknown>;
    return {
      ts: String(print.ts),
      price: Number(print.price),
      lots: Number(print.lots),
      side: String(print.side) as "bid" | "ask",
    };
  });
  
  const sanitizedGates = gates.map((g: unknown) => {
    const gate = g as Record<string, unknown>;
    return {
      level: Number(gate.level),
      status: String(gate.status) as "untested" | "testing" | "broken",
      closeCount: Number(gate.closeCount),
    };
  });
  
  return {
    ts: raw.ts,
    es: {
      last: es.last,
      vwap: es.vwap,
      onHigh: es.onHigh,
      onLow: es.onLow,
      cvd: es.cvd,
      cvdLow: es.cvdLow,
      bars1m: sanitizedBars,
      deltaAtPrice: sanitizedDelta,
      bigPrints: sanitizedPrints,
    },
    nq: {
      last: nq.last,
      vwap: nq.vwap,
    },
    gex: {
      callWall: gex.callWall,
      putWall: gex.putWall,
      flip: gex.flip,
      pin: gex.pin,
      asOf: gex.asOf,
    },
    gates: sanitizedGates,
  };
}

export async function POST(request: NextRequest) {
  const authHeader = request.headers.get("authorization");
  const expectedToken = process.env.FLOW_INGEST_TOKEN;
  
  if (!expectedToken) {
    console.error("[flow/ingest] FLOW_INGEST_TOKEN not configured");
    return NextResponse.json(
      { error: "Server misconfigured" },
      { status: 500 }
    );
  }
  
  if (!authHeader || !authHeader.startsWith("Bearer ")) {
    return NextResponse.json(
      { error: "Unauthorized" },
      { status: 401 }
    );
  }
  
  const token = authHeader.slice(7);
  
  if (!constantTimeCompare(token, expectedToken)) {
    return NextResponse.json(
      { error: "Unauthorized" },
      { status: 401 }
    );
  }
  
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json(
      { error: "Invalid JSON" },
      { status: 400 }
    );
  }
  
  const sanitized = sanitizeFlowData(body);
  
  if (!sanitized) {
    return NextResponse.json(
      { error: "Invalid flow data schema" },
      { status: 400 }
    );
  }
  
  const blobToken = process.env.BLOB_READ_WRITE_TOKEN;
  
  if (!blobToken) {
    console.error("[flow/ingest] BLOB_READ_WRITE_TOKEN not configured");
    return NextResponse.json(
      { error: "Storage not configured" },
      { status: 500 }
    );
  }
  
  try {
    await put("flow/latest.json", JSON.stringify(sanitized), {
      access: "public",
      token: blobToken,
    });
    
    return NextResponse.json({ success: true, ts: sanitized.ts });
  } catch (err) {
    console.error("[flow/ingest] Failed to store blob:", err);
    return NextResponse.json(
      { error: "Storage failed" },
      { status: 500 }
    );
  }
}
