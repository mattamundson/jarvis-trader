import { NextResponse } from "next/server";
import { unavailableHermesGates } from "@/lib/hermesGates";

export const dynamic = "force-dynamic";

export function GET() {
  return NextResponse.json(unavailableHermesGates(), {
    headers: { "Cache-Control": "no-store" },
  });
}
