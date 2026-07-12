import { NextRequest } from "next/server";
import { runProxy, type ProxyConfig } from "@/lib/api-proxy";

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

async function proxy(request: NextRequest, path: string[]): Promise<Response> {
  const config: ProxyConfig = {
    baseUrl: getEngineBaseUrl(),
    apiKey: getEngineApiKey(),
    // 25s: cold-cache engine endpoints (TV/yfinance-backed prices, mtf,
    // discord intelligence) exceed 5s on first hit and were 502ing every page
    // load right after an engine restart.
    timeoutMs: 25_000,
    forwardClientHeaders: true,
    redirect: "manual",
    errorTag: "engine_proxy_failed",
  };

  return runProxy(
    config,
    {
      method: request.method,
      headers: request.headers,
      search: request.nextUrl.search,
      body: () => request.arrayBuffer(),
    },
    path,
  );
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
