import { NextResponse } from "next/server";
import { loadClaudeRead, tapeStateDir } from "@/lib/tape/claudeReadLoad";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

// Read-only. Serves the allow-listed claude-read-latest.json. Never writes, never orders.
export async function GET() {
  const payload = await loadClaudeRead(tapeStateDir(), Date.now());
  return NextResponse.json(payload, { headers: { "Cache-Control": "no-store" } });
}
