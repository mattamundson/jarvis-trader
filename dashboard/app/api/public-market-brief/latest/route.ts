import { NextResponse } from "next/server";
import { loadLatestMarketBrief } from "@/lib/marketBrief/server";
import { toPublicMarketBrief } from "@/lib/marketBrief/public";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET() {
  const snapshot = await loadLatestMarketBrief();
  const payload = toPublicMarketBrief(snapshot);
  return NextResponse.json(payload, {
    status: 200,
    headers: {
      "Cache-Control": "public, max-age=60, stale-while-revalidate=300",
    },
  });
}
