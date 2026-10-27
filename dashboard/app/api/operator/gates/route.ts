import { NextResponse } from "next/server";
import { readHermesGates } from "@/lib/hermesGates";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET() {
  const report = await readHermesGates();
  return NextResponse.json(report);
}
