import { NextRequest, NextResponse } from "next/server";

// Read-only server-side proxy to the amo-arbitrage system (separate service on
// Railway). Mirrors app/api/engine/[...path]/route.ts so the Trust Pane can read
// amo health/status without a cross-origin (CORS) call from the browser. Only GET
// is exposed — the Trust Pane never mutates amo state. The two engines stay fully
// independent; this is observability-only, no coupling.

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

function getAmoBaseUrl(): string {
  return (
    process.env.AMO_BASE_URL ??
    process.env.NEXT_PUBLIC_AMO_BASE_URL ??
    "https://amo-arbitrage-production.up.railway.app"
  );
}

async function proxyGet(request: NextRequest, path: string[]): Promise<NextResponse> {
  const target = new URL(`${getAmoBaseUrl()}/${path.join("/")}`);
  target.search = request.nextUrl.search;

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15_000);

  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: "GET",
      // amo /api/health is public; identify ourselves (Railway edge 1010s a
      // missing UA — see amo-arbitrage Railway notes).
      headers: { "User-Agent": "jarvis-trust-pane/1.0" },
      cache: "no-store",
      signal: controller.signal,
    });
  } catch (error) {
    return NextResponse.json(
      {
        error: "amo_proxy_failed",
        target: target.toString(),
        message: error instanceof Error ? error.message : "Unknown proxy error",
      },
      { status: 502 },
    );
  } finally {
    clearTimeout(timeout);
  }

  const responseHeaders = new Headers(upstream.headers);
  responseHeaders.delete("content-encoding");
  responseHeaders.delete("content-length");
  responseHeaders.delete("transfer-encoding");

  return new NextResponse(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: responseHeaders,
  });
}

type RouteContext = {
  params: Promise<{ path: string[] }>;
};

export async function GET(request: NextRequest, context: RouteContext) {
  const { path } = await context.params;
  return proxyGet(request, path);
}
