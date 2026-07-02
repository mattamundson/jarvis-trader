import { NextRequest, NextResponse } from "next/server";

// Read-only server-side proxy to the master-api service (separate service,
// not in this repo — see AGENTS.md "External service: master-api"). Mirrors
// app/api/amo/[...path]/route.ts so lib/masterApi.ts never puts the
// master-api URL or key in the client bundle. Only GET is exposed — the
// dashboard never mutates master-api state, including the /master/command/stream
// SSE endpoint (EventSource is GET-only by spec).

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
// 60s: covers the /master/command/stream SSE chat responses, which can run
// longer than a plain JSON fetch. Longer than the amo proxy's 15s on purpose.
export const maxDuration = 60;

function getMasterBaseUrl(): string {
  return process.env.MASTER_API_URL ?? "http://127.0.0.1:8030";
}

function getMasterApiKey(): string | undefined {
  // Server-only var — never NEXT_PUBLIC_* — so the key is never inlined into
  // the client bundle.
  return process.env.MASTER_API_KEY;
}

async function proxyGet(request: NextRequest, path: string[]): Promise<NextResponse> {
  const target = new URL(`${getMasterBaseUrl()}/${path.join("/")}`);
  target.search = request.nextUrl.search;

  const headers: HeadersInit = {};
  const masterApiKey = getMasterApiKey();
  if (masterApiKey) {
    headers["X-API-Key"] = masterApiKey;
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 55_000);

  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: "GET",
      headers,
      cache: "no-store",
      signal: controller.signal,
    });
  } catch (error) {
    return NextResponse.json(
      {
        error: "master_proxy_failed",
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
