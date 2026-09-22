import { NextResponse } from "next/server";
import { loadLatestPublicMarketBrief } from "@/lib/marketBrief/server";
import { toPublicMarketBrief } from "@/lib/marketBrief/public";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET() {
  const snapshot = await loadLatestPublicMarketBrief();
  const payload = toPublicMarketBrief(snapshot);
  return NextResponse.json(payload, {
    status: 200,
    headers: {
      "Cache-Control": "public, max-age=60, stale-while-revalidate=300",
    },
  });
}
