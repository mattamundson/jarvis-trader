import { NextResponse } from "next/server";
import { loadLatestMarketBrief } from "@/lib/marketBrief/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET() {
  const payload = await loadLatestMarketBrief();
  return NextResponse.json(payload, {
    status: 200,
    headers: { "Cache-Control": "no-store, max-age=0" },
  });
}
