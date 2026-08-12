import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
export const maxDuration = 30;

// Same-origin proxy to the isolated jarvis-domflow service (port 8031).
// Mirrors app/api/engine/[...path]/route.ts but WITHOUT engine auth headers:
// domflow is a read-only, 127.0.0.1-bound market-data consumer with no API key
// (its PM2 app env pins DOMFLOW_IB_HOST/PORT/CLIENT_ID, and it has no order
// path). Keeping the proxy here (rather than a bare cross-origin fetch in the
// browser) preserves the repo's "all dashboard calls go through the proxy"
// convention and avoids CORS in production.
// NOTE: was originally 8030, which collides with the separate external
// master-api service (see AGENTS.md "External service: master-api (:8030)").
// Moved to 8031 (2026-08-12) — see engine/ecosystem.config.js jarvis-domflow entry.
function getDomflowBaseUrl(): string {
  return (
    process.env.DOMFLOW_INTERNAL_URL ??
    process.env.DOMFLOW_URL_INTERNAL ??
    // 127.0.0.1, not localhost: Windows resolves localhost to ::1 first
    // and the domflow service binds IPv4 only.
    "http://127.0.0.1:8031"
  ).replace(/\/$/, "");
}

async function proxy(request: NextRequest, path: string[]): Promise<NextResponse> {
  const target = new URL(`${getDomflowBaseUrl()}/${path.join("/")}`);
  target.search = request.nextUrl.search;

  const headers = new Headers(request.headers);
  headers.delete("host");
  headers.delete("connection");
  headers.delete("content-length");

  const init: RequestInit = {
    method: request.method,
    headers,
    redirect: "manual",
  };

  if (request.method !== "GET" && request.method !== "HEAD") {
    init.body = await request.arrayBuffer();
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 30_000);

  let upstream: Response;
  try {
    upstream = await fetch(target, {
      ...init,
      cache: "no-store",
      signal: controller.signal,
    });
  } catch (error) {
    return NextResponse.json(
      {
        error: "domflow_proxy_failed",
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

export async function GET(request: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;
  return proxy(request, path);
}

export async function POST(request: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;
  return proxy(request, path);
}
