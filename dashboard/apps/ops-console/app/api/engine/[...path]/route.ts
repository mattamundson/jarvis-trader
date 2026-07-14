import { NextRequest, NextResponse } from "next/server";
import { applyEngineAuthHeaders } from "@/lib/engineProxyHeaders";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
export const maxDuration = 30; // platform-enforced ceiling: if the in-app 25s AbortController ever fails to fire (e.g. engine fully unreachable), fail here instead of hanging to Vercel's default 60s

function getEngineBaseUrl(): string {
  return (
    process.env.ENGINE_INTERNAL_URL ??
    process.env.ENGINE_URL_INTERNAL ??
    "http://localhost:8010"
  );
}

function getEngineApiKey(): string | undefined {
  // Server-only var — never NEXT_PUBLIC_* — so the key is never inlined into
  // the client bundle.
  return process.env.ENGINE_API_KEY;
}

// user:pass credential matching the ngrok tunnel's basic-auth (ngrok.yml). Only
// set on deployments where the engine sits behind the tunnel; absent for local dev
// where the proxy targets 127.0.0.1:8010 directly.
function getTunnelBasicAuth(): string | undefined {
  return process.env.ENGINE_TUNNEL_BASIC_AUTH;
}

async function proxy(request: NextRequest, path: string[]): Promise<NextResponse> {
  const target = new URL(`${getEngineBaseUrl()}/${path.join("/")}`);
  target.search = request.nextUrl.search;

  const headers = new Headers(request.headers);
  headers.delete("host");
  headers.delete("connection");
  headers.delete("content-length");

  // Inject engine + tunnel auth (X-API-Key, Authorization: Basic, ngrok-skip-
  // browser-warning) server-side only. See lib/engineProxyHeaders.ts for why.
  applyEngineAuthHeaders(headers, {
    apiKey: getEngineApiKey(),
    tunnelBasicAuth: getTunnelBasicAuth(),
  });

  // When the engine is reached through an ngrok free-tier tunnel, ngrok injects
  // an HTML "browser warning" interstitial for requests with browser-like
  // headers (which this proxy forwards from the client). This header bypasses
  // it so we always get the engine's JSON. Harmless for other tunnels.
  headers.set("ngrok-skip-browser-warning", "true");

  // If the tunnel (ngrok) enforces HTTP basic-auth, inject it server-side so the
  // credential never reaches the browser. ENGINE_TUNNEL_BASIC_AUTH is "user:pass".
  // No-op when unset (local dev / tunnels without basic-auth).
  const tunnelAuth = process.env.ENGINE_TUNNEL_BASIC_AUTH;
  if (tunnelAuth) {
    headers.set("Authorization", `Basic ${Buffer.from(tunnelAuth).toString("base64")}`);
  }

  const init: RequestInit = {
    method: request.method,
    headers,
    redirect: "manual",
  };

  if (request.method !== "GET" && request.method !== "HEAD") {
    init.body = await request.arrayBuffer();
  }

  const controller = new AbortController();
  // 60s: cold-cache engine endpoints (TV/yfinance-backed prices, mtf,
  // discord intelligence) exceed 5s on first hit and were 502ing every page
  // load right after an engine restart. The Hidden Pivots full scan fetches
  // bars for ~33 symbols and can run past 25s cold, so the ceiling is 60s.
  const timeout = setTimeout(() => controller.abort(), 60_000);

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
        error: "engine_proxy_failed",
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
  return proxy(request, path);
}

export async function POST(request: NextRequest, context: RouteContext) {
  const { path } = await context.params;
  return proxy(request, path);
}

export async function PUT(request: NextRequest, context: RouteContext) {
  const { path } = await context.params;
  return proxy(request, path);
}

export async function PATCH(request: NextRequest, context: RouteContext) {
  const { path } = await context.params;
  return proxy(request, path);
}

export async function DELETE(request: NextRequest, context: RouteContext) {
  const { path } = await context.params;
  return proxy(request, path);
}

export async function OPTIONS(request: NextRequest, context: RouteContext) {
  const { path } = await context.params;
  return proxy(request, path);
}
