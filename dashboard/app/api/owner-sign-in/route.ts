import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";

/** Middleware challenges here only on explicit navigation. The browser caches
 * Basic Auth for /api/, allowing owner actions without gating public pages.
 */
export async function GET(request: NextRequest) {
  return NextResponse.redirect(new URL("/", request.url), {
    status: 303,
    headers: { "Cache-Control": "no-store" },
  });
}
