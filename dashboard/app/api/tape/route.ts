import { NextResponse } from "next/server";
import { readHermesGates } from "@/lib/hermesGates";
import { buildTapePayload, findPrivateKeys } from "@/lib/tape/serialize";
import { readTapeState } from "@/lib/tape/state";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

// Read-only public-safe feed for /tape. Allow-list serializer: no $, positions, P&L or account fields.
export async function GET() {
  const [flow, gex, doublewide, aaron, gates] = await Promise.all([
    readTapeState("flow"), readTapeState("gex"), readTapeState("doublewide"), readTapeState("aaron"),
    readHermesGates().catch(() => null),
  ]);
  const payload = buildTapePayload({ flow, gex, doublewide, aaron, gates }, Date.now());
  const leaks = findPrivateKeys(payload);
  if (leaks.length > 0) {
    return NextResponse.json({ error: "serializer_violation", count: leaks.length }, { status: 500 });
  }
  return NextResponse.json(payload, { headers: { "Cache-Control": "no-store" } });
}
